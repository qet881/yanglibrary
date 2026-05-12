from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from .base import ProviderResult
from ..utils import identity_key, primary_author_key


def collect_millie(config: dict[str, Any], query_plan: dict[str, Any] | None = None) -> ProviderResult:
    provider_config = config.get("providers", {}).get("millie", {})
    if not provider_config.get("enabled", False):
        return ProviderResult(source="millie", raw_results={"mode": "disabled"})

    mode = provider_config.get("provider", "manual_or_public")
    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    raw_results: dict[str, Any] = {"mode": mode}

    if mode in {"public", "manual_or_public"}:
        public = collect_public_search(config, query_plan or {"queries": []})
        candidates.extend(public.candidates)
        errors.extend(public.errors)
        raw_results["public_search"] = public.raw_results

    if mode in {"manual", "manual_or_public"}:
        manual = collect_manual_watchlist(provider_config)
        candidates.extend(manual.candidates)
        errors.extend(manual.errors)
        raw_results["manual_watchlist"] = manual.raw_results

    return ProviderResult(source="millie", raw_results=raw_results, candidates=dedupe_candidates(candidates), errors=errors)


def collect_manual_watchlist(provider_config: dict[str, Any]) -> ProviderResult:
    manual_file = provider_config.get("manual_input_file", "data/millie_watchlist.csv")
    path = Path(manual_file)
    if not path.exists():
        return ProviderResult(
            source="millie",
            raw_results={"mode": "manual_or_public", "manual_input_file": str(path), "missing": True},
            errors=[{"stage": "manual_input", "error": f"{path} not found"}],
        )

    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=2):
            title = (row.get("title") or row.get("제목") or "").strip()
            author = (row.get("author") or row.get("저자") or row.get("작가") or "").strip()
            if not title:
                errors.append({"row": row_number, "error": "title is required"})
                continue
            availability = (row.get("availability") or row.get("이용상태") or "확인 필요").strip()
            source_url = (row.get("source_url") or row.get("url") or "").strip()
            key = identity_key(title, author)
            candidates.append(
                {
                    "title": title,
                    "author": author,
                    "author_key": primary_author_key(author),
                    "source": "millie",
                    "source_label": "밀리의 서재",
                    "availability": availability if availability in {"확인됨", "확인 필요", "미지원"} else "확인 필요",
                    "source_url": source_url,
                    "collected_at": row.get("collected_at", ""),
                    "identity_key": key,
                    "raw_queries": ["millie_manual_watchlist"],
                    "library_holdings": [
                        {
                            "library": "밀리의 서재",
                            "availability": availability,
                            "source_url": source_url,
                        }
                    ],
                    "portfolio_status": "new",
                }
            )

    return ProviderResult(
        source="millie",
        raw_results={"mode": "manual_or_public", "manual_input_file": str(path), "count": len(candidates)},
        candidates=candidates,
        errors=errors,
    )


def collect_public_search(config: dict[str, Any], query_plan: dict[str, Any]) -> ProviderResult:
    provider_config = config.get("providers", {}).get("millie", {})
    api_url = provider_config.get("public_search_url", "https://live-api.millie.co.kr/v3/search/content")
    referer_base = provider_config.get("referer_base", "https://www.millie.co.kr/v4/library/search")
    max_queries = int(provider_config.get("max_queries", min(12, len(query_plan.get("queries", [])))))
    limit = int(provider_config.get("limit_per_query", 10))
    delay = float(provider_config.get("request_delay_seconds", config.get("yplib", {}).get("request_delay_seconds", 1.0)))
    timeout = float(provider_config.get("timeout_seconds", config.get("yplib", {}).get("timeout_seconds", 20)))
    candidates: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 book-radar/0.1 (+public metadata availability check)",
            "Origin": "https://www.millie.co.kr",
        }
    )

    for query_item in query_plan.get("queries", [])[:max_queries]:
        query = str(query_item.get("query", "")).strip()
        if not query:
            continue
        params = {
            "keyword": query,
            "orderBy": provider_config.get("order_by", "accuracy"),
            "startPage": 0,
            "limitCount": limit,
            "searchType": provider_config.get("search_type", "isInactive"),
            "rent_yn": "N",
            "adult_yn": provider_config.get("adult_yn", "Y"),
            "contentCode": "",
            "fileTypeCode": "",
        }
        try:
            response = session.get(
                api_url,
                params=params,
                headers={"Referer": f"{referer_base}/{quote(query)}"},
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("RESP_CD") != 200:
                raise ValueError(f"{data.get('RESP_CD')}: {data.get('RESP_MSG')}")
            items = (data.get("RESP_DATA") or {}).get("list") or []
            results.append({"query": query, "count": len(items)})
            for item in items:
                candidate = normalize_public_item(item, query)
                if candidate:
                    candidates.append(candidate)
        except Exception as exc:
            errors.append({"query": query, "error": str(exc)})
        time.sleep(delay)

    return ProviderResult(
        source="millie_public",
        raw_results={"source": api_url, "results": results, "errors": errors},
        candidates=candidates,
        errors=errors,
    )


def normalize_public_item(item: dict[str, Any], query: str) -> dict[str, Any] | None:
    title = str(item.get("content_name") or item.get("series_group_name") or "").strip()
    author = str(item.get("author") or item.get("reader_name") or "").strip()
    if not title:
        return None
    book_id = str(item.get("book_id") or item.get("book_seq") or "").strip()
    is_service = bool(item.get("is_service"))
    availability = "확인됨" if is_service else "확인 필요"
    source_url = f"https://www.millie.co.kr/v4/book/{book_id}" if book_id else f"https://www.millie.co.kr/v4/library/search/{quote(query)}"
    category = " ".join(str(item.get(key, "")) for key in ["category", "category2"] if item.get(key))
    publisher = str(item.get("book_brand") or "").strip()
    isbn = str(item.get("book_isbn") or "").strip()
    key = identity_key(title, author)
    return {
        "title": title,
        "author": author,
        "author_key": primary_author_key(author),
        "isbn": isbn,
        "publisher": publisher,
        "pub_year": "",
        "material_type": "ebook",
        "class_description": category,
        "source": "millie",
        "source_label": "밀리의 서재",
        "availability": availability,
        "source_url": source_url,
        "collected_at": "",
        "identity_key": key,
        "raw_queries": [query],
        "library_holdings": [
            {
                "library": "밀리의 서재",
                "availability": availability,
                "call_number": "",
                "source_url": source_url,
            }
        ],
        "portfolio_status": "new",
        "millie": {
            "book_id": book_id,
            "is_service": is_service,
            "content_code": item.get("content_code", ""),
            "file_type_code": item.get("file_type_code", ""),
        },
    }


def dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = candidate.get("identity_key")
        if not key:
            continue
        if key not in merged:
            merged[key] = candidate
            continue
        merged[key]["raw_queries"] = sorted(set(merged[key].get("raw_queries", []) + candidate.get("raw_queries", [])))
        if candidate.get("availability") == "확인됨":
            merged[key]["availability"] = "확인됨"
            merged[key]["source_url"] = candidate.get("source_url") or merged[key].get("source_url", "")
            merged[key]["library_holdings"] = candidate.get("library_holdings", merged[key].get("library_holdings", []))
    return list(merged.values())
