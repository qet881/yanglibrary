from __future__ import annotations

from typing import Any

from .utils import normalize_text, primary_author_key


AVAILABLE_TOKENS = ("대출가능", "대출 가능", "available")


def score_candidates(candidates: list[dict[str, Any]], taste_profile: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    preferred_libraries = set(config.get("recommendation", {}).get("preferred_libraries", []))
    min_score = int(config.get("recommendation", {}).get("min_score", 0) or 0)
    read_author_keys = set(taste_profile.get("read_author_keys", []))
    high_titles = {normalize_text(book.get("title", "")) for book in taste_profile.get("high_rating_books", [])}
    interest_titles = {
        normalize_text(book.get("title", ""))
        for book in taste_profile.get("recent_interest_books", [])
        if book.get("title")
    }
    note_keywords = {word for word, _count in taste_profile.get("note_keywords", [])[:15]}
    scored = []
    for candidate in candidates:
        holdings = candidate.get("library_holdings", [])
        available = any(any(token in h.get("availability", "") for token in AVAILABLE_TOKENS) for h in holdings)
        preferred = any(any(lib in h.get("library", "") for lib in preferred_libraries) for h in holdings)
        author_key = candidate.get("author_key") or primary_author_key(candidate.get("author", ""))
        unread_author = bool(author_key and author_key not in read_author_keys)
        title_key = normalize_text(candidate.get("title", ""))
        title_related = any(
            high_title and len(high_title) >= 5 and (high_title in title_key or title_key in high_title)
            for high_title in high_titles
        )
        wishlist_related = any(
            interest_title and len(interest_title) >= 5 and (interest_title in title_key or title_key in interest_title)
            for interest_title in interest_titles
        )
        text = " ".join([candidate.get("title", ""), candidate.get("author", ""), candidate.get("class_description", "")])
        keyword_hits = [word for word in note_keywords if word and word in text]
        has_taste_evidence = title_related or wishlist_related or bool(keyword_hits)

        taste_match = min(
            40,
            8
            + (6 if unread_author and has_taste_evidence else 0)
            + (10 if title_related else 0)
            + (8 if wishlist_related else 0)
            + len(keyword_hits) * 3,
        )
        thirty_page_pull = (
            8
            + (2 if unread_author and has_taste_evidence else 0)
            + (4 if title_related or wishlist_related else 0)
            + min(3, len(keyword_hits))
        )
        freshness = 14 if unread_author else 4
        library_access = 15 if available and preferred else 12 if available else 7
        portfolio_fit = 9 if candidate.get("portfolio_status") == "wishlist" else 10
        score = taste_match + thirty_page_pull + freshness + library_access + portfolio_fit
        if min_score and score < min_score:
            continue
        scored.append(
            {
                **candidate,
                "score": min(100, score),
                "subscores": {
                    "taste_match": taste_match,
                    "thirty_page_pull": thirty_page_pull,
                    "freshness": freshness,
                    "library_access": library_access,
                    "portfolio_fit": portfolio_fit,
                },
                "score_reason": build_reason(unread_author, title_related, wishlist_related, keyword_hits, available, preferred),
                "reasoning_sources": ["portfolio_stats", "candidate_metadata", "library_holdings"],
                "confidence": "medium" if has_taste_evidence else "low",
                "inference_notes": "도서관 메타데이터와 독서 포트폴리오 통계 기반 자동 점수입니다. 작품 분위기 단정은 Codex 검토가 필요합니다.",
                "taste_matches": (["미독 작가"] if unread_author else [])
                + (["고평점 제목 유사"] if title_related else [])
                + (["최근 관심 도서 유사"] if wishlist_related else [])
                + keyword_hits,
                "thirty_page_test": "첫 30쪽에서 문체, 서사 진입 속도, 설명 비중을 확인해 계속 읽을지 판단하세요.",
                "availability_summary": summarize_availability(holdings),
                "acquisition_summary": summarize_acquisition(holdings),
                "section": "바로 빌릴 책" if available else "예약하거나 추적할 책",
            }
        )
    return sorted(scored, key=lambda item: item.get("score", 0), reverse=True)


def build_reason(unread_author: bool, title_related: bool, wishlist_related: bool, keyword_hits: list[str], available: bool, preferred: bool) -> str:
    parts = []
    if unread_author:
        parts.append("읽은 기록이 없는 작가라 새 취향 탐색 후보입니다")
    if title_related:
        parts.append("고평점 도서 제목과 직접 유사합니다")
    if wishlist_related:
        parts.append("최근 관심 도서와 직접 유사합니다")
    if keyword_hits:
        parts.append("메모 키워드와 겹칩니다: " + ", ".join(keyword_hits[:5]))
    if available:
        parts.append("현재 대출 가능 후보입니다")
    if preferred:
        parts.append("선호 도서관 접근성 신호가 있습니다")
    return "; ".join(parts) if parts else "메타데이터만으로는 취향 근거가 약해 확인 필요 후보로 봅니다"


def summarize_availability(holdings: list[dict[str, Any]]) -> str:
    if not holdings:
        return "확인 필요"
    return ", ".join(f"{h.get('library')}: {h.get('availability') or '확인 필요'}" for h in holdings[:5])


def summarize_acquisition(holdings: list[dict[str, Any]]) -> str:
    chunks = []
    for holding in holdings[:5]:
        label = holding.get("acquisition_date_label") or "등록일"
        value = holding.get("acquisition_date") or "확인 필요"
        chunks.append(f"{holding.get('library')}: {label} {value}")
    return ", ".join(chunks) if chunks else "확인 필요"
