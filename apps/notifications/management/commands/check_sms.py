import re

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.module_loading import import_string

API_BASE = "https://api.semaphore.co/api/v4"


class Command(BaseCommand):
    help = "Check the SMS provider connection, send a test SMS, or look up message statuses."

    def add_arguments(self, parser):
        parser.add_argument("--send", metavar="NUMBER", help="Send a test SMS to this number (uses credits).")
        parser.add_argument("--message", metavar="TEXT", help="Custom text for the test SMS.")
        parser.add_argument("--status", metavar="MESSAGE_ID", help="Look up one message's status by its id.")
        parser.add_argument("--recent", metavar="COUNT", type=int, help="List your most recent messages and their statuses.")
        parser.add_argument("--skip-check", action="store_true", help="Skip the account/credit check.")

    def handle(self, *args, **options):
        self.stdout.write(f"SMS backend: {settings.SMS_BACKEND}")
        self.stdout.write(f"Sender name: {settings.SMS_SENDER_NAME or '(account default)'}")

        key = settings.SMS_API_KEY or ""
        if "semaphore" in settings.SMS_BACKEND.lower():
            self.stdout.write(f"API key loaded: {'yes' if key else 'NO (empty)'} (length {len(key)})")
            if not options["skip_check"]:
                self._check_account(key)

        if options["send"]:
            self._send_test(options)
        if options["status"]:
            self._show_status(options["status"], key)
        if options["recent"]:
            self._show_recent(options["recent"], key)

    def _get(self, path, key, extra=None):
        params = {"apikey": key}
        if extra:
            params.update(extra)
        try:
            response = requests.get(f"{API_BASE}{path}", params=params, timeout=10)
        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f"Could not reach Semaphore: {e}"))
            return None, None

        if response.status_code == 429:
            self.stdout.write(self.style.WARNING(
                "Semaphore rate limit hit (HTTP 429). Wait a minute and try again "
                "(the account check allows only 2 calls per minute; add --skip-check)."
            ))
            return response, None

        try:
            return response, response.json()
        except ValueError:
            self.stdout.write(self.style.ERROR(
                f"HTTP {response.status_code}, not JSON: {response.text[:200] or '(empty reply)'}"
            ))
            return response, None

    def _check_account(self, key):
        response, data = self._get("/account", key)
        if data is None:
            return
        if response.status_code == 200 and isinstance(data, dict) and "credit_balance" in data:
            self.stdout.write(self.style.SUCCESS(
                f"Connected. Account: {data.get('account_name')} | "
                f"Status: {data.get('status')} | Credits: {data.get('credit_balance')}"
            ))
        else:
            self.stdout.write(self.style.ERROR(f"Semaphore did not accept the key: {data}"))

    def _show_status(self, message_id, key):
        response, data = self._get(f"/messages/{message_id}", key)
        if data is None:
            return
        if isinstance(data, list) and data:
            data = data[0]
        if isinstance(data, dict) and "status" in data:
            self.stdout.write(
                f"Message {message_id}: status={data.get('status')} | to={data.get('recipient')} | "
                f"network={data.get('network')} | sender={data.get('sender_name')}"
            )
        else:
            self.stdout.write(self.style.ERROR(f"Unexpected reply (HTTP {response.status_code}): {data}"))

    def _show_recent(self, count, key):
        response, data = self._get("/messages", key, {"limit": count})
        if data is None:
            return
        if not isinstance(data, list):
            self.stdout.write(self.style.ERROR(f"Unexpected reply (HTTP {response.status_code}): {data}"))
            return
        if not data:
            self.stdout.write("No messages found.")
            return
        for m in data:
            text = (m.get("message") or "").replace("\n", " ")
            self.stdout.write(
                f"{m.get('created_at')} | {m.get('recipient')} | {m.get('status')} | "
                f"{m.get('network')} | {m.get('sender_name')} | {text[:70]}"
            )

    def _send_test(self, options):
        text = options["message"] or "Hello from the Tricycle Franchise System. This is a delivery check."
        if re.match(r"test\b", text.strip(), re.IGNORECASE):
            self.stdout.write(self.style.ERROR(
                "Semaphore silently ignores messages that begin with the word TEST. Reword the message."
            ))
            return

        backend = import_string(settings.SMS_BACKEND)()
        result = backend.send(options["send"], text)
        if result["success"]:
            self.stdout.write(self.style.SUCCESS(f"SMS accepted. Message id: {result['provider_message_id']}"))
        else:
            self.stdout.write(self.style.ERROR(f"SMS failed: {result['raw_response']}"))