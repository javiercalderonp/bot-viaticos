from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv_file(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists() or not env_path.is_file():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_dotenv_file()


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class Settings:
    app_name: str = os.getenv("APP_NAME", "Travel Expense AI Agent")
    app_env: str = os.getenv("APP_ENV", "dev")
    debug: bool = _as_bool(os.getenv("DEBUG"), default=True)

    twilio_account_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_auth_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_whatsapp_from: str = os.getenv("TWILIO_WHATSAPP_FROM", "")
    twilio_validate_signature: bool = _as_bool(
        os.getenv("TWILIO_VALIDATE_SIGNATURE"), default=False
    )

    google_application_credentials: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    google_sheets_spreadsheet_id: str = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
    drive_receipts_folder_id: str = os.getenv("DRIVE_RECEIPTS_FOLDER_ID", "")

    document_ai_project_id: str = os.getenv("DOCUMENT_AI_PROJECT_ID", "")
    document_ai_location: str = os.getenv("DOCUMENT_AI_LOCATION", "us")
    document_ai_processor_id: str = os.getenv("DOCUMENT_AI_PROCESSOR_ID", "")

    expense_category_llm_enabled: bool = _as_bool(
        os.getenv("EXPENSE_CATEGORY_LLM_ENABLED"), default=False
    )
    chat_assistant_enabled: bool = _as_bool(
        os.getenv("CHAT_ASSISTANT_ENABLED"), default=True
    )
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_timeout_seconds: int = int(os.getenv("OPENAI_TIMEOUT_SECONDS", "12") or "12")

    default_timezone: str = os.getenv("DEFAULT_TIMEZONE", "America/Santiago")
    scheduler_endpoint_token: str = os.getenv("SCHEDULER_ENDPOINT_TOKEN", "")
    scheduler_reminder_window_minutes: int = int(
        os.getenv("SCHEDULER_REMINDER_WINDOW_MINUTES", "10") or "10"
    )
    scheduler_morning_hour_local: int = int(
        os.getenv("SCHEDULER_MORNING_HOUR_LOCAL", "9") or "9"
    )
    scheduler_evening_hour_local: int = int(
        os.getenv("SCHEDULER_EVENING_HOUR_LOCAL", "20") or "20"
    )

    @property
    def google_sheets_enabled(self) -> bool:
        return bool(
            self.google_application_credentials and self.google_sheets_spreadsheet_id
        )


settings = Settings()
