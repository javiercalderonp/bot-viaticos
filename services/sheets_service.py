from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.config import Settings
from utils.helpers import (
    json_dumps,
    json_loads,
    normalize_whatsapp_phone,
    parse_iso_date,
    truthy,
    utc_now_iso,
)


SHEET_NAMES = {
    "employees": "Employees",
    "trips": "Trips",
    "expenses": "Expenses",
    "conversations": "Conversations",
}

_EXPENSE_REQUIRED_HEADERS = {"receipt_drive_url"}


@dataclass
class SheetsService:
    settings: Settings

    def __post_init__(self) -> None:
        self._client = None
        self._spreadsheet = None
        self._worksheet_cache: dict[str, Any] = {}
        self._memory_store: dict[str, list[dict[str, Any]]] = {
            "Employees": [],
            "Trips": [],
            "Expenses": [],
            "Conversations": [],
        }
        if self.settings.google_sheets_enabled:
            self._connect()
            self._ensure_expenses_headers()

    @property
    def enabled(self) -> bool:
        return self._spreadsheet is not None

    def _connect(self) -> None:
        try:
            import gspread
            from google.oauth2.service_account import Credentials
        except ImportError as exc:  # pragma: no cover - dependency setup
            raise RuntimeError(
                "Faltan dependencias para Google Sheets. Instala gspread y google-auth."
            ) from exc

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(
            self.settings.google_application_credentials,
            scopes=scopes,
        )
        self._client = gspread.authorize(creds)
        self._spreadsheet = self._client.open_by_key(
            self.settings.google_sheets_spreadsheet_id
        )

    def _worksheet(self, name: str):
        if not self._spreadsheet:
            return None
        cached = self._worksheet_cache.get(name)
        if cached is not None:
            return cached
        ws = self._with_retry(lambda: self._spreadsheet.worksheet(name))
        self._worksheet_cache[name] = ws
        return ws

    def _get_records(self, name: str) -> list[dict[str, Any]]:
        ws = self._worksheet(name)
        if ws is None:
            return list(self._memory_store.get(name, []))
        return self._with_retry(ws.get_all_records)

    def _append_row(self, name: str, row_dict: dict[str, Any]) -> None:
        ws = self._worksheet(name)
        if ws is None:
            self._memory_store.setdefault(name, []).append(row_dict.copy())
            return
        headers = self._with_retry(lambda: ws.row_values(1))
        row = [row_dict.get(header, "") for header in headers]
        self._with_retry(lambda: ws.append_row(row, value_input_option="USER_ENTERED"))

    def _ensure_expenses_headers(self) -> None:
        ws = self._worksheet(SHEET_NAMES["expenses"])
        if ws is None:
            return
        headers = self._with_retry(lambda: ws.row_values(1))
        missing = [header for header in _EXPENSE_REQUIRED_HEADERS if header not in headers]
        if not missing:
            return
        updated_headers = headers + missing
        self._with_retry(lambda: ws.update("A1", [updated_headers]))

    def _upsert_by_key(
        self, name: str, key_field: str, key_value: Any, payload: dict[str, Any]
    ) -> None:
        ws = self._worksheet(name)
        if ws is None:
            rows = self._memory_store.setdefault(name, [])
            for idx, row in enumerate(rows):
                if self._keys_match(key_field, row.get(key_field), key_value):
                    updated = row.copy()
                    updated.update(payload)
                    rows[idx] = updated
                    return
            rows.append(payload.copy())
            return

        headers = self._with_retry(lambda: ws.row_values(1))
        records = self._with_retry(ws.get_all_records)
        matching_rows: list[int] = []
        for index, record in enumerate(records, start=2):
            if self._keys_match(key_field, record.get(key_field, ""), key_value):
                matching_rows.append(index)
        row_number = matching_rows[-1] if matching_rows else None

        row_values = [payload.get(header, "") for header in headers]
        if row_number is None:
            self._with_retry(lambda: ws.append_row(row_values, value_input_option="USER_ENTERED"))
        else:
            start_col = "A"
            end_col = chr(ord("A") + len(headers) - 1)
            self._with_retry(
                lambda: ws.update(f"{start_col}{row_number}:{end_col}{row_number}", [row_values])
            )

    def _with_retry(self, operation, retries: int = 3, base_delay: float = 0.5):
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return operation()
            except Exception as exc:  # pragma: no cover - runtime dependency/errors
                last_exc = exc
                if not self._is_retryable_sheets_error(exc) or attempt >= retries:
                    raise
                time.sleep(base_delay * (2**attempt))
        if last_exc:
            raise last_exc
        raise RuntimeError("Unexpected retry state")

    def _is_retryable_sheets_error(self, exc: Exception) -> bool:
        status_code = getattr(exc, "code", None)
        if status_code == 429:
            return True
        response = getattr(exc, "response", None)
        if response is not None:
            try:
                if int(getattr(response, "status_code", 0)) == 429:
                    return True
            except Exception:
                pass
            text = str(getattr(response, "text", "") or "")
            if "Quota exceeded" in text or "429" in text:
                return True
        message = str(exc)
        return "Quota exceeded" in message or "[429]" in message

    def _keys_match(self, key_field: str, left_value: Any, right_value: Any) -> bool:
        if key_field == "phone":
            return normalize_whatsapp_phone(left_value) == normalize_whatsapp_phone(
                right_value
            )
        return str(left_value).strip() == str(right_value).strip()

    def get_employee_by_phone(self, phone: str) -> dict[str, Any] | None:
        target_phone = normalize_whatsapp_phone(phone)
        for row in self._get_records(SHEET_NAMES["employees"]):
            row_phone = normalize_whatsapp_phone(row.get("phone", ""))
            if row_phone != target_phone:
                continue
            if row.get("active", "") in ("", None):
                return row
            if truthy(row.get("active")):
                return row
        return None

    def get_active_trip_by_phone(self, phone: str) -> dict[str, Any] | None:
        today = parse_iso_date(utc_now_iso()[:10])
        target_phone = normalize_whatsapp_phone(phone)
        candidates: list[dict[str, Any]] = []
        for row in self._get_records(SHEET_NAMES["trips"]):
            row_phone = normalize_whatsapp_phone(row.get("phone", ""))
            if row_phone != target_phone:
                continue
            if str(row.get("status", "")).strip().lower() != "active":
                continue
            start_date = parse_iso_date(str(row.get("start_date", "")))
            end_date = parse_iso_date(str(row.get("end_date", "")))
            if today and start_date and end_date and start_date <= today <= end_date:
                return row
            candidates.append(row)
        return candidates[0] if candidates else None

    def create_expense(self, expense_data: dict[str, Any]) -> dict[str, Any]:
        self._append_row(SHEET_NAMES["expenses"], expense_data)
        return expense_data

    def get_trip_by_id(self, trip_id: str) -> dict[str, Any] | None:
        target_trip_id = str(trip_id or "").strip()
        if not target_trip_id:
            return None
        for row in self._get_records(SHEET_NAMES["trips"]):
            row_trip_id = str(row.get("trip_id", "")).strip()
            if row_trip_id == target_trip_id:
                return row
        return None

    def list_expenses_by_phone_trip(self, phone: str, trip_id: str) -> list[dict[str, Any]]:
        target_phone = normalize_whatsapp_phone(phone)
        target_trip_id = str(trip_id or "").strip()
        if not target_phone or not target_trip_id:
            return []
        expenses: list[dict[str, Any]] = []
        for row in self._get_records(SHEET_NAMES["expenses"]):
            row_phone = normalize_whatsapp_phone(row.get("phone", ""))
            row_trip_id = str(row.get("trip_id", "")).strip()
            if row_phone != target_phone or row_trip_id != target_trip_id:
                continue
            expenses.append(row)
        return expenses

    def list_active_trips(self) -> list[dict[str, Any]]:
        active_rows: list[dict[str, Any]] = []
        for row in self._get_records(SHEET_NAMES["trips"]):
            if str(row.get("status", "")).strip().lower() == "active":
                active_rows.append(row)
        return active_rows

    def get_conversation(self, phone: str) -> dict[str, Any] | None:
        target_phone = normalize_whatsapp_phone(phone)
        latest_match: dict[str, Any] | None = None
        latest_match_ts: datetime | None = None
        for row in self._get_records(SHEET_NAMES["conversations"]):
            row_phone = normalize_whatsapp_phone(row.get("phone", ""))
            if row_phone == target_phone:
                candidate = row.copy()
                candidate_ts = self._parse_updated_at(candidate.get("updated_at"))
                if latest_match is None:
                    latest_match = candidate
                    latest_match_ts = candidate_ts
                    continue
                if candidate_ts and (latest_match_ts is None or candidate_ts >= latest_match_ts):
                    latest_match = candidate
                    latest_match_ts = candidate_ts
        if latest_match is None:
            return None
        latest_match["context_json"] = json_loads(
            latest_match.get("context_json"), default={}
        )
        return latest_match

    def _parse_updated_at(self, value: Any) -> datetime | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    def update_conversation(self, phone: str, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self.get_conversation(phone) or {}
        context = payload.get("context_json")
        if isinstance(context, str):
            context_obj = json_loads(context, default={})
        else:
            context_obj = context if context is not None else existing.get("context_json", {})

        conversation = {
            "phone": phone,
            "state": payload.get("state", existing.get("state", "WAIT_RECEIPT")),
            "current_step": payload.get(
                "current_step", existing.get("current_step", "")
            ),
            "context_json": context_obj,
            "updated_at": payload.get("updated_at", utc_now_iso()),
        }
        to_sheet = conversation.copy()
        to_sheet["context_json"] = json_dumps(conversation["context_json"])
        self._upsert_by_key(SHEET_NAMES["conversations"], "phone", phone, to_sheet)
        return conversation
