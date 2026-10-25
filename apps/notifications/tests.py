from django.test import TestCase
from django.test import override_settings
from unittest.mock import patch

from .models import Notification
from .services import send_email_notification


class EmailNotificationTests(TestCase):
    @override_settings(DEFAULT_FROM_EMAIL="noreply@example.com")
    @patch("apps.notifications.services.send_mail", side_effect=TimeoutError("SMTP connection timed out"))
    def test_smtp_timeout_is_recorded_as_failed_delivery(self, send_mail):
        notification = send_email_notification(
            "owner@example.com",
            "Franchise update",
            "Your franchise information was updated.",
        )

        self.assertEqual(notification.delivery_status, Notification.DeliveryStatus.FAILED)
        self.assertEqual(Notification.objects.count(), 1)
        send_mail.assert_called_once()
