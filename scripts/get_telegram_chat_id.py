from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.env import load_env_file


def main() -> None:
    load_env_file()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is missing. Put it in .env first.")

    response = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30)
    data = response.json()
    if not response.ok or not data.get("ok"):
        raise SystemExit(data.get("description") or response.text)

    chats = []
    for update in data.get("result", []):
        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat") or {}
        if chat.get("id") is not None:
            chats.append(
                {
                    "chat_id": chat.get("id"),
                    "type": chat.get("type"),
                    "title": chat.get("title") or chat.get("username") or chat.get("first_name"),
                }
            )

    if not chats:
        raise SystemExit("No chat found. Send any message to your bot in Telegram, then run this script again.")

    seen = set()
    for chat in chats:
        key = chat["chat_id"]
        if key in seen:
            continue
        seen.add(key)
        print(f"TELEGRAM_CHAT_ID={chat['chat_id']}  type={chat.get('type')}  title={chat.get('title')}")


if __name__ == "__main__":
    main()
