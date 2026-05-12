from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from src.portfolio import build_taste_profile, normalize_portfolio
from src.radar import compare_radar_state, effective_radar_config, finalize_alert_state, merge_candidates, run_radar
from src.radar_scoring import build_radar_taste_dna, score_radar_candidates
from src.utils import now_kst, read_json
from src.notify import chunk_text, is_email_enabled, is_telegram_enabled
from src.env import load_env_file


def base_config(tmp_path: Path) -> dict:
    return {
        "sheets": {
            "required": {"read": "읽은 책", "reading": "읽는 중", "wishlist": "읽을 예정"},
            "optional": {"settings": "추천 설정"},
        },
        "recommendation": {
            "high_rating_threshold": 4.0,
            "min_acquisition_year": 2024,
            "new_arrival_days": 90,
        },
        "yplib": {"exclude_candidate_keywords": ["아동", "초등"]},
        "radar": {
            "state_file": str(tmp_path / "radar_state.json"),
            "alert_score_threshold": 90,
            "watch_score_threshold": 80,
            "min_alert_confidence": "medium",
            "max_alerts_per_run": 5,
            "suppress_repeat_days": 14,
            "disable_freshness_filter": True,
        },
        "providers": {
            "yplib": {"enabled": False, "provider": "auto"},
            "millie": {"enabled": False, "provider": "manual_or_public", "manual_input_file": str(tmp_path / "missing.csv")},
        },
        "notify": {"email": {"enabled": False, "subject_prefix": "[Book Radar]", "max_items": 5}},
    }


def sample_portfolio(config: dict) -> dict:
    snapshot = read_json(Path("tests/fixtures/sample_portfolio_snapshot.json"))
    return normalize_portfolio(snapshot, config)


def scored_candidate(tmp_path: Path, **overrides) -> dict:
    item = {
        "identity_key": "newbook|writer",
        "title": "강한 반전의 연작 추리소설",
        "author": "writer",
        "source": "yplib",
        "source_label": "양평도서관",
        "score": 94,
        "grade": "강력 매수",
        "confidence": "medium",
        "availability_summary": "양평: 대출중",
        "source_url": "https://example.test/book",
        "alert_eligible": True,
    }
    item.update(overrides)
    return item


def test_new_strong_candidate_detected(tmp_path: Path) -> None:
    config = effective_radar_config(base_config(tmp_path))
    changes, _state = compare_radar_state([scored_candidate(tmp_path)], {"version": 1, "items": {}}, config, now_kst())
    assert len(changes["new_strong"]) == 1
    assert len(changes["alert_items"]) == 1
    assert len(changes["pending_alert_items"]) == 1


def test_repeat_alert_suppressed(tmp_path: Path) -> None:
    config = effective_radar_config(base_config(tmp_path))
    now = now_kst()
    previous = {
        "version": 1,
        "items": {
            "newbook|writer": {
                "identity_key": "newbook|writer",
                "last_alerted_at": (now - timedelta(days=2)).isoformat(),
                "alert_count": 1,
                "last_score": 94,
                "last_confidence": "medium",
                "last_availability": "양평: 대출중",
            }
        },
    }
    changes, _state = compare_radar_state([scored_candidate(tmp_path)], previous, config, now)
    assert changes["alert_items"] == []


def test_silent_watch_accumulates_pending_without_alerting(tmp_path: Path) -> None:
    config = effective_radar_config(base_config(tmp_path))
    changes, state = compare_radar_state(
        [scored_candidate(tmp_path)],
        {"version": 1, "items": {}},
        config,
        now_kst(),
        notify_policy="silent",
    )
    assert changes["alert_items"] == []
    assert len(changes["pending_alert_items"]) == 1
    assert "newbook|writer" in state["pending_alerts"]
    assert not state["items"]["newbook|writer"].get("last_alerted_at")


def test_digest_sends_pending_and_finalize_clears_it(tmp_path: Path) -> None:
    config = effective_radar_config(base_config(tmp_path))
    now = now_kst()
    _changes, watch_state = compare_radar_state(
        [scored_candidate(tmp_path)],
        {"version": 1, "items": {}},
        config,
        now,
        notify_policy="silent",
    )
    digest_changes, digest_state = compare_radar_state([], watch_state, config, now + timedelta(hours=3), notify_policy="digest")
    assert len(digest_changes["alert_items"]) == 1
    finalized = finalize_alert_state(digest_state, digest_changes["alert_items"], now + timedelta(hours=3))
    assert finalized["pending_alerts"] == {}
    assert finalized["items"]["newbook|writer"]["alert_count"] == 1


def test_availability_change_detected(tmp_path: Path) -> None:
    config = effective_radar_config(base_config(tmp_path))
    previous = {
        "version": 1,
        "items": {
            "newbook|writer": {
                "identity_key": "newbook|writer",
                "last_score": 88,
                "last_confidence": "medium",
                "last_availability": "양평: 대출중",
            }
        },
    }
    item = scored_candidate(tmp_path, availability_summary="양평: 대출가능")
    changes, _state = compare_radar_state([item], previous, config, now_kst())
    assert len(changes["availability_changed"]) == 1
    assert len(changes["alert_items"]) == 1


def test_portfolio_duplicate_and_wishlist_excluded(tmp_path: Path) -> None:
    config = effective_radar_config(base_config(tmp_path))
    portfolio = sample_portfolio(config)
    wishlist = portfolio["wishlist_books"][0]
    merged = merge_candidates(
        [
            {
                "title": wishlist["title"],
                "author": wishlist["author"],
                "identity_key": wishlist["identity_key"],
                "source": "millie",
                "availability": "확인됨",
            }
        ],
        portfolio,
        config,
    )
    assert merged == []


def test_radar_disables_freshness_filter(tmp_path: Path) -> None:
    config = effective_radar_config(base_config(tmp_path))
    assert config["recommendation"]["min_acquisition_year"] == 0
    assert config["recommendation"]["new_arrival_days"] == 0


def test_keyword_only_candidate_is_not_alert(tmp_path: Path) -> None:
    config = effective_radar_config(base_config(tmp_path))
    portfolio = sample_portfolio(config)
    taste_profile = build_taste_profile(portfolio, 4.0)
    dna = build_radar_taste_dna(portfolio, taste_profile)
    scored = score_radar_candidates(
        [
            {
                "title": "미스터리 심리 반전",
                "author": "unknown",
                "source": "yplib",
                "source_label": "양평도서관",
                "class_description": "미스터리",
                "library_holdings": [{"library": "양평", "availability": "대출가능"}],
                "identity_key": "mystery|unknown",
            }
        ],
        dna,
        config,
    )
    assert scored[0]["keyword_only"] is True
    assert scored[0]["alert_eligible"] is False


def test_weak_single_abstract_match_is_not_alert(tmp_path: Path) -> None:
    config = effective_radar_config(base_config(tmp_path))
    portfolio = sample_portfolio(config)
    taste_profile = build_taste_profile(portfolio, 4.0)
    dna = build_radar_taste_dna(portfolio, taste_profile)
    scored = score_radar_candidates(
        [
            {
                "title": "관점의 재발견",
                "author": "unknown",
                "source": "millie",
                "source_label": "밀리의 서재",
                "availability": "확인됨",
                "class_description": "인문",
                "library_holdings": [{"library": "밀리의 서재", "availability": "확인됨"}],
                "identity_key": "viewpoint|unknown",
            }
        ],
        dna,
        config,
    )
    assert scored[0]["strong_basis"] is False
    assert scored[0]["alert_eligible"] is False


def test_email_disabled_generates_markdown_only(tmp_path: Path) -> None:
    config = effective_radar_config(base_config(tmp_path))
    summary = run_radar(config, tmp_path / "output", Path("tests/fixtures/sample_portfolio_snapshot.json"))
    assert summary["email"]["sent"] is False
    assert Path(summary["alerts"]).exists()
    assert Path(summary["report"]).exists()


def test_email_enabled_env_override(monkeypatch) -> None:
    monkeypatch.setenv("BOOK_RADAR_EMAIL_ENABLED", "true")
    assert is_email_enabled({"enabled": False}) is True
    monkeypatch.setenv("BOOK_RADAR_EMAIL_ENABLED", "false")
    assert is_email_enabled({"enabled": True}) is False


def test_telegram_enabled_env_override(monkeypatch) -> None:
    monkeypatch.setenv("BOOK_RADAR_TELEGRAM_ENABLED", "true")
    assert is_telegram_enabled({"enabled": False}) is True
    monkeypatch.setenv("BOOK_RADAR_TELEGRAM_ENABLED", "false")
    assert is_telegram_enabled({"enabled": True}) is False


def test_chunk_text_splits_long_messages() -> None:
    chunks = chunk_text("a\n\n" * 1000, max_chars=500)
    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)


def test_load_env_file_does_not_override_existing_env(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("BOOK_RADAR_EMAIL_ENABLED=true\nSMTP_HOST=smtp.naver.com\n", encoding="utf-8")
    monkeypatch.setenv("SMTP_HOST", "already-set.example")
    monkeypatch.delenv("BOOK_RADAR_EMAIL_ENABLED", raising=False)
    load_env_file(env_file)
    assert is_email_enabled({"enabled": False}) is True
    assert __import__("os").environ["SMTP_HOST"] == "already-set.example"


def test_millie_public_item_normalization() -> None:
    from src.providers.millie import normalize_public_item

    item = normalize_public_item(
        {
            "book_id": "abc123",
            "content_name": "13.67 (개정판)",
            "author": "찬호께이",
            "is_service": True,
            "category": "소설",
            "category2": "추리/스릴러",
            "book_brand": "한스미디어",
            "book_isbn": "9791160078572",
        },
        "13.67",
    )
    assert item is not None
    assert item["source"] == "millie"
    assert item["availability"] == "확인됨"
    assert item["source_url"].endswith("/v4/book/abc123")
