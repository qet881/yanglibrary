from __future__ import annotations

import time
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .base import ProviderResult
from ..utils import clean_html, identity_key, primary_author_key


def collect_yplib_crawler(config: dict[str, Any], query_plan: dict[str, Any], portfolio: dict[str, Any]) -> ProviderResult:
    yplib = config.get("yplib", {})
    base_url = yplib.get("base_url", "https://www.yplib.go.kr").rstrip("/")
    search_path = yplib.get("crawler_search_path", "/searchResult")
    delay = float(yplib.get("request_delay_seconds", 1.0))
    timeout = float(yplib.get("timeout_seconds", 20))
    max_pages = int(yplib.get("max_pages_per_query", 1))
    verify_ssl = bool(yplib.get("verify_ssl", True))
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 book-radar/0.1 (+metadata search)"})

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    candidates: dict[str, dict[str, Any]] = {}

    robots = _check_robots(session, base_url, timeout, verify_ssl)
    if robots.get("error"):
        errors.append({"stage": "robots", "error": robots["error"]})

    for query_item in query_plan.get("queries", []):
        query = str(query_item.get("query", "")).strip()
        if not query:
            continue
        for page in range(1, max_pages + 1):
            try:
                response = session.get(
                    urljoin(base_url, search_path),
                    params={"searchKeyword": query, "page": page},
                    timeout=timeout,
                    verify=verify_ssl,
                )
                response.raise_for_status()
                parsed = _parse_search_page(response.text, base_url)
                results.append({"query": query, "page": page, "items": parsed})
                for item in parsed:
                    title = item.get("title", "")
                    author = item.get("author", "")
                    if not title or not author:
                        continue
                    key = identity_key(title, author)
                    if key not in candidates:
                        candidates[key] = {
                            "title": title,
                            "author": author,
                            "author_key": primary_author_key(author),
                            "isbn": item.get("isbn", ""),
                            "publisher": item.get("publisher", ""),
                            "pub_year": item.get("pub_year", ""),
                            "material_type": item.get("material_type", ""),
                            "class_description": item.get("class_description", ""),
                            "library_holdings": [],
                            "portfolio_status": "new",
                            "identity_key": key,
                            "raw_queries": [],
                            "source": "yplib",
                            "source_label": "양평도서관",
                            "source_url": item.get("link") or urljoin(base_url, search_path),
                        }
                    candidates[key]["raw_queries"].append(query)
                    candidates[key]["library_holdings"].append(
                        {
                            "library": item.get("library", ""),
                            "availability": item.get("availability", "확인 필요"),
                            "call_number": item.get("call_number", ""),
                            "acquisition_date": item.get("acquisition_date", ""),
                            "source_url": item.get("link") or urljoin(base_url, search_path),
                        }
                    )
            except Exception as exc:
                errors.append({"query": query, "page": page, "error": str(exc)})
                break
            time.sleep(delay)

    return ProviderResult(
        source="yplib_crawler",
        raw_results={"source": urljoin(base_url, search_path), "results": results, "errors": errors},
        candidates=list(candidates.values()),
        errors=errors,
    )


def _check_robots(session: requests.Session, base_url: str, timeout: float, verify_ssl: bool) -> dict[str, str]:
    try:
        response = session.get(urljoin(base_url, "/robots.txt"), timeout=timeout, verify=verify_ssl)
        if response.status_code >= 400:
            return {"error": f"robots.txt returned {response.status_code}"}
        return {"text": response.text[:2000]}
    except Exception as exc:
        return {"error": str(exc)}


def _parse_search_page(html: str, base_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict[str, Any]] = []
    rows = soup.select(".book, .book-list li, .search-list li, tbody tr")
    if not rows:
        rows = soup.select("li, tr")
    for row in rows:
        text = clean_html(row.get_text(" "))
        if len(text) < 8:
            continue
        link_tag = row.select_one("a[href]")
        title = clean_html(link_tag.get_text(" ")) if link_tag else ""
        if not title:
            title = _first_labeled_value(text, ["제목", "도서명"]) or text.split(" / ")[0][:80]
        author = _first_labeled_value(text, ["저자", "작가"])
        publisher = _first_labeled_value(text, ["출판사"])
        pub_year = _first_labeled_value(text, ["발행년", "출판연도", "발행년도"])
        availability = _first_matching(text, ["대출가능", "대출중", "예약가능", "관외대출중", "확인 필요"])
        library = _first_labeled_value(text, ["소장도서관", "도서관"])
        call_number = _first_labeled_value(text, ["청구기호"])
        link = urljoin(base_url, link_tag["href"]) if link_tag else urljoin(base_url, "/searchResult")
        if title and author:
            items.append(
                {
                    "title": title,
                    "author": author,
                    "publisher": publisher,
                    "pub_year": pub_year,
                    "library": library,
                    "availability": availability or "확인 필요",
                    "call_number": call_number,
                    "link": link,
                }
            )
    return items


def _first_labeled_value(text: str, labels: list[str]) -> str:
    for label in labels:
        marker = f"{label} "
        if marker in text:
            tail = text.split(marker, 1)[1].strip()
            return tail.split("  ", 1)[0].split(" / ", 1)[0].strip(" :")
    return ""


def _first_matching(text: str, values: list[str]) -> str:
    for value in values:
        if value in text:
            return value
    return ""
