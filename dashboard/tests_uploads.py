"""
Tests for the file inputs on the dashboard's edit forms.

Every one of them offers the same three outcomes, and the third is the one
that did not exist before: an edit form could only ever *add*, so an image put
on a service by mistake stayed there for good.

  upload nothing   keep what is there
  choose a file    replace it
  tick Remove      clear it
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from services.models import Service, ServiceCategory, SubCategory

from .testing import sign_in

# The smallest thing Django's ImageField will accept as an image.
GIF = (
    b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00'
    b'\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00'
    b'\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b'
)


def an_image(name='pic.gif'):
    return SimpleUploadedFile(name, GIF, content_type='image/gif')


class ServiceImageTests(TestCase):
    def setUp(self):
        admin = User.objects.create_user(
            username='fileadmin', password='pw12345', role=User.Role.ADMIN,
        )
        sign_in(self.client, admin)
        self.category = ServiceCategory.objects.create(name='Plumbing')
        self.service = Service.objects.create(
            category=self.category, name='Tap repair', price=500,
            image=an_image(),
        )

    def _post(self, **overrides):
        payload = {
            'name': self.service.name,
            'description': '',
            'price': '500',
            'pricing_type': 'FIXED',
            'duration_minutes': '60',
            'is_active': 'on',
        }
        payload.update(overrides)
        return self.client.post(
            reverse('service_edit', args=[self.service.id]), payload)

    def test_saving_without_touching_it_keeps_the_image(self):
        before = self.service.image.name

        self.assertEqual(self._post(name='Tap repair v2').status_code, 302)

        self.service.refresh_from_db()
        self.assertEqual(self.service.image.name, before)

    def test_choosing_a_file_replaces_it(self):
        before = self.service.image.name

        self._post(image=an_image('replacement.gif'))

        self.service.refresh_from_db()
        self.assertTrue(self.service.image)
        self.assertNotEqual(self.service.image.name, before)

    def test_ticking_remove_clears_it(self):
        self._post(image_clear='on')

        self.service.refresh_from_db()
        self.assertFalse(self.service.image)

    def test_a_new_file_wins_over_the_remove_tick(self):
        """Choosing a file is the clearer intent of the two."""
        self._post(image=an_image('replacement.gif'), image_clear='on')

        self.service.refresh_from_db()
        self.assertTrue(self.service.image)

    def test_removing_when_there_is_nothing_to_remove_is_harmless(self):
        self.service.image = None
        self.service.save()

        self.assertEqual(self._post(image_clear='on').status_code, 302)
        self.service.refresh_from_db()
        self.assertFalse(self.service.image)


class CategoryIconTests(TestCase):
    def setUp(self):
        admin = User.objects.create_user(
            username='fileadmin2', password='pw12345', role=User.Role.ADMIN,
        )
        sign_in(self.client, admin)
        self.category = ServiceCategory.objects.create(
            name='Plumbing', icon=an_image())
        self.subcategory = SubCategory.objects.create(
            category=self.category, name='Bathroom', icon=an_image())

    def test_a_category_icon_can_be_removed(self):
        self.client.post(
            reverse('category_edit', args=[self.category.id]),
            {
                'name': self.category.name,
                'description': '',
                'base_price': '0',
                'sort_order': '0',
                'is_active': 'on',
                'icon_clear': 'on',
            },
        )

        self.category.refresh_from_db()
        self.assertFalse(self.category.icon)

    def test_a_subcategory_icon_can_be_removed(self):
        self.client.post(
            reverse('subcategory_edit', args=[self.subcategory.id]),
            {
                'name': self.subcategory.name,
                'description': '',
                'base_price': '0',
                'is_active': 'on',
                'icon_clear': 'on',
            },
        )

        self.subcategory.refresh_from_db()
        self.assertFalse(self.subcategory.icon)

    def test_an_untouched_icon_survives_an_edit(self):
        before = self.category.icon.name

        self.client.post(
            reverse('category_edit', args=[self.category.id]),
            {
                'name': 'Plumbing & Drains',
                'description': '',
                'base_price': '0',
                'sort_order': '0',
                'is_active': 'on',
            },
        )

        self.category.refresh_from_db()
        self.assertEqual(self.category.icon.name, before)
        self.assertEqual(self.category.name, 'Plumbing & Drains')


class UploadHelperTests(TestCase):
    """The helper on its own, including the paths a form cannot easily reach."""

    def setUp(self):
        self.category = ServiceCategory.objects.create(name='Plumbing')
        self.service = Service.objects.create(
            category=self.category, name='Tap repair', price=500,
            image=an_image(),
        )

    def _request(self, post=None, files=None):
        from django.test import RequestFactory

        request = RequestFactory().post('/', data=post or {})
        request.FILES.update(files or {})
        return request

    def test_it_reports_whether_anything_changed(self):
        from .uploads import apply_uploaded_file

        untouched = apply_uploaded_file(
            self._request(), self.service, 'image')
        self.assertFalse(untouched)

        cleared = apply_uploaded_file(
            self._request({'image_clear': 'on'}), self.service, 'image')
        self.assertTrue(cleared)

    def test_a_storage_that_will_not_delete_still_clears_the_record(self):
        """
        The reference is what the admin was asking about. A remote that has
        already lost the file must not fail the whole save.
        """
        from unittest.mock import patch

        from .uploads import apply_uploaded_file

        with patch(
            'django.db.models.fields.files.FieldFile.delete',
            side_effect=OSError('storage is down'),
        ):
            changed = apply_uploaded_file(
                self._request({'image_clear': 'on'}), self.service, 'image')

        self.assertTrue(changed)
        self.assertFalse(self.service.image)
