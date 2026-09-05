"""
Vendor ID documents must not be readable without a permission check.

VendorDocument.file is kept on local disk rather than Cloudinary precisely so
that access *can* be gated (config.storages.private_storage says as much). The
gate is dashboard.views.vendor_document_view; these tests are what stop the
template drifting back to a bare MEDIA_URL link, which under nginx would put
government ID proofs on the open web.
"""

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from vendors.models import Vendor, VendorDocument

from .testing import sign_in

User = get_user_model()


class VendorDocumentAccessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='doc-admin', password='sup3r-secret-pw', role=User.Role.ADMIN,
        )
        vendor_user = User.objects.create_user(
            username='9990001111', password='vendor-pw', role=User.Role.VENDOR,
        )
        self.vendor = Vendor.objects.create(user=vendor_user, service_area='North')
        self.document = VendorDocument.objects.create(
            vendor=self.vendor,
            doc_type=VendorDocument.DocType.ID_PROOF,
            file=SimpleUploadedFile('aadhaar.png', b'not-a-real-png', 'image/png'),
        )
        self.url = reverse('vendor_document', args=[self.vendor.id, self.document.id])

    def tearDown(self):
        self.document.file.delete(save=False)

    def test_signed_out_visitor_is_refused(self):
        response = self.client.get(self.url)
        self.assertNotEqual(response.status_code, 200)

    def test_admin_without_vendor_access_is_refused(self):
        sign_in(self.client, self.admin, permissions=['bookings.view'])
        response = self.client.get(self.url)
        self.assertNotEqual(response.status_code, 200)

    def test_admin_with_vendor_access_gets_the_file(self):
        sign_in(self.client, self.admin, permissions=['vendors.view'])
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'not-a-real-png')

    def test_document_of_another_vendor_is_not_reachable(self):
        """The vendor id in the URL must actually own the document id."""
        other_user = User.objects.create_user(
            username='9990002222', password='vendor-pw', role=User.Role.VENDOR,
        )
        other = Vendor.objects.create(user=other_user, service_area='South')

        sign_in(self.client, self.admin, permissions=['vendors.view'])
        response = self.client.get(
            reverse('vendor_document', args=[other.id, self.document.id])
        )
        self.assertEqual(response.status_code, 404)

    @override_settings(
        MEDIA_X_ACCEL_REDIRECT=True, MEDIA_X_ACCEL_PREFIX='/protected-media/'
    )
    def test_nginx_mode_hands_off_the_path_instead_of_the_bytes(self):
        sign_in(self.client, self.admin, permissions=['vendors.view'])
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['X-Accel-Redirect'],
            f'/protected-media/{self.document.file.name}',
        )
        # nginx supplies the body; Python must not also send one.
        self.assertEqual(response.content, b'')


class VendorDetailTemplateTests(TestCase):
    """The page must link through the gated view, never at the file itself."""

    def test_detail_page_does_not_leak_a_media_url(self):
        admin = User.objects.create_user(
            username='tpl-admin', password='sup3r-secret-pw', role=User.Role.ADMIN,
        )
        vendor_user = User.objects.create_user(
            username='9990003333', password='vendor-pw', role=User.Role.VENDOR,
        )
        vendor = Vendor.objects.create(user=vendor_user, service_area='East')
        document = VendorDocument.objects.create(
            vendor=vendor,
            doc_type=VendorDocument.DocType.ID_PROOF,
            file=SimpleUploadedFile('pan.png', b'bytes', 'image/png'),
        )
        self.addCleanup(document.file.delete, save=False)

        sign_in(self.client, admin)
        body = self.client.get(
            reverse('vendor_detail', args=[vendor.id])
        ).content.decode()

        self.assertIn(reverse('vendor_document', args=[vendor.id, document.id]), body)
        self.assertNotIn('/media/vendor_documents/', body)
