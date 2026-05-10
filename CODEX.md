# Codex 실행 지침

이 프로젝트는 외부 LLM API를 호출하지 않는다. 취향 해석과 최종 추천 문장 품질은 Codex가 로컬 산출물을 읽고 보강하는 방식으로 처리한다.

원칙:

- Google Spreadsheet를 독서 포트폴리오의 단일 원본으로 둔다.
- `읽은 책`, `읽는 중`, `읽을 예정` 시트를 매 실행마다 새로 읽는다.
- 양평군도서관 공식 사이트 `https://www.yplib.go.kr`의 공개 검색 API만 사용한다.
- 전자책과 오디오북은 v1 추천 후보에서 제외한다.
- 후보가 부족하면 20권을 억지로 채우지 않고 조건부 실패로 보고한다.
- Google Sheets 쓰기는 승인용 변경표와 `sheets_update_plan.json`을 먼저 만든 뒤, `--approved --commit`이 모두 있을 때만 실행한다.
- `secrets/`, `output/`, `backups/`는 커밋하지 않는다.

권장 확인 흐름:

```bash
python -m src.main --config config/app.yaml --mode check-setup
python -m src.main --config config/app.yaml --mode recommend --output output
```

추천 실행 뒤 Codex는 `recommendation_report.md`와 `validation_report.json`을 읽고, 추정이 과한 문장이나 확인 필요 항목이 숨겨진 부분이 없는지 검토한다.

