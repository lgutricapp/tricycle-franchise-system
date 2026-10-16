class BaseSMSBackend:
    def send(self, to_number: str, message: str) -> dict:
        """
        Send an SMS. Must return a dict with at least:
        {"success": bool, "provider_message_id": str | None, "raw_response": dict}
        """
        raise NotImplementedError