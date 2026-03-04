from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.config import Settings
from services.sheets_service import SheetsService
from services.whatsapp_service import WhatsAppService
from utils.helpers import normalize_whatsapp_phone, parse_iso_date, utc_now_iso


logger = logging.getLogger(__name__)

_COUNTRY_TIMEZONE_MAP = {
    "CHILE": "America/Santiago",
    "PERU": "America/Lima",
    "PERÚ": "America/Lima",
    "CHINA": "Asia/Shanghai",
    "MEXICO": "America/Mexico_City",
    "MÉXICO": "America/Mexico_City",
    "ARGENTINA": "America/Argentina/Buenos_Aires",
    "COLOMBIA": "America/Bogota",
    "BRAZIL": "America/Sao_Paulo",
    "BRASIL": "America/Sao_Paulo",
    "SPAIN": "Europe/Madrid",
    "ESPAÑA": "Europe/Madrid",
    "FRANCE": "Europe/Paris",
    "ITALY": "Europe/Rome",
    "GERMANY": "Europe/Berlin",
    "DEUTSCHLAND": "Europe/Berlin",
    "UNITED STATES": "America/New_York",
    "USA": "America/New_York",
    "U.S.A.": "America/New_York",
    "ESTADOS UNIDOS": "America/New_York",
}

_DESTINATION_TIMEZONE_MAP = {
    "santiago": "America/Santiago",
    "lima": "America/Lima",
    "beijing": "Asia/Shanghai",
    "shanghai": "Asia/Shanghai",
    "cdmx": "America/Mexico_City",
    "mexico city": "America/Mexico_City",
    "buenos aires": "America/Argentina/Buenos_Aires",
    "bogota": "America/Bogota",
    "bogotá": "America/Bogota",
    "sao paulo": "America/Sao_Paulo",
    "são paulo": "America/Sao_Paulo",
    "madrid": "Europe/Madrid",
    "paris": "Europe/Paris",
    "rome": "Europe/Rome",
    "roma": "Europe/Rome",
    "berlin": "Europe/Berlin",
    "new york": "America/New_York",
    "miami": "America/New_York",
    "los angeles": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
}


@dataclass
class SchedulerService:
    settings: Settings
    sheets_service: SheetsService
    whatsapp_service: WhatsAppService

    def start(self) -> None:
        # MVP: se ejecuta por endpoint + cron externo/job scheduler.
        return None

    def run_trip_reminders(
        self,
        *,
        dry_run: bool = False,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        now = self._ensure_utc(now_utc)
        report: dict[str, Any] = {
            "ok": True,
            "dry_run": dry_run,
            "now_utc": now.isoformat(),
            "window_minutes": self._window_minutes,
            "processed_trips": 0,
            "due_trips": 0,
            "sent_count": 0,
            "skipped_count": 0,
            "errors": [],
            "items": [],
        }

        for trip in self.sheets_service.list_active_trips():
            report["processed_trips"] += 1
            item = self._evaluate_trip_reminder(trip=trip, now_utc=now, dry_run=dry_run)
            report["items"].append(item)
            if item.get("due"):
                report["due_trips"] += 1
            outcome = item.get("outcome")
            if outcome == "sent":
                report["sent_count"] += 1
            elif outcome != "not_due":
                report["skipped_count"] += 1
            if item.get("error"):
                report["errors"].append(item["error"])

        return report

    @property
    def _window_minutes(self) -> int:
        return max(1, int(getattr(self.settings, "scheduler_reminder_window_minutes", 10) or 10))

    def _ensure_utc(self, value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _evaluate_trip_reminder(
        self,
        *,
        trip: dict[str, Any],
        now_utc: datetime,
        dry_run: bool,
    ) -> dict[str, Any]:
        phone = normalize_whatsapp_phone(trip.get("phone"))
        trip_id = str(trip.get("trip_id", "") or "").strip()
        timezone_name = self._resolve_trip_timezone(trip)
        local_now = now_utc.astimezone(ZoneInfo(timezone_name))
        local_date = local_now.date()
        destination = str(trip.get("destination", "") or "").strip()

        item: dict[str, Any] = {
            "trip_id": trip_id,
            "phone": phone,
            "destination": destination,
            "country": trip.get("country"),
            "timezone": timezone_name,
            "local_now": local_now.isoformat(),
            "due": False,
            "outcome": "not_due",
        }

        if not phone:
            item["outcome"] = "skipped_invalid_phone"
            return item

        if not self._trip_is_active_on_local_date(trip, local_date):
            item["outcome"] = "skipped_outside_trip_window"
            return item

        start_intro_key = self._trip_start_intro_key(trip_id=trip_id, local_date=local_date.isoformat())
        if self._trip_start_intro_due(trip=trip, local_now=local_now) and not self._reminder_already_sent(
            phone, start_intro_key
        ):
            item["due"] = True
            item["slot"] = "trip_start_intro"
            item["reminder_key"] = start_intro_key
            message = self._build_trip_start_intro_message(trip=trip)
            item["message"] = message

            if dry_run:
                item["outcome"] = "sent"
                item["dry_run"] = True
                return item

            try:
                send_result = self.whatsapp_service.send_outbound_text(phone, message)
            except Exception as exc:  # pragma: no cover - depends on Twilio/network
                logger.exception("Trip start intro send failed trip_id=%s phone=%s", trip_id, phone)
                item["outcome"] = "error"
                item["error"] = str(exc)
                return item

            self._mark_reminder_sent(
                phone=phone,
                reminder_key=start_intro_key,
                payload={
                    "sent_at_utc": utc_now_iso(),
                    "slot": "trip_start_intro",
                    "trip_id": trip_id,
                    "timezone": timezone_name,
                    "twilio_message_sid": send_result.get("sid"),
                },
            )
            item["outcome"] = "sent"
            item["send_result"] = send_result
            return item

        reminder_slot = self._current_slot(local_now)
        if not reminder_slot:
            return item

        item["due"] = True
        item["slot"] = reminder_slot
        reminder_key = self._reminder_key(trip_id=trip_id, local_date=local_date.isoformat(), slot=reminder_slot)
        item["reminder_key"] = reminder_key

        if self._reminder_already_sent(phone, reminder_key):
            item["outcome"] = "skipped_already_sent"
            return item

        message = self._build_trip_reminder_message(trip=trip, slot=reminder_slot)
        item["message"] = message

        if dry_run:
            item["outcome"] = "sent"
            item["dry_run"] = True
            return item

        try:
            send_result = self.whatsapp_service.send_outbound_text(phone, message)
        except Exception as exc:  # pragma: no cover - depends on Twilio/network
            logger.exception("Trip reminder send failed trip_id=%s phone=%s", trip_id, phone)
            item["outcome"] = "error"
            item["error"] = str(exc)
            return item

        self._mark_reminder_sent(
            phone=phone,
            reminder_key=reminder_key,
            payload={
                "sent_at_utc": utc_now_iso(),
                "slot": reminder_slot,
                "trip_id": trip_id,
                "timezone": timezone_name,
                "twilio_message_sid": send_result.get("sid"),
            },
        )
        item["outcome"] = "sent"
        item["send_result"] = send_result
        return item

    def _trip_is_active_on_local_date(self, trip: dict[str, Any], local_date) -> bool:
        start_date = parse_iso_date(trip.get("start_date"))
        end_date = parse_iso_date(trip.get("end_date"))
        if start_date and end_date:
            return start_date <= local_date <= end_date
        return str(trip.get("status", "")).strip().lower() == "active"

    def _trip_start_intro_due(self, *, trip: dict[str, Any], local_now: datetime) -> bool:
        start_date = parse_iso_date(trip.get("start_date"))
        if not start_date or local_now.date() != start_date:
            return False
        morning_hour = int(getattr(self.settings, "scheduler_morning_hour_local", 9) or 9)
        return local_now.hour == morning_hour and local_now.minute < self._window_minutes

    def _current_slot(self, local_now: datetime) -> str | None:
        target_hours = {
            int(getattr(self.settings, "scheduler_morning_hour_local", 9) or 9): "morning_0900",
            int(getattr(self.settings, "scheduler_evening_hour_local", 20) or 20): "evening_2000",
        }
        slot = target_hours.get(local_now.hour)
        if not slot:
            return None
        if local_now.minute >= self._window_minutes:
            return None
        return slot

    def _resolve_trip_timezone(self, trip: dict[str, Any]) -> str:
        destination = str(trip.get("destination", "") or "").strip().lower()
        for key, tz_name in _DESTINATION_TIMEZONE_MAP.items():
            if key in destination:
                return tz_name

        country = str(trip.get("country", "") or "").strip().upper()
        if country in _COUNTRY_TIMEZONE_MAP:
            return _COUNTRY_TIMEZONE_MAP[country]

        default_tz = (getattr(self.settings, "default_timezone", "") or "America/Santiago").strip()
        try:
            ZoneInfo(default_tz)
            return default_tz
        except Exception:
            return "America/Santiago"

    def _build_trip_reminder_message(self, *, trip: dict[str, Any], slot: str) -> str:
        destination = str(trip.get("destination", "") or "").strip()
        destination_text = f" en {destination}" if destination else ""
        if slot.startswith("morning"):
            return (
                f"🌅 ¡Buen día! Recordatorio de viáticos{destination_text}:\n"
                "Guarda tus boletas de hoy y envíalas por este chat cuando tengas un minuto 🙌"
            )
        return (
            f"🌙 Cierre del día{destination_text}:\n"
            "Si tienes boletas pendientes, envíalas ahora por este chat para dejar tu registro al día ✅"
        )

    def _build_trip_start_intro_message(self, *, trip: dict[str, Any]) -> str:
        destination = str(trip.get("destination", "") or "").strip()
        destination_text = f" a {destination}" if destination else ""
        return (
            f"👋 Hola, soy tu agente de viáticos. ¡Buen viaje{destination_text}!\n"
            "Funciona así: cada vez que tengas una boleta, envíame una foto por este chat 📸\n"
            "Yo extraigo los datos, te pido lo que falte y dejo el gasto registrado ✅"
        )

    def _reminder_key(self, *, trip_id: str, local_date: str, slot: str) -> str:
        trip_id_safe = trip_id or "NO_TRIP"
        return f"trip_reminder:{trip_id_safe}:{local_date}:{slot}"

    def _trip_start_intro_key(self, *, trip_id: str, local_date: str) -> str:
        trip_id_safe = trip_id or "NO_TRIP"
        return f"trip_intro:{trip_id_safe}:{local_date}"

    def _reminder_already_sent(self, phone: str, reminder_key: str) -> bool:
        conversation = self.sheets_service.get_conversation(phone) or {}
        context = conversation.get("context_json")
        if not isinstance(context, dict):
            return False
        scheduler_ctx = context.get("scheduler")
        if not isinstance(scheduler_ctx, dict):
            return False
        sent = scheduler_ctx.get("sent_reminders")
        if not isinstance(sent, dict):
            return False
        return reminder_key in sent

    def _mark_reminder_sent(self, *, phone: str, reminder_key: str, payload: dict[str, Any]) -> None:
        conversation = self.sheets_service.get_conversation(phone) or {}
        context = conversation.get("context_json")
        if not isinstance(context, dict):
            context = {}

        scheduler_ctx = context.get("scheduler")
        if not isinstance(scheduler_ctx, dict):
            scheduler_ctx = {}
        sent = scheduler_ctx.get("sent_reminders")
        if not isinstance(sent, dict):
            sent = {}

        sent[reminder_key] = payload
        scheduler_ctx["sent_reminders"] = sent
        context["scheduler"] = scheduler_ctx
        context.setdefault("draft_expense", {})
        context.setdefault("missing_fields", [])
        context.setdefault("last_question", None)

        self.sheets_service.update_conversation(
            phone,
            {
                "state": conversation.get("state", "WAIT_RECEIPT"),
                "current_step": conversation.get("current_step", ""),
                "context_json": context,
            },
        )
