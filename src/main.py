from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .env import load_env_file
from .pipeline import run_recommend
from .radar import run_radar
from .sheets import check_setup
from .update_plan import execute_update_plan, write_approval_preview
from .utils import ensure_dir, make_run_id, read_json, write_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Book Radar and Yangpyeong Library portfolio pipeline")
    parser.add_argument("--config", default="config/app.yaml")
    parser.add_argument("--mode", choices=["check-setup", "recommend", "update-sheets", "radar"], required=True)
    parser.add_argument("--output", default="output")
    parser.add_argument("--snapshot", help="Use a local portfolio_snapshot.json instead of Google Sheets.")
    parser.add_argument(
        "--notify-policy",
        choices=["immediate", "silent", "digest"],
        default="immediate",
        help="radar notification policy: immediate sends now, silent only records state, digest sends accumulated alerts.",
    )
    parser.add_argument("--update-plan", help="Path to sheets_update_plan.json")
    parser.add_argument("--approved", action="store_true", help="Mark a Google Sheets update plan as approved.")
    parser.add_argument("--commit", action="store_true", help="Actually write approved updates to Google Sheets.")
    return parser


def main() -> None:
    load_env_file()
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

    if args.mode == "radar":
        result = run_radar(
            config,
            output_root,
            Path(args.snapshot) if args.snapshot else None,
            notify_policy=args.notify_policy,
        )
        print(f"Book Radar report: {result['report']}")
        print(f"Book Radar alerts: {result['alerts']}")
        print(f"Book Radar alert count: {result['alert_count']}")
        return

    if args.mode == "update-sheets":
        if not args.update_plan:
            raise SystemExit("--update-plan is required")
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
