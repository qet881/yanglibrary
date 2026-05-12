from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import requests


def send_email_report(config: dict[str, Any], body_path: Path, run_id: str) -> dict[str, Any]:
    email_config = config.get("notify", {}).get("email", {})
    if not is_email_enabled(email_config):
        return {"enabled": False, "sent": False, "reason": "email disabled"}

    required = ["SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "MAIL_FROM", "MAIL_TO"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        return {"enabled": True, "sent": False, "error": "missing environment variables: " + ", ".join(missing)}

    try:
        port = int(os.environ["SMTP_PORT"])
        body = body_path.read_text(encoding="utf-8")
        message = EmailMessage()
        message["Subject"] = f"{email_config.get('subject_prefix', '[Book Radar]')} {run_id}"
        message["From"] = os.environ["MAIL_FROM"]
        message["To"] = os.environ["MAIL_TO"]
        message.set_content(body)

        with smtplib.SMTP(os.environ["SMTP_HOST"], port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(message)
        return {"enabled": True, "sent": True, "to": os.environ["MAIL_TO"]}
    except Exception as exc:
        return {"enabled": True, "sent": False, "error": str(exc)}


def is_email_enabled(email_config: dict[str, Any]) -> bool:
    override = os.environ.get("BOOK_RADAR_EMAIL_ENABLED")
    if override is not None:
        return override.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(email_config.get("enabled", False))


def send_telegram_report(config: dict[str, Any], body_path: Path, run_id: str) -> dict[str, Any]:
    telegram_config = config.get("notify", {}).get("telegram", {})
    if not is_telegram_enabled(telegram_config):
        return {"enabled": False, "sent": False, "reason": "telegram disabled"}

    required = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        return {"enabled": True, "sent": False, "error": "missing environment variables: " + ", ".join(missing)}

    try:
        token = os.environ["TELEGRAM_BOT_TOKEN"]
        chat_id = os.environ["TELEGRAM_CHAT_ID"]
        max_chars = int(telegram_config.get("max_chars_per_message", 3500))
        text = body_path.read_text(encoding="utf-8")
        prefix = telegram_config.get("subject_prefix", "[Book Radar]")
        chunks = chunk_text(f"{prefix} {run_id}\n\n{text}", max_chars=max_chars)
        sent_messages = []
        for chunk in chunks:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": chunk,
                    "disable_web_page_preview": True,
                },
                timeout=30,
            )
            data = response.json()
            if not response.ok or not data.get("ok"):
                return {
                    "enabled": True,
                    "sent": False,
                    "error": data.get("description") or response.text,
                    "status_code": response.status_code,
                }
            sent_messages.append(data.get("result", {}).get("message_id"))
        return {"enabled": True, "sent": True, "chat_id": chat_id, "message_count": len(sent_messages), "message_ids": sent_messages}
    except Exception as exc:
        return {"enabled": True, "sent": False, "error": str(exc)}


def is_telegram_enabled(telegram_config: dict[str, Any]) -> bool:
    override = os.environ.get("BOOK_RADAR_TELEGRAM_ENABLED")
    if override is not None:
        return override.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(telegram_config.get("enabled", False))


def chunk_text(text: str, max_chars: int = 3500) -> list[str]:
    if max_chars < 500:
        max_chars = 500
    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        split_at = remaining.rfind("\n\n", 0, max_chars)
        if split_at < max_chars // 2:
            split_at = remaining.rfind("\n", 0, max_chars)
        if split_at < max_chars // 2:
            split_at = max_chars
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks
