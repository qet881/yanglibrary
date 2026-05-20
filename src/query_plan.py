from __future__ import annotations

from typing import Any


GENERIC_TITLES = {
    "인생",
    "마음",
    "고백",
    "모모",
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

    # Prefer taste descriptors over already-liked author names so discovery is biased
    # toward authors the reader has not tried yet.
    for word, _count in taste_profile.get("note_keywords", [])[:10]:
        add(word, "taste-note-keyword", 1)

    for book in portfolio.get("wishlist_books", [])[:10]:
        title = str(book.get("title", "")).strip()
        if title:
            add(title, "wishlist-title", 2)

    for book in taste_profile.get("high_rating_books", [])[:30]:
        title = str(book.get("title", "")).strip()
        if len(title) >= 5 and title not in GENERIC_TITLES:
            add(title, "high-rating-title-similarity", 4)

    for fallback in ["추리 스릴러", "미스터리 소설", "단편소설", "한국소설", "사회파 소설"]:
        add(fallback, "taste-discovery-fallback", 5)

    queries = sorted(queries, key=lambda item: item["priority"])[:max_queries]
    return {"queries": queries, "query_count": len(queries)}
