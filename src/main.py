from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .pipeline import run_recommend
from .sheets import check_setup
from .update_plan import execute_update_plan, write_approval_preview
from .utils import ensure_dir, make_run_id, read_json, write_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="양평군도서관 Google Sheets 독서 추천 에이전트")
    parser.add_argument("--config", default="config/app.yaml")
    parser.add_argument("--mode", choices=["check-setup", "recommend", "update-sheets"], required=True)
    parser.add_argument("--output", default="output")
    parser.add_argument("--snapshot", help="Google Sheets 대신 로컬 portfolio_snapshot.json을 사용합니다.")
    parser.add_argument("--update-plan", help="sheets_update_plan.json 경로")
    parser.add_argument("--approved", action="store_true", help="사용자가 변경표를 승인했음을 표시합니다.")
    parser.add_argument("--commit", action="store_true", help="승인된 계획을 실제 Google Sheets에 씁니다.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = load_config(args.config)
    output_root = ensure_dir(Path(args.output))

    if args.mode == "check-setup":
        run_id = make_run_id()
        run_dir = ensure_dir(output_root / run_id)
        result = check_setup(config)
        write_json(run_dir / "sheets_connection_check.json", result)
        print(f"check-setup complete: {run_dir / 'sheets_connection_check.json'}")
        if result.get("errors"):
            print("errors:", "; ".join(result["errors"]))
        return

    if args.mode == "recommend":
        result = run_recommend(config, output_root, Path(args.snapshot) if args.snapshot else None)
        print(f"recommendation report: {result['recommendation_report']}")
        print(f"validation: {result['validation_status']} ({result['validation_report']})")
        return

    if args.mode == "update-sheets":
        if not args.update_plan:
            raise SystemExit("--update-plan이 필요합니다.")
        plan = read_json(Path(args.update_plan))
        run_id = plan.get("run_id") or make_run_id()
        run_dir = ensure_dir(output_root / run_id)
        write_approval_preview(run_dir / "approval_preview.md", plan)
        result = execute_update_plan(config, plan, commit=args.commit, approved=args.approved, output_dir=run_dir)
        write_json(run_dir / "sheets_update_result.json", result)
        print(f"update-sheets {result['mode']}: {run_dir / 'sheets_update_result.json'}")
        return


if __name__ == "__main__":
    main()

