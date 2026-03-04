from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response, status

from app.config import settings
from services.conversation_service import ConversationService
from services.drive_service import DriveService
from services.expense_service import ExpenseService
from services.llm_service import LLMService
from services.ocr_service import OCRService
from services.scheduler_service import SchedulerService
from services.sheets_service import SheetsService
from services.travel_service import TravelService
from services.whatsapp_service import TwilioDailyLimitExceededError, WhatsAppService
from utils.helpers import normalize_whatsapp_phone

logger = logging.getLogger(__name__)


@dataclass
class ServiceContainer:
    sheets: SheetsService
    travel: TravelService
    drive: DriveService
    ocr: OCRService
    expense: ExpenseService
    conversation: ConversationService
    whatsapp: WhatsAppService
    scheduler: SchedulerService


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, debug=settings.debug)

    sheets_service = SheetsService(settings=settings)
    llm_service = LLMService(settings=settings)
    expense_service = ExpenseService(sheets_service=sheets_service, llm_service=llm_service)
    whatsapp_service = WhatsAppService(settings=settings)
    container = ServiceContainer(
        sheets=sheets_service,
        travel=TravelService(sheets_service=sheets_service),
        drive=DriveService(settings=settings),
        ocr=OCRService(settings=settings),
        expense=expense_service,
        conversation=ConversationService(expense_service=expense_service),
        whatsapp=whatsapp_service,
        scheduler=SchedulerService(
            settings=settings,
            sheets_service=sheets_service,
            whatsapp_service=whatsapp_service,
        ),
    )
    app.state.services = container

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "app": settings.app_name,
            "sheets_enabled": container.sheets.enabled,
            "category_llm_flag": settings.expense_category_llm_enabled,
            "chat_assistant_flag": settings.chat_assistant_enabled,
            "openai_api_key_present": bool(settings.openai_api_key),
            "category_llm_enabled": llm_service.category_classification_enabled,
            "chat_assistant_enabled": llm_service.chat_assistant_enabled,
            "openai_model": settings.openai_model if llm_service.category_classification_enabled else None,
            "scheduler_window_minutes": settings.scheduler_reminder_window_minutes,
            "scheduler_morning_hour_local": settings.scheduler_morning_hour_local,
            "scheduler_evening_hour_local": settings.scheduler_evening_hour_local,
            "env": settings.app_env,
        }

    @app.post("/jobs/reminders/run")
    async def run_trip_reminders(
        dry_run: bool = False,
        x_scheduler_token: Optional[str] = Header(default=None, alias="X-Scheduler-Token"),
    ) -> dict[str, Any]:
        configured_token = (settings.scheduler_endpoint_token or "").strip()
        if configured_token and x_scheduler_token != configured_token:
            raise HTTPException(status_code=401, detail="Unauthorized scheduler token")
        return container.scheduler.run_trip_reminders(dry_run=dry_run)

    @app.post("/webhook")
    async def twilio_webhook(request: Request, background_tasks: BackgroundTasks) -> Response:
        try:
            form = await request.form()
            payload = {key: form.get(key) for key in form.keys()}
            num_media = int(payload.get("NumMedia") or 0)
            body = (payload.get("Body") or "").strip()
            from_raw = payload.get("From") or ""
            phone = normalize_whatsapp_phone(from_raw)
            signature = request.headers.get("X-Twilio-Signature")
            request_url = str(request.url)

            if not container.whatsapp.validate_incoming_request(
                request_url, payload, signature
            ):
                xml = container.whatsapp.build_twiml_message("Firma Twilio inválida.")
                return Response(content=xml, media_type="application/xml", status_code=403)

            if not phone:
                xml = container.whatsapp.build_twiml_message(
                    "No pude identificar tu número. Intenta nuevamente."
                )
                return Response(content=xml, media_type="application/xml")

            employee = container.sheets.get_employee_by_phone(phone)
            if not employee:
                xml = container.whatsapp.build_twiml_message(
                    "Tu número no está registrado como empleado activo."
                )
                return Response(content=xml, media_type="application/xml")

            if num_media > 0:
                background_tasks.add_task(_process_media_message_async, container, phone, payload)
                xml = container.whatsapp.build_empty_twiml()
                return Response(content=xml, media_type="application/xml", status_code=status.HTTP_200_OK)
            else:
                response_text = _handle_text_message(container, phone, body)

            xml = container.whatsapp.build_twiml_message(response_text)
            return Response(content=xml, media_type="application/xml", status_code=status.HTTP_200_OK)
        except Exception as exc:  # pragma: no cover - runtime dependency/errors
            logger.exception("Webhook processing failed")
            message = (
                "Estoy con alta carga temporal y no pude procesar tu mensaje. "
                "Intenta nuevamente en 1 minuto."
            )
            if settings.debug:
                message += f"\nDetalle técnico: {exc}"
            xml = container.whatsapp.build_twiml_message(message)
            return Response(content=xml, media_type="application/xml", status_code=status.HTTP_200_OK)

    return app


def _handle_media_message(container: ServiceContainer, phone: str, payload: dict[str, Any]) -> str:
    media_url = payload.get("MediaUrl0") or ""
    media_content_type = payload.get("MediaContentType0")
    ocr_warning = ""
    drive_link = ""

    container.sheets.update_conversation(
        phone,
        container.conversation.begin_processing(phone),
    )

    try:
        ocr_data = container.ocr.extract_receipt_data(media_url, media_content_type)
    except Exception as exc:  # pragma: no cover - depende de red/API externa
        logger.exception("OCR processing failed for phone=%s", phone)
        ocr_data = {}
        ocr_warning = (
            "No pude extraer datos automáticamente de la boleta. "
            "Te pediré los datos manualmente."
        )
        if settings.debug:
            ocr_warning += f"\nDetalle técnico: {exc}"

    if container.drive.enabled and media_url and settings.drive_receipts_folder_id:
        try:
            drive_upload = container.drive.upload_receipt_from_url(
                phone=phone,
                media_url=media_url,
                media_content_type=media_content_type,
            )
            drive_link = (
                drive_upload.get("web_view_link")
                or drive_upload.get("web_content_link")
                or ""
            )
        except Exception as exc:  # pragma: no cover - depende de red/API externa
            logger.exception("Drive upload failed for phone=%s", phone)
            if settings.debug:
                logger.warning(
                    "Falling back to temporary Twilio media URL phone=%s error=%s",
                    phone,
                    exc,
                )

    # Fallback: si Drive falla/no está configurado, guarda MediaUrl0 temporal de Twilio.
    ocr_data["receipt_drive_url"] = drive_link or media_url

    trip = container.travel.get_active_trip_for_phone(phone)
    transition = container.conversation.process_ocr_result(phone, ocr_data, trip)

    container.sheets.update_conversation(
        phone,
        {
            "state": transition["state"],
            "current_step": transition.get("current_step", ""),
            "context_json": transition.get("context_json", {}),
        },
    )
    reply = transition.get(
        "reply",
        "Recibí tu boleta. Estoy procesándola.",
    )
    if ocr_warning:
        reply = f"{ocr_warning}\n\n{reply}"
    return reply


def _handle_text_message(container: ServiceContainer, phone: str, body: str) -> str:
    conversation = container.sheets.get_conversation(phone)
    if not conversation:
        conversation = container.sheets.update_conversation(
            phone,
            {
                "state": "WAIT_RECEIPT",
                "current_step": "",
                "context_json": container.conversation.default_context(),
            },
        )

    result = container.conversation.handle_text_message(conversation, body)

    if result.get("action") == "save_expense":
        draft = result.get("context_json", {}).get("draft_expense", {})
        try:
            saved = container.expense.save_confirmed_expense(phone, draft)
            budget_message = container.expense.build_budget_progress_message(
                phone=phone,
                trip_id=str(saved.get("trip_id", "") or ""),
            )
            budget_section = f"{budget_message}\n\n" if budget_message else ""
            reply = (
                "Gasto guardado con éxito.\n"
                f"ID: {saved.get('expense_id')}\n"
                f"Estado: {saved.get('status')}\n\n"
                f"{budget_section}"
                "Envíame otra boleta cuando quieras."
            )
            container.sheets.update_conversation(
                phone,
                {
                    "state": "WAIT_RECEIPT",
                    "current_step": "",
                    "context_json": container.conversation.default_context(),
                },
            )
            return reply
        except Exception as exc:  # pragma: no cover - runtime dependency/errors
            result = {
                "state": "CONFIRM_SUMMARY",
                "current_step": "confirm_summary",
                "context_json": result.get("context_json", {}),
                "reply": f"No pude guardar el gasto: {exc}",
            }

    container.sheets.update_conversation(
        phone,
        {
            "state": result.get("state", conversation.get("state", "WAIT_RECEIPT")),
            "current_step": result.get("current_step", conversation.get("current_step", "")),
            "context_json": result.get("context_json", conversation.get("context_json", {})),
        },
    )
    return result.get("reply", "No pude procesar tu mensaje.")


def _process_media_message_async(
    container: ServiceContainer,
    phone: str,
    payload: dict[str, Any],
) -> None:
    try:
        response_text = _handle_media_message(container, phone, payload)
    except Exception as exc:  # pragma: no cover - runtime dependency/errors
        logger.exception("Async media processing failed for phone=%s", phone)
        response_text = (
            "No pude procesar tu boleta en este intento. "
            "Por favor reenvíala o escribe 'reiniciar'."
        )
        if settings.debug:
            response_text += f"\nDetalle técnico: {exc}"
    try:
        container.whatsapp.send_outbound_text(phone, response_text)
    except TwilioDailyLimitExceededError:
        logger.warning(
            "No se pudo enviar respuesta por WhatsApp: límite diario de Twilio alcanzado phone=%s",
            phone,
        )
    except Exception:  # pragma: no cover - runtime dependency/errors
        logger.exception("Failed to send outbound WhatsApp reply phone=%s", phone)


app = create_app()
