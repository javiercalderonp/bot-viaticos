from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime
from typing import Any


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def normalize_whatsapp_phone(value: Any) -> str:
    if not value:
        return ""

    # Google Sheets puede devolver teléfonos como int/float si la celda fue interpretada como número.
    if isinstance(value, float) and value.is_integer():
        value = int(value)

    normalized = str(value).strip()
    if normalized.endswith(".0") and re.fullmatch(r"\d+\.0", normalized):
        normalized = normalized[:-2]

    if normalized.startswith("whatsapp:"):
        normalized = normalized.split(":", 1)[1]
    normalized = normalized.strip()
    if normalized.startswith("+"):
        return normalized
    digits = re.sub(r"\D+", "", normalized)
    return f"+{digits}" if digits else ""


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True)


def json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y", "si", "sí"}


def make_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
