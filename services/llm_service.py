from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)

ALLOWED_EXPENSE_CATEGORIES = ("Meals", "Transport", "Lodging", "Other")
KNOWN_CURRENCY_CODES = {"CLP", "USD", "PEN", "CNY", "EUR", "MXN", "ARS", "BRL", "COP"}
COUNTRY_TO_CURRENCY = {
    "CHILE": "CLP",
    "PERU": "PEN",
    "PERÚ": "PEN",
    "CHINA": "CNY",
    "UNITED STATES": "USD",
    "USA": "USD",
    "U.S.A.": "USD",
    "ESTADOS UNIDOS": "USD",
    "MEXICO": "MXN",
    "MÉXICO": "MXN",
    "ARGENTINA": "ARS",
    "BRAZIL": "BRL",
    "BRASIL": "BRL",
    "COLOMBIA": "COP",
    "SPAIN": "EUR",
    "ESPAÑA": "EUR",
    "FRANCE": "EUR",
    "ITALY": "EUR",
    "GERMANY": "EUR",
    "DEUTSCHLAND": "EUR",
}
_GENERIC_COUNTRY_VALUES = {
    "N/A",
    "NA",
    "UNKNOWN",
    "DESCONOCIDO",
    "OTRO",
    "OTHER",
}
INVALID_MERCHANT_EXACT = {
    "COMPROBANTE DE VENTA",
    "BOLETA",
    "BOLETA ELECTRONICA",
    "BOLETA ELECTRÓNICA",
    "FACTURA",
    "FACTURA ELECTRONICA",
    "FACTURA ELECTRÓNICA",
    "RECIBO",
    "TICKET",
    "TARJETA DE DEBITO",
    "TARJETA DE DÉBITO",
    "TARJETA DE CREDITO",
    "TARJETA DE CRÉDITO",
    "VISA",
    "VISA DEBITO",
    "VISA DÉBITO",
    "VISA CREDITO",
    "VISA CRÉDITO",
    "MASTERCARD",
    "COPIA CLIENTE",
}
INVALID_MERCHANT_CONTAINS = (
    "COMPROBANTE",
    "BOLETA",
    "FACTURA",
    "RECIBO",
    "TARJETA",
    "VISA",
    "MASTERCARD",
    "AMEX",
    "COPIA CLIENTE",
)

TRAVEL_AGENT_CHAT_CONTEXT = """
Eres el asistente de un agente de viaticos por WhatsApp.
Contexto base del MVP:
- El usuario puede enviar una foto de boleta por WhatsApp para registrar gastos.
- Campos obligatorios del gasto: merchant, date, total, currency, category, country, trip_id.
- Si faltan datos, el bot pregunta uno por uno.
- Cuando el gasto esta completo, el bot envia un resumen para confirmar:
  1) Confirmar 2) Corregir 3) Cancelar.
- Al confirmar, el gasto se guarda con estado pending_approval.
- Si el usuario quiere empezar un gasto nuevo, debe enviar otra foto de boleta.
- Si quiere cancelar/reiniciar flujo puede escribir: cancelar o reiniciar.
Instrucciones:
- Responde en espanol claro y corto.
- No inventes capacidades que no esten en el contexto.
- Si no sabes algo, dilo y sugiere enviar boleta o escribir con mas detalle.
""".strip()


@dataclass
class LLMService:
    settings: Any | None = None

    @property
    def category_classification_enabled(self) -> bool:
        if not self.settings:
            return False
        return bool(
            getattr(self.settings, "expense_category_llm_enabled", False)
            and getattr(self.settings, "openai_api_key", "")
        )

    @property
    def chat_assistant_enabled(self) -> bool:
        if not self.settings:
            return False
        return bool(
            getattr(self.settings, "chat_assistant_enabled", True)
            and getattr(self.settings, "openai_api_key", "")
        )

    def answer_general_question(self, question: str) -> str | None:
        if not self.chat_assistant_enabled:
            logger.info(
                "LLM chat assistant skipped enabled=%s key_present=%s",
                bool(getattr(self.settings, "chat_assistant_enabled", True)),
                bool(getattr(self.settings, "openai_api_key", "")),
            )
            return None

        prompt = (question or "").strip()
        if not prompt:
            return None

        payload = {
            "model": getattr(self.settings, "openai_model", "gpt-4o-mini"),
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": TRAVEL_AGENT_CHAT_CONTEXT},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            answer = self._chat_text(payload)
        except Exception as exc:  # pragma: no cover - depends on network/API
            logger.warning("LLM chat assistant failed: %s", exc)
            return None

        cleaned = " ".join(str(answer or "").split()).strip()
        return cleaned or None

    def classify_expense_category(self, draft_expense: dict[str, Any]) -> str | None:
        if not self.category_classification_enabled:
            logger.info(
                "LLM category classification skipped enabled=%s key_present=%s",
                bool(getattr(self.settings, "expense_category_llm_enabled", False)),
                bool(getattr(self.settings, "openai_api_key", "")),
            )
            return None

        merchant = str(draft_expense.get("merchant", "") or "").strip()
        ocr_text = str(draft_expense.get("ocr_text", "") or "").strip()
        if not merchant and not ocr_text:
            logger.info("LLM category classification skipped missing merchant and ocr_text")
            return None

        payload = {
            "model": getattr(self.settings, "openai_model", "gpt-4o-mini"),
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You classify travel expenses into exactly one category. "
                        "Allowed categories: Meals, Transport, Lodging, Other. "
                        "Return valid JSON only with keys: category, confidence, reason. "
                        "confidence must be one of: high, medium, low."
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_classification_prompt(draft_expense),
                },
            ],
        }

        try:
            parsed = self._chat_json(payload)
        except Exception as exc:  # pragma: no cover - depends on network/API
            logger.warning("LLM category classification failed: %s", exc)
            return None

        category = str(parsed.get("category", "") or "").strip()
        if category not in ALLOWED_EXPENSE_CATEGORIES:
            logger.warning("LLM returned invalid category=%r payload=%r", category, parsed)
            return None
        logger.info(
            "LLM category classification success category=%s confidence=%s merchant=%r",
            category,
            parsed.get("confidence"),
            merchant,
        )
        return category

    def infer_expense_merchant(self, draft_expense: dict[str, Any]) -> str | None:
        if not self.category_classification_enabled:
            logger.info(
                "LLM merchant inference skipped enabled=%s key_present=%s",
                bool(getattr(self.settings, "expense_category_llm_enabled", False)),
                bool(getattr(self.settings, "openai_api_key", "")),
            )
            return None

        ocr_text = str(draft_expense.get("ocr_text", "") or "").strip()
        merchant_hint = str(draft_expense.get("merchant", "") or "").strip()
        if not ocr_text and not merchant_hint:
            logger.info("LLM merchant inference skipped missing ocr_text and merchant hint")
            return None

        payload = {
            "model": getattr(self.settings, "openai_model", "gpt-4o-mini"),
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You extract the merchant name from a receipt OCR text. "
                        "Return valid JSON only with keys: merchant, confidence, reason. "
                        "merchant must be the business/store/provider name only, not a document label. "
                        "If uncertain, return the best short merchant name. "
                        "Avoid generic values like 'COMPROBANTE DE VENTA', 'BOLETA', 'FACTURA', "
                        "'RECIBO', 'TARJETA DE DEBITO', 'VISA', 'MASTERCARD', 'COPIA CLIENTE'. "
                        "Prefer the restaurant/store name even if a payment method header appears larger."
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_merchant_prompt(draft_expense),
                },
            ],
        }

        try:
            parsed = self._chat_json(payload)
        except Exception as exc:  # pragma: no cover - depends on network/API
            logger.warning("LLM merchant inference failed: %s", exc)
            return None

        merchant = str(parsed.get("merchant", "") or "").strip()
        merchant = self._normalize_merchant_candidate(merchant)
        if not merchant:
            logger.warning("LLM merchant inference returned invalid merchant payload=%r", parsed)
            return None
        logger.info(
            "LLM merchant inference success merchant=%r confidence=%s",
            merchant,
            parsed.get("confidence"),
        )
        return merchant

    def infer_expense_country_currency(self, draft_expense: dict[str, Any]) -> dict[str, str]:
        if not self.category_classification_enabled:
            logger.info(
                "LLM country/currency inference skipped enabled=%s key_present=%s",
                bool(getattr(self.settings, "expense_category_llm_enabled", False)),
                bool(getattr(self.settings, "openai_api_key", "")),
            )
            return {}

        ocr_text = str(draft_expense.get("ocr_text", "") or "").strip()
        if not ocr_text:
            logger.info("LLM country/currency inference skipped missing ocr_text")
            return {}

        payload = {
            "model": getattr(self.settings, "openai_model", "gpt-4o-mini"),
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You identify the receipt country and transaction currency from receipt data. "
                        "Return valid JSON only with keys: country, currency, confidence, reason. "
                        "currency must be a 3-letter ISO code (e.g., CLP, USD, PEN, CNY, EUR). "
                        "Make the decision from receipt evidence only (address, city, province/state, tax IDs, mall/branch names, currency markers, OCR text). "
                        "Use this evidence priority: 1) explicit tax/country markers, 2) city/province/address/branch, 3) currency code/symbol + locale terms, 4) merchant name. "
                        "Prioritize receipt location evidence over merchant brand/name text, because brand names may reference another country. "
                        "If merchant name conflicts with receipt city/address, trust the city/address shown in the receipt. "
                        "Country clues examples: 'RUT' or 'Rol Unico Tributario' strongly indicates Chile; "
                        "'RUC' strongly indicates Peru; "
                        "'CUIT' indicates Argentina; "
                        "'NIT' often indicates Colombia; "
                        "'RFC' indicates Mexico. "
                        "Look for locality clues such as comuna/provincia/departamento, mall names, and branch labels ('sucursal', 'local'). "
                        "If evidence is mixed, choose the country with strongest direct on-receipt evidence and explain the tie-break in reason. "
                        "Do not copy placeholders like unknown/n/a."
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_country_currency_prompt(draft_expense),
                },
            ],
        }

        try:
            parsed = self._chat_json(payload)
        except Exception as exc:  # pragma: no cover - depends on network/API
            logger.warning("LLM country/currency inference failed: %s", exc)
            return {}

        country = self._normalize_country_candidate(parsed.get("country"))
        currency = self._normalize_currency_candidate(parsed.get("currency"))

        if not currency and country:
            currency = COUNTRY_TO_CURRENCY.get(country.upper())
        if not country and currency:
            country = self._infer_country_from_currency(currency)

        result: dict[str, str] = {}
        if country:
            result["country"] = country
        if currency:
            result["currency"] = currency

        if not result:
            logger.warning("LLM country/currency inference returned invalid payload=%r", parsed)
            return {}

        logger.info(
            "LLM country/currency inference success country=%r currency=%r confidence=%s",
            result.get("country"),
            result.get("currency"),
            parsed.get("confidence"),
        )
        return result

    def _build_classification_prompt(self, draft_expense: dict[str, Any]) -> str:
        merchant = draft_expense.get("merchant")
        country = draft_expense.get("country")
        currency = draft_expense.get("currency")
        total = draft_expense.get("total")
        date = draft_expense.get("date")
        ocr_text = str(draft_expense.get("ocr_text", "") or "").strip()
        ocr_text_snippet = ocr_text[:2000] if ocr_text else None

        return (
            "Classify this travel expense.\n"
            f"merchant: {merchant!r}\n"
            f"country: {country!r}\n"
            f"currency: {currency!r}\n"
            f"total: {total!r}\n"
            f"date: {date!r}\n\n"
            f"ocr_text_snippet: {ocr_text_snippet!r}\n\n"
            "Examples:\n"
            "- restaurant/cafe/coffee => Meals\n"
            "- hotel/hostel/airbnb => Lodging\n"
            "- taxi/uber/metro/airline/fuel/toll => Transport\n"
            "- anything else => Other\n"
        )

    def _build_merchant_prompt(self, draft_expense: dict[str, Any]) -> str:
        merchant_hint = draft_expense.get("merchant")
        country = draft_expense.get("country")
        total = draft_expense.get("total")
        currency = draft_expense.get("currency")
        ocr_text = str(draft_expense.get("ocr_text", "") or "").strip()
        ocr_text_snippet = ocr_text[:3000] if ocr_text else None
        return (
            "Extract the merchant name from this receipt data.\n"
            f"merchant_hint_from_ocr: {merchant_hint!r}\n"
            f"country: {country!r}\n"
            f"total: {total!r}\n"
            f"currency: {currency!r}\n"
            f"ocr_text_snippet: {ocr_text_snippet!r}\n\n"
            "Return the actual business/provider name. "
            "Do not return generic document labels or payment method labels. "
            "If you see lines like 'TARJETA DE DEBITO' and a business name like 'NIU SUSHI', "
            "return 'NIU SUSHI'."
        )

    def _build_country_currency_prompt(self, draft_expense: dict[str, Any]) -> str:
        merchant = draft_expense.get("merchant")
        country_hint = draft_expense.get("country_hint") or draft_expense.get("country")
        currency_hint = draft_expense.get("currency")
        total = draft_expense.get("total")
        date = draft_expense.get("date")
        ocr_text = str(draft_expense.get("ocr_text", "") or "").strip()
        ocr_text_snippet = ocr_text[:3500] if ocr_text else None
        return (
            "Identify the country and currency used in this receipt.\n"
            f"merchant_hint: {merchant!r}\n"
            f"country_hint_from_ocr_or_trip: {country_hint!r}\n"
            f"currency_hint_from_ocr: {currency_hint!r}\n"
            f"total: {total!r}\n"
            f"date: {date!r}\n"
            f"ocr_text_snippet: {ocr_text_snippet!r}\n\n"
            "Use receipt evidence first and be intuitive with local clues. "
            "Prioritize city/address/province/branch/mall location written on the receipt over the merchant name. "
            "Pay attention to country-specific tax words: RUT (Chile), RUC (Peru), CUIT (Argentina), NIT (Colombia), RFC (Mexico). "
            "If a city/province appears, infer the country from that location even if the merchant name suggests another country. "
            "If the country is clear but currency is missing, infer the typical local currency. "
            "If the receipt clearly shows a currency code/symbol, prefer that.\n\n"
            "Conflict example:\n"
            "- merchant name says 'MISTURA DEL PERU' but receipt address/city says 'Santiago' => country should be Chile, currency likely CLP.\n"
            "- receipt includes 'RUT' and 'Santiago Centro' => country should be Chile even if merchant brand has foreign wording."
        )

    def _normalize_merchant_candidate(self, merchant: str | None) -> str | None:
        if not merchant:
            return None
        cleaned = " ".join(str(merchant).split()).strip(" -:|")
        if not cleaned:
            return None
        upper = cleaned.upper()
        if upper in INVALID_MERCHANT_EXACT:
            return None
        if any(token in upper for token in INVALID_MERCHANT_CONTAINS) and len(upper) <= 40:
            return None
        return cleaned

    def _normalize_currency_candidate(self, currency: Any) -> str | None:
        if currency is None:
            return None
        cleaned = "".join(ch for ch in str(currency).upper().strip() if ch.isalpha())
        if len(cleaned) != 3:
            return None
        if cleaned in KNOWN_CURRENCY_CODES:
            return cleaned
        return cleaned

    def _normalize_country_candidate(self, country: Any) -> str | None:
        if country is None:
            return None
        cleaned = " ".join(str(country).split()).strip(" -:|,")
        if not cleaned:
            return None
        upper = cleaned.upper()
        if upper in _GENERIC_COUNTRY_VALUES:
            return None
        return cleaned

    def _infer_country_from_currency(self, currency: str) -> str | None:
        mapping = {
            "CLP": "Chile",
            "PEN": "Peru",
            "CNY": "China",
            "USD": "United States",
            "MXN": "Mexico",
            "ARS": "Argentina",
            "BRL": "Brazil",
            "COP": "Colombia",
            "EUR": "Spain",
        }
        return mapping.get((currency or "").upper())

    def _post_openai_chat_completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        base_url = (getattr(self.settings, "openai_base_url", "") or "https://api.openai.com/v1").rstrip("/")
        url = f"{base_url}/chat/completions"
        timeout = int(getattr(self.settings, "openai_timeout_seconds", 12) or 12)
        api_key = str(getattr(self.settings, "openai_api_key", "") or "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY no configurada")

        body = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "TravelExpenseAgent/1.0",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:  # pragma: no cover - depends on network/API
            detail = ""
            try:
                detail = exc.read().decode("utf-8")
            except Exception:
                detail = str(exc)
            raise RuntimeError(f"OpenAI HTTP {exc.code}: {detail}") from exc
        except URLError as exc:  # pragma: no cover - depends on network/API
            raise RuntimeError("No se pudo conectar a OpenAI") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Respuesta no JSON desde OpenAI") from exc

    def _chat_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = self._post_openai_chat_completions(payload)
        return self._extract_json_message(raw)

    def _chat_text(self, payload: dict[str, Any]) -> str:
        raw = self._post_openai_chat_completions(payload)
        return self._extract_text_message(raw)

    def _extract_json_message(self, response: dict[str, Any]) -> dict[str, Any]:
        choices = response.get("choices") or []
        if not choices:
            raise RuntimeError("OpenAI sin choices")
        message = choices[0].get("message") or {}
        content = message.get("content")

        if isinstance(content, str):
            return json.loads(content)

        # Compatibilidad defensiva si el proveedor devuelve estructura por partes.
        if isinstance(content, list):
            text_parts: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    text_parts.append(part["text"])
            if text_parts:
                return json.loads("".join(text_parts))

        raise RuntimeError("No se pudo extraer JSON de la respuesta del modelo")

    def _extract_text_message(self, response: dict[str, Any]) -> str:
        choices = response.get("choices") or []
        if not choices:
            raise RuntimeError("OpenAI sin choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    text_parts.append(part["text"])
            if text_parts:
                return "".join(text_parts)
        raise RuntimeError("No se pudo extraer texto de la respuesta del modelo")
