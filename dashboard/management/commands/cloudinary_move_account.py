"""
Copy every Cloudinary asset from one account to another.

Used once, at handover, to move media off the developer's Cloudinary account
and onto the client's. Different problem from media_to_cloudinary, which lifts
files off local disk -- here the files are already on Cloudinary and only the
account underneath them changes.

Nothing in the database is written. A stored value like

    media/category_icons/Gemini_Generated_Image_9wxsvp9wxsvp9wxs

is the public_id, and the account is not part of it -- it comes from
CLOUDINARY_CLOUD_NAME at URL-build time. So re-uploading each asset to the new
account under the *same* public_id makes every existing row correct without
touching a single column. That is what makes this safe to re-run, and what
makes rolling back a matter of putting the old cloud name back in .env.

Cloudinary fetches each file itself from the old account's delivery URL, so
the bytes never travel through this machine.

Order matters. The new credentials must already be in .env before running
this, because the destination is read from settings -- and until the copy
finishes, images 404, since URLs already point at an account that has nothing
in it. Expect a broken-looking dashboard between the switch and the finish.

    python manage.py cloudinary_move_account --from-cloud OLD --from-key K --from-secret S --dry-run
    python manage.py cloudinary_move_account --from-cloud OLD --from-key K --from-secret S

Vendor ID documents are not touched. They are on local disk by design and are
excluded here by their storage class, not by a filter that could be argued
away -- see config/storages.py.
"""

import time

import cloudinary
import cloudinary.api
import cloudinary.uploader
import cloudinary.utils
from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import models

from cloudinary_storage.storage import (
    MediaCloudinaryStorage,
    RawMediaCloudinaryStorage,
    VideoMediaCloudinaryStorage,
)


def _resource_type_for(field):
    """Which of Cloudinary's three buckets this field's files live in."""
    storage = field.storage
    if isinstance(storage, VideoMediaCloudinaryStorage):
        return 'video'
    if isinstance(storage, RawMediaCloudinaryStorage):
        return 'raw'
    return 'image'


def _iter_file_fields():
    """
    Every field whose files are on Cloudinary and therefore need moving.

    Selection is by storage class, exactly as in media_to_cloudinary. Vendor ID
    proofs use private_storage, which is plain local disk, so they can never be
    picked up here however this command is invoked.
    """
    for model in apps.get_models():
        if model._meta.app_label in {'admin', 'auth', 'contenttypes', 'sessions'}:
            continue
        for field in model._meta.get_fields():
            if not isinstance(field, models.FileField):
                continue
            if not isinstance(field.storage, MediaCloudinaryStorage):
                continue
            yield model, field


class Command(BaseCommand):
    help = "Copy Cloudinary assets from another account into the one configured in .env."

    def add_arguments(self, parser):
        parser.add_argument('--from-cloud', required=True,
                            help="The OLD account's cloud name.")
        parser.add_argument('--from-key', required=True,
                            help="The OLD account's API key.")
        parser.add_argument('--from-secret', required=True,
                            help="The OLD account's API secret.")
        parser.add_argument('--dry-run', action='store_true',
                            help='List what would be copied and change nothing.')
        parser.add_argument('--limit', type=int,
                            help='Stop after this many assets. For a trial run.')
        parser.add_argument('--overwrite', action='store_true',
                            help='Re-copy assets that already exist in the new '
                                 'account, instead of skipping them.')

    def handle(self, *args, **options):
        source_cloud = options['from_cloud']
        dry_run = options['dry_run']
        limit = options['limit']
        overwrite = options['overwrite']

        if not settings.USE_CLOUDINARY:
            raise CommandError(
                'The destination account is not configured. Put the new '
                'CLOUDINARY_CLOUD_NAME / API_KEY / API_SECRET in .env first -- '
                'this command copies *into* whatever .env points at.'
            )

        target_cloud = settings.CLOUDINARY_CLOUD_NAME
        if source_cloud == target_cloud:
            raise CommandError(
                f'--from-cloud and the configured account are both '
                f'"{target_cloud}". Nothing to move. Check .env has already '
                f'been switched to the new account.'
            )

        # Signing source URLs with the old account's credentials, so this works
        # even if that account has restricted delivery turned on.
        source_config = cloudinary.Config()
        source_config.cloud_name = source_cloud
        source_config.api_key = options['from_key']
        source_config.api_secret = options['from_secret']
        source_config.secure = True

        # The destination. cloudinary.config() is process-global and is what
        # uploader.upload() reads, so it must hold the *new* account.
        cloudinary.config(
            cloud_name=target_cloud,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
            secure=True,
        )

        self.stdout.write(f'From: {source_cloud}')
        self.stdout.write(f'To:   {target_cloud}')
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN -- nothing will be copied.\n'))
        else:
            self.stdout.write('')

        copied = skipped = failed = 0

        for model, field in _iter_file_fields():
            resource_type = _resource_type_for(field)
            label = f'{model._meta.label}.{field.name}'

            rows = (model._default_manager
                    .exclude(**{field.name: ''})
                    .exclude(**{field.name: None})
                    .values_list('pk', field.name))
            rows = list(rows)
            if not rows:
                continue

            self.stdout.write(self.style.MIGRATE_HEADING(
                f'{label}  ({len(rows)} file(s), {resource_type})'
            ))

            for pk, public_id in rows:
                if limit is not None and copied >= limit:
                    self.stdout.write(self.style.WARNING(
                        f'\nStopped at --limit {limit}.'
                    ))
                    self._summary(copied, skipped, failed, dry_run)
                    return

                if not public_id:
                    continue

                if not overwrite and self._exists_in_target(public_id, resource_type):
                    self.stdout.write(f'  skip  {public_id} (already there)')
                    skipped += 1
                    continue

                source_url, _ = cloudinary.utils.cloudinary_url(
                    public_id,
                    resource_type=resource_type,
                    type='upload',
                    secure=True,
                    sign_url=True,
                    config=source_config,
                )

                if dry_run:
                    self.stdout.write(f'  would copy [{resource_type}] {public_id}')
                    copied += 1
                    continue

                try:
                    started = time.monotonic()
                    # Handing Cloudinary a URL rather than bytes: it fetches
                    # from the old account directly, so a 100 MB video never
                    # travels down and back up through here.
                    response = cloudinary.uploader.upload(
                        source_url,
                        public_id=public_id,
                        resource_type=resource_type,
                        # Same reasoning as media_to_cloudinary: a re-run after
                        # a partial failure must converge, not accumulate
                        # banner_1, banner_2, banner_3.
                        overwrite=True,
                        invalidate=True,
                        unique_filename=False,
                        use_filename=False,
                        tags=[settings.CLOUDINARY_STORAGE.get(
                            'MEDIA_TAG', 'home_service_media')],
                    )
                except Exception as exc:
                    self.stdout.write(self.style.ERROR(
                        f'  FAIL  {label} pk={pk} ({public_id}): {exc}'
                    ))
                    failed += 1
                    continue

                landed = response.get('public_id')
                if landed != public_id:
                    # The database is not rewritten, so a public_id that shifts
                    # leaves that row pointing at nothing. Loud, not silent.
                    self.stdout.write(self.style.ERROR(
                        f'  FAIL  {public_id} landed as {landed} -- this row '
                        f'will 404. Copy it by hand and check the public_id.'
                    ))
                    failed += 1
                    continue

                elapsed = time.monotonic() - started
                copied += 1
                self.stdout.write(self.style.SUCCESS(
                    f'  OK    [{resource_type}] {public_id} ({elapsed:.1f}s)'
                ))

        self._summary(copied, skipped, failed, dry_run)

    def _exists_in_target(self, public_id, resource_type):
        try:
            cloudinary.api.resource(public_id, resource_type=resource_type)
            return True
        except cloudinary.api.NotFound:
            return False
        except Exception:
            # Anything else -- rate limit, network -- must not be read as
            # "already copied", or the asset gets silently skipped for ever.
            return False

    def _summary(self, copied, skipped, failed, dry_run):
        self.stdout.write('')
        verb = 'would copy' if dry_run else 'copied'
        self.stdout.write(f'{verb}: {copied}   already there: {skipped}   failed: {failed}')

        if failed:
            self.stdout.write(self.style.ERROR(
                'Some assets did not copy. Re-run the same command -- finished '
                'ones are skipped, so it picks up where it stopped.'
            ))
        elif not dry_run and copied:
            self.stdout.write(self.style.SUCCESS(
                'Done. Nothing in the database changed: the public_ids are '
                'identical, only the account under them is new.'
            ))
