# Book Radar v0.1

Book Radar는 양평도서관 검색기가 아니라, 내 독서 포트폴리오를 기준으로 아직 몰랐지만 좋아할 가능성이 높은 책을 조용히 감시하는 취향 레이더입니다.

4.0점 이상 책은 취향 DNA로, 2.0점 이하 책은 함정 픽 회피 데이터로 사용합니다. 강한 후보가 없으면 억지로 추천하지 않고 “오늘은 알림 없음”을 정상 결과로 둡니다.

## 준비

1. Google Cloud 서비스 계정 JSON을 `secrets/google-service-account.json`에 둡니다.
2. 대상 Google Spreadsheet를 서비스 계정 이메일에 공유합니다.
3. [config/app.yaml](config/app.yaml)의 `google.spreadsheet_id`를 실제 ID 또는 URL로 설정합니다.
4. 의존성을 설치합니다.

```bash
pip install -r requirements.txt
```

## 기존 모드

```bash
python -m src.main --config config/app.yaml --mode check-setup
python -m src.main --config config/app.yaml --mode recommend --output output
python -m src.main --config config/app.yaml --mode recommend --snapshot tests/fixtures/sample_portfolio_snapshot.json --output output
python -m src.main --config config/app.yaml --mode update-sheets --update-plan output/<run_id>/sheets_update_plan.json
```

## Book Radar 실행

```bash
python -m src.main --config config/app.yaml --mode radar --output output
```

알림 정책은 세 가지입니다.

```bash
python -m src.main --config config/app.yaml --mode radar --notify-policy immediate --output output
python -m src.main --config config/app.yaml --mode radar --notify-policy silent --output output
python -m src.main --config config/app.yaml --mode radar --notify-policy digest --output output
```

- `immediate`: 이번 실행에서 강한 후보가 있으면 바로 알림을 보냅니다.
- `silent`: 후보를 찾고 상태에 누적하지만 알림은 보내지 않습니다.
- `digest`: 누적된 강한 후보와 이번 실행 후보를 묶어 알림을 보냅니다.

샘플 데이터로 실행:

```bash
python -m src.main --config config/app.yaml --mode radar --snapshot tests/fixtures/sample_portfolio_snapshot.json --output output
```

각 실행은 `output/<run_id>/` 아래에 다음 파일을 만듭니다.

- `radar_candidates.json`
- `radar_scored_candidates.json`
- `radar_changes.json`
- `radar_report.md`
- `radar_alerts.md`
- `radar_state_after.json`
- `radar_run_summary.json`
- `radar_email_result.json`
- `radar_telegram_result.json`

상태 파일은 기본적으로 `output/radar/radar_state.json`에 저장됩니다. 같은 책을 너무 자주 보내지 않도록 `last_alerted_at`과 `alert_count`를 사용합니다.
`silent` 실행에서 발견한 강한 후보는 `pending_alerts`에 누적되고, `digest` 실행이 성공적으로 알림을 보내면 정리됩니다.

## Provider 설정

양평도서관은 기본값 `auto`를 사용합니다. 추천 후보 수집은 양평도서관 provider만 사용합니다.

```yaml
providers:
  yplib:
    enabled: true
    provider: "auto"  # auto | api | crawler
```

현재 `/api/search` POST 방식은 JSON 응답과 `bookList`를 반환하는 것을 확인했습니다. `auto`는 API 결과가 없고 오류가 강하면 HTML crawler로 fallback합니다.

## Telegram 알림

Telegram 알림은 기본적으로 꺼져 있고, 환경변수 또는 GitHub Actions Secrets로만 켭니다.

```yaml
notify:
  telegram:
    enabled: false
    subject_prefix: "[Book Radar]"
    max_chars_per_message: 3500
```

필요한 값:

- `BOOK_RADAR_TELEGRAM_ENABLED=true`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

로컬 설정:

1. Telegram에서 `@BotFather`에게 `/newbot`을 보내 bot token을 받습니다.
2. 만든 bot에게 아무 메시지나 하나 보냅니다.
3. `.env.example`을 `.env`로 복사합니다.
4. `.env`에 `TELEGRAM_BOT_TOKEN`을 넣습니다.
5. chat id를 확인합니다.

```bash
python scripts/get_telegram_chat_id.py
```

6. 출력된 `TELEGRAM_CHAT_ID=...` 값을 `.env`에 넣습니다.
7. 테스트 메시지를 보냅니다.

```bash
python scripts/send_test_telegram.py
```

Telegram Bot API의 `sendMessage`, `getUpdates` 방식을 사용합니다. 공식 문서: https://core.telegram.org/bots/api

## 이메일 알림

이메일 알림도 남겨두었지만, 현재 GitHub Actions 기본 동작은 Telegram만 켜도록 되어 있습니다. 이메일을 쓰려면 다음 값을 설정하고 `BOOK_RADAR_EMAIL_ENABLED=true`를 켭니다.

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `MAIL_FROM`
- `MAIL_TO`

로컬에서 네이버 메일로 테스트하려면 `.env.example`을 `.env`로 복사한 뒤 값을 채우고 실행합니다.

```bash
python scripts/send_test_email.py
```

네이버 메일을 쓰는 경우 보통 `SMTP_HOST=smtp.naver.com`, `SMTP_PORT=587`을 사용합니다. 네이버 메일 설정에서 IMAP/SMTP 사용을 먼저 켜고, 계정에 2단계 인증이 적용되어 있으면 애플리케이션 비밀번호가 필요할 수 있습니다.

## GitHub Actions 예약 실행

GitHub Actions는 두 단계로 동작합니다.

- `Book Radar Watch`: 3시간마다 실행, 후보를 찾고 상태에 누적, 알림 없음
- `Book Radar Digest`: 매일 07:00 KST 실행, 누적된 강한 후보를 Telegram으로 발송

저장소 Secrets에 다음 값을 넣습니다.

- `GOOGLE_SERVICE_ACCOUNT_JSON`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

이메일도 같이 쓰려면 SMTP Secrets도 추가하고 workflow의 `BOOK_RADAR_EMAIL_ENABLED`를 `"true"`로 바꾸면 됩니다.

workflow는 결과를 artifact로 업로드하며, `output`을 저장소에 자동 커밋하지 않습니다. 반복 알림 억제, 누적 digest, 상태 비교에 필요한 `output/radar/radar_state.json`은 GitHub Actions cache로 복원/저장합니다.

## 테스트

```bash
pytest -q
```

테스트는 외부 API나 크롤링 없이 새 후보 감지, 반복 알림 억제, 이용 가능 상태 변경, 포트폴리오 중복 제외, 읽을 예정 제외, 신간 필터 비활성화, 키워드만 겹치는 후보 차단, Telegram/email env override, markdown 생성을 검증합니다.
