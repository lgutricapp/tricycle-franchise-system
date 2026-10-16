from django.db import models


class Violation(models.Model):
    class Status(models.TextChoices):
        UNSETTLED = "UNSETTLED", "Unsettled"
        PENDING = "PENDING", "Pending"
        UNDER_REVIEW = "UNDER_REVIEW", "Under Review"
        SETTLED = "SETTLED", "Settled"

    franchise = models.ForeignKey(
        "franchises.Franchise", on_delete=models.PROTECT, related_name="violations"
    )
    violation_type = models.CharField(max_length=100)
    date = models.DateField()
    location = models.CharField(max_length=255, blank=True)
    details = models.TextField(blank=True)
    penalty_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNSETTLED)
    settlement_date = models.DateField(null=True, blank=True)
    remarks = models.TextField(blank=True)
    evidence_file = models.FileField(upload_to="violations/evidence/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.violation_type} — {self.franchise.franchise_number}"