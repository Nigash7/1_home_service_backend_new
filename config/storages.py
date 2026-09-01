"""
Cloudinary storage backends for this project's media.

Cloudinary splits everything it stores into three "resource types" -- image,
video, and raw -- and a file uploaded under the wrong one is not retrievable
under another. Django has no equivalent concept: an ImageField and a FileField
holding a 100 MB mp4 look the same to it. So the mapping has to be made here,
per field, via the FileField(storage=...) argument.

Each storage is exposed as a *callable* rather than an instance. Django accepts
a callable for FileField.storage and resolves it at runtime, which gives two
things an instance would not:

  * media falls back to local disk when Cloudinary is unconfigured, so tests,
    a fresh clone, and offline work all still run; and
  * the generated migration references this function by dotted path, so
    switching Cloudinary on or off later never needs a new migration.
"""

import cloudinary
from django.conf import settings
from django.core.files.storage import FileSystemStorage

from cloudinary_storage.storage import (
    MediaCloudinaryStorage,
    RawMediaCloudinaryStorage,
    VideoMediaCloudinaryStorage,
)


class OptimizedImageCloudinaryStorage(MediaCloudinaryStorage):
    """
    Image storage that optimizes on delivery rather than on upload.

    The original upload is kept untouched; `f_auto,q_auto` in the URL is what
    makes it small. Cloudinary picks the best format the requesting browser
    accepts (WebP/AVIF on modern phones, JPEG on old ones) and the lowest
    quality that still looks unchanged. In practice a 2 MB PNG category icon
    is delivered as roughly 30-80 KB without anyone re-uploading anything.

    Doing this in the storage layer rather than at each call site means every
    `.url` in the project -- serializers, dashboard templates, Django admin --
    gets it automatically and cannot forget to.
    """

    def _get_url(self, name):
        name = self._prepend_prefix(name)
        resource = cloudinary.CloudinaryResource(
            name, default_resource_type=self._get_resource_type(name)
        )
        return resource.build_url(fetch_format='auto', quality='auto')


class OptimizedVideoCloudinaryStorage(VideoMediaCloudinaryStorage):
    """
    Video storage, delivered through Cloudinary's CDN with automatic quality.

    Video is the expensive one: a single 119 MB upload streamed by a thousand
    people is 119 GB of egress, which no free tier survives. `q_auto` re-encodes
    down to a far smaller stream, and `f_auto` serves the right container per
    client. Bandwidth is still worth watching -- see docs in the media_to_cloudinary
    command for the compress-before-upload step this does not replace.
    """

    def _get_url(self, name):
        name = self._prepend_prefix(name)
        resource = cloudinary.CloudinaryResource(
            name, default_resource_type=self._get_resource_type(name)
        )
        return resource.build_url(fetch_format='auto', quality='auto')


def _local():
    """Fallback used whenever Cloudinary credentials are absent."""
    return FileSystemStorage()


def image_storage():
    """Default for ImageFields. Applied globally via STORAGES['default']."""
    if settings.USE_CLOUDINARY:
        return OptimizedImageCloudinaryStorage()
    return _local()


def video_storage():
    """For FileFields holding video, e.g. curations.CurationItem.video."""
    if settings.USE_CLOUDINARY:
        return OptimizedVideoCloudinaryStorage()
    return _local()


def raw_storage():
    """
    For FileFields holding arbitrary documents that are not identity records --
    currently tender attachments (customer drawings, plans, site photos).

    Uploaded as `raw` rather than `image` even though many of these are in fact
    photos, because raw is the only resource type that accepts a PDF and a JPEG
    through the same field. Raw also preserves the file extension in the stored
    public_id, which TenderAttachment.is_image and .filename both read.

    Not for anything covered by private_storage below.
    """
    if settings.USE_CLOUDINARY:
        return RawMediaCloudinaryStorage()
    return _local()


def private_storage():
    """
    Deliberately never Cloudinary. Do not "fix" this to match the others.

    Backs VendorDocument.file -- government ID proofs, address proofs and trade
    certificates, uploaded so an admin can verify a vendor. A Cloudinary URL is
    readable by anyone who has it: there is no per-request authorization, and a
    delivery URL is derived from the file's path rather than granted to a
    signed-in user. That is acceptable for a category icon and not acceptable
    for someone's ID.

    Keeping these on the server's own disk means they never leave
    infrastructure we control, and access can later be put behind an
    authenticated view. Media served from Cloudinary cannot be.
    """
    return _local()
