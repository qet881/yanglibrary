from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.env import load_env_file
from src.notify import send_telegram_report
from src.utils import ensure_dir, make_run_id


def main() -> None:
    load_env_file()
    run_id = make_run_id()
    output_dir = ensure_dir(Path("output") / run_id)
    body_path = output_dir / "telegram_test_message.md"
    body_path.write_text(
        "# Book Radar Telegram 테스트\n\n이 메시지가 도착했다면 Telegram 알림 설정이 정상입니다.\n",
        encoding="utf-8",
    )
    config = load_config("config/app.yaml")
    result = send_telegram_report(config, body_path, f"telegram-test-{run_id}")
    print(result)
    if not result.get("sent"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
