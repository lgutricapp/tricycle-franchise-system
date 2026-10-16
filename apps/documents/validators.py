import os
from django.core.exceptions import ValidationError

ALLOWED_EXTENSIONS = [".pdf", ".jpg", ".jpeg", ".png"]
MAX_UPLOAD_SIZE_MB = 5

# Known file signatures ("magic bytes") for the types we accept.
MAGIC_SIGNATURES = {
    b"%PDF": "pdf",
    b"\xff\xd8\xff": "jpg",
    b"\x89PNG\r\n\x1a\n": "png",
}


def validate_document_file(file):
    ext = os.path.splitext(file.name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file type '{ext}'. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}."
        )

    if file.size > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise ValidationError(f"File too large. Maximum size is {MAX_UPLOAD_SIZE_MB}MB.")

    file.seek(0)
    header = file.read(8)
    file.seek(0)  # reset the read pointer so Django can still save the file afterward

    if not any(header.startswith(sig) for sig in MAGIC_SIGNATURES):
        raise ValidationError(
            "This file's content doesn't match a supported PDF/JPG/PNG format. "
            "It may be corrupted or mislabeled."
        )