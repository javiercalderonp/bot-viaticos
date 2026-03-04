from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)


class TwilioDailyLimitExceededError(RuntimeError):
    """Raised when Twilio blocks outbound send due to daily quota."""


@dataclass
class WhatsAppService:
    settings: Settings

    def validate_incoming_request(
        self, url: str, form_data: dict[str, Any], signature: str | None
    ) -> bool:
        if not self.settings.twilio_validate_signature:
            return True
        if not signature:
            return False
        try:
            from twilio.request_validator import RequestValidator
        except ImportError:
            return False
        validator = RequestValidator(self.settings.twilio_auth_token)
        return bool(validator.validate(url, form_data, signature))

    def build_twiml_message(self, message: str) -> str:
        safe_msg = escape(message or "")
        return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{safe_msg}</Message></Response>'

    def build_empty_twiml(self) -> str:
        return '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'

    def send_outbound_text(self, to_phone: str, message: str) -> dict[str, Any]:
        account_sid = (self.settings.twilio_account_sid or "").strip()
        auth_token = (self.settings.twilio_auth_token or "").strip()
        from_whatsapp = (self.settings.twilio_whatsapp_from or "").strip()
        if not account_sid or not auth_token or not from_whatsapp:
            raise RuntimeError(
                "Faltan credenciales/config de Twilio para envío saliente "
                "(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM)."
            )

        if not from_whatsapp.startswith("whatsapp:"):
            from_whatsapp = f"whatsapp:{from_whatsapp}"
        to_whatsapp = to_phone if str(to_phone).startswith("whatsapp:") else f"whatsapp:{to_phone}"

        try:
            from twilio.rest import Client
        except ImportError as exc:
            raise RuntimeError("Falta dependencia twilio para envío saliente.") from exc

        client = Client(account_sid, auth_token)
        try:
            twilio_message = client.messages.create(
                from_=from_whatsapp,
                to=to_whatsapp,
                body=message or "",
            )
        except Exception as exc:
            code = getattr(exc, "code", None)
            if code == 63038:
                logger.warning("Twilio daily outbound message limit reached account_sid=%s", account_sid)
                raise TwilioDailyLimitExceededError(str(exc)) from exc
            raise
        return {
            "sid": getattr(twilio_message, "sid", None),
            "status": getattr(twilio_message, "status", None),
            "to": to_whatsapp,
            "from": from_whatsapp,
        }
