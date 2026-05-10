from __future__ import annotations

from pathlib import Path
from typing import Any

from .portfolio import build_taste_profile, normalize_portfolio
from .query_plan import build_query_plan
from .reporting import write_recommendation_report, write_taste_profile_md, write_validation_summary
from .scoring import score_candidates
from .sheets import fetch_snapshot
from .update_plan import write_approval_preview
from .utils import ensure_dir, make_run_id, normalize_text, read_json, write_json
from .utils import primary_author_key
from .validation import validate_recommendations
from .yplib import normalize_candidates, search_yplib


def run_recommend(config: dict[str, Any], output_root: Path, snapshot_path: Path | None = None) -> dict[str, Any]:
    run_id = make_run_id()
    run_dir = ensure_dir(output_root / run_id)
    snapshot = read_json(snapshot_path) if snapshot_path else fetch_snapshot(config)
    write_json(run_dir / "portfolio_snapshot.json", snapshot)

    portfolio = normalize_portfolio(snapshot, config)
    write_json(run_dir / "portfolio_normalized.json", portfolio)

    threshold = float(config.get("recommendation", {}).get("high_rating_threshold", 4.0))
    taste_profile = build_taste_profile(portfolio, threshold)
    write_json(run_dir / "taste_profile.json", taste_profile)
    write_taste_profile_md(run_dir / "taste_profile.md", taste_profile)

    max_queries = int(config.get("yplib", {}).get("max_queries", 12))
    query_plan = build_query_plan(portfolio, taste_profile, max_queries)
    write_json(run_dir / "query_plan.json", query_plan)

    raw_results = search_yplib(config, query_plan)
    write_json(run_dir / "raw_search_results.json", raw_results)

    candidates = normalize_candidates(raw_results, portfolio, config)
    write_json(run_dir / "candidate_pool.json", candidates)

    scored_all = score_candidates(candidates, taste_profile, config)
    target = int(config.get("recommendation", {}).get("target_count", 20))
    scored = apply_author_limits(scored_all, config)[:target]
    for item in scored:
        if "대출가능" not in item.get("availability_summary", "") and item.get("section") != "예약하거나 추적할 책":
            item["section"] = "확인 필요하지만 취향상 강한 책"
    write_json(run_dir / "scored_candidates.json", scored)

    validation = validate_recommendations(scored, len(candidates), config)
    write_json(run_dir / "validation_report.json", validation)
    write_validation_summary(run_dir / "validation_summary.md", validation)
    write_recommendation_report(run_dir / "recommendation_report.md", scored, validation, run_id)
    update_plan = build_recommendation_update_plan(config, scored, run_id)
    write_json(run_dir / "sheets_update_plan.json", update_plan)
    write_approval_preview(run_dir / "approval_preview.md", update_plan)

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "recommendation_report": str(run_dir / "recommendation_report.md"),
        "validation_report": str(run_dir / "validation_report.json"),
        "validation_status": validation.get("status"),
    }


def build_recommendation_update_plan(config: dict[str, Any], scored: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
    target_sheet = config.get("sheets", {}).get("optional", {}).get("recommendations", "추천 결과")
    actions = []
    for rank, item in enumerate(scored, start=1):
        actions.append(
            {
                "action": "append_row",
                "target_sheet": target_sheet,
                "match_keys": ["title", "author"],
                "summary": f"{rank}위 『{item.get('title', '')}』 추천 결과 저장",
                "data": {
                    "순위": rank,
                    "제목": item.get("title", ""),
                    "저자": item.get("author", ""),
                    "점수": item.get("score", ""),
                    "상태": item.get("section", ""),
                    "대출 가능 여부": item.get("availability_summary", ""),
                    "링크": "https://www.yplib.go.kr/searchResult",
                    "메모": item.get("score_reason", ""),
                },
            }
        )
    return {"run_id": run_id, "mode": "dry_run", "actions": actions}


def apply_author_limits(scored: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    max_per_author = int(config.get("recommendation", {}).get("max_per_author", 0) or 0)
    limits = config.get("recommendation", {}).get("author_limits", [])
    if not max_per_author and not limits:
        return scored
    counts: dict[str, int] = {}
    specific_limits = {
        primary_author_key(limit.get("author", "")): int(limit.get("max_total", max_per_author or 999999))
        for limit in limits
        if limit.get("author")
    }
    filtered = []
    for item in scored:
        author_key = item.get("author_key") or primary_author_key(item.get("author", ""))
        title_key = normalize_text(item.get("title", ""))
        if max_per_author and any(used_author and used_author in title_key for used_author in counts):
            continue
        if not author_key:
            filtered.append(item)
            continue
        limit = specific_limits.get(author_key, max_per_author or 999999)
        used = counts.get(author_key, 0)
        if used >= limit:
            continue
        counts[author_key] = used + 1
        filtered.append(item)
    return filtered
