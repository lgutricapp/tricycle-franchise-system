import smtplib
from unittest.mock import Mock, patch

from django.core.mail import EmailMessage
from django.test import SimpleTestCase, TestCase
from django.test import override_settings

from .email_backends.gmail_api import EmailBackend
from .models import Notification
from .services import send_email_notification
from .views import _report_results


class GmailApiEmailBackendTests(SimpleTestCase):
    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="client-id",
        GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
        GOOGLE_OAUTH_REFRESH_TOKEN="refresh-token",
    )
    @patch("apps.notifications.email_backends.gmail_api.requests.post")
    def test_sends_email_using_refreshed_oauth_token(self, post):
        token_response = Mock(ok=True)
        token_response.json.return_value = {"access_token": "access-token", "expires_in": 3600}
        sent_response = Mock(ok=True)
        post.side_effect = [token_response, sent_response]
        message = EmailMessage(
            "Subject", "Body", "sender@example.com", ["recipient@example.com"]
        )

        self.assertEqual(EmailBackend().send_messages([message]), 1)

        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer access-token")
        self.assertIn("raw", post.call_args.kwargs["json"])

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="",
        GOOGLE_OAUTH_CLIENT_SECRET="",
        GOOGLE_OAUTH_REFRESH_TOKEN="",
    )
    def test_missing_oauth_configuration_fails_explicitly(self):
        message = EmailMessage("Subject", "Body", "sender@example.com", ["recipient@example.com"])

        with self.assertRaisesRegex(smtplib.SMTPException, "credentials are missing"):
            EmailBackend().send_messages([message])


class EmailNotificationTests(TestCase):
    @override_settings(DEFAULT_FROM_EMAIL="noreply@example.com")
    @patch("apps.notifications.services.send_mail", side_effect=TimeoutError("Email request timed out"))
    def test_email_timeout_is_recorded_as_failed_delivery(self, send_mail):
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
