from django.db import models


class Notification(models.Model):
    class Channel(models.TextChoices):
        SMS = "SMS", "SMS"
        EMAIL = "EMAIL", "Email"

    class DeliveryStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"
        DELIVERED = "DELIVERED", "Delivered"

    channel = models.CharField(max_length=10, choices=Channel.choices)
    recipient_contact = models.CharField(max_length=255)
    message = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)
    sent_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sent_notifications",
    )
    delivery_status = models.CharField(
        max_length=20, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING
    )

    # Optional context links — nullable, so a Notification can exist without
    # being tied to a specific application (e.g. a general SMS blast).
    application = models.ForeignKey(
        "applications.Application", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="notifications",
    )
    franchise = models.ForeignKey(
        "franchises.Franchise", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="notifications",
    )

    class Meta:
        ordering = ["-sent_at"]

    def __str__(self):
        return f"{self.channel} to {self.recipient_contact} ({self.delivery_status})"