import json
import tempfile
from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from apps.applicants.models import Applicant
from apps.applications.models import Application
from .models import document_upload_path, franchise_document_path
from .storage import GoogleDriveStorage
from .validators import validate_document_file


class DocumentValidatorTests(SimpleTestCase):
    def test_valid_pdf_passes(self):
        file = SimpleUploadedFile("clearance.pdf", b"%PDF-1.4 fake pdf content", content_type="application/pdf")
        validate_document_file(file)  # should not raise

    def test_valid_jpg_passes(self):
        file = SimpleUploadedFile("photo.jpg", b"\xff\xd8\xff\xe0 fake jpg content", content_type="image/jpeg")
        validate_document_file(file)  # should not raise

    def test_disallowed_extension_is_rejected(self):
        file = SimpleUploadedFile("script.exe", b"MZ fake exe content", content_type="application/octet-stream")
        with self.assertRaises(ValidationError):
            validate_document_file(file)

    def test_mislabeled_file_is_rejected(self):
        # A .pdf extension but the actual content is plain text, not a real PDF.
        file = SimpleUploadedFile("fake.pdf", b"this is just plain text, not a pdf", content_type="application/pdf")
        with self.assertRaises(ValidationError):
            validate_document_file(file)

    def test_oversized_file_is_rejected(self):
        big_content = b"%PDF-1.4" + b"a" * (6 * 1024 * 1024)  # 6MB, over the 5MB limit
        file = SimpleUploadedFile("big.pdf", big_content, content_type="application/pdf")
        with self.assertRaises(ValidationError):
            validate_document_file(file)


class DocumentUploadPathTests(SimpleTestCase):
    @patch("apps.documents.models.timezone.localdate", return_value=date(2026, 10, 31))
    def test_application_document_uses_requirement_name_and_upload_date(self, _localdate):
        document = SimpleNamespace(
            application_id=15,
            document_requirement_id=4,
            document_requirement=SimpleNamespace(name="Health Certificate"),
        )

        path = document_upload_path(document, "my-uploaded-file.PDF")

        self.assertEqual(
            path,
            "applications/15/req_4/Health Certificate - 2026-10-31.PDF",
        )

    @patch("apps.documents.models.timezone.localdate", return_value=date(2026, 10, 31))
    def test_franchise_document_sanitizes_requirement_name(self, _localdate):
        document = SimpleNamespace(
            franchise_id=8,
            document_requirement_id=3,
            document_requirement=SimpleNamespace(name="ID/Passport"),
        )

        path = franchise_document_path(document, "original.jpg")

        self.assertEqual(
            path,
            "franchises/8/req_3/ID-Passport - 2026-10-31.jpg",
        )


class GoogleDriveStorageTests(SimpleTestCase):
    @override_settings(
        GOOGLE_DRIVE_FOLDER_ID="folder-id",
        GOOGLE_OAUTH_CLIENT_ID="client-id",
        GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
        GOOGLE_DRIVE_REFRESH_TOKEN="refresh-token",
    )
    @patch("apps.documents.storage.requests.request")
    @patch("apps.documents.storage.requests.post")
    def test_save_uploads_to_configured_folder(self, token_request, drive_request):
        token_request.return_value = Mock(
            ok=True,
            json=Mock(return_value={"access_token": "access-token", "expires_in": 3600}),
        )
        drive_request.return_value = Mock(
            ok=True,
            status_code=200,
            json=Mock(return_value={"id": "drive-file-id"}),
        )
        storage = GoogleDriveStorage()
        content = ContentFile(b"%PDF-1.4 document", name="identity.pdf")

        saved_name = storage.save("franchises/12/req_3/identity.pdf", content)

        self.assertEqual(saved_name, "drive/drive-file-id")
        upload_call = drive_request.call_args
        self.assertEqual(upload_call.args[:2], ("post", storage.upload_url))
        metadata = json.loads(upload_call.kwargs["files"]["metadata"][1])
        self.assertEqual(metadata, {"name": "identity.pdf", "parents": ["folder-id"]})

    @override_settings(GOOGLE_DRIVE_FOLDER_ID="parent-folder-id")
    @patch("apps.documents.storage.transaction.atomic", return_value=nullcontext())
    @patch("apps.documents.storage.timezone.localdate", return_value=date(2026, 10, 31))
    @patch.object(Application.objects, "only")
    @patch.object(Applicant.objects, "select_for_update")
    def test_application_upload_creates_and_reuses_applicant_folder(
        self, select_for_update, application_only, _localdate, _atomic
    ):
        applicant = SimpleNamespace(
            first_name="Ada",
            last_name="Lovelace",
            google_drive_folder_id="",
            save=Mock(),
        )
        select_for_update.return_value.get.return_value = applicant
        application_only.return_value.get.return_value = SimpleNamespace(applicant_id=42)
        storage = GoogleDriveStorage()
        storage._request = Mock(
            return_value=Mock(json=Mock(return_value={"id": "ada-folder-id"}))
        )

        folder_id = storage._folder_id_for_name("applications/15/req_2/id.pdf")

        self.assertEqual(folder_id, "ada-folder-id")
        self.assertEqual(applicant.google_drive_folder_id, "ada-folder-id")
        applicant.save.assert_called_once_with(update_fields=["google_drive_folder_id"])
        self.assertEqual(storage._request.call_args.kwargs["json"], {
            "name": "Ada Lovelace 2026-10-31",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": ["parent-folder-id"],
        })

        storage._request.reset_mock()
        self.assertEqual(
            storage._folder_id_for_name("applications/15/req_3/new-id.pdf"),
            "ada-folder-id",
        )
        storage._request.assert_not_called()

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="client-id",
        GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
        GOOGLE_DRIVE_REFRESH_TOKEN="refresh-token",
    )
    @patch("apps.documents.storage.requests.request")
    @patch("apps.documents.storage.requests.post")
    def test_open_downloads_drive_document_and_retains_filename(
        self, token_request, drive_request
    ):
        token_request.return_value = Mock(
            ok=True,
            json=Mock(return_value={"access_token": "access-token", "expires_in": 3600}),
        )
        drive_request.side_effect = [
            Mock(ok=True, status_code=200, json=Mock(return_value={"name": "identity.pdf"})),
            Mock(ok=True, status_code=200, content=b"%PDF-1.4 document"),
        ]
        storage = GoogleDriveStorage()

        with storage.open("drive/drive-file-id", "rb") as document:
            self.assertEqual(document.name, "identity.pdf")
            self.assertEqual(document.read(), b"%PDF-1.4 document")

        self.assertEqual(
            drive_request.call_args_list[1].args[:2],
            ("get", f"{storage.api_url}/drive-file-id"),
        )
        self.assertEqual(
            drive_request.call_args_list[1].kwargs["params"],
            {"alt": "media"},
        )

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="client-id",
        GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
        GOOGLE_DRIVE_REFRESH_TOKEN="refresh-token",
    )
    @patch("apps.documents.storage.requests.request")
    @patch("apps.documents.storage.requests.post")
    def test_drive_api_error_includes_google_reason_without_raw_error_message(
        self, token_request, drive_request
    ):
        token_request.return_value = Mock(
            ok=True,
            json=Mock(return_value={"access_token": "access-token", "expires_in": 3600}),
        )
        drive_request.return_value = Mock(
            ok=False,
            status_code=403,
            json=Mock(return_value={
                "error": {
                    "status": "PERMISSION_DENIED",
                    "message": "Sensitive provider details",
                    "errors": [{"reason": "insufficientPermissions"}],
                },
            }),
        )
        storage = GoogleDriveStorage()

        with self.assertRaisesRegex(OSError, "HTTP 403.*insufficientPermissions") as error:
            storage.exists("drive/drive-file-id")

        self.assertNotIn("Sensitive provider details", str(error.exception))

    @override_settings(
        GOOGLE_DRIVE_FOLDER_ID="folder-id",
        GOOGLE_OAUTH_CLIENT_ID="",
        GOOGLE_OAUTH_CLIENT_SECRET="",
        GOOGLE_DRIVE_REFRESH_TOKEN="",
    )
    def test_drive_upload_fails_explicitly_without_credentials(self):
        storage = GoogleDriveStorage()

        with self.assertRaisesMessage(OSError, "Google Drive credentials are missing"):
            storage.save("franchises/12/req_3/identity.pdf", ContentFile(b"document"))

    def test_old_local_document_names_still_open_from_media_root(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                storage = GoogleDriveStorage()
                storage.local_storage.save(
                    "applications/12/req_3/identity.pdf",
                    ContentFile(b"existing local document"),
                )

                with storage.open("applications/12/req_3/identity.pdf", "rb") as document:
                    self.assertEqual(document.read(), b"existing local document")