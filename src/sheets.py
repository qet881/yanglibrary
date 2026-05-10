from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from .config import project_path
from .utils import parse_spreadsheet_id


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


def get_client(credentials_file: Path) -> gspread.Client:
    creds = Credentials.from_service_account_file(str(credentials_file), scopes=SCOPES)
    return gspread.authorize(creds)


def open_spreadsheet(config: dict[str, Any]) -> gspread.Spreadsheet:
    google = config.get("google", {})
    credentials_file = project_path(config, google.get("credentials_file", ""))
    spreadsheet_id = parse_spreadsheet_id(google.get("spreadsheet_id", ""))
    if not spreadsheet_id:
        raise ValueError("config/app.yaml의 google.spreadsheet_id를 채워주세요.")
    if not credentials_file.exists():
        raise FileNotFoundError(f"서비스 계정 키 파일이 없습니다: {credentials_file}")
    return get_client(credentials_file).open_by_key(spreadsheet_id)


def worksheet_records(spreadsheet: gspread.Spreadsheet, sheet_name: str) -> list[dict[str, Any]]:
    worksheet = spreadsheet.worksheet(sheet_name)
    values = worksheet.get_all_values()
    if not values:
        return []
    headers = [h.strip() for h in values[0]]
    records: list[dict[str, Any]] = []
    for row_number, row in enumerate(values[1:], start=2):
        record = {headers[i]: row[i] if i < len(row) else "" for i in range(len(headers)) if headers[i]}
        record["_row_number"] = row_number
        records.append(record)
    return records


def fetch_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    spreadsheet = open_spreadsheet(config)
    required = config.get("sheets", {}).get("required", {})
    optional = config.get("sheets", {}).get("optional", {})
    target_sheets = list(required.values()) + list(optional.values())
    sheet_names = {ws.title for ws in spreadsheet.worksheets()}
    sheets: dict[str, list[dict[str, Any]]] = {}
    missing: list[str] = []
    for sheet_name in target_sheets:
        if sheet_name in sheet_names:
            sheets[sheet_name] = worksheet_records(spreadsheet, sheet_name)
        elif sheet_name in required.values():
            missing.append(sheet_name)
    return {
        "spreadsheet_id": parse_spreadsheet_id(config.get("google", {}).get("spreadsheet_id", "")),
        "spreadsheet_title": spreadsheet.title,
        "fetched_at": datetime.now().astimezone().isoformat(),
        "missing_required_sheets": missing,
        "sheets": sheets,
    }


def check_setup(config: dict[str, Any]) -> dict[str, Any]:
    google = config.get("google", {})
    credentials_file = project_path(config, google.get("credentials_file", ""))
    spreadsheet_id = parse_spreadsheet_id(google.get("spreadsheet_id", ""))
    result: dict[str, Any] = {
        "credentials_file": str(credentials_file),
        "credentials_exists": credentials_file.exists(),
        "spreadsheet_id_present": bool(spreadsheet_id),
        "spreadsheet_accessible": False,
        "required_sheets": config.get("sheets", {}).get("required", {}),
        "missing_required_sheets": [],
        "errors": [],
    }
    if not credentials_file.exists() or not spreadsheet_id:
        return result
    try:
        snapshot = fetch_snapshot(config)
        result["spreadsheet_accessible"] = True
        result["spreadsheet_title"] = snapshot.get("spreadsheet_title")
        result["missing_required_sheets"] = snapshot.get("missing_required_sheets", [])
    except Exception as exc:  # diagnostics should report, not crash
        result["errors"].append(str(exc))
    return result


def append_row(config: dict[str, Any], sheet_name: str, row_data: dict[str, Any]) -> dict[str, Any]:
    spreadsheet = open_spreadsheet(config)
    worksheet = spreadsheet.worksheet(sheet_name)
    headers = worksheet.row_values(1)
    row = [row_data.get(header, "") for header in headers]
    worksheet.append_row(row, value_input_option="USER_ENTERED")
    return {"target_sheet": sheet_name, "appended_columns": headers}

