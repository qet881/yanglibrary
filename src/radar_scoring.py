from __future__ import annotations

from collections import Counter
from typing import Any

from .utils import normalize_text, primary_author_key


TASTE_AXES = {
    "genre": ["미스터리", "추리", "스릴러", "SF", "과학", "소설", "에세이", "사회", "철학"],
    "narrative_structure": ["반전", "복선", "연작", "단편", "구조", "구성", "퍼즐", "시점"],
    "pace": ["몰입", "속도", "흡입", "빠른", "긴장", "전개"],
    "impact": ["타격", "충격", "강렬", "먹먹", "여운", "잔상"],
    "intellectual_charge": ["지적", "관점", "전환", "발견", "통찰", "과학", "세계관"],
    "prose_density": ["문체", "밀도", "건조", "정교", "문장"],
    "practical_value": ["실용", "효용", "적용", "업무", "습관", "생산성"],
}

TRAP_TERMS = [
    "장황",
    "지루",
    "늘어짐",
    "고전",
    "교훈",
    "자기계발",
    "힐링",
    "성공",
    "부자",
    "초등",
    "아동",
    "학습",
    "오디오북",
    "전자책",
    "입문서",
    "기초",
    "사용법",
    "소소한",
    "신앙",
    "예수",
    "영원불멸",
]

GENERIC_KEYWORDS = {"미스터리", "심리", "반전", "소설", "추리", "스릴러"}


def build_radar_taste_dna(portfolio: dict[str, Any], taste_profile: dict[str, Any]) -> dict[str, Any]:
    high_books = [book for book in portfolio.get("read_books", []) if float(book.get("rating") or 0) >= 4.0]
    low_books = [book for book in portfolio.get("read_books", []) if 0 < float(book.get("rating") or 0) <= 2.0]
    reading_books = portfolio.get("reading_books", [])
    wishlist_books = portfolio.get("wishlist_books", [])

    axis_terms: dict[str, Counter[str]] = {axis: Counter() for axis in TASTE_AXES}
    examples: dict[str, list[str]] = {axis: [] for axis in TASTE_AXES}
    weighted_books = []

    for book in high_books:
        rating = float(book.get("rating") or 0)
        weight = rating_weight(rating)
        text = book_text(book)
        weighted_books.append({**book, "dna_weight": weight, "rating_band": rating_band(rating)})
        for axis, terms in TASTE_AXES.items():
            hits = [term for term in terms if term in text]
            for term in hits:
                axis_terms[axis][term] += weight
            if hits and len(examples[axis]) < 5:
                examples[axis].append(str(book.get("title", "")))

    return {
        "summary": {
            "high_rating_count": len(high_books),
            "life_changing_count": sum(1 for book in high_books if float(book.get("rating") or 0) >= 5.0),
            "cutoff_count": len(low_books),
            "reading_count": len(reading_books),
            "wishlist_count": len(wishlist_books),
        },
        "high_rating_books": weighted_books,
        "life_books": [book for book in weighted_books if float(book.get("rating") or 0) >= 5.0],
        "strong_books": [book for book in weighted_books if float(book.get("rating") or 0) >= 4.5],
        "stable_books": [book for book in weighted_books if 4.0 <= float(book.get("rating") or 0) < 4.5],
        "cutoff_books": low_books,
        "recent_interest_books": reading_books + wishlist_books,
        "axis_terms": {
            axis: [{"term": term, "weight": weight} for term, weight in counter.most_common(12)]
            for axis, counter in axis_terms.items()
        },
        "axis_examples": examples,
        "favorite_authors": taste_profile.get("favorite_authors", []),
        "read_author_keys": taste_profile.get("read_author_keys", []),
        "positive_patterns": taste_profile.get("positive_patterns", []),
        "negative_patterns": taste_profile.get("negative_patterns", []),
        "note_keywords": taste_profile.get("note_keywords", []),
        "negative_note_keywords": taste_profile.get("negative_note_keywords", []),
    }


def score_radar_candidates(candidates: list[dict[str, Any]], dna: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    read_author_keys = set(dna.get("read_author_keys", []))
    high_books = dna.get("high_rating_books", [])
    life_books = dna.get("life_books", [])
    cutoff_books = dna.get("cutoff_books", [])
    positive_terms = weighted_positive_terms(dna)
    negative_terms = weighted_negative_terms(dna)

    scored = []
    for candidate in candidates:
        context = candidate_context(candidate)
        normalized_context = normalize_text(context)
        author_key = candidate.get("author_key") or primary_author_key(candidate.get("author", ""))
        unread_author = bool(author_key and author_key not in read_author_keys)
        axis_hits = term_hits(context, positive_terms)
        trap_hits = term_hits(context, negative_terms)
        similar_books = similar_high_books(candidate, high_books)
        life_connection = similar_high_books(candidate, life_books, limit=2)
        cutoff_distance = cutoff_distance_label(candidate, cutoff_books, trap_hits)
        availability_bonus = 6 if is_available(candidate) else 0
        direct_life_bonus = 14 if life_connection else 0
        high_similarity_bonus = min(24, sum(book.get("dna_weight", 0) for book in similar_books[:3]) * 3)
        positive_pattern_signal = min(28, sum(weight for _term, weight in axis_hits[:8]))
        negative_penalty = min(30, sum(weight for _term, weight in trap_hits[:8]))
        has_taste_evidence = bool(axis_hits or similar_books or life_connection)
        discovery_signal = 10 if unread_author and has_taste_evidence else 0
        known_author_penalty = 18 if author_key and author_key in read_author_keys else 0
        evidence_markers = [
            discovery_signal > 0,
            bool(axis_hits),
            bool(similar_books),
            bool(life_connection),
            is_available(candidate),
        ]
        evidence_count = sum(1 for marker in evidence_markers if marker)
        keyword_only = is_keyword_only(axis_hits, similar_books, normalized_context)
        strong_basis = has_strong_basis(positive_pattern_signal, high_similarity_bonus, direct_life_bonus)

        raw_score = (
            46
            + discovery_signal
            + positive_pattern_signal
            + high_similarity_bonus
            + direct_life_bonus
            + availability_bonus
            - negative_penalty
            - known_author_penalty
        )
        if keyword_only:
            raw_score = min(raw_score, 74)
        confidence = confidence_label(evidence_count, bool(similar_books), bool(life_connection), keyword_only, negative_penalty, strong_basis)
        score = max(0, min(100, int(round(raw_score))))
        grade = grade_label(score, confidence)
        reading_mode = reading_mode_label(axis_hits, candidate)
        thirty_page_test = build_thirty_page_test(axis_hits, trap_hits, reading_mode)
        risk_factors = build_risk_factors(trap_hits, keyword_only, candidate)
        scored.append(
            {
                **candidate,
                "score": score,
                "grade": grade,
                "confidence": confidence,
                "confidence_rank": confidence_rank(confidence),
                "recommendation_reason": build_recommendation_reason(candidate, axis_hits, similar_books, life_connection, discovery_signal),
                "dna_connection": build_dna_connection(axis_hits, similar_books),
                "life_book_connection": [book.get("title", "") for book in life_connection] or ["직접 연결 없음"],
                "similar_high_books": [book.get("title", "") for book in similar_books[:5]],
                "avoidance_distance": cutoff_distance,
                "risk_factors": risk_factors,
                "reading_mode": reading_mode,
                "thirty_page_test": thirty_page_test,
                "why_now": build_why_now(candidate),
                "taste_matches": [term for term, _weight in axis_hits],
                "negative_matches": [term for term, _weight in trap_hits],
                "subscores": {
                    "discovery_signal": discovery_signal,
                    "known_author_penalty": known_author_penalty,
                    "positive_pattern_signal": positive_pattern_signal,
                    "high_similarity_bonus": high_similarity_bonus,
                    "life_book_bonus": direct_life_bonus,
                    "availability_bonus": availability_bonus,
                    "negative_penalty": negative_penalty,
                    "evidence_count": evidence_count,
                },
                "keyword_only": keyword_only,
                "strong_basis": strong_basis,
                "alert_eligible": score >= int(config.get("radar", {}).get("alert_score_threshold", 90))
                and confidence_rank(confidence) >= confidence_rank(config.get("radar", {}).get("min_alert_confidence", "medium"))
                and not keyword_only
                and strong_basis,
                "availability_summary": availability_summary(candidate),
                "source_url": candidate.get("source_url") or first_holding_url(candidate),
            }
        )

    return sorted(scored, key=lambda item: (item.get("score", 0), item.get("confidence_rank", 0)), reverse=True)


def rating_weight(rating: float) -> int:
    if rating >= 5.0:
        return 5
    if rating >= 4.5:
        return 4
    if rating >= 4.0:
        return 3
    return 1


def rating_band(rating: float) -> str:
    if rating >= 5.0:
        return "life_changing"
    if rating >= 4.5:
        return "strong"
    if rating >= 4.0:
        return "stable"
    return "reference"


def book_text(book: dict[str, Any]) -> str:
    return " ".join(str(book.get(key, "")) for key in ["title", "author", "note", "recommended"])


def candidate_context(candidate: dict[str, Any]) -> str:
    parts = [
        candidate.get("title", ""),
        candidate.get("author", ""),
        candidate.get("publisher", ""),
        candidate.get("pub_year", ""),
        candidate.get("material_type", ""),
        candidate.get("class_description", ""),
        candidate.get("availability", ""),
        candidate.get("source_label", ""),
    ]
    for holding in candidate.get("library_holdings", []):
        parts.extend([holding.get("library", ""), holding.get("availability", ""), holding.get("call_number", "")])
    return " ".join(str(part) for part in parts if part)


def weighted_positive_terms(dna: dict[str, Any]) -> dict[str, int]:
    terms: dict[str, int] = {}
    for axis_items in dna.get("axis_terms", {}).values():
        for item in axis_items:
            term = item.get("term")
            if term:
                terms[term] = max(terms.get(term, 0), int(item.get("weight", 1)) + 4)
    for pattern in dna.get("positive_patterns", []):
        for term in pattern.get("terms", []):
            if term:
                terms[term] = max(terms.get(term, 0), min(10, int(pattern.get("score", 1)) + 4))
    for word, count in dna.get("note_keywords", [])[:20]:
        if word:
            terms[word] = max(terms.get(word, 0), min(8, int(count) + 3))
    return terms


def weighted_negative_terms(dna: dict[str, Any]) -> dict[str, int]:
    terms = {term: 8 for term in TRAP_TERMS}
    for pattern in dna.get("negative_patterns", []):
        for term in pattern.get("terms", []):
            if term:
                terms[term] = max(terms.get(term, 0), min(12, int(pattern.get("score", 1)) + 5))
    for word, count in dna.get("negative_note_keywords", [])[:20]:
        if word:
            terms[word] = max(terms.get(word, 0), min(10, int(count) + 4))
    return terms


def term_hits(context: str, weighted: dict[str, int]) -> list[tuple[str, int]]:
    raw_context = str(context)
    normalized_context = normalize_text(raw_context)
    hits = []
    for term, weight in weighted.items():
        normalized_term = normalize_text(term)
        if term in raw_context or (len(normalized_term) >= 2 and normalized_term in normalized_context):
            hits.append((term, weight))
    return sorted(hits, key=lambda item: item[1], reverse=True)


def similar_high_books(candidate: dict[str, Any], high_books: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    context = normalize_text(candidate_context(candidate))
    title = normalize_text(candidate.get("title", ""))
    matches = []
    for book in high_books:
        book_title = normalize_text(book.get("title", ""))
        note_tokens = [normalize_text(token) for token in str(book.get("note", "")).replace(",", " ").split() if len(token) >= 2]
        shared_note_tokens = [token for token in note_tokens if len(token) >= 2 and token in context]
        title_related = len(book_title) >= 4 and (book_title in title or title in book_title)
        if title_related or len(shared_note_tokens) >= 2:
            matches.append({**book, "shared_terms": shared_note_tokens[:5]})
    return sorted(matches, key=lambda item: (item.get("dna_weight", 0), len(item.get("shared_terms", []))), reverse=True)[:limit]


def cutoff_distance_label(candidate: dict[str, Any], cutoff_books: list[dict[str, Any]], trap_hits: list[tuple[str, int]]) -> str:
    if trap_hits:
        return "가까움: 손절 패턴 신호가 일부 감지됨"
    author = primary_author_key(candidate.get("author", ""))
    if author and any(primary_author_key(book.get("author", "")) == author for book in cutoff_books):
        return "주의: 낮은 평점 작가와 겹침"
    return "멀다: 2.0점 이하 손절 패턴과 직접 충돌 없음"


def is_available(candidate: dict[str, Any]) -> bool:
    text = availability_summary(candidate)
    return any(token in text for token in ["대출가능", "가능", "확인됨", "available"])


def availability_summary(candidate: dict[str, Any]) -> str:
    holdings = candidate.get("library_holdings", [])
    if not holdings:
        return candidate.get("availability") or "확인 필요"
    return ", ".join(f"{h.get('library') or '소장처'}: {h.get('availability') or '확인 필요'}" for h in holdings[:6])


def first_holding_url(candidate: dict[str, Any]) -> str:
    for holding in candidate.get("library_holdings", []):
        if holding.get("source_url"):
            return holding["source_url"]
    return ""


def is_keyword_only(axis_hits: list[tuple[str, int]], similar_books: list[dict[str, Any]], normalized_context: str) -> bool:
    if similar_books:
        return False
    hit_terms = {term for term, _weight in axis_hits}
    return bool(hit_terms) and hit_terms.issubset(GENERIC_KEYWORDS)


def has_strong_basis(positive_pattern_signal: int, high_similarity_bonus: int, direct_life_bonus: int) -> bool:
    return (
        high_similarity_bonus >= 18
        or positive_pattern_signal >= 20
        or (direct_life_bonus > 0 and positive_pattern_signal >= 14)
    )


def confidence_label(
    evidence_count: int,
    has_similar_book: bool,
    has_life_connection: bool,
    keyword_only: bool,
    negative_penalty: int,
    strong_basis: bool,
) -> str:
    if keyword_only:
        return "low"
    if not strong_basis and evidence_count <= 3:
        return "low"
    if negative_penalty >= 18 and not has_life_connection:
        return "low"
    if evidence_count >= 4 and (has_similar_book or has_life_connection):
        return "high"
    if evidence_count >= 2 and has_similar_book:
        return "medium"
    if evidence_count >= 2:
        return "medium"
    return "low"


def confidence_rank(label: str) -> int:
    return {"low": 1, "medium": 2, "high": 3, "낮음": 1, "중간": 2, "높음": 3}.get(str(label), 1)


def grade_label(score: int, confidence: str) -> str:
    if score >= 90 and confidence_rank(confidence) >= 2:
        return "강력 매수"
    if score >= 80 and confidence_rank(confidence) >= 2:
        return "관심 종목"
    if score >= 70:
        return "보류"
    return "매도"


def reading_mode_label(axis_hits: list[tuple[str, int]], candidate: dict[str, Any]) -> str:
    terms = {term for term, _weight in axis_hits}
    if {"반전", "몰입", "긴장", "전개"} & terms:
        return "30페이지 테스트형"
    if {"실용", "효용", "적용"} & terms:
        return "발췌독형"
    return "정독형"


def build_thirty_page_test(axis_hits: list[tuple[str, int]], trap_hits: list[tuple[str, int]], reading_mode: str) -> str:
    positives = ", ".join(term for term, _weight in axis_hits[:4]) or "초반 몰입 근거"
    negatives = ", ".join(term for term, _weight in trap_hits[:3]) or "장황함"
    return f"첫 30페이지에서 {positives}가 실제 서사나 논지로 작동하는지, {negatives} 신호가 강한지 확인."


def build_risk_factors(trap_hits: list[tuple[str, int]], keyword_only: bool, candidate: dict[str, Any]) -> list[str]:
    risks = [term for term, _weight in trap_hits[:4]]
    if keyword_only:
        risks.append("키워드 겹침 외 포트폴리오 근거 부족")
    if not candidate.get("publisher") and not candidate.get("class_description"):
        risks.append("메타데이터 부족")
    return risks or ["뚜렷한 위험 신호 없음"]


def build_recommendation_reason(
    candidate: dict[str, Any],
    axis_hits: list[tuple[str, int]],
    similar_books: list[dict[str, Any]],
    life_connection: list[dict[str, Any]],
    discovery_signal: int,
) -> str:
    parts = []
    if life_connection:
        parts.append("5.0점 인생작과 직접 닿는 신호가 있습니다.")
    if similar_books:
        titles = ", ".join(book.get("title", "") for book in similar_books[:3])
        parts.append(f"4.0점 이상 포트폴리오의 {titles}와 주제/정서/메모 신호가 연결됩니다.")
    if axis_hits:
        parts.append("감지된 취향 축: " + ", ".join(term for term, _weight in axis_hits[:5]))
    if discovery_signal:
        parts.append("읽은 기록이 없는 작가라 새 취향 탐색 후보입니다.")
    return " ".join(parts) if parts else "메타데이터만으로는 강한 추천 근거가 부족합니다."


def build_dna_connection(axis_hits: list[tuple[str, int]], similar_books: list[dict[str, Any]]) -> str:
    axis = ", ".join(term for term, _weight in axis_hits[:6]) or "명확한 축 없음"
    examples = ", ".join(book.get("title", "") for book in similar_books[:4]) or "직접 유사 고평점 책 없음"
    return f"취향 축({axis}) / 연결 고평점 책({examples})"


def build_why_now(candidate: dict[str, Any]) -> str:
    if is_available(candidate):
        return "양평도서관에서 이용 가능한 상태라 30페이지 테스트를 바로 걸 수 있습니다."
    return "강한 취향 신호가 있어 추적 목록에 둘 만하지만, 이용 가능성과 근거 보강이 필요합니다."
