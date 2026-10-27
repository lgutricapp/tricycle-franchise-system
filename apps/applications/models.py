import secrets
from django.db import models

REFERENCE_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I — avoids visual ambiguity
CURRENT_POLICY_VERSION = "2026-10-18"


def generate_reference_code(length=10):
    return "".join(secrets.choice(REFERENCE_CODE_ALPHABET) for _ in range(length))


class Application(models.Model):
    class ApplicationType(models.TextChoices):
        NEW = "NEW", "New Application"
        RENEWAL = "RENEWAL", "Renewal"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        UNDER_REVIEW = "UNDER_REVIEW", "Under Review"
        REVISION_REQUIRED = "REVISION_REQUIRED", "Revision Required"
        RESUBMITTED = "RESUBMITTED", "Resubmitted"
        FOR_APPROVAL = "FOR_APPROVAL", "For Approval"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"
        COMPLETED = "COMPLETED", "Completed"

    reference_code = models.CharField(max_length=10, unique=True, editable=False)
    applicant = models.ForeignKey(
        "applicants.Applicant", on_delete=models.PROTECT, related_name="applications"
    )
    vehicle = models.ForeignKey(
        "franchises.Vehicle", on_delete=models.PROTECT, null=True, blank=True,
        related_name="applications",
    )
    franchise = models.ForeignKey(
        "franchises.Franchise", on_delete=models.PROTECT, null=True, blank=True,
        related_name="applications",
    )
    type = models.CharField(max_length=10, choices=ApplicationType.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    submitted_at = models.DateTimeField(null=True, blank=True)
    policy_accepted_at = models.DateTimeField(null=True, blank=True)
    policy_version_accepted = models.CharField(max_length=20, blank=True)
    franchise_number_unlocked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.reference_code:
            code = generate_reference_code()
            while Application.objects.filter(reference_code=code).exists():
                code = generate_reference_code()
            self.reference_code = code
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference_code} ({self.get_type_display()})"


class StatusHistory(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="status_history")
    status = models.CharField(max_length=20, choices=Application.Status.choices)
    changed_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="status_changes",
    )
    changed_at = models.DateTimeField(auto_now_add=True)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-changed_at"]
        verbose_name_plural = "Status histories"

    def __str__(self):
        return f"{self.application.reference_code} → {self.status}"