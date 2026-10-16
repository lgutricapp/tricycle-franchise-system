import logging
import re

import requests
from django.conf import settings

from .base import BaseSMSBackend

logger = logging.getLogger(__name__)


def normalize_ph_number(raw):
    """Return the number as 09XXXXXXXXX, or None if it isn't a valid PH mobile number."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("63") and len(digits) == 12:
        digits = "0" + digits[2:]
    elif len(digits) == 10 and digits.startswith("9"):
        digits = "0" + digits
    return digits if re.fullmatch(r"09\d{9}", digits) else None


class SemaphoreSMSBackend(BaseSMSBackend):
    API_URL = "https://api.semaphore.co/api/v4/messages"

    def send(self, to_number, message):
        number = normalize_ph_number(to_number)
        if number is None:
            logger.warning("Semaphore SMS skipped: %r is not a valid Philippine mobile number.", to_number)
            return {"success": False, "provider_message_id": None,
                    "raw_response": {"error": "invalid number"}}
        
        if re.match(r"test\b", (message or "").strip(), re.IGNORECASE):
            logger.warning("Semaphore silently ignores messages that begin with 'TEST'; not sent.")
            return {"success": False, "provider_message_id": None,
                    "raw_response": {"error": "message starts with the word TEST"}}

        payload = {"apikey": settings.SMS_API_KEY, "number": number, "message": message}
        if settings.SMS_SENDER_NAME:
            payload["sendername"] = settings.SMS_SENDER_NAME

        try:
            response = requests.post(self.API_URL, data=payload, timeout=10)
        except requests.RequestException as e:
            logger.warning("Semaphore SMS request failed: %s", e)
            return {"success": False, "provider_message_id": None, "raw_response": {"error": str(e)}}

        try:
            data = response.json()
        except ValueError:
            logger.warning(
                "Semaphore returned a non-JSON response (HTTP %s): %s",
                response.status_code, response.text[:300],
            )
            return {"success": False, "provider_message_id": None,
                    "raw_response": {"error": "non-JSON response", "http_status": response.status_code}}

        accepted = (
            response.status_code == 200
            and isinstance(data, list)
            and bool(data)
            and "message_id" in data[0]
        )
        if not accepted:
            logger.warning("Semaphore rejected the SMS (HTTP %s): %s", response.status_code, data)
            return {"success": False, "provider_message_id": None, "raw_response": data}

        return {"success": True, "provider_message_id": str(data[0]["message_id"]), "raw_response": data}