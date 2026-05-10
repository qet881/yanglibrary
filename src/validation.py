from __future__ import annotations

from typing import Any


REQUIRED_FIELDS = ["title", "author", "library_holdings", "score", "subscores", "score_reason", "confidence", "thirty_page_test"]


def validate_recommendations(scored: list[dict[str, Any]], candidate_pool_size: int, config: dict[str, Any]) -> dict[str, Any]:
    target = int(config.get("recommendation", {}).get("target_count", 20))
    min_pool = int(config.get("yplib", {}).get("min_candidate_pool", 40))
    issues: list[str] = []
    if candidate_pool_size < min_pool:
        issues.append(f"후보 도서가 {candidate_pool_size}권으로 최소 권장 {min_pool}권보다 적습니다.")
    if len(scored) < target:
        issues.append(f"최종 추천 후보가 {len(scored)}권으로 목표 {target}권보다 적습니다.")
    seen: set[str] = set()
    for item in scored:
        key = item.get("identity_key")
        if key in seen:
            issues.append(f"중복 후보가 있습니다: {item.get('title')}")
        seen.add(key)
        missing = [field for field in REQUIRED_FIELDS if not item.get(field)]
        if missing:
            issues.append(f"{item.get('title', '제목 없음')} 필수 필드 누락: {', '.join(missing)}")
    status = "pass" if not issues else "conditional_fail"
    return {
        "status": status,
        "candidate_pool_size": candidate_pool_size,
        "recommendation_count": len(scored),
        "issues": issues,
        "summary": "검증 통과" if not issues else "조건부 실패: " + " / ".join(issues[:3]),
    }

