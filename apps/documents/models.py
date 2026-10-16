from django.db import models
from .validators import validate_document_file


class DocumentRequirement(models.Model):
    class ApplicationType(models.TextChoices):
        NEW = "NEW", "New Application"
        RENEWAL = "RENEWAL", "Renewal"
        BOTH = "BOTH", "Both"

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    application_type = models.CharField(
        max_length=10, choices=ApplicationType.choices, default=ApplicationType.BOTH
    )
    required = models.BooleanField(default=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


def document_upload_path(instance, filename):
    return f"applications/{instance.application_id}/req_{instance.document_requirement_id}/{filename}"


def franchise_document_path(instance, filename):
    return f"franchises/{instance.franchise_id}/req_{instance.document_requirement_id}/{filename}"


class ApplicationDocument(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending Review"
        APPROVED = "APPROVED", "Approved"
        REVISION_REQUIRED = "REVISION_REQUIRED", "Revision Required"
        REJECTED = "REJECTED", "Rejected"

    application = models.ForeignKey(
        "applications.Application", on_delete=models.CASCADE, related_name="documents"
    )
    document_requirement = models.ForeignKey(
        DocumentRequirement, on_delete=models.PROTECT, related_name="submissions"
    )
    uploaded_file = models.FileField(upload_to=document_upload_path, max_length=255, validators=[validate_document_file])
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    admin_remarks = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reviewed_documents",
    )
    supersedes = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="superseded_by_set",
    )

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.document_requirement.name} — Application #{self.application_id}"


class FranchiseDocument(models.Model):
    """A document attached directly to a franchise (used for manually added franchises)."""

    franchise = models.ForeignKey(
        "franchises.Franchise", on_delete=models.CASCADE, related_name="documents"
    )
    document_requirement = models.ForeignKey(
        DocumentRequirement, on_delete=models.PROTECT, related_name="franchise_submissions"
    )
    uploaded_file = models.FileField(upload_to=franchise_document_path, max_length=255, validators=[validate_document_file])
    uploaded_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="franchise_documents_uploaded",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["document_requirement__name"]

    def __str__(self):
        return f"{self.document_requirement.name} — {self.franchise.franchise_number}"