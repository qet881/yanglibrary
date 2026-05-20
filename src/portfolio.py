from __future__ import annotations

from collections import Counter
from typing import Any

from .utils import identity_key, safe_float


FIELD_ALIASES = {
    "author": ["작가", "저자", "글쓴이", "author"],
    "title": ["제목", "도서명", "책제목", "title"],
    "rating": ["별점", "평점", "현재 평점", "rating"],
    "note": ["비고", "메모", "감상", "note"],
    "recommended": ["추천여부", "추천 여부", "recommended"],
}


def map_columns(records: list[dict[str, Any]]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    if not records:
        return {}, []
    headers = [h for h in records[0].keys() if not h.startswith("_")]
    mapping: dict[str, str] = {}
    ambiguous: list[dict[str, Any]] = []
    for field, aliases in FIELD_ALIASES.items():
        matches = [header for header in headers if normalize_header(header) in [normalize_header(a) for a in aliases]]
        if len(matches) == 1:
            mapping[field] = matches[0]
        elif len(matches) > 1:
            ambiguous.append({"field": field, "candidates": matches})
    return mapping, ambiguous


def normalize_header(value: str) -> str:
    return "".join(str(value).strip().lower().split())


def normalize_book(record: dict[str, Any], mapping: dict[str, str], source_sheet: str) -> dict[str, Any]:
    title = record.get(mapping.get("title", ""), "")
    author = record.get(mapping.get("author", ""), "")
    return {
        "author": str(author).strip(),
        "title": str(title).strip(),
        "rating": safe_float(record.get(mapping.get("rating", ""), "")),
        "note": str(record.get(mapping.get("note", ""), "")).strip(),
        "recommended": str(record.get(mapping.get("recommended", ""), "")).strip(),
        "source_sheet": source_sheet,
        "row_number": record.get("_row_number"),
        "identity_key": identity_key(str(title), str(author)),
    }


def normalize_portfolio(snapshot: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    required = config.get("sheets", {}).get("required", {})
    sheets = snapshot.get("sheets", {})
    all_ambiguous: list[dict[str, Any]] = []
    all_mappings: dict[str, dict[str, str]] = {}

    def normalize_sheet(logical_name: str) -> list[dict[str, Any]]:
        sheet_name = required.get(logical_name, "")
        records = sheets.get(sheet_name, [])
        mapping, ambiguous = map_columns(records)
        all_mappings[sheet_name] = mapping
        for item in ambiguous:
            item["sheet"] = sheet_name
        all_ambiguous.extend(ambiguous)
        return [normalize_book(record, mapping, sheet_name) for record in records]

    settings = parse_settings(sheets.get(config.get("sheets", {}).get("optional", {}).get("settings", ""), []))
    result = {
        "read_books": normalize_sheet("read"),
        "reading_books": normalize_sheet("reading"),
        "wishlist_books": normalize_sheet("wishlist"),
        "settings": {
            "exclude_authors": settings.get("exclude_authors", []),
            "preferred_libraries": settings.get(
                "preferred_libraries",
                config.get("recommendation", {}).get("preferred_libraries", []),
            ),
            "include_small_libraries": settings.get("include_small_libraries", True),
            "column_mappings": all_mappings,
            "ambiguous_columns": all_ambiguous,
        },
    }
    for book in config.get("recommendation", {}).get("manual_read_books", []):
        title = str(book.get("title", "")).strip()
        author = str(book.get("author", "")).strip()
        if not title:
            continue
        result["read_books"].append(
            {
                "author": author,
                "title": title,
                "rating": safe_float(book.get("rating", "")),
                "note": str(book.get("note", "")).strip(),
                "recommended": "",
                "source_sheet": "config.manual_read_books",
                "row_number": None,
                "identity_key": identity_key(title, author),
            }
        )
    for key, group in [("read_identity_keys", "read_books"), ("reading_identity_keys", "reading_books"), ("wishlist_identity_keys", "wishlist_books")]:
        result[key] = sorted({item["identity_key"] for item in result[group] if item.get("title")})
    result["portfolio_identity_keys"] = sorted(set(result["read_identity_keys"] + result["reading_identity_keys"] + result["wishlist_identity_keys"]))
    return result


def parse_settings(records: list[dict[str, Any]]) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    for row in records:
        key = str(row.get("key") or row.get("키") or "").strip()
        value = str(row.get("value") or row.get("값") or "").strip()
        if not key:
            continue
        if key in {"exclude_authors", "제외 작가"}:
            settings["exclude_authors"] = [v.strip() for v in value.split(",") if v.strip()]
        elif key in {"preferred_libraries", "우선 도서관"}:
            settings["preferred_libraries"] = [v.strip() for v in value.split(",") if v.strip()]
        elif key in {"include_small_libraries", "작은도서관 포함"}:
            settings["include_small_libraries"] = value.lower() not in {"false", "n", "no", "0", "아니오"}
    return settings


def build_taste_profile(portfolio: dict[str, Any], high_rating_threshold: float) -> dict[str, Any]:
    read_books = portfolio.get("read_books", [])
    high_books = [b for b in read_books if b.get("rating", 0) >= high_rating_threshold]
    low_books = [b for b in read_books if b.get("rating", 0) and b.get("rating", 0) < high_rating_threshold]
    author_counter = Counter(b.get("author", "") for b in high_books if b.get("author"))
    read_author_keys = sorted({identity_key("", b.get("author", "")).split("|", 1)[1] for b in read_books if b.get("author")})
    note_words = Counter()
    for book in high_books + portfolio.get("wishlist_books", []):
        for word in extract_keywords(book.get("note", "")):
            note_words[word] += 1
    return {
        "summary": {
            "read_count": len(read_books),
            "reading_count": len(portfolio.get("reading_books", [])),
            "wishlist_count": len(portfolio.get("wishlist_books", [])),
            "high_rating_count": len(high_books),
            "low_rating_count": len(low_books),
        },
        "high_rating_books": high_books[:30],
        "low_rating_books": low_books[:20],
        "favorite_authors": author_counter.most_common(15),
        "read_author_keys": read_author_keys,
        "note_keywords": note_words.most_common(30),
        "recent_interest_books": portfolio.get("reading_books", [])[:20] + portfolio.get("wishlist_books", [])[:20],
    }


def extract_keywords(text: str) -> list[str]:
    stopwords = {
        "있는",
        "없는",
        "좋았다",
        "좋다",
        "같이",
        "오래",
        "남았다",
        "책",
        "소설",
        "도서",
        "그리고",
        "하지만",
        "너무",
    }
    words = []
    for token in str(text).replace(",", " ").split():
        token = token.strip(" .!?;:()[]{}<>\"'")
        if len(token) >= 2 and not token.isdigit() and token not in stopwords:
            words.append(token)
    return words
