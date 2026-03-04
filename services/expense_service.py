from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from services.llm_service import LLMService
from services.sheets_service import SheetsService
from utils.exchange_rate import convert_to_clp
from utils.helpers import make_id, parse_float, utc_now_iso


logger = logging.getLogger(__name__)

_GENERIC_MERCHANT_VALUES = {
    "comprobante de venta",
    "boleta",
    "boleta electronica",
    "boleta electrónica",
    "factura",
    "factura electronica",
    "factura electrónica",
    "recibo",
    "ticket",
    "tarjeta de debito",
    "tarjeta de débito",
    "tarjeta de credito",
    "tarjeta de crédito",
    "visa debito",
    "visa débito",
    "visa credito",
    "visa crédito",
    "mastercard",
    "copia cliente",
}


REQUIRED_EXPENSE_FIELDS = [
    "merchant",
    "date",
    "total",
    "currency",
    "category",
    "country",
    "trip_id",
]

_BUDGET_ALERT_THRESHOLDS = (50, 75, 90, 100)

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Meals": (
        "restaurant",
        "restaurante",
        "cafe",
        "cafeteria",
        "coffee",
        "bar",
        "food",
        "pizza",
        "burger",
        "mcdonald",
        "starbucks",
        "kfc",
        "subway",
        "sushi",
        "grill",
    ),
    "Lodging": (
        "hotel",
        "hostal",
        "hostel",
        "inn",
        "resort",
        "lodging",
        "airbnb",
        "booking",
        "motel",
    ),
    "Transport": (
        "uber",
        "cabify",
        "didi",
        "taxi",
        "bus",
        "metro",
        "train",
        "tren",
        "flight",
        "airline",
        "aerolinea",
        "airport",
        "peaje",
        "toll",
        "gas",
        "gasolina",
        "combustible",
        "shell",
        "copec",
        "esso",
    ),
}

_COUNTRY_TO_CURRENCY: dict[str, str] = {
    "chile": "CLP",
    "peru": "PEN",
    "perú": "PEN",
    "china": "CNY",
    "usa": "USD",
    "eeuu": "USD",
    "estados unidos": "USD",
    "united states": "USD",
}


@dataclass
class ExpenseService:
    sheets_service: SheetsService
    llm_service: LLMService | None = None

    def enrich_draft_expense(self, draft_expense: dict[str, Any]) -> dict[str, Any]:
        draft = dict(draft_expense or {})
        merchant = str(draft.get("merchant", "") or "").strip()
        if self._should_infer_merchant_with_llm(draft):
            inferred_merchant = self.infer_merchant_with_llm(draft)
            if inferred_merchant:
                draft["merchant"] = inferred_merchant
                logger.info("Expense merchant inferred source=llm merchant=%r", inferred_merchant)
            else:
                logger.info(
                    "Expense merchant not inferred by llm keeping_ocr_merchant=%r",
                    merchant or None,
                )

        if self._should_infer_country_currency_with_llm(draft):
            inferred_geo = self.infer_country_currency_with_llm(draft)
            if inferred_geo:
                current_country = str(draft.get("country", "") or "").strip()
                current_currency = str(draft.get("currency", "") or "").strip()
                if not current_country and inferred_geo.get("country"):
                    draft["country"] = inferred_geo["country"]
                if not current_currency and inferred_geo.get("currency"):
                    draft["currency"] = inferred_geo["currency"]
                logger.info(
                    "Expense country/currency inferred source=llm country=%r currency=%r",
                    draft.get("country"),
                    draft.get("currency"),
                )
            else:
                logger.info(
                    "Expense country/currency not inferred by llm keeping country=%r currency=%r",
                    draft.get("country"),
                    draft.get("currency"),
                )

        draft = self._apply_chile_guardrails(draft)

        category = draft.get("category")
        if category is None or str(category).strip() == "":
            inferred = self.infer_category_with_fallback(draft)
            if inferred:
                draft["category"] = inferred
                logger.info(
                    "Expense category inferred category=%s merchant=%r",
                    inferred,
                    draft.get("merchant"),
                )
            else:
                logger.info(
                    "Expense category not inferred merchant=%r country=%r",
                    draft.get("merchant"),
                    draft.get("country"),
                )
        return draft

    def infer_currency_from_country(self, country: Any) -> str | None:
        normalized = str(country or "").strip().lower()
        if not normalized:
            return None
        return _COUNTRY_TO_CURRENCY.get(normalized)

    def infer_merchant_with_llm(self, draft_expense: dict[str, Any]) -> str | None:
        if not self.llm_service:
            return None
        return self.llm_service.infer_expense_merchant(draft_expense)

    def answer_general_question(self, question: str) -> str | None:
        if not self.llm_service:
            return None
        return self.llm_service.answer_general_question(question)

    def infer_category_with_fallback(self, draft_expense: dict[str, Any]) -> str | None:
        llm_category = self.infer_category_with_llm(draft_expense)
        if llm_category:
            logger.info("Category classification source=llm category=%s", llm_category)
            return llm_category
        rule_category = self.infer_category(draft_expense)
        if rule_category:
            logger.info("Category classification source=rules category=%s", rule_category)
        else:
            logger.info("Category classification source=none")
        return rule_category

    def infer_category_with_llm(self, draft_expense: dict[str, Any]) -> str | None:
        if not self.llm_service:
            return None
        return self.llm_service.classify_expense_category(draft_expense)

    def infer_country_currency_with_llm(self, draft_expense: dict[str, Any]) -> dict[str, str]:
        if not self.llm_service:
            return {}
        return self.llm_service.infer_expense_country_currency(draft_expense)

    def infer_category(self, draft_expense: dict[str, Any]) -> str | None:
        merchant = str(draft_expense.get("merchant", "") or "").strip().lower()
        if not merchant:
            return None

        for category, keywords in _CATEGORY_KEYWORDS.items():
            if any(keyword in merchant for keyword in keywords):
                return category
        return None

    def _apply_chile_guardrails(self, draft_expense: dict[str, Any]) -> dict[str, Any]:
        ocr_text = str(draft_expense.get("ocr_text", "") or "")
        if not ocr_text:
            return draft_expense
        if not self._has_strong_chile_receipt_evidence(ocr_text):
            return draft_expense

        country_before = str(draft_expense.get("country", "") or "").strip()
        if country_before.lower() != "chile":
            draft_expense["country"] = "Chile"
            logger.info(
                "Expense country overridden by Chile guardrail previous=%r new=%r",
                country_before or None,
                draft_expense["country"],
            )

        currency_before = str(draft_expense.get("currency", "") or "").strip().upper()
        has_explicit_usd = self._has_explicit_usd_marker(ocr_text)
        looks_clp_amount = self._has_clp_amount_format(ocr_text)

        if not currency_before:
            draft_expense["currency"] = "CLP"
            logger.info("Expense currency set by Chile guardrail currency=%r", draft_expense["currency"])
        elif currency_before == "USD" and not has_explicit_usd and looks_clp_amount:
            draft_expense["currency"] = "CLP"
            logger.info(
                "Expense currency overridden by Chile guardrail previous=%r new=%r",
                currency_before,
                draft_expense["currency"],
            )
        return draft_expense

    def _has_strong_chile_receipt_evidence(self, text: str) -> bool:
        upper = (text or "").upper()
        if not upper:
            return False

        hard_hits = 0
        if re.search(r"\bRUT\b", upper):
            hard_hits += 1
        if "SII.CL" in upper:
            hard_hits += 1
        if re.search(r"\b[\w.-]+\.CL\b", upper):
            hard_hits += 1

        soft_hits = 0
        for token in ("LAS CONDES", "SANTIAGO", "PARQUE ARAUCO", "AV. KENNEDY", "COMUNA"):
            if token in upper:
                soft_hits += 1

        return hard_hits >= 2 or (hard_hits >= 1 and soft_hits >= 1)

    def _has_explicit_usd_marker(self, text: str) -> bool:
        upper = (text or "").upper()
        return bool(re.search(r"\bUSD\b|US\$|DOLAR|DÓLAR", upper))

    def _has_clp_amount_format(self, text: str) -> bool:
        return bool(re.search(r"\$\s*\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?\b", text or ""))

    def _should_infer_merchant_with_llm(self, draft_expense: dict[str, Any]) -> bool:
        if not self.llm_service:
            return False
        ocr_text = str(draft_expense.get("ocr_text", "") or "").strip()
        return bool(ocr_text)

    def _should_infer_country_currency_with_llm(self, draft_expense: dict[str, Any]) -> bool:
        if not self.llm_service:
            return False
        ocr_text = str(draft_expense.get("ocr_text", "") or "").strip()
        return bool(ocr_text)

    def find_missing_required_fields(self, draft_expense: dict[str, Any]) -> list[str]:
        missing: list[str] = []
        for field in REQUIRED_EXPENSE_FIELDS:
            value = draft_expense.get(field)
            if value is None or str(value).strip() == "":
                missing.append(field)
        return missing

    def build_summary_message(self, draft_expense: dict[str, Any]) -> str:
        return (
            "Detecte este gasto:\n"
            f"Merchant: {draft_expense.get('merchant', '-')}\n"
            f"Fecha: {draft_expense.get('date', '-')}\n"
            f"Total: {draft_expense.get('total', '-')} {draft_expense.get('currency', '-')}\n"
            f"Categoria: {draft_expense.get('category', '-')}\n"
            f"Pais: {draft_expense.get('country', '-')}\n\n"
            "1. Confirmar\n"
            "2. Corregir\n"
            "3. Cancelar"
        )

    def save_confirmed_expense(self, phone: str, draft_expense: dict[str, Any]) -> dict[str, Any]:
        total = parse_float(draft_expense.get("total"))
        if total is None:
            raise ValueError("El total no es valido")

        currency = str(draft_expense.get("currency", "CLP")).upper()
        total_clp = convert_to_clp(total, currency)

        expense_row = {
            "expense_id": make_id("EXP"),
            "phone": phone,
            "trip_id": draft_expense.get("trip_id", ""),
            "merchant": draft_expense.get("merchant", ""),
            "date": draft_expense.get("date", ""),
            "currency": currency,
            "total": total,
            "total_clp": round(total_clp, 2),
            "category": draft_expense.get("category", ""),
            "country": draft_expense.get("country", ""),
            "shared": "FALSE",
            "status": "pending_approval",
            "receipt_drive_url": draft_expense.get("receipt_drive_url", ""),
            "created_at": utc_now_iso(),
        }
        return self.sheets_service.create_expense(expense_row)

    def build_budget_progress_message(self, phone: str, trip_id: str) -> str | None:
        progress = self.get_budget_progress(phone=phone, trip_id=trip_id)
        if not progress:
            return None

        budget_clp = progress["budget_clp"]
        spent_clp = progress["spent_clp"]
        remaining_clp = progress["remaining_clp"]
        spent_pct = progress["spent_pct"]
        alerts = progress["alerts"]

        lines = [
            "Estado de presupuesto del viaje:",
            f"- Presupuesto: {self._format_clp(budget_clp)} CLP",
            f"- Gastado: {self._format_clp(spent_clp)} CLP ({spent_pct:.1f}%)",
            f"- Disponible: {self._format_clp(remaining_clp)} CLP",
        ]
        if alerts:
            lines.append("")
            lines.append("Alertas:")
            lines.extend(f"- {alert}" for alert in alerts)
        return "\n".join(lines)

    def get_budget_progress(self, phone: str, trip_id: str) -> dict[str, Any] | None:
        trip = self.sheets_service.get_trip_by_id(trip_id)
        if not trip:
            return None

        budget_clp = parse_float(trip.get("budget"))
        if budget_clp is None or budget_clp <= 0:
            return None

        expenses = self.sheets_service.list_expenses_by_phone_trip(phone=phone, trip_id=trip_id)
        total_values = [parse_float(item.get("total_clp")) or 0.0 for item in expenses]
        spent_clp = round(sum(total_values), 2)

        current_ratio = spent_clp / budget_clp
        previous_ratio = (spent_clp - total_values[-1]) / budget_clp if total_values else 0.0
        spent_pct = round(current_ratio * 100, 1)
        remaining_clp = round(budget_clp - spent_clp, 2)

        alerts: list[str] = []
        for threshold in _BUDGET_ALERT_THRESHOLDS:
            limit = threshold / 100.0
            if previous_ratio < limit <= current_ratio:
                if threshold == 90:
                    alerts.append("Te queda 10% del presupuesto disponible.")
                elif threshold == 100:
                    alerts.append("Llegaste al 100% del presupuesto.")
                else:
                    alerts.append(f"Alcanzaste el {threshold}% del presupuesto.")
        if spent_clp > budget_clp:
            excess = spent_clp - budget_clp
            alerts.append(f"Excediste el presupuesto en {self._format_clp(excess)} CLP.")

        return {
            "budget_clp": budget_clp,
            "spent_clp": spent_clp,
            "remaining_clp": remaining_clp,
            "spent_pct": spent_pct,
            "alerts": alerts,
        }

    def _format_clp(self, amount: float) -> str:
        return f"${amount:,.0f}".replace(",", ".")
