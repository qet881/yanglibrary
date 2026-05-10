from __future__ import annotations

from pathlib import Path
from typing import Any

from .sheets import append_row, fetch_snapshot
from .utils import now_kst, write_json


def write_approval_preview(path: Path, plan: dict[str, Any]) -> None:
    lines = [
        "# Google Sheets 변경 승인 미리보기",
        "",
        f"- 실행 ID: {plan.get('run_id', '')}",
        f"- 모드: {plan.get('mode', 'dry_run')}",
        "- 실제 쓰기 여부: 승인 전에는 쓰지 않음",
        "",
        "| 위험도 | 작업 | 대상 시트 | 대상 행 | 변경 요약 |",
        "|---|---|---|---:|---|",
    ]
    for action in plan.get("actions", []):
        summary = action.get("summary") or f"{action.get('target_sheet')}에 {action.get('action')} 실행"
        lines.append(f"| 낮음 | {action.get('action')} | {action.get('target_sheet')} | 새 행 | {summary} |")
    lines.extend(
        [
            "",
            "승인 전 확인:",
            "- 중복 후보가 있는가?",
            "- 사용자가 요청하지 않은 컬럼을 바꾸는가?",
            "- 쓰기 전 스냅샷 경로가 있는가?",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def execute_update_plan(config: dict[str, Any], plan: dict[str, Any], commit: bool, approved: bool, output_dir: Path) -> dict[str, Any]:
    if commit and not approved:
        raise PermissionError("실제 쓰기는 --approved와 --commit이 모두 필요합니다.")
    result: dict[str, Any] = {
        "executed_at": now_kst().isoformat(),
        "mode": "commit" if commit else "dry_run",
        "actions": [],
    }
    if not commit:
        preview_path = output_dir / "approval_preview.md"
        write_approval_preview(preview_path, plan)
        result["approval_preview"] = str(preview_path)
        return result

    before = fetch_snapshot(config)
    write_json(output_dir / "snapshot_before_write.json", before)
    for action in plan.get("actions", []):
        if action.get("action") != "append_row":
            result["actions"].append({"action": action, "status": "skipped", "reason": "지원하지 않는 작업"})
            continue
        write_result = append_row(config, action["target_sheet"], action.get("data", {}))
        result["actions"].append({"action": action, "status": "done", "result": write_result})
    after = fetch_snapshot(config)
    write_json(output_dir / "snapshot_after_write.json", after)
    return result

