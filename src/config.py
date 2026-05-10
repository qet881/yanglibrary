from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {config_path}")
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    data["_config_path"] = str(config_path)
    data["_project_root"] = str(config_path.parent.parent if config_path.parent.name == "config" else Path.cwd())
    return data


def project_path(config: dict[str, Any], value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return Path(config.get("_project_root", ".")).joinpath(path)

