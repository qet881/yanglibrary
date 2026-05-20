from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .notify import is_email_enabled, is_telegram_enabled, send_email_report, send_telegram_report
from .portfolio import build_taste_profile, normalize_portfolio
from .providers.yplib_api import collect_yplib_api
from .providers.yplib_crawler import collect_yplib_crawler
from .query_plan import build_query_plan
from .radar_scoring import build_radar_taste_dna, confidence_rank, score_radar_candidates
from .sheets import fetch_snapshot
from .utils import ensure_dir, identity_key, make_run_id, now_kst, primary_author_key, read_json, write_json
from .yplib import matches_existing


def run_radar(
    config: dict[str, Any],
    output_root: Path,
    snapshot_path: Path | None = None,
    notify_policy: str = "immediate",
) -> dict[str, Any]:
    if notify_policy not in {"immediate", "silent", "digest"}:
        raise ValueError(f"unsupported notify_policy: {notify_policy}")
    run_id = make_run_id()
    run_dir = ensure_dir(output_root / run_id)
    radar_config = effective_radar_config(config)

    snapshot = read_json(snapshot_path) if snapshot_path else fetch_snapshot(radar_config)
    write_json(run_dir / "portfolio_snapshot.json", snapshot)

    portfolio = normalize_portfolio(snapshot, radar_config)
    write_json(run_dir / "portfolio_normalized.json", portfolio)

    threshold = float(radar_config.get("recommendation", {}).get("high_rating_threshold", 4.0))
    taste_profile = build_taste_profile(portfolio, threshold)
    dna = build_radar_taste_dna(portfolio, taste_profile)
    write_json(run_dir / "radar_taste_dna.json", dna)

    max_queries = int(radar_config.get("yplib", {}).get("max_queries", 12))
    query_plan = build_query_plan(portfolio, taste_profile, max_queries)
    write_json(run_dir / "query_plan.json", query_plan)

    provider_results = collect_providers(radar_config, query_plan, portfolio)
    write_json(run_dir / "radar_provider_results.json", {key: value.as_dict() for key, value in provider_results.items()})

    candidates = merge_candidates(
        [
            candidate
            for provider_result in provider_results.values()
            for candidate in provider_result.candidates
        ],
        portfolio,
        radar_config,
    )
    write_json(run_dir / "radar_candidates.json", candidates)

    scored = score_radar_candidates(candidates, dna, radar_config)
    write_json(run_dir / "radar_scored_candidates.json", scored)

    state_path = Path(radar_config.get("radar", {}).get("state_file", output_root / "radar" / "radar_state.json"))
    previous_state = load_radar_state(state_path)
    now = now_kst()
    changes, next_state = compare_radar_state(scored, previous_state, radar_config, now, notify_policy=notify_policy)
    write_json(run_dir / "radar_changes.json", changes)
    write_json(run_dir / "radar_state_after.json", next_state)
    write_json(state_path, next_state)

    report_path = run_dir / "radar_report.md"
    alerts_path = run_dir / "radar_alerts.md"
    write_radar_report(report_path, run_id, provider_results, candidates, scored, changes, email_sent=False)
    write_radar_alerts(alerts_path, changes)

    should_notify = notify_policy in {"immediate", "digest"} and bool(changes.get("alert_items"))
    email_enabled = is_email_enabled(radar_config.get("notify", {}).get("email", {}))
    email_result = (
        send_email_report(radar_config, alerts_path, run_id)
        if should_notify
        else {"enabled": email_enabled, "sent": False, "reason": "notification suppressed" if notify_policy == "silent" else "no alert items"}
    )
    write_json(run_dir / "radar_email_result.json", email_result)
    telegram_enabled = is_telegram_enabled(radar_config.get("notify", {}).get("telegram", {}))
    telegram_result = (
        send_telegram_report(radar_config, alerts_path, run_id)
        if should_notify
        else {"enabled": telegram_enabled, "sent": False, "reason": "notification suppressed" if notify_policy == "silent" else "no alert items"}
    )
    write_json(run_dir / "radar_telegram_result.json", telegram_result)
    notification_sent = bool(email_result.get("sent") or telegram_result.get("sent"))
    if notification_sent:
        next_state = finalize_alert_state(next_state, changes.get("alert_items", []), now)
        write_json(run_dir / "radar_state_after.json", next_state)
        write_json(state_path, next_state)
    write_radar_report(report_path, run_id, provider_results, candidates, scored, changes, email_sent=bool(email_result.get("sent")))

    summary = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "yplib_candidate_count": len(provider_results.get("yplib", empty_provider()).candidates),
        "deduped_candidate_count": len(candidates),
        "alert_count": len(changes.get("alert_items", [])),
        "notify_policy": notify_policy,
        "email": email_result,
        "telegram": telegram_result,
        "report": str(report_path),
        "alerts": str(alerts_path),
        "state_file": str(state_path),
        "errors": [
            error
            for provider_result in provider_results.values()
            for error in provider_result.errors
        ],
    }
    write_json(run_dir / "radar_run_summary.json", summary)
    return summary


def effective_radar_config(config: dict[str, Any]) -> dict[str, Any]:
    radar_config = deepcopy(config)
    radar_settings = radar_config.setdefault("radar", {})
    if radar_settings.get("disable_freshness_filter", True):
        radar_config.setdefault("recommendation", {})["min_acquisition_year"] = 0
        radar_config.setdefault("recommendation", {})["new_arrival_days"] = 0
    radar_config.setdefault("providers", {})
    radar_config["providers"].setdefault("yplib", {"enabled": True, "provider": "auto"})
    radar_config["providers"].setdefault("millie", {"enabled": False})
    radar_config["providers"]["millie"]["enabled"] = False
    radar_config.setdefault("notify", {}).setdefault("email", {"enabled": False, "subject_prefix": "[Book Radar]", "max_items": 5})
    radar_config.setdefault("notify", {}).setdefault("telegram", {"enabled": False, "subject_prefix": "[Book Radar]", "max_chars_per_message": 3500})
    return radar_config


def collect_providers(config: dict[str, Any], query_plan: dict[str, Any], portfolio: dict[str, Any]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    yplib_provider = config.get("providers", {}).get("yplib", {})
    if yplib_provider.get("enabled", True):
        mode = yplib_provider.get("provider", "auto")
        if mode == "api":
            results["yplib"] = collect_yplib_api(config, query_plan, portfolio)
        elif mode == "crawler":
            results["yplib"] = collect_yplib_crawler(config, query_plan, portfolio)
        else:
            api_result = collect_yplib_api(config, query_plan, portfolio)
            has_api_results = bool(api_result.candidates)
            has_hard_errors = bool(api_result.errors) and not has_api_results
            results["yplib"] = api_result if has_api_results or not has_hard_errors else collect_yplib_crawler(config, query_plan, portfolio)
    return results


def empty_provider() -> Any:
    class Empty:
        candidates: list[dict[str, Any]] = []

    return Empty()


def merge_candidates(candidates: list[dict[str, Any]], portfolio: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        title = str(candidate.get("title", "")).strip()
        author = str(candidate.get("author", "")).strip()
        if not title:
            continue
        if is_portfolio_duplicate(title, author, portfolio):
            continue
        if is_excluded_author(author, portfolio):
            continue
        if has_excluded_keyword(candidate, config):
            continue
        key = candidate.get("identity_key") or identity_key(title, author)
        if key not in merged:
            merged[key] = {**candidate, "identity_key": key, "sources": []}
        else:
            merged[key]["library_holdings"] = merge_holdings(merged[key].get("library_holdings", []), candidate.get("library_holdings", []))
            merged[key]["raw_queries"] = sorted(set(merged[key].get("raw_queries", []) + candidate.get("raw_queries", [])))
        source = candidate.get("source", "unknown")
        if source not in merged[key]["sources"]:
            merged[key]["sources"].append(source)
    return list(merged.values())


def is_portfolio_duplicate(title: str, author: str, portfolio: dict[str, Any]) -> bool:
    return (
        matches_existing(title, author, portfolio.get("read_books", []))
        or matches_existing(title, author, portfolio.get("reading_books", []))
        or matches_existing(title, author, portfolio.get("wishlist_books", []))
    )


def is_excluded_author(author: str, portfolio: dict[str, Any]) -> bool:
    author_key = primary_author_key(author)
    for excluded in portfolio.get("settings", {}).get("exclude_authors", []):
        excluded_key = primary_author_key(excluded)
        if excluded_key and excluded_key == author_key:
            return True
        if excluded and excluded in author:
            return True
    return False


def has_excluded_keyword(candidate: dict[str, Any], config: dict[str, Any]) -> bool:
    keywords = config.get("yplib", {}).get("exclude_candidate_keywords", [])
    text = " ".join(
        str(candidate.get(key, ""))
        for key in ["title", "author", "publisher", "material_type", "class_description"]
    )
    return any(keyword and keyword in text for keyword in keywords)


def merge_holdings(existing: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {(item.get("library", ""), item.get("availability", ""), item.get("call_number", "")) for item in existing}
    merged = list(existing)
    for item in new:
        key = (item.get("library", ""), item.get("availability", ""), item.get("call_number", ""))
        if key not in seen:
            seen.add(key)
            merged.append(item)
    return merged


def load_radar_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "items": {}}
    data = read_json(path)
    if "items" not in data:
        return {"version": 1, "items": {str(item.get("identity_key")): item for item in data if item.get("identity_key")}}
    return data


def compare_radar_state(
    scored: list[dict[str, Any]],
    previous_state: dict[str, Any],
    config: dict[str, Any],
    now: datetime,
    notify_policy: str = "immediate",
) -> tuple[dict[str, Any], dict[str, Any]]:
    previous_items = previous_state.get("items", {})
    next_items = dict(previous_items)
    previous_pending = previous_state.get("pending_alerts", {})
    next_pending = dict(previous_pending)
    changes = {
        "new_strong": [],
        "availability_changed": [],
        "score_confidence_rise": [],
        "watchlist": [],
        "alert_items": [],
        "pending_alert_items": [],
    }
    watch_threshold = int(config.get("radar", {}).get("watch_score_threshold", 80))
    max_alerts = int(config.get("radar", {}).get("max_alerts_per_run", 5))
    email_max_items = int(config.get("notify", {}).get("email", {}).get("max_items", max_alerts) or max_alerts)
    telegram_max_items = int(config.get("notify", {}).get("telegram", {}).get("max_items", max_alerts) or max_alerts)
    max_alerts = min(max_alerts, email_max_items, telegram_max_items)
    suppress_days = int(config.get("radar", {}).get("suppress_repeat_days", 14))

    if notify_policy == "digest":
        for pending in previous_pending.values():
            item = pending_to_alert_item(pending)
            if item and len(changes["alert_items"]) < max_alerts:
                changes["alert_items"].append(item)

    for item in scored:
        key = item.get("identity_key")
        if not key:
            continue
        previous = previous_items.get(key)
        availability = item_availability_key(item)
        state_item = build_state_item(item, previous, availability, now)
        alert_reasons: list[str] = []

        if not previous and item.get("alert_eligible"):
            changes["new_strong"].append(item)
            alert_reasons.append("새로 발견된 강한 후보")
        elif previous:
            old_availability = previous.get("last_availability", "")
            if old_availability != availability and is_available_key(availability):
                changes["availability_changed"].append(item)
                alert_reasons.append("이용 가능 상태로 변경")
            if rose_above_threshold(item, previous, config):
                changes["score_confidence_rise"].append(item)
                alert_reasons.append("점수와 확신도 상승")

        if item.get("score", 0) >= watch_threshold and not item.get("alert_eligible"):
            changes["watchlist"].append(item)

        if alert_reasons and should_send_alert(previous, now, suppress_days):
            alert_item = {**item, "alert_reasons": alert_reasons}
            next_pending[key] = pending_alert_entry(alert_item, next_pending.get(key), now)
            changes["pending_alert_items"].append(alert_item)
            if notify_policy in {"immediate", "digest"} and not has_alert_item(changes["alert_items"], key) and len(changes["alert_items"]) < max_alerts:
                changes["alert_items"].append(alert_item)

        next_items[key] = state_item

    return changes, {"version": 1, "updated_at": now.isoformat(), "items": next_items, "pending_alerts": next_pending}


def pending_alert_entry(item: dict[str, Any], previous: dict[str, Any] | None, now: datetime) -> dict[str, Any]:
    reasons = sorted(set((previous or {}).get("alert_reasons", []) + item.get("alert_reasons", [])))
    return {
        "identity_key": item.get("identity_key"),
        "first_detected_at": (previous or {}).get("first_detected_at") or now.isoformat(),
        "last_detected_at": now.isoformat(),
        "alert_reasons": reasons,
        "item": compact_alert_item(item, reasons),
    }


def compact_alert_item(item: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    keep = [
        "identity_key",
        "title",
        "author",
        "source",
        "source_label",
        "availability",
        "availability_summary",
        "grade",
        "score",
        "confidence",
        "recommendation_reason",
        "dna_connection",
        "life_book_connection",
        "similar_high_books",
        "avoidance_distance",
        "risk_factors",
        "reading_mode",
        "thirty_page_test",
        "why_now",
        "source_url",
    ]
    compact = {key: item.get(key) for key in keep if key in item}
    compact["alert_reasons"] = reasons
    return compact


def pending_to_alert_item(pending: dict[str, Any]) -> dict[str, Any] | None:
    item = pending.get("item")
    if not isinstance(item, dict):
        return None
    reasons = pending.get("alert_reasons") or item.get("alert_reasons") or []
    return {**item, "alert_reasons": reasons, "pending_since": pending.get("first_detected_at")}


def has_alert_item(items: list[dict[str, Any]], key: str) -> bool:
    return any(item.get("identity_key") == key for item in items)


def finalize_alert_state(state: dict[str, Any], alert_items: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    items = state.get("items", {})
    pending = dict(state.get("pending_alerts", {}))
    for alert in alert_items:
        key = alert.get("identity_key")
        if not key:
            continue
        state_item = items.get(key)
        if state_item:
            state_item["last_alerted_at"] = now.isoformat()
            state_item["alert_count"] = int(state_item.get("alert_count", 0) or 0) + 1
        pending.pop(key, None)
    state["pending_alerts"] = pending
    state["updated_at"] = now.isoformat()
    return state


def build_state_item(item: dict[str, Any], previous: dict[str, Any] | None, availability: str, now: datetime) -> dict[str, Any]:
    return {
        "identity_key": item.get("identity_key"),
        "isbn": item.get("isbn", ""),
        "title": item.get("title", ""),
        "author": item.get("author", ""),
        "source": item.get("source", ""),
        "first_seen_at": (previous or {}).get("first_seen_at") or now.isoformat(),
        "last_seen_at": now.isoformat(),
        "last_score": item.get("score", 0),
        "last_grade": item.get("grade", ""),
        "last_confidence": item.get("confidence", "low"),
        "last_availability": availability,
        "last_source_url": item.get("source_url", ""),
        "last_alerted_at": (previous or {}).get("last_alerted_at"),
        "alert_count": int((previous or {}).get("alert_count", 0)),
    }


def item_availability_key(item: dict[str, Any]) -> str:
    return item.get("availability_summary") or ""


def is_available_key(value: str) -> bool:
    return any(token in str(value) for token in ["대출가능", "가능", "확인됨", "available"])


def rose_above_threshold(item: dict[str, Any], previous: dict[str, Any], config: dict[str, Any]) -> bool:
    threshold = int(config.get("radar", {}).get("alert_score_threshold", 90))
    min_conf = confidence_rank(config.get("radar", {}).get("min_alert_confidence", "medium"))
    old_score = int(previous.get("last_score", 0) or 0)
    old_conf = confidence_rank(previous.get("last_confidence", "low"))
    new_score = int(item.get("score", 0) or 0)
    new_conf = confidence_rank(item.get("confidence", "low"))
    return new_score >= threshold and new_conf >= min_conf and (old_score < threshold or new_conf > old_conf)


def should_send_alert(previous: dict[str, Any] | None, now: datetime, suppress_days: int) -> bool:
    if not previous or not previous.get("last_alerted_at"):
        return True
    try:
        last = datetime.fromisoformat(previous["last_alerted_at"])
    except ValueError:
        return True
    return now - last >= timedelta(days=suppress_days)


def write_radar_report(
    path: Path,
    run_id: str,
    provider_results: dict[str, Any],
    candidates: list[dict[str, Any]],
    scored: list[dict[str, Any]],
    changes: dict[str, Any],
    email_sent: bool,
) -> None:
    lines = [
        "# Book Radar 리포트",
        "",
        "## 이번 실행 요약",
        "",
        f"- 실행 시간: {run_id}",
        f"- 양평도서관 후보 수: {len(provider_results.get('yplib', empty_provider()).candidates)}",
        f"- 중복 제거 후 후보 수: {len(candidates)}",
        f"- 알림 후보 수: {len(changes.get('alert_items', []))}",
        f"- 오늘 이메일 발송 여부: {'예' if email_sent else '아니오'}",
        "",
    ]
    sections = [
        ("새로 감지된 강력 후보", changes.get("new_strong", [])),
        ("대출 가능으로 바뀐 후보", changes.get("availability_changed", [])),
        ("점수와 확신도가 상승한 후보", changes.get("score_confidence_rise", [])),
        ("계속 추적할 후보", changes.get("watchlist", [])),
    ]
    for title, items in sections:
        lines.extend([f"## {title}", ""])
        if not items:
            lines.extend(["- 해당 없음", ""])
            continue
        for item in items[:10]:
            append_candidate_block(lines, item)
    if not changes.get("alert_items"):
        lines.extend(["## 오늘은 알림 없음", "", "강한 후보가 없거나, 이전 알림 억제 기간 안에 있어 이메일 후보로 올리지 않았습니다.", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def write_radar_alerts(path: Path, changes: dict[str, Any]) -> None:
    lines = ["# Book Radar 알림", ""]
    alert_items = changes.get("alert_items", [])
    if not alert_items:
        lines.extend(["오늘은 알림 없음", ""])
    else:
        for item in alert_items:
            append_candidate_block(lines, item)
    path.write_text("\n".join(lines), encoding="utf-8")


def append_candidate_block(lines: list[str], item: dict[str, Any]) -> None:
    reasons = ", ".join(item.get("alert_reasons", [])) or item.get("recommendation_reason", "")
    risks = ", ".join(item.get("risk_factors", [])) if isinstance(item.get("risk_factors"), list) else str(item.get("risk_factors", ""))
    similar = ", ".join(item.get("similar_high_books", [])) or "확인 필요"
    life = ", ".join(item.get("life_book_connection", [])) or "직접 연결 없음"
    lines.extend(
        [
            f"### {item.get('title', '')} / {item.get('author', '')}",
            f"- 출처: {item.get('source_label') or item.get('source') or '확인 필요'}",
            f"- 이용 가능 상태: {item.get('availability_summary') or item.get('availability') or '확인 필요'}",
            f"- 등급: {item.get('grade', '')}",
            f"- 점수: {item.get('score', 0)}",
            f"- 확신도: {item.get('confidence', 'low')}",
            f"- 추천 이유: {reasons}",
            f"- 4.0점 이상 고평점 DNA 연결: {item.get('dna_connection', '')}",
            f"- 5.0점 인생작과의 직접 연결 여부: {life}",
            f"- 비슷한 고평점 책: {similar}",
            f"- 손절 패턴과의 거리: {item.get('avoidance_distance', '')}",
            f"- 위험 요소: {risks}",
            f"- 읽는 방식 판정: {item.get('reading_mode', '')}",
            f"- 30페이지 테스트 포인트: {item.get('thirty_page_test', '')}",
            f"- 왜 지금 읽을 만한지: {item.get('why_now', '')}",
            f"- 링크: {item.get('source_url') or '확인 필요'}",
            "",
        ]
    )
