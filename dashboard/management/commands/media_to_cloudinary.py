"""
One-time move of existing media/ files onto Cloudinary.

Switching STORAGES only changes where *new* uploads go. Every row already in
the database still points at a path under MEDIA_ROOT, and those files would 404
the moment the local media/ folder stops being served. This command walks every
FileField on every model, uploads what it finds on disk, and rewrites the
column to the Cloudinary public_id.

Run it with --dry-run first. It is safe to re-run: a row whose file is no longer
on local disk is treated as already migrated and skipped.

  python manage.py media_to_cloudinary --dry-run
  python manage.py media_to_cloudinary
  python manage.py media_to_cloudinary --app curations --limit 5

Note on the writes: the new path is applied with a queryset .update() rather
than instance.save(). That writes exactly one column and skips model save()
hooks and signals entirely, which matters here because several of these models
are also edited through dashboard forms that save every field at once -- doing
this through a form would blank out whatever the form did not include.
"""

import os
import time

import cloudinary
import cloudinary.uploader
from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import models

from cloudinary_storage.storage import (
    MediaCloudinaryStorage,
    RawMediaCloudinaryStorage,
    VideoMediaCloudinaryStorage,
)

# Cloudinary's own API rejects a single-shot upload well before this, and the
# chunked endpoint is slower, so only large files pay for it.
CHUNKED_UPLOAD_THRESHOLD = 20 * 1024 * 1024

# The free plan refuses video above 100 MB outright. Worth saying so before
# spending several minutes uploading something that cannot succeed.
FREE_PLAN_VIDEO_LIMIT = 100 * 1024 * 1024


def _human(num_bytes):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if num_bytes < 1024 or unit == 'GB':
            return f'{num_bytes:.1f} {unit}' if unit != 'B' else f'{num_bytes} B'
        num_bytes /= 1024


def _resource_type_for(field):
    """
    Which of Cloudinary's three storage buckets this field belongs in.

    Read off the storage the field was actually configured with, so this stays
    correct if a field's storage changes later without anyone editing here.
    """
    storage = field.storage
    if isinstance(storage, VideoMediaCloudinaryStorage):
        return 'video'
    if isinstance(storage, RawMediaCloudinaryStorage):
        return 'raw'
    return 'image'


def _public_id_for(name, resource_type, storage):
    """
    The Cloudinary name to store this file under.

    Two rules, both dictated by what the storage class does when it reads a
    file back, since a migrated file and a newly uploaded one have to be
    indistinguishable afterwards:

    * The storage prefixes every name with MEDIA_URL ('media/') on both write
      and read. Uploading without that prefix puts the file somewhere .url()
      will never look, and every migrated image 404s. Delegated to the storage's
      own _prepend_prefix so it tracks MEDIA_URL instead of hardcoding it.
    * Image and video public_ids carry no extension -- Cloudinary derives the
      format, and with f_auto may serve a different one than was uploaded. Raw
      files keep theirs, because nothing inspects a raw file's contents and
      VendorDocument.is_image / TenderAttachment.is_image both read the
      extension off the stored name.
    """
    name = name.replace('\\', '/')
    if resource_type != 'raw':
        name = os.path.splitext(name)[0]
    return storage._prepend_prefix(name)


def _iter_file_fields():
    """
    Every concrete FileField/ImageField that is allowed on Cloudinary.

    A field configured with a non-Cloudinary storage is skipped rather than
    forced up. That is what keeps vendor ID proofs on local disk: they are
    excluded here by virtue of their storage, so no future run of this command
    can quietly publish them, whatever arguments it is given.
    """
    for model in apps.get_models():
        # Django's own tables (sessions, admin log) hold no media.
        if model._meta.app_label in {'admin', 'auth', 'contenttypes', 'sessions'}:
            continue
        for field in model._meta.get_fields():
            if not isinstance(field, models.FileField):
                continue
            if not isinstance(field.storage, MediaCloudinaryStorage):
                continue
            yield model, field


class Command(BaseCommand):
    help = 'Upload existing local media files to Cloudinary and repoint the database at them.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be uploaded without contacting Cloudinary or writing to the database.',
        )
        parser.add_argument(
            '--app', default=None,
            help='Restrict to a single app label, e.g. --app curations.',
        )
        parser.add_argument(
            '--limit', type=int, default=None,
            help='Stop after this many files. Useful for a first cautious run.',
        )
        parser.add_argument(
            '--skip-video', action='store_true',
            help='Leave video fields alone. Video is by far the largest consumer of Cloudinary credits.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        app_filter = options['app']
        limit = options['limit']
        skip_video = options['skip_video']

        if not settings.USE_CLOUDINARY:
            raise CommandError(
                'Cloudinary is not configured. Set CLOUDINARY_CLOUD_NAME, '
                'CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET in .env first.'
            )

        if not dry_run:
            # Fail here, on one cheap call, rather than partway through an
            # upload run with some rows rewritten and some not.
            cloudinary.config(
                cloud_name=settings.CLOUDINARY_CLOUD_NAME,
                api_key=settings.CLOUDINARY_API_KEY,
                api_secret=settings.CLOUDINARY_API_SECRET,
                secure=True,
            )
            try:
                cloudinary.api.ping()
            except Exception as exc:
                raise CommandError(
                    f'Could not authenticate with Cloudinary: {exc}\n'
                    'Check that CLOUDINARY_CLOUD_NAME matches the "Cloud name" '
                    'shown in your Cloudinary console -- a mismatch between the '
                    'cloud name and the API key gives "cloud_name mismatch".'
                )

        media_root = str(settings.MEDIA_ROOT)
        migrated = skipped = failed = 0
        uploaded_bytes = 0
        processed = 0

        for model, field in _iter_file_fields():
            if app_filter and model._meta.app_label != app_filter:
                continue

            resource_type = _resource_type_for(field)
            if skip_video and resource_type == 'video':
                continue

            label = f'{model._meta.app_label}.{model.__name__}.{field.name}'
            rows = (
                model._default_manager
                .exclude(**{field.name: ''})
                .exclude(**{f'{field.name}__isnull': True})
                .values_list('pk', field.name)
            )

            for pk, name in rows:
                if limit is not None and processed >= limit:
                    self.stdout.write(self.style.WARNING(f'\nReached --limit {limit}, stopping.'))
                    self._summary(migrated, skipped, failed, uploaded_bytes, dry_run)
                    return

                local_path = os.path.join(media_root, name.replace('/', os.sep))

                if not os.path.exists(local_path):
                    # Either already migrated, or the row points at a file that
                    # was never there. Both cases: nothing to upload.
                    skipped += 1
                    continue

                processed += 1
                size = os.path.getsize(local_path)
                public_id = _public_id_for(name, resource_type, field.storage)

                if resource_type == 'video' and size > FREE_PLAN_VIDEO_LIMIT:
                    stem, ext = os.path.splitext(local_path)
                    self.stdout.write(self.style.ERROR(
                        f'  SKIP {label} pk={pk}: {_human(size)} video exceeds the '
                        f'{_human(FREE_PLAN_VIDEO_LIMIT)} hard limit on Cloudinary\'s free plan.\n'
                        f'       Compress it, then point the row at the new file and re-run.\n'
                        f'       This recipe took a 119 MB 1080x1920/60fps clip to 19 MB:\n'
                        f'         ffmpeg -i "{local_path}" -vcodec libx264 -preset slow -crf 26 \\\n'
                        f'           -vf "scale=-2:1280,fps=30" -pix_fmt yuv420p \\\n'
                        f'           -acodec aac -b:a 128k -movflags +faststart "{stem}_720p{ext}"'
                    ))
                    failed += 1
                    continue

                if dry_run:
                    self.stdout.write(
                        f'  would upload [{resource_type}] {name} ({_human(size)}) -> {public_id}'
                    )
                    migrated += 1
                    uploaded_bytes += size
                    continue

                try:
                    started = time.monotonic()
                    upload = (
                        cloudinary.uploader.upload_large
                        if size > CHUNKED_UPLOAD_THRESHOLD
                        else cloudinary.uploader.upload
                    )
                    response = upload(
                        local_path,
                        public_id=public_id,
                        resource_type=resource_type,
                        # Re-running after a partial failure should converge,
                        # not create plumbing_1, plumbing_2, plumbing_3.
                        overwrite=True,
                        invalidate=True,
                        unique_filename=False,
                        use_filename=False,
                        tags=[settings.CLOUDINARY_STORAGE.get('MEDIA_TAG', 'home_service_media')],
                    )
                except Exception as exc:
                    self.stdout.write(self.style.ERROR(f'  FAIL {label} pk={pk} ({name}): {exc}'))
                    failed += 1
                    continue

                new_name = response['public_id']
                # One column, no signals, no full-form save. See module docstring.
                model._default_manager.filter(pk=pk).update(**{field.name: new_name})

                elapsed = time.monotonic() - started
                migrated += 1
                uploaded_bytes += size
                self.stdout.write(self.style.SUCCESS(
                    f'  OK   [{resource_type}] {name} ({_human(size)}, {elapsed:.1f}s) -> {new_name}'
                ))

        self._summary(migrated, skipped, failed, uploaded_bytes, dry_run)

    def _summary(self, migrated, skipped, failed, uploaded_bytes, dry_run):
        verb = 'Would migrate' if dry_run else 'Migrated'
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Summary'))
        self.stdout.write(f'  {verb}: {migrated} file(s), {_human(uploaded_bytes)}')
        self.stdout.write(f'  Skipped (not on local disk): {skipped}')
        if failed:
            self.stdout.write(self.style.ERROR(f'  Failed: {failed}'))
        if dry_run:
            self.stdout.write('')
            self.stdout.write('Dry run only -- nothing was uploaded or written. Re-run without --dry-run to apply.')
