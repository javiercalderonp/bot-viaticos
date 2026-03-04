from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.expense_service import ExpenseService
from utils.helpers import json_loads


WAIT_RECEIPT = "WAIT_RECEIPT"
PROCESSING = "PROCESSING"
NEEDS_INFO = "NEEDS_INFO"
CONFIRM_SUMMARY = "CONFIRM_SUMMARY"
DONE = "DONE"

FIELD_PROMPTS = {
    "merchant": "¿Cuál es el comercio/merchant?",
    "date": "¿Cuál es la fecha? (formato YYYY-MM-DD)",
    "total": "¿Cuál es el total del gasto? (solo número)",
    "currency": "¿Cuál es la moneda?\n1. CLP\n2. USD\n3. PEN\n4. CNY",
    "category": "¿Cuál es la categoría?\n1. Meals\n2. Transport\n3. Lodging\n4. Other",
    "country": "¿En qué país fue el gasto?\n1. Chile\n2. Peru\n3. China\n4. Otro (escribir texto)",
    "trip_id": "No encontré viaje activo. Indica el trip_id del viaje.",
}

CURRENCY_OPTIONS = {"1": "CLP", "2": "USD", "3": "PEN", "4": "CNY"}
CATEGORY_OPTIONS = {"1": "Meals", "2": "Transport", "3": "Lodging", "4": "Other"}
COUNTRY_OPTIONS = {"1": "Chile", "2": "Peru", "3": "China"}
CORRECTION_FIELD_OPTIONS = {
    "1": "merchant",
    "2": "date",
    "3": "total",
    "4": "currency",
    "5": "category",
    "6": "country",
}
CORRECTION_FIELD_ALIASES = {
    "merchant": "merchant",
    "comercio": "merchant",
    "tienda": "merchant",
    "fecha": "date",
    "date": "date",
    "total": "total",
    "monto": "total",
    "importe": "total",
    "moneda": "currency",
    "currency": "currency",
    "categoria": "category",
    "categoría": "category",
    "category": "category",
    "pais": "country",
    "país": "country",
    "country": "country",
}
CORRECTION_FIELD_LABELS = {
    "merchant": "merchant",
    "date": "fecha",
    "total": "total",
    "currency": "moneda",
    "category": "categoría",
    "country": "país",
}


@dataclass
class ConversationService:
    expense_service: ExpenseService

    def default_context(self) -> dict[str, Any]:
        return {
            "draft_expense": {},
            "missing_fields": [],
            "last_question": None,
            "scheduler": {"sent_reminders": {}},
        }

    def ensure_conversation(self, conversation: dict[str, Any] | None) -> dict[str, Any]:
        if not conversation:
            return {
                "state": WAIT_RECEIPT,
                "current_step": "",
                "context_json": self.default_context(),
            }
        context = conversation.get("context_json")
        if isinstance(context, str):
            context = json_loads(context, default=self.default_context())
        if not isinstance(context, dict):
            context = self.default_context()
        scheduler_ctx = context.get("scheduler")
        if not isinstance(scheduler_ctx, dict):
            scheduler_ctx = {"sent_reminders": {}}
        sent_reminders = scheduler_ctx.get("sent_reminders")
        if not isinstance(sent_reminders, dict):
            sent_reminders = {}
        normalized_context = dict(context)
        normalized_context["draft_expense"] = context.get("draft_expense", {})
        normalized_context["missing_fields"] = context.get("missing_fields", [])
        normalized_context["last_question"] = context.get("last_question")
        normalized_context["scheduler"] = {
            **scheduler_ctx,
            "sent_reminders": sent_reminders,
        }
        conversation["context_json"] = normalized_context
        conversation.setdefault("state", WAIT_RECEIPT)
        conversation.setdefault("current_step", "")
        return conversation

    def begin_processing(self, phone: str) -> dict[str, Any]:
        return {
            "phone": phone,
            "state": PROCESSING,
            "current_step": "",
            "context_json": self.default_context(),
        }

    def process_ocr_result(
        self,
        phone: str,
        ocr_data: dict[str, Any],
        trip: dict[str, Any] | None,
    ) -> dict[str, Any]:
        draft = dict(ocr_data or {})
        if trip:
            draft.setdefault("trip_id", trip.get("trip_id"))
            if not draft.get("country_hint"):
                draft["country_hint"] = trip.get("country")

        draft = self.expense_service.enrich_draft_expense(draft)

        missing = self.expense_service.find_missing_required_fields(draft)
        if missing:
            first_field = missing[0]
            return {
                "phone": phone,
                "state": NEEDS_INFO,
                "current_step": first_field,
                "context_json": {
                    "draft_expense": draft,
                    "missing_fields": missing,
                    "last_question": first_field,
                },
                "reply": self.prompt_for_field(first_field),
            }

        return {
            "phone": phone,
            "state": CONFIRM_SUMMARY,
            "current_step": "confirm_summary",
            "context_json": {
                "draft_expense": draft,
                "missing_fields": [],
                "last_question": None,
            },
            "reply": self.expense_service.build_summary_message(draft),
        }

    def handle_text_message(self, conversation: dict[str, Any], text: str) -> dict[str, Any]:
        conversation = self.ensure_conversation(conversation)
        state = conversation.get("state", WAIT_RECEIPT)
        context = conversation["context_json"]
        message = (text or "").strip()
        normalized = message.lower()

        if normalized in {"cancelar", "cancel", "salir", "reiniciar", "reset"}:
            return {
                "state": WAIT_RECEIPT,
                "current_step": "",
                "context_json": self.default_context(),
                "reply": "Flujo cancelado y reiniciado. Envíame una boleta para comenzar de nuevo.",
                "action": "cancel",
            }

        if state in {WAIT_RECEIPT, DONE}:
            answer = self._answer_general_question_if_needed(message)
            if answer:
                return {
                    "state": WAIT_RECEIPT,
                    "current_step": "",
                    "context_json": context,
                    "reply": (
                        f"{answer}\n\n"
                        "Si quieres registrar un gasto, envíame una foto de la boleta."
                    ),
                    "action": "noop",
                }
            return {
                "state": WAIT_RECEIPT,
                "current_step": "",
                "context_json": context,
                "reply": "Envíame una foto de la boleta para procesar el gasto.",
                "action": "noop",
            }

        if state == PROCESSING:
            return {
                "state": PROCESSING,
                "current_step": "",
                "context_json": context,
                "reply": "Estoy procesando tu boleta. Espera un momento o envía otra foto si quieres reintentar.",
                "action": "noop",
            }

        if state == NEEDS_INFO:
            return self._handle_needs_info(context, message)

        if state == CONFIRM_SUMMARY:
            return self._handle_confirm_summary(
                context=context,
                message=message,
                current_step=conversation.get("current_step", ""),
            )

        return {
            "state": WAIT_RECEIPT,
            "current_step": "",
            "context_json": self.default_context(),
            "reply": "No entendí el estado actual. Envíame una boleta para comenzar.",
            "action": "reset",
        }

    def _handle_needs_info(self, context: dict[str, Any], message: str) -> dict[str, Any]:
        draft = dict(context.get("draft_expense", {}))
        missing = list(context.get("missing_fields", []))
        current_field = missing[0] if missing else context.get("last_question")

        if not current_field:
            missing = self.expense_service.find_missing_required_fields(draft)
            current_field = missing[0] if missing else None

        if not current_field:
            return self._to_confirm_summary(draft)

        parsed_value = self._parse_field_value(current_field, message)
        if parsed_value is None:
            answer = self._answer_general_question_if_needed(message)
            if answer:
                reply = (
                    f"{answer}\n\n"
                    f"Para continuar con este gasto:\n{self.prompt_for_field(current_field)}"
                )
            else:
                reply = f"No pude entender esa respuesta.\n{self.prompt_for_field(current_field)}"
            return {
                "state": NEEDS_INFO,
                "current_step": current_field,
                "context_json": {
                    "draft_expense": draft,
                    "missing_fields": missing,
                    "last_question": current_field,
                },
                "reply": reply,
                "action": "noop",
            }

        draft[current_field] = parsed_value
        if current_field == "country":
            inferred_currency = self.expense_service.infer_currency_from_country(parsed_value)
            if inferred_currency:
                draft["currency"] = inferred_currency
        draft = self.expense_service.enrich_draft_expense(draft)
        missing = self.expense_service.find_missing_required_fields(draft)

        if missing:
            next_field = missing[0]
            return {
                "state": NEEDS_INFO,
                "current_step": next_field,
                "context_json": {
                    "draft_expense": draft,
                    "missing_fields": missing,
                    "last_question": next_field,
                },
                "reply": self.prompt_for_field(next_field),
                "action": "noop",
            }

        return self._to_confirm_summary(draft)

    def _to_confirm_summary(self, draft: dict[str, Any]) -> dict[str, Any]:
        draft = self.expense_service.enrich_draft_expense(draft)
        return {
            "state": CONFIRM_SUMMARY,
            "current_step": "confirm_summary",
            "context_json": {
                "draft_expense": draft,
                "missing_fields": [],
                "last_question": None,
            },
            "reply": self.expense_service.build_summary_message(draft),
            "action": "noop",
        }

    def _handle_confirm_summary(
        self,
        context: dict[str, Any],
        message: str,
        current_step: str,
    ) -> dict[str, Any]:
        normalized = message.strip().lower()
        draft = dict(context.get("draft_expense", {}))

        if current_step == "select_correction_field":
            selected_field = self._parse_correction_field_choice(message)
            if selected_field:
                return self._to_needs_info_for_field(draft, selected_field)
            return {
                "state": CONFIRM_SUMMARY,
                "current_step": "select_correction_field",
                "context_json": {
                    "draft_expense": draft,
                    "missing_fields": [],
                    "last_question": None,
                },
                "reply": (
                    "No entendí qué campo quieres corregir.\n"
                    f"{self._build_correction_field_prompt()}"
                ),
                "action": "noop",
            }

        if normalized in {"1", "confirmar", "confirmo", "ok", "si", "sí"}:
            return {
                "state": DONE,
                "current_step": "",
                "context_json": {
                    "draft_expense": draft,
                    "missing_fields": [],
                    "last_question": None,
                },
                "reply": "Confirmado. Guardando gasto...",
                "action": "save_expense",
            }

        if normalized in {"2", "corregir"}:
            return {
                "state": CONFIRM_SUMMARY,
                "current_step": "select_correction_field",
                "context_json": {
                    "draft_expense": draft,
                    "missing_fields": [],
                    "last_question": None,
                },
                "reply": self._build_correction_field_prompt(),
                "action": "noop",
            }

        if normalized in {"3", "cancelar"}:
            return {
                "state": WAIT_RECEIPT,
                "current_step": "",
                "context_json": self.default_context(),
                "reply": "Operación cancelada. Envíame otra boleta cuando quieras.",
                "action": "cancel",
            }

        return {
            "state": CONFIRM_SUMMARY,
            "current_step": "confirm_summary",
            "context_json": {
                "draft_expense": draft,
                "missing_fields": [],
                "last_question": None,
            },
            "reply": "Respuesta no válida.\nEscribe 1, 2 o 3.\n\n"
            + self.expense_service.build_summary_message(draft),
            "action": "noop",
        }

    def _answer_general_question_if_needed(self, message: str) -> str | None:
        if not self._looks_like_question(message):
            return None
        return self.expense_service.answer_general_question(message)

    def _looks_like_question(self, message: str) -> bool:
        normalized = (message or "").strip().lower()
        if not normalized:
            return False
        if "?" in normalized:
            return True
        question_starts = (
            "como",
            "cómo",
            "que ",
            "qué ",
            "donde",
            "dónde",
            "cuando",
            "cuándo",
            "cual",
            "cuál",
            "puedo",
            "se puede",
            "me ayudas",
            "ayuda",
            "explica",
        )
        return normalized.startswith(question_starts)

    def prompt_for_field(self, field_name: str) -> str:
        return FIELD_PROMPTS.get(field_name, f"Falta el campo {field_name}. Indícalo.")

    def _parse_field_value(self, field_name: str, message: str) -> Any:
        text = message.strip()
        if not text:
            return None

        if field_name == "currency":
            return CURRENCY_OPTIONS.get(text) or text.upper()
        if field_name == "category":
            return CATEGORY_OPTIONS.get(text) or text
        if field_name == "country":
            return COUNTRY_OPTIONS.get(text) or text
        if field_name == "total":
            try:
                return float(text.replace(",", "."))
            except ValueError:
                return None
        return text

    def _build_correction_field_prompt(self) -> str:
        return (
            "¿Qué campo quieres corregir?\n"
            "1. Merchant\n"
            "2. Fecha\n"
            "3. Total\n"
            "4. Moneda\n"
            "5. Categoría\n"
            "6. País"
        )

    def _parse_correction_field_choice(self, message: str) -> str | None:
        text = (message or "").strip()
        if not text:
            return None
        return CORRECTION_FIELD_OPTIONS.get(text) or CORRECTION_FIELD_ALIASES.get(text.lower())

    def _to_needs_info_for_field(self, draft: dict[str, Any], field_name: str) -> dict[str, Any]:
        extra = ""
        if field_name == "country":
            extra = "\nActualizaré moneda automáticamente según el país."
        field_label = CORRECTION_FIELD_LABELS.get(field_name, field_name)
        return {
            "state": NEEDS_INFO,
            "current_step": field_name,
            "context_json": {
                "draft_expense": draft,
                "missing_fields": [field_name],
                "last_question": field_name,
            },
            "reply": f"Vamos a corregir {field_label}.{extra}\n{self.prompt_for_field(field_name)}",
            "action": "noop",
        }
