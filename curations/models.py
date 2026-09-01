from django.db import models

from config.storages import video_storage


class CurationSection(models.Model):
    title = models.CharField(max_length=200, help_text="e.g. Thoughtful curations")
    subtitle = models.CharField(max_length=300, blank=True, help_text="e.g. of our finest experiences")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', '-created_at']
        verbose_name_plural = "Curation Sections"

    def __str__(self):
        return self.title


class CurationItem(models.Model):
    section = models.ForeignKey(
        CurationSection, on_delete=models.CASCADE, related_name='items'
    )
    title = models.CharField(max_length=200, help_text="Text overlay on the card")
    thumbnail = models.ImageField(upload_to='curation_thumbnails/')
    # Uploaded as a Cloudinary video, not an image: only the video resource
    # type can transcode and stream, and these files run to 100 MB+.
    video = models.FileField(upload_to='curation_videos/', storage=video_storage)
    service = models.ForeignKey(
        'services.Service', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='curation_items',
        help_text="Service shown at the bottom of the video screen"
    )
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order']

    def __str__(self):
        return f"{self.section.title} → {self.title}"