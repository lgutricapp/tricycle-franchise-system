import base64
import smtplib
import time

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


class EmailBackend(BaseEmailBackend):
    token_url = "https://oauth2.googleapis.com/token"
    send_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    timeout = 15

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._access_token = None
        self._token_expires_at = 0

    def send_messages(self, email_messages):
        sent_count = 0
        for email_message in email_messages:
            try:
                self._send(email_message)
            except (requests.RequestException, smtplib.SMTPException):
                if not self.fail_silently:
                    raise
            else:
                sent_count += 1
        return sent_count

    def _send(self, email_message):
        message = email_message.message()
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        response = requests.post(
            self.send_url,
            headers={"Authorization": f"Bearer {self._get_access_token()}"},
            json={"raw": raw_message},
            timeout=self.timeout,
        )
        if not response.ok:
            raise smtplib.SMTPException(
                f"Gmail API send failed with HTTP {response.status_code}."
            )

    def _get_access_token(self):
        if self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token

        credentials = {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "refresh_token": settings.GOOGLE_OAUTH_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        }
        if not all(credentials[key] for key in ("client_id", "client_secret", "refresh_token")):
            raise smtplib.SMTPException(
                "Gmail API credentials are missing. Configure the Google OAuth environment variables."
            )

        try:
            response = requests.post(self.token_url, data=credentials, timeout=self.timeout)
        except requests.RequestException as error:
            raise smtplib.SMTPException("Gmail API token request failed.") from error

        if not response.ok:
            raise smtplib.SMTPException(
                f"Gmail API token request failed with HTTP {response.status_code}."
            )

        try:
            token_data = response.json()
            self._access_token = token_data["access_token"]
            expires_in = int(token_data.get("expires_in", 3600))
        except (KeyError, TypeError, ValueError) as error:
            raise smtplib.SMTPException("Gmail API returned an invalid access token response.") from error

        self._token_expires_at = time.monotonic() + max(expires_in - 60, 0)
        return self._access_token
