from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from .validators import validate_document_file


class DocumentValidatorTests(TestCase):
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