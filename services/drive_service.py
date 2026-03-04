from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import Settings


logger = logging.getLogger(__name__)


class DriveUploadError(RuntimeError):
    pass


@dataclass
class DriveService:
    settings: Settings

    def __post_init__(self) -> None:
        self._service = None
        if self.enabled:
            self._connect()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.google_application_credentials)

    def _connect(self) -> None:
        try:
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover - dependency setup
            raise RuntimeError(
                "Faltan dependencias para Google Drive. Instala google-api-python-client."
            ) from exc

        scopes = ["https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(
            self.settings.google_application_credentials,
            scopes=scopes,
        )
        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)

    def upload_receipt_from_url(
        self,
        *,
        phone: str,
        media_url: str,
        media_content_type: str | None = None,
    ) -> dict[str, str]:
        if not self._service:
            raise DriveUploadError("Google Drive no está habilitado")
        if not media_url:
            raise DriveUploadError("MediaUrl0 vacío")
        if not (self.settings.drive_receipts_folder_id or "").strip():
            raise DriveUploadError(
                "Falta DRIVE_RECEIPTS_FOLDER_ID. Con service account debes subir a carpeta en Shared Drive."
            )

        content, mime_type = self._download_media(media_url, media_content_type)
        file_name = self._build_file_name(phone=phone, mime_type=mime_type)
        upload_result = self._upload_bytes(
            file_name=file_name,
            content=content,
            mime_type=mime_type,
        )
        file_id = upload_result.get("id", "")
        if file_id:
            self._grant_public_read(file_id)
        return upload_result

    def _download_media(self, media_url: str, media_content_type: str | None) -> tuple[bytes, str]:
        headers = {"User-Agent": "TravelExpenseAgent/1.0"}
        basic_auth = self._twilio_basic_auth_header()
        if basic_auth:
            headers["Authorization"] = basic_auth

        request = Request(media_url, headers=headers)
        try:
            with urlopen(request, timeout=20) as response:
                content = response.read()
                response_mime = response.headers.get_content_type()
        except HTTPError as exc:  # pragma: no cover - depends on external network
            raise DriveUploadError(f"Error HTTP descargando media Twilio: {exc.code}") from exc
        except URLError as exc:  # pragma: no cover - depends on external network
            raise DriveUploadError("No se pudo descargar la imagen desde Twilio") from exc

        if not content:
            raise DriveUploadError("La imagen descargada está vacía")

        mime_type = self._resolve_mime_type(media_content_type, response_mime)
        return content, mime_type

    def _twilio_basic_auth_header(self) -> str | None:
        sid = (self.settings.twilio_account_sid or "").strip()
        token = (self.settings.twilio_auth_token or "").strip()
        if not sid or not token:
            return None
        raw = f"{sid}:{token}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def _resolve_mime_type(
        self,
        media_content_type: str | None,
        response_mime: str | None,
    ) -> str:
        for candidate in (media_content_type, response_mime):
            if candidate and "/" in candidate:
                return candidate.split(";", 1)[0].strip().lower()
        return "image/jpeg"

    def _build_file_name(self, *, phone: str, mime_type: str) -> str:
        extension = self._guess_extension(mime_type)
        safe_phone = "".join(ch for ch in (phone or "") if ch.isdigit()) or "unknown"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"receipt_{safe_phone}_{timestamp}{extension}"

    def _guess_extension(self, mime_type: str) -> str:
        if mime_type == "image/png":
            return ".png"
        if mime_type == "image/webp":
            return ".webp"
        if mime_type in {"application/pdf", "image/pdf"}:
            return ".pdf"
        return ".jpg"

    def _upload_bytes(self, *, file_name: str, content: bytes, mime_type: str) -> dict[str, str]:
        try:
            from googleapiclient.http import MediaIoBaseUpload
        except ImportError as exc:  # pragma: no cover - dependency setup
            raise RuntimeError(
                "Faltan dependencias para Google Drive. Instala google-api-python-client."
            ) from exc

        metadata: dict[str, Any] = {"name": file_name}
        folder_id = (self.settings.drive_receipts_folder_id or "").strip()
        if folder_id:
            metadata["parents"] = [folder_id]

        media = MediaIoBaseUpload(BytesIO(content), mimetype=mime_type, resumable=False)
        created = (
            self._service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id,webViewLink,webContentLink",
                supportsAllDrives=True,
            )
            .execute()
        )
        return {
            "id": created.get("id", ""),
            "web_view_link": created.get("webViewLink", ""),
            "web_content_link": created.get("webContentLink", ""),
        }

    def _grant_public_read(self, file_id: str) -> None:
        try:
            self._service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
                supportsAllDrives=True,
            ).execute()
        except Exception:  # pragma: no cover - depends on drive org policies
            logger.warning("No se pudo compartir archivo públicamente file_id=%s", file_id)
