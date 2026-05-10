from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import requests
import urllib3

from .utils import clean_html, identity_key, normalize_text, primary_author_key


def search_yplib(config: dict[str, Any], query_plan: dict[str, Any]) -> dict[str, Any]:
    yplib = config.get("yplib", {})
    base_url = yplib.get("base_url", "https://www.yplib.go.kr").rstrip("/")
    endpoint = yplib.get("search_endpoint", "/api/search")
    url = f"{base_url}{endpoint}"
    verify_ssl = bool(yplib.get("verify_ssl", True))
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    delay = float(yplib.get("request_delay_seconds", 1.0))
    timeout = float(yplib.get("timeout_seconds", 20))
    max_pages = int(yplib.get("max_pages_per_query", 2))
    default_payload = dict(yplib.get("default_payload", {}))
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    headers = {
        "User-Agent": "Mozilla/5.0 yangpyeong-library-agent/0.1",
        "Referer": yplib.get("referer", f"{base_url}/searchResult"),
    }
    for query_item in query_plan.get("queries", []):
        query = query_item.get("query", "")
        for page in range(1, max_pages + 1):
            payload = dict(default_payload)
            payload.update({"searchKeyword": query, "page": page})
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=timeout, verify=verify_ssl)
                response.raise_for_status()
                data = response.json()
                contents = data.get("contents") or {}
                results.append(
                    {
                        "query": query,
                        "page": page,
                        "payload": payload,
                        "result": data.get("result", {}),
                        "total_count": contents.get("totalCount", 0),
                        "book_list": contents.get("bookList", []),
                    }
                )
                if page >= int(contents.get("totalPage") or 1):
                    break
            except Exception as exc:
                errors.append({"query": query, "page": page, "error": str(exc)})
                break
            time.sleep(delay)
    return {"source": f"{base_url}{endpoint}", "results": results, "errors": errors}


def normalize_candidates(raw_results: dict[str, Any], portfolio: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    exclude_codes = set(config.get("yplib", {}).get("exclude_pub_form_codes", []))
    exclude_media = config.get("yplib", {}).get("exclude_media_keywords", [])
    exclude_candidate_keywords = config.get("yplib", {}).get("exclude_candidate_keywords", [])
    min_acquisition_year = int(config.get("recommendation", {}).get("min_acquisition_year", 0) or 0)
    read_books = portfolio.get("read_books", [])
    reading_books = portfolio.get("reading_books", [])
    wishlist_books = portfolio.get("wishlist_books", [])
    exclude_authors = set(portfolio.get("settings", {}).get("exclude_authors", []))
    merged: dict[str, dict[str, Any]] = {}

    for result in raw_results.get("results", []):
        query = result.get("query", "")
        for item in result.get("book_list", []):
            if item.get("pubFormCode") in exclude_codes:
                continue
            if any(keyword in str(item.get("contentsType", "")) for keyword in exclude_media):
                continue
            title = clean_html(item.get("originalTitle") or item.get("title"))
            author = clean_html(item.get("originalAuthor") or item.get("author"))
            if not title or not author:
                continue
            candidate_text = " ".join(
                [
                    title,
                    author,
                    clean_html(item.get("classNoMdesc") or item.get("classNoSdesc")),
                    clean_html(item.get("useObject")),
                    clean_html(item.get("shelfLocName")),
                ]
            )
            if any(keyword and keyword in candidate_text for keyword in exclude_candidate_keywords):
                continue
            if any(excluded in author for excluded in exclude_authors):
                continue
            key = identity_key(title, author)
            if matches_existing(title, author, read_books) or matches_existing(title, author, reading_books):
                continue
            portfolio_status = "wishlist" if matches_existing(title, author, wishlist_books) else "new"
            holding = {
                "library": clean_html(item.get("libName")),
                "availability": clean_html(item.get("loanStatus") or item.get("workingStatus") or "확인 필요"),
                "call_number": clean_html(item.get("callNo")),
                "acquisition_date": clean_html(item.get("inputDate")),
                "acquisition_date_label": "등록일" if item.get("inputDate") else "",
                "is_new_arrival": False,
                "source_url": "https://www.yplib.go.kr/searchResult",
            }
            if min_acquisition_year and not holding_meets_min_year(holding, min_acquisition_year):
                continue
            if key not in merged:
                merged[key] = {
                    "title": title,
                    "author": author,
                    "author_key": primary_author_key(author),
                    "isbn": clean_html(item.get("isbn")),
                    "publisher": clean_html(item.get("originalPublisher") or item.get("publisher")),
                    "pub_year": clean_html(item.get("pubYear")),
                    "material_type": clean_html(item.get("contentsType")),
                    "class_description": clean_html(item.get("classNoMdesc") or item.get("classNoSdesc")),
                    "library_holdings": [],
                    "portfolio_status": portfolio_status,
                    "identity_key": key,
                    "raw_queries": [],
                }
            merged[key]["raw_queries"].append(query)
            merged[key]["library_holdings"].append(holding)

    return list(merged.values())


def holding_meets_min_year(holding: dict[str, Any], min_year: int) -> bool:
    raw_date = str(holding.get("acquisition_date") or "").strip()
    if not raw_date:
        return False
    try:
        return datetime.fromisoformat(raw_date[:10]).year >= min_year
    except ValueError:
        return raw_date[:4].isdigit() and int(raw_date[:4]) >= min_year


def matches_existing(title: str, author: str, books: list[dict[str, Any]]) -> bool:
    candidate_title = normalize_text(title)
    candidate_author = primary_author_key(author)
    for book in books:
        existing_title = normalize_text(book.get("title", ""))
        existing_author = primary_author_key(book.get("author", ""))
        if not existing_title or not existing_author:
            continue
        same_author = existing_author == candidate_author
        title_variant = existing_title in candidate_title or candidate_title in existing_title
        if same_author and title_variant:
            return True
    return False
