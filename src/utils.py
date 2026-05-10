from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    return datetime.now(KST)


def make_run_id() -> str:
    return now_kst().strftime("%Y%m%d_%H%M%S")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def clean_html(value: Any) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_text(value: Any) -> str:
    text = clean_html(value).lower()
    text = re.sub(r"[\[\]\(\){}<>『』「」'\"“”‘’·:;,.!?/\\|-]", "", text)
    return re.sub(r"\s+", "", text)


def primary_author_key(value: Any) -> str:
    text = clean_html(value)
    text = re.sub(r"(지은이|저자|글쓴이|옮긴이|역자)\s*[:：]", "", text)
    text = re.sub(r"[\[\]\(\)]", " ", text)
    text = re.sub(r"\.{2,}", " ", text)
    text = re.split(r"\s*(?:;|,|/|·|\+|＆|&)\s*", text)[0]
    text = re.split(r"\s*(?:외|등|같이)\s*", text)[0]
    text = re.sub(r"\s*(?:지음|저|글|옮김|역|편|엮음|그림).*$", "", text)
    return normalize_text(text)


def identity_key(title: str, author: str) -> str:
    return f"{normalize_text(title)}|{primary_author_key(author) or normalize_text(author)}"


def parse_spreadsheet_id(value: str) -> str:
    value = (value or "").strip()
    if "/spreadsheets/d/" in value:
        return value.split("/spreadsheets/d/", 1)[1].split("/", 1)[0]
    return value


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        text = str(value).strip()
        return float(text) if text else default
    except (TypeError, ValueError):
        return default
