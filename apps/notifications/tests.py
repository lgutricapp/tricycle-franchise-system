from django.test import TestCase
from django.test import override_settings
from unittest.mock import patch

from .models import Notification
from .services import send_email_notification
from .views import _report_results


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


class NotificationDeliveryFeedbackTests(TestCase):
    def notification(self, channel, delivery_status):
        return Notification(channel=channel, delivery_status=delivery_status)

    @patch("apps.notifications.views.messages.success")
    def test_sms_success_is_reported_as_sent_by_sms(self, success):
        results = [self.notification(Notification.Channel.SMS, Notification.DeliveryStatus.SENT)]

        self.assertTrue(_report_results(None, results, "Maria Santos"))

        success.assert_called_once_with(None, "Message sent to Maria Santos by SMS.")

    @patch("apps.notifications.views.messages.success")
    def test_successful_channel_is_success_when_other_channel_fails(self, success):
        results = [
            self.notification(Notification.Channel.SMS, Notification.DeliveryStatus.SENT),
            self.notification(Notification.Channel.EMAIL, Notification.DeliveryStatus.FAILED),
        ]

        self.assertTrue(_report_results(None, results, "Maria Santos"))

        success.assert_called_once_with(
            None, "Message sent to Maria Santos by SMS. Delivery failed by email."
        )

    @patch("apps.notifications.views.messages.error")
    def test_reports_failure_when_no_channel_succeeds(self, error):
        results = [
            self.notification(Notification.Channel.SMS, Notification.DeliveryStatus.FAILED),
            self.notification(Notification.Channel.EMAIL, Notification.DeliveryStatus.FAILED),
        ]

        self.assertTrue(_report_results(None, results, "Maria Santos"))

        error.assert_called_once_with(
            None,
            "The message to Maria Santos could not be delivered by SMS and email. "
            "See the notification history.",
        )
