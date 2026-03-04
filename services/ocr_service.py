from __future__ import annotations

import base64
import mimetypes
import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_ENTITY_TYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "merchant": (
        "supplier_name",
        "merchant_name",
        "vendor_name",
        "seller_name",
        "company_name",
    ),
    "date": (
        "receipt_date",
        "invoice_date",
        "transaction_date",
        "payment_date",
        "date",
    ),
    "total": (
        "total_amount",
        "amount_due",
        "grand_total",
        "total",
        "net_amount",
    ),
    "currency": (
        "currency",
        "currency_code",
    ),
    "country": (
        "country",
        "merchant_country",
        "supplier_address.country",
        "vendor_address.country",
    ),
}

_GENERIC_MERCHANT_TERMS = {
    "comprobante de venta",
    "boleta",
    "boleta electronica",
    "boleta electrónica",
    "factura",
    "factura electronica",
    "factura electrónica",
    "ticket",
    "recibo",
    "tarjeta de debito",
    "tarjeta de débito",
    "tarjeta de credito",
    "tarjeta de crédito",
    "visa",
    "visa debito",
    "visa débito",
    "mastercard",
    "copia cliente",
}


class OCRProcessingError(RuntimeError):
    pass


@dataclass
class OCRService:
    settings: Any | None = None

    def extract_receipt_data(self, media_url: str, media_content_type: str | None = None) -> dict[str, Any]:
        if not self._document_ai_enabled:
            return self._placeholder_extract(media_url)

        content, mime_type = self._download_media(media_url, media_content_type)
        document = self._process_document_ai(content, mime_type)
        extracted = self._map_document_to_expense_fields(document)
        extracted["category"] = None
        return extracted

    @property
    def _document_ai_enabled(self) -> bool:
        if not self.settings:
            return False
        return bool(
            getattr(self.settings, "document_ai_project_id", "")
            and getattr(self.settings, "document_ai_location", "")
            and getattr(self.settings, "document_ai_processor_id", "")
        )

    def _placeholder_extract(self, media_url: str) -> dict[str, Any]:
        url = (media_url or "").lower()
        today = date.today().isoformat()

        currency = "CLP"
        country = None
        merchant = "Comercio OCR"
        total = 12500.0

        if "usd" in url:
            currency = "USD"
            total = 12.5
        if "pen" in url or "lima" in url or "peru" in url:
            currency = "PEN"
            country = "Peru"
            total = 35.0
        if "starbucks" in url:
            merchant = "Starbucks"
        elif "uber" in url:
            merchant = "Uber"
        elif "hotel" in url:
            merchant = "Hotel"

        # Intencionalmente deja category/country a veces vacíos para probar slot filling.
        return {
            "merchant": merchant,
            "date": today,
            "total": total,
            "currency": currency,
            "country": country,
            "category": None,
        }

    def _download_media(
        self,
        media_url: str,
        media_content_type: str | None,
    ) -> tuple[bytes, str]:
        if not media_url:
            raise OCRProcessingError("MediaUrl0 vacío")

        headers = {"User-Agent": "TravelExpenseAgent/1.0"}
        basic_auth = self._twilio_basic_auth_header()
        if basic_auth:
            headers["Authorization"] = basic_auth

        request = Request(media_url, headers=headers)
        try:
            with urlopen(request, timeout=20) as response:
                content = response.read()
                response_mime = response.headers.get_content_type()
        except HTTPError as exc:  # pragma: no cover - depende de red externa
            raise OCRProcessingError(f"Error HTTP descargando media Twilio: {exc.code}") from exc
        except URLError as exc:  # pragma: no cover - depende de red externa
            raise OCRProcessingError("No se pudo descargar la imagen de la boleta") from exc

        if not content:
            raise OCRProcessingError("La imagen descargada está vacía")

        mime_type = self._resolve_mime_type(media_url, media_content_type, response_mime)
        return content, mime_type

    def _twilio_basic_auth_header(self) -> str | None:
        if not self.settings:
            return None
        sid = (getattr(self.settings, "twilio_account_sid", "") or "").strip()
        token = (getattr(self.settings, "twilio_auth_token", "") or "").strip()
        if not sid or not token:
            return None
        raw = f"{sid}:{token}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def _resolve_mime_type(
        self,
        media_url: str,
        media_content_type: str | None,
        response_mime: str | None,
    ) -> str:
        candidates = [media_content_type, response_mime]
        for candidate in candidates:
            if candidate and "/" in candidate:
                return candidate.split(";", 1)[0].strip().lower()

        guessed, _ = mimetypes.guess_type(media_url or "")
        if guessed:
            return guessed
        return "image/jpeg"

    def _process_document_ai(self, content: bytes, mime_type: str):
        try:
            from google.api_core.client_options import ClientOptions
            from google.cloud import documentai
        except ImportError as exc:  # pragma: no cover - depende de instalación local
            raise OCRProcessingError(
                "Falta dependencia google-cloud-documentai. Instala requirements.txt."
            ) from exc

        location = getattr(self.settings, "document_ai_location", "us") or "us"
        client_options = None
        if location != "us":
            client_options = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
        client = documentai.DocumentProcessorServiceClient(client_options=client_options)
        name = client.processor_path(
            getattr(self.settings, "document_ai_project_id", ""),
            location,
            getattr(self.settings, "document_ai_processor_id", ""),
        )
        raw_document = documentai.RawDocument(content=content, mime_type=mime_type)
        request = documentai.ProcessRequest(name=name, raw_document=raw_document)
        try:
            result = client.process_document(request=request)
        except Exception as exc:  # pragma: no cover - depende de API externa
            raise OCRProcessingError(f"Document AI no pudo procesar la boleta: {exc}") from exc
        return result.document

    def _map_document_to_expense_fields(self, document: Any) -> dict[str, Any]:
        entities = self._flatten_entities(getattr(document, "entities", []) or [])
        text = getattr(document, "text", "") or ""

        merchant = self._pick_entity_text(entities, "merchant")
        merchant = self._normalize_merchant_name(merchant)
        if not merchant:
            merchant = self._infer_merchant_from_text(text)
        parsed_date = self._pick_date_value(entities) or self._extract_date_from_text(text)
        total, money_currency = self._pick_total_value(entities, text)
        currency = (
            self._pick_currency_value(entities)
            or money_currency
            or self._infer_currency_from_text(text)
        )
        country = self._pick_entity_text(entities, "country") or self._infer_country_from_text(text)

        return {
            "merchant": merchant,
            "date": parsed_date,
            "total": total,
            "currency": currency,
            "country": country,
            "ocr_text": text[:4000] if text else None,
        }

    def _flatten_entities(self, entities: list[Any]) -> list[Any]:
        flat: list[Any] = []
        for entity in entities:
            flat.append(entity)
            children = getattr(entity, "properties", None) or []
            flat.extend(self._flatten_entities(list(children)))
        return flat

    def _pick_entity_text(self, entities: list[Any], target: str) -> str | None:
        aliases = set(_ENTITY_TYPE_ALIASES.get(target, ()))
        for entity in entities:
            entity_type = (getattr(entity, "type_", "") or "").lower()
            if entity_type in aliases:
                value = self._entity_text_value(entity)
                if value:
                    return value
        return None

    def _pick_date_value(self, entities: list[Any]) -> str | None:
        aliases = set(_ENTITY_TYPE_ALIASES["date"])
        for entity in entities:
            entity_type = (getattr(entity, "type_", "") or "").lower()
            if entity_type not in aliases:
                continue
            normalized = getattr(entity, "normalized_value", None)
            date_value = getattr(normalized, "date_value", None)
            if date_value and getattr(date_value, "year", 0):
                year = int(getattr(date_value, "year", 0))
                month = int(getattr(date_value, "month", 1) or 1)
                day = int(getattr(date_value, "day", 1) or 1)
                try:
                    return date(year, month, day).isoformat()
                except ValueError:
                    pass
            mention = self._entity_text_value(entity)
            parsed = self._normalize_date_text(mention)
            if parsed:
                return parsed
        return None

    def _pick_total_value(self, entities: list[Any], text: str) -> tuple[float | None, str | None]:
        aliases = set(_ENTITY_TYPE_ALIASES["total"])
        for entity in entities:
            entity_type = (getattr(entity, "type_", "") or "").lower()
            if entity_type not in aliases:
                continue
            normalized = getattr(entity, "normalized_value", None)
            money_value = getattr(normalized, "money_value", None)
            if money_value is not None:
                units = float(getattr(money_value, "units", 0) or 0)
                nanos = float(getattr(money_value, "nanos", 0) or 0) / 1_000_000_000
                amount = round(units + nanos, 2)
                currency = (getattr(money_value, "currency_code", "") or "").upper() or None
                if amount:
                    return amount, currency
            amount = self._parse_amount_text(self._entity_text_value(entity))
            if amount is not None:
                return amount, self._infer_currency_from_text(self._entity_text_value(entity) or "")
        return self._extract_total_from_text(text), None

    def _pick_currency_value(self, entities: list[Any]) -> str | None:
        aliases = set(_ENTITY_TYPE_ALIASES["currency"])
        for entity in entities:
            entity_type = (getattr(entity, "type_", "") or "").lower()
            if entity_type not in aliases:
                continue
            value = (self._entity_text_value(entity) or "").upper()
            if value in {"CLP", "USD", "PEN", "CNY"}:
                return value
            if "SOL" in value or "PEN" in value:
                return "PEN"
            if "DOLAR" in value or "USD" in value:
                return "USD"
        return None

    def _entity_text_value(self, entity: Any) -> str | None:
        normalized = getattr(entity, "normalized_value", None)
        if normalized is not None:
            text_val = getattr(normalized, "text", None)
            if text_val:
                return str(text_val).strip()
        mention = getattr(entity, "mention_text", None)
        if mention:
            return str(mention).strip()
        return None

    def _extract_date_from_text(self, text: str) -> str | None:
        return self._normalize_date_text(text)

    def _normalize_date_text(self, text: str | None) -> str | None:
        if not text:
            return None
        text = text.strip()
        match = re.search(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b", text)
        if match:
            year, month, day = map(int, match.groups())
            try:
                return date(year, month, day).isoformat()
            except ValueError:
                return None

        match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", text)
        if not match:
            return None

        day, month, year = match.groups()
        year_i = int(year)
        if year_i < 100:
            year_i += 2000
        try:
            return date(year_i, int(month), int(day)).isoformat()
        except ValueError:
            return None

    def _extract_total_from_text(self, text: str) -> float | None:
        if not text:
            return None
        total_line_match = re.search(
            r"(?:total|importe|monto)\D{0,10}([0-9][0-9\., ]+)",
            text,
            flags=re.IGNORECASE,
        )
        if total_line_match:
            parsed = self._parse_amount_text(total_line_match.group(1))
            if parsed is not None:
                return parsed
        return None

    def _parse_amount_text(self, text: str | None) -> float | None:
        if not text:
            return None
        cleaned = re.sub(r"[^\d,.\-]", "", text)
        if not cleaned:
            return None

        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif cleaned.count(",") == 1 and cleaned.count(".") == 0:
            whole, frac = cleaned.split(",", 1)
            if len(frac) == 3 and len(whole) >= 1:
                cleaned = whole + frac
            else:
                cleaned = whole + "." + frac
        elif cleaned.count(".") == 1 and cleaned.count(",") == 0:
            whole, frac = cleaned.split(".", 1)
            if len(frac) == 3 and len(whole) >= 1:
                cleaned = whole + frac
        elif cleaned.count(".") > 1 and cleaned.count(",") == 0:
            cleaned = cleaned.replace(".", "")

        try:
            return float(cleaned)
        except ValueError:
            return None

    def _infer_currency_from_text(self, text: str) -> str | None:
        upper = (text or "").upper()
        if "PEN" in upper or "S/" in upper or "SOLES" in upper or "SOL" in upper:
            return "PEN"
        if "USD" in upper or "US$" in upper or "DOLAR" in upper:
            return "USD"
        if "CLP" in upper:
            return "CLP"
        if "CNY" in upper or "RMB" in upper:
            return "CNY"
        return None

    def _infer_country_from_text(self, text: str) -> str | None:
        upper = (text or "").upper()
        if "PERU" in upper:
            return "Peru"
        if "CHILE" in upper:
            return "Chile"
        if "CHINA" in upper:
            return "China"
        return None

    def _normalize_merchant_name(self, merchant: str | None) -> str | None:
        if not merchant:
            return None
        normalized = re.sub(r"\s+", " ", merchant).strip()
        if not normalized:
            return None
        lower = normalized.lower()
        if lower in _GENERIC_MERCHANT_TERMS:
            return None
        if any(term in lower for term in _GENERIC_MERCHANT_TERMS) and len(lower) <= 40:
            return None
        return normalized

    def _infer_merchant_from_text(self, text: str) -> str | None:
        if not text:
            return None

        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
        candidates: list[str] = []
        for line in lines[:20]:
            if not line:
                continue
            lower = line.lower()
            if len(line) < 3 or len(line) > 60:
                continue
            if not re.search(r"[a-zA-Z]", line):
                continue
            if re.search(
                r"\b(total|fecha|date|ruc|nro|numero|n[°º]|invoice|receipt|terminal|hora|monto|propina|tarjeta|visa|mastercard)\b",
                lower,
            ):
                continue
            if lower in _GENERIC_MERCHANT_TERMS or any(term in lower for term in _GENERIC_MERCHANT_TERMS):
                continue
            # Filtra líneas mayormente numéricas/código.
            digits = sum(ch.isdigit() for ch in line)
            letters = sum(ch.isalpha() for ch in line)
            if digits > letters:
                continue
            candidates.append(line)

        if not candidates:
            return None
        return candidates[0]
