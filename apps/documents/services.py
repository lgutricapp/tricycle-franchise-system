from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.services import log_action
from .validators import validate_document_file


def review_document(document, new_status, actor, remarks=""):
    document.status = new_status
    document.admin_remarks = remarks
    document.reviewed_at = timezone.now()
    document.reviewed_by = actor
    document.save()
    log_action(actor, "document_reviewed", document, {"status": new_status, "remarks": remarks})
    return document


def validate_document_uploads(files, requirements):
    """
    Checks required documents are present and every uploaded file is valid.
    `files` is request.FILES. Returns (missing_required_names, file_errors, valid_files),
    where valid_files maps requirement.id -> uploaded file.
    """
    missing, errors, valid = [], [], {}
    for req in requirements:
        uploaded = files.get(f"document_{req.id}")
        if not uploaded:
            if req.required:
                missing.append(req.name)
            continue
        try:
            validate_document_file(uploaded)
            valid[req.id] = uploaded
        except ValidationError as e:
            errors.append(f"{req.name}: {'; '.join(e.messages)}")
    return missing, errors, valid