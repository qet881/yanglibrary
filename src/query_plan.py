from __future__ import annotations

import re
from typing import Any

from .utils import primary_author_key


GENERIC_TITLES = {
    "인생",
    "마구",
    "악의",
    "숙명",
    "희망",
    "고래",
    "나무",
    "모모",
    "마음",
    "고백",
}


def build_query_plan(portfolio: dict[str, Any], taste_profile: dict[str, Any], max_queries: int) -> dict[str, Any]:
    queries: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(query: str, reason: str, priority: int) -> None:
        query = (query or "").strip()
        if not query or query in seen:
            return
        seen.add(query)
        queries.append({"query": query, "reason": reason, "priority": priority})

    for author, count in taste_profile.get("favorite_authors", [])[:12]:
        if is_risky_common_korean_name(author) and count < 4:
            continue
        add(author, "고평점 반복 작가 기반", 1)
    for book in portfolio.get("wishlist_books", [])[:10]:
        title = str(book.get("title", "")).strip()
        author = str(book.get("author", "")).strip()
        if title:
            add(title, "읽을 예정 도서 보유 여부 확인", 2)
        if author and primary_author_key(author):
            add(author, "읽을 예정 작가 기반", 3)
    for book in taste_profile.get("high_rating_books", [])[:30]:
        title = str(book.get("title", "")).strip()
        if len(title) >= 5 and title not in GENERIC_TITLES:
            add(title, "고평점 도서 제목 기반", 4)
    for word, _count in taste_profile.get("note_keywords", [])[:5]:
        add(word, "비고/메모 키워드 기반", 3)
    for fallback in ["심리 스릴러", "미스터리 소설", "장편소설", "한국소설", "판타지 소설"]:
        add(fallback, "후보 부족 대비 넓은 검색어", 5)

    queries = sorted(queries, key=lambda item: item["priority"])[:max_queries]
    return {"queries": queries, "query_count": len(queries)}


def is_risky_common_korean_name(author: str) -> bool:
    text = str(author).strip()
    return bool(re.fullmatch(r"[가-힣]{3,4}", text))
