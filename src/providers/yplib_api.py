from __future__ import annotations

from typing import Any

from .base import ProviderResult
from ..yplib import normalize_candidates, search_yplib


def collect_yplib_api(config: dict[str, Any], query_plan: dict[str, Any], portfolio: dict[str, Any]) -> ProviderResult:
    raw = search_yplib(config, query_plan)
    candidates = normalize_candidates(raw, portfolio, config)
    for candidate in candidates:
        candidate.setdefault("source", "yplib")
        candidate.setdefault("source_label", "양평도서관")
        candidate.setdefault("source_url", "https://www.yplib.go.kr/searchResult")
        for holding in candidate.get("library_holdings", []):
            holding.setdefault("source_url", candidate["source_url"])
    return ProviderResult(
        source="yplib_api",
        raw_results=raw,
        candidates=candidates,
        errors=raw.get("errors", []),
    )
