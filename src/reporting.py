from __future__ import annotations

from pathlib import Path
from typing import Any


def write_taste_profile_md(path: Path, profile: dict[str, Any]) -> None:
    lines = ["# 취향 프로필", ""]
    summary = profile.get("summary", {})
    for key, value in summary.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## 선호 작가"])
    for author, count in profile.get("favorite_authors", []):
        lines.append(f"- {author}: {count}")
    lines.extend(["", "## 주요 메모 키워드"])
    for word, count in profile.get("note_keywords", []):
        lines.append(f"- {word}: {count}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_recommendation_report(path: Path, scored: list[dict[str, Any]], validation: dict[str, Any], run_id: str) -> None:
    lines = [
        "# 양평군도서관 취향 기반 추천 리포트",
        "",
        f"- 실행 ID: {run_id}",
        "- 원본 데이터: Google Spreadsheet",
        "- 검색 범위: 양평군 통합도서관 공개 자료검색",
        "- 추천 기준 요약: 취향 일치, 30페이지 입질 가능성, 신선도, 도서관 접근성, 포트폴리오 상태",
        f"- 검증 요약: {validation.get('status', 'unknown')}",
        f"- 실패/확인 필요 요약: {validation.get('summary', '')}",
        "",
    ]
    sections = ["바로 빌릴 책", "예약하거나 추적할 책", "확인 필요하지만 취향상 강한 책"]
    for section in sections:
        lines.extend([f"## {section}", ""])
        section_items = [item for item in scored if item.get("section") == section]
        if not section_items:
            lines.extend(["- 해당 없음", ""])
            continue
        for idx, item in enumerate(section_items, start=1):
            subscores = item.get("subscores", {})
            lines.extend(
                [
                    f"### {idx}. {item.get('title', '')}",
                    f"- 제목: {item.get('title', '')}",
                    f"- 저자: {item.get('author', '')}",
                    f"- 소장 도서관: {', '.join(sorted({h.get('library', '') for h in item.get('library_holdings', []) if h.get('library')})) or '확인 필요'}",
                    f"- 대출 가능 여부: {item.get('availability_summary', '확인 필요')}",
                    f"- 입고일/등록일: {item.get('acquisition_summary', '확인 필요')}",
                    "- 신착 여부: 정보 표시용, 점수 가산 없음",
                    f"- 추천 점수: {item.get('score', 0)}",
                    "- 세부 점수: "
                    f"취향 일치 {subscores.get('taste_match', 0)} / "
                    f"입질 가능성 {subscores.get('thirty_page_pull', 0)} / "
                    f"신선도 {subscores.get('freshness', 0)} / "
                    f"접근성 {subscores.get('library_access', 0)} / "
                    f"포트폴리오 반영 {subscores.get('portfolio_fit', 0)}",
                    f"- 내 취향과 맞는 이유: {item.get('score_reason', '')}",
                    f"- 근거와 확신도: {item.get('confidence', 'low')} / {item.get('inference_notes', '')}",
                    f"- 30페이지 테스트 포인트: {item.get('thirty_page_test', '')}",
                    "",
                ]
            )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_validation_summary(path: Path, validation: dict[str, Any]) -> None:
    lines = ["# 검증 요약", "", f"- 상태: {validation.get('status')}", f"- 요약: {validation.get('summary')}"]
    for issue in validation.get("issues", []):
        lines.append(f"- {issue}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

