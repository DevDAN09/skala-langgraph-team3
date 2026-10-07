# Supervisor 기반 동적 리서치 오케스트레이션 및 품질 게이트 도입

## 배경

기존 그래프는 `START → paper_analysis`, `START → market_research → stakeholder_research`처럼 Research Agent 간 실행 순서와 연결이 직접 고정되어 있었습니다.

이번 변경은 Research Agent 간 직접 edge를 제거하고, 현재 State의 근거 상태·감사 이슈·재시도 횟수·의존성을 기준으로 다음 작업을 선택하는 Supervisor 패턴으로 전환합니다.

## 주요 변경

### 1. Supervisor 중심 그래프 전환

```text
START
  → supervisor
    → paper_analysis / market_research / stakeholder_research
    → evaluation_synthesis
  → report_generation
  → quality_eval
  → END 또는 재작업 루프
```

- 모든 Research Agent는 작업 후 반드시 `supervisor`로 복귀합니다.
- Research Agent 간 직접 edge를 제거했습니다.
- `market_research` 결과는 State에 저장되며, Supervisor가 시장 데이터 확보 상태를 확인한 뒤 `stakeholder_research`를 선택합니다.
- `evidence_audit`는 별도 그래프 노드가 아니라 Supervisor 내부에서 사용하는 검증 로직으로 정리했습니다.

### 2. State 기반 동적 라우팅

`OverallState`에 Supervisor 제어용 State를 추가했습니다.

- `next_agent`: 다음 실행 대상
- `node_status`: `pending`, `complete`, `stale` 상태
- `retry_count`: 실제 재작업 dispatch 횟수
- `step_count`: Supervisor가 Research Agent를 dispatch한 횟수
- `trace_id`: 실행 단위 UUID
- `quality`: 품질 평가 결과, 실패 사유, 재작업 대상, 평가 횟수

Supervisor는 `audit.issues`, `quality.rework_targets`, Agent별 재시도 가능 여부, `market → stakeholder` 의존성, `node_status`, `MAX_STEPS`를 기반으로 한 번에 하나의 Agent만 선택합니다.

### 3. retry_count 의미 수정

- Audit은 이슈 탐지만 수행합니다.
- Supervisor가 특정 Agent를 실제 재작업 대상으로 dispatch할 때만 해당 Agent의 `retry_count`를 증가시킵니다.
- 최초 실행은 retry로 계산하지 않습니다.
- Agent별 `RETRY_LIMIT=2`를 유지합니다.
- 두 번째 실제 rework worker가 반환된 뒤 fresh audit에서도 이슈가 남거나 `MAX_STEPS=10`에 도달한 경우에만, 미해결 Claim을 `insufficient` 또는 `rejected`로 확정한 뒤 synthesis로 진행합니다.

### 4. market 재조사 후 stakeholder stale 처리

1. stakeholder 최초 실행은 market 완료 후에만 가능합니다.
2. stakeholder 완료 이후 market이 재작업되면 stakeholder 상태를 `stale`로 변경합니다.
3. market 재작업 완료 후 Supervisor가 stale stakeholder를 다시 선택할 수 있습니다.
4. stakeholder는 최신 `state["market"]` 값을 사용합니다.

### 5. quality_eval 품질 기준

| 항목 | 판정 기준 |
| --- | --- |
| Groundedness | `status="ok"` Claim만 대상으로 `Claim → Evidence → Source` 참조 연결을 검증 |
| Neutrality | 실제 추천/우열 판정 표현만 탐지. “추천하지 않는다”, “우열을 판정하지 않는다” 같은 부정 표현은 통과 |
| Bias control | market/stakeholder/MAT-A Claim의 `counter_searched`를 검증. 반대 근거가 없어도 `counter_searched=True`이면 통과하며, 관점별 verified external Claim이 2건 이상이면 하나의 source_id 편중도 실패로 처리 |
| Coverage | maturity, market, stakeholder, domain 네 관점의 Claim 존재 여부를 검증 |

품질 실패 시 재작업 대상도 원인별로 계산합니다.

- domain/maturity 근거 또는 관점 누락 → `paper`
- market 근거/반대검색/관점 누락 → `market`
- stakeholder 근거/반대검색/관점 누락 → `stakeholder`
- `SUMMARY`, `REFERENCE` 목차 누락 또는 neutrality 문구 문제 → `report_generation`

### 6. 품질 루프 및 종료 보장

- `quality_eval`은 최대 2회 평가합니다.
- Research 품질 문제는 Supervisor로 되돌아가 해당 Agent만 재실행합니다.
- 문서 형식·문체 문제는 Research 재실행 없이 `report_generation`으로만 되돌립니다.
- 품질 평가 한도 도달 시 무한 루프 없이 종료합니다.
- `MAX_STEPS=10` 도달 후에도 마지막 Research 결과는 audit한 뒤 synthesis로 진행합니다.

### 7. 실행 및 UI 개선

- `trace_id`는 `make_initial_state()`에서 실행마다 UUID로 생성합니다.
- Streamlit 화면은 버튼 클릭 한 번당 `graph.invoke()`를 한 번만 호출하도록 수정했습니다.
- 기존 `graph.stream()` 실행 후 `graph.invoke()`를 다시 호출하던 이중 실행을 제거했습니다.
- Supervisor, quality_eval 노드 라벨과 23-field State 표시를 최신 구조에 맞췄습니다.

### 8. 최신 main 반영

- 최신 `origin/main`을 fetch한 뒤 현재 브랜치에 rebase했습니다.
- 충돌 난 `tests/test_graph.py`에서 main의 외부 API mock/deprecated 테스트 처리와 Supervisor 테스트를 모두 보존했습니다.
- `tests/conftest.py`의 Tavily/OpenAI/외부 메타데이터 mock 구성을 유지했습니다.

## 검증

```text
pytest -q
149 passed, 2 skipped, 1 warning
```

## 참고

- `src/synthesis/pdf_export.py`의 기존 로컬 변경은 본 PR에 포함하지 않았습니다.

## 제출용 LangSmith 캡처

- Trace A: `Supervisor → research agents → Supervisor → synthesis → report → quality pass`에서 conditional routing, 방문 순서, `trace_id`, 종료를 캡처합니다.
- Trace B: `Supervisor → targeted agent → Supervisor → audit issue → rework → Supervisor → synthesis → report → quality`에서 retry/rework 또는 quality loop를 캡처합니다.
- 최종 실행 후 PDF가 10p 이하이고 `SUMMARY`/`REFERENCE`를 포함하는지 수동 확인합니다.
