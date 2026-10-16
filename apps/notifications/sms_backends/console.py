from .base import BaseSMSBackend


class ConsoleSMSBackend(BaseSMSBackend):
    def send(self, to_number, message):
        print(f"\n--- [DEV SMS] To: {to_number} ---\n{message}\n--- end SMS ---\n")
        return {"success": True, "provider_message_id": "console-dev", "raw_response": {}}