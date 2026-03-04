#!/usr/bin/env python3
"""Inicializa headers y carga datos demo en Google Sheets para el MVP.

Uso:
  python scripts/seed_sheets.py \
    --credentials ./service-account.json \
    --spreadsheet-id <SPREADSHEET_ID> \
    --clear-data \
    --seed-demo

Requisitos:
  pip install gspread google-auth
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import gspread
from google.oauth2.service_account import Credentials


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_HEADERS: dict[str, list[str]] = {
    "Employees": ["phone", "name", "rut", "active"],
    "Trips": [
        "trip_id",
        "phone",
        "destination",
        "country",
        "start_date",
        "end_date",
        "budget",
        "status",
    ],
    "Expenses": [
        "expense_id",
        "phone",
        "trip_id",
        "merchant",
        "date",
        "currency",
        "total",
        "total_clp",
        "category",
        "country",
        "shared",
        "status",
        "receipt_drive_url",
        "created_at",
    ],
    "Conversations": ["phone", "state", "current_step", "context_json", "updated_at"],
}


@dataclass
class SeedConfig:
    spreadsheet_id: str
    credentials_path: str
    clear_data: bool
    seed_demo: bool
    employee_phone: str
    employee_name: str
    employee_rut: str
    collaborator_phone: str


def parse_args() -> SeedConfig:
    parser = argparse.ArgumentParser(
        description="Inicializa headers y datos demo para Travel_Agent_MVP"
    )
    parser.add_argument(
        "--spreadsheet-id",
        default=os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", ""),
        help="ID del Google Spreadsheet",
    )
    parser.add_argument(
        "--credentials",
        dest="credentials_path",
        default=os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""),
        help="Path al JSON de Service Account",
    )
    parser.add_argument(
        "--clear-data",
        action="store_true",
        help="Borra filas existentes (mantiene headers)",
    )
    parser.add_argument(
        "--seed-demo",
        action="store_true",
        help="Carga filas de ejemplo después de crear headers",
    )
    parser.add_argument(
        "--employee-phone",
        default="+56974340422",
        help="Teléfono del empleado demo (E.164)",
    )
    parser.add_argument(
        "--employee-name",
        default="Javier Calderon",
        help="Nombre del empleado demo",
    )
    parser.add_argument(
        "--employee-rut",
        default="12.345.678-9",
        help="RUT del empleado demo",
    )
    parser.add_argument(
        "--collaborator-phone",
        default="+56970000000",
        help="Teléfono colaborador demo para shared expense",
    )

    args = parser.parse_args()

    if not args.spreadsheet_id:
        parser.error("Falta --spreadsheet-id (o env GOOGLE_SHEETS_SPREADSHEET_ID)")
    if not args.credentials_path:
        parser.error("Falta --credentials (o env GOOGLE_APPLICATION_CREDENTIALS)")
    if not os.path.exists(args.credentials_path):
        parser.error(f"No existe el archivo de credenciales: {args.credentials_path}")

    return SeedConfig(
        spreadsheet_id=args.spreadsheet_id,
        credentials_path=args.credentials_path,
        clear_data=args.clear_data,
        seed_demo=args.seed_demo,
        employee_phone=args.employee_phone,
        employee_name=args.employee_name,
        employee_rut=args.employee_rut,
        collaborator_phone=args.collaborator_phone,
    )


def get_client(credentials_path: str) -> gspread.Client:
    creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
    return gspread.authorize(creds)


def ensure_worksheet(spreadsheet: gspread.Spreadsheet, title: str) -> gspread.Worksheet:
    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        # Tamaño pequeño suficiente para MVP; se puede ajustar luego.
        return spreadsheet.add_worksheet(title=title, rows=200, cols=20)


def set_headers(ws: gspread.Worksheet, headers: list[str]) -> None:
    ws.update("A1", [headers])


def clear_rows_keep_headers(ws: gspread.Worksheet) -> None:
    row_count = ws.row_count
    if row_count > 1:
        ws.batch_clear([f"A2:Z{row_count}"])


def demo_rows(cfg: SeedConfig) -> dict[str, list[list[Any]]]:
    today = date.today()
    start_date = today.isoformat()
    end_date = (today + timedelta(days=2)).isoformat()
    created_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    trip_id = f"TRIP-{today.strftime('%Y%m%d')}-001"
    expense_id = f"EXP-{today.strftime('%Y%m%d')}-001"
    conversation_context = {
        "draft_expense": {
            "merchant": "Starbucks",
            "date": today.isoformat(),
            "currency": "USD",
            "total": 12.5,
            "category": "Meals",
            "country": "Chile",
            "trip_id": trip_id,
        },
        "missing_fields": [],
        "last_question": None,
    }

    return {
        "Employees": [
            [cfg.employee_phone, cfg.employee_name, cfg.employee_rut, "TRUE"],
            [cfg.collaborator_phone, "Colaborador Demo", "98.765.432-1", "TRUE"],
        ],
        "Trips": [
            [
                trip_id,
                cfg.employee_phone,
                "Lima",
                "Peru",
                start_date,
                end_date,
                "500000",
                "active",
            ]
        ],
        "Expenses": [
            [
                expense_id,
                cfg.employee_phone,
                trip_id,
                "Starbucks",
                today.isoformat(),
                "USD",
                "12.5",
                "11875",
                "Meals",
                "Chile",
                "FALSE",
                "pending_approval",
                "",
                created_at,
            ]
        ],
        "Conversations": [
            [
                cfg.employee_phone,
                "WAIT_RECEIPT",
                "",
                json.dumps({"draft_expense": {}, "missing_fields": [], "last_question": None}),
                created_at,
            ],
            [
                cfg.collaborator_phone,
                "WAIT_RECEIPT",
                "",
                json.dumps(conversation_context),
                created_at,
            ],
        ],
    }


def append_rows(ws: gspread.Worksheet, rows: list[list[Any]]) -> None:
    if rows:
        # RAW preserva formatos como '+569...' para teléfonos.
        ws.append_rows(rows, value_input_option="RAW")


def main() -> int:
    cfg = parse_args()
    client = get_client(cfg.credentials_path)
    spreadsheet = client.open_by_key(cfg.spreadsheet_id)

    print(f"Spreadsheet: {spreadsheet.title} ({cfg.spreadsheet_id})")

    for sheet_name, headers in SHEET_HEADERS.items():
        ws = ensure_worksheet(spreadsheet, sheet_name)
        set_headers(ws, headers)
        if cfg.clear_data:
            clear_rows_keep_headers(ws)
        print(f"OK headers -> {sheet_name}")

    if cfg.seed_demo:
        rows_by_sheet = demo_rows(cfg)
        for sheet_name, rows in rows_by_sheet.items():
            ws = spreadsheet.worksheet(sheet_name)
            append_rows(ws, rows)
            print(f"OK seed rows -> {sheet_name}: {len(rows)}")

    print("Listo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
