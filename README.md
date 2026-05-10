# 양평군도서관 Google Sheets 독서 추천 에이전트

설계서 `yangpyeong_library_google_sheets_agent_design.md`를 실행 가능한 로컬 Python 파이프라인으로 옮긴 MVP입니다.

## 준비

1. Google Cloud 서비스 계정 키 JSON을 `secrets/google-service-account.json`에 둡니다.
2. 대상 Google Spreadsheet를 서비스 계정 이메일에 공유합니다.
3. [config/app.yaml](config/app.yaml)의 `google.spreadsheet_id`를 실제 ID 또는 URL로 채웁니다.
4. 의존성을 설치합니다.

```bash
pip install -r requirements.txt
```

## 실행

설정과 시트 접근 진단:

```bash
python -m src.main --config config/app.yaml --mode check-setup
```

추천 리포트 생성:

```bash
python -m src.main --config config/app.yaml --mode recommend --output output
```

Google Sheets 없이 파이프라인만 점검하려면 샘플 스냅샷을 사용할 수 있습니다.

```bash
python -m src.main --config config/app.yaml --mode recommend --snapshot tests/fixtures/sample_portfolio_snapshot.json --output output
```

Google Sheets 쓰기 계획 검증 또는 dry-run:

```bash
python -m src.main --config config/app.yaml --mode update-sheets --update-plan output/<run_id>/sheets_update_plan.json
```

실제 쓰기는 승인 플래그와 커밋 플래그가 모두 있을 때만 실행됩니다.

```bash
python -m src.main --config config/app.yaml --mode update-sheets --update-plan output/<run_id>/sheets_update_plan.json --approved --commit
```

## 산출물

각 실행은 `output/<run_id>/` 아래에 다음 파일을 저장합니다.

- `portfolio_snapshot.json`
- `portfolio_normalized.json`
- `taste_profile.json`, `taste_profile.md`
- `query_plan.json`
- `raw_search_results.json`
- `candidate_pool.json`
- `scored_candidates.json`
- `recommendation_report.md`
- `validation_report.json`, `validation_summary.md`
- `sheets_update_plan.json`, `approval_preview.md`
