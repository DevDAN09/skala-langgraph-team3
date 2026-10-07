# Supervisor 전환 계획 (2안: `evidence_audit` → Supervisor)

> 기준: `origin/main` c2e37e6 · 과제 지시사항 "Multi-Agent Orchestration" · 설계서 `KV_cache_최적화_기술_평가_설계서_최종.md`
> 이전 문서 [`2026-10-07-supervisor-architecture.md`](2026-10-07-supervisor-architecture.md)는 1안(별도 Supervisor 노드)이다. 이 문서가 최종안이다.

---

## 1. 결정 요약

| 항목 | 결정 |
|---|---|
| 패턴 | Supervisor |
| Supervisor 노드 | 기존 `evidence_audit`(D)를 확장하고, 노드 이름을 `supervisor`로 변경한다 |
| 하위 노드 (6) | `paper_analysis`, `market_research`, `stakeholder_research`, `evaluation_synthesis`, `report_generation`, `quality_eval`(신규) |
| 선정 이유 | 지시사항의 "Supervisor가 근거 충분성을 평가한 후 보고서 작성"과 문구 그대로 일치한다. 기존 R1~R5 검증과 표적 재작업 코드를 재사용한다 |

## 2. 아키텍처

```mermaid
flowchart TD
    S([START]) --> SUP{{"Supervisor<br/>(근거 검증 확장)<br/>R1–R5 검증 → 다음 노드 결정"}}

    subgraph 근거 수집
        P["원문 분석<br/>Agentic RAG"]
        M["시장성 조사<br/>Tavily 지지·반대"]
        ST["이해관계자 조사<br/>market 완료 후"]
    end

    subgraph 종합·보고서·품질
        Y["평가 종합<br/>TRL 이원화"]
        R["보고서 생성<br/>Jinja2 + Polishing"]
        Q["품질 평가 (신규)<br/>규칙 + LLM Judge"]
    end

    SUP <--> P
    SUP <--> M
    SUP <--> ST
    SUP <--> Y
    SUP <--> R
    SUP <--> Q
    SUP -->|"품질 통과 또는 상한 도달"| E([END])
```

- 노드끼리 직접 잇는 엣지는 0개다. 분기는 `add_conditional_edges("supervisor", ...)` 하나로 처리한다.
- 근거 검증은 Supervisor 안에서 **수집 노드가 끝난 직후에만** 실행한다(`collect_seq > audited_seq`일 때).

### Supervisor 노드 내부 흐름

```python
def supervisor_node(state):
    update = {}
    if state["collect_seq"] > state["audited_seq"]:   # 수집 노드가 끝난 뒤에만
        update |= run_audit(state)                    # 기존 evidence_audit_node 본문
        update["audited_seq"] = state["collect_seq"]
    next_nodes, reason, extra = decide({**state, **update})
    return {**update, **extra,
            "last_decision": {"next": next_nodes, "reason": reason},
            "step_count": state.get("step_count", 0) + 1}
```

### `decide()` 판단 규칙 (위에서부터 먼저 걸리는 것 적용)

판단 근거는 **State뿐**이다. 스텝 번호로 분기하지 않는다(순서 하드코딩 금지).

| 우선순위 | 조건 (State) | 다음 노드 | 함께 갱신하는 것 |
|---|---|---|---|
| 1 | `step_count ≥ MAX_STEPS` | 보고서가 없으면 `report_generation`, 있으면 END | reason에 "step 상한" 기록 |
| 2 | 어떤 노드가 `failed`이고 재시도 여유가 있음 | 그 노드 | 여유가 없으면 `skipped`로 바꾸고 Evidence Gap으로 넘김 |
| 3 | `paper` 또는 `market`이 `pending` | pending인 노드 전부 (병렬) | — |
| 4 | `market`이 `done`이고 `stakeholder`가 `pending`/`stale` | `stakeholder_research` | — |
| 5 | `audit.issues`가 있고 해당 관점의 `retry_count < 2` | 해당 수집 노드 | market이면 `stakeholder`를 `stale`로. 이미 보고서가 있으면 `synthesis`/`report`/`quality`도 `stale`로 |
| 6 | 관점별 충분성 미달인데 재시도 여유가 있음 | 해당 수집 노드 | 5와 동일 |
| 7 | 충분성 통과 또는 한도 소진, `synthesis`가 `pending`/`stale` | `evaluation_synthesis` | 한도를 소진했으면 reason에 "Evidence Gap으로 격리" 기록 |
| 8 | `report`가 `pending`/`stale` | `report_generation` | — |
| 9 | `report_eval`이 없거나 `quality`가 `stale` | `quality_eval` | — |
| 10 | `report_eval.passed == False`이고 `retry_count["report"] < 2` | `report_eval.target` | 대상이 수집 노드면 이후 단계를 `stale`로 |
| 11 | 그 외 | END | — |

**충분성 기준**: 관점별로 `ok` Claim 수를 기대 슬롯 수로 나눈 비율이 기준(예: 0.7) 이상이어야 한다.

- 기대 슬롯: 도메인 6축 × 2기술, 이해관계자 4 Actor × 2, 시장 4항목 × 2, MAT 연구/채택 근거 각 1개 이상

## 3. 진행 순서

### Step 0. 준비 (A 윤영민)
- `main`에서 `feat/supervisor-pattern` 브랜치를 만든다. 지시사항상 기존 작업과 브랜치를 구분해야 한다.
- 이 문서를 팀에 공유하고 역할을 확정한다.
- 로컬에서 삭제된 `.env.example`을 복구한다.

### Step 1. State 계약 확정 (A, 전원 리뷰) ← 다른 작업은 이게 끝나야 본격 시작
- `src/state.py`에 제어 필드와 reducer를 추가한다(아래 5.2절).
- 노드 이름 상수와 한도 상수를 정한다: `RETRY_LIMIT=2`, `REPORT_REVISION_LIMIT=2`, `MAX_STEPS=30`.
- 공통 데코레이터 `track_node(name)`를 만든다. 기능:
  - 성공하면 `node_status[name]="done"`
  - 예외가 나면 `failed`와 `last_error`를 기록
  - 수집 노드면 `collect_seq += 1`
- `tests/mock_data.py`에 새 필드를 반영한다.

### Step 2. 병렬 구현 (각자 소유 파일만 수정)

| 담당 | 작업 | 소유 파일 | 완료 조건 |
|---|---|---|---|
| **D 강건호** | Supervisor 구현<br/>① `evidence_audit_node` 본문을 `run_audit()`로 분리<br/>② `decide()` 구현(위 표). `graph.py`의 `route_audit_decision` 로직을 옮겨온다<br/>③ `supervisor_node` 작성 | `src/audit/**`, `src/supervisor/` | `tests/test_supervisor.py`: 라우팅 표 각 행, 수집 직후에만 검증, step 상한 종료 |
| **A 윤영민** | ① 그래프 재배선: 직접 엣지, `route_after_paper`, `route_audit_decision` 삭제<br/>② LangSmith 설정: `run_id`, metadata, `recursion_limit=80`<br/>③ `app.py`의 그래프 이중 실행 수정<br/>④ `main.py` 초기 State 갱신 | `src/graph.py`, `src/state.py`, `main.py`, `app.py`, `src/config.py` | mock으로 START부터 END까지 무한 루프 없이 실행 |
| **B 최지윤** | ① `paper_analysis`에 `track_node` 적용<br/>② 품질 평가 LLM Judge 구현(5.3절) | `src/rag/**`, `src/quality/judge.py` | Judge 구조화 출력 테스트 (LLM은 mock) |
| **C 전경호** | ① `market_research`에 `track_node` 적용<br/>② 편향 미달로 재조사할 때 기존과 다른 출처를 찾는 경로(기존 `exclude_urls` 활용) | `src/research/market.py`, `client.py` | `test_research.py` 통과 |
| **C 김효민** | ① `stakeholder_research`에 `track_node` 적용<br/>② 품질 평가 규칙 구현과 `quality_eval` 노드 작성(규칙 결과와 Judge 결과를 합쳐 `report_eval` 생성) | `src/research/stakeholder.py`, `src/quality/rules.py`, `src/quality/node.py` | 규칙별 통과/실패 테스트, `target` 결정 테스트 |
| **E 정은희** | ① `evaluation_synthesis`의 하드코딩 문구를 Claim ID를 인용하는 LLM 종합으로 교체(0건 Fallback 유지)<br/>② `report_generation`이 `report_eval.feedback`을 반영해 다시 쓰게 수정<br/>③ PDF 10장 이하 맞추기 | `src/synthesis/**` | `test_synthesis.py` 통과, 개정 시 feedback이 프롬프트에 들어감 |

### Step 3. 통합 (A 주도)
- 머지 순서: Step 1(계약) → D(Supervisor) → A(그래프) → B/C 노드 → 김효민/B 품질 평가 → E
- `OPENAI_API_KEY`가 없는 mock 모드로 끝까지 실행해 본다.
- 종료 보장 테스트를 추가한다: Judge가 항상 실패하도록 mock해도 `MAX_STEPS` 안에서 END에 도달해야 한다.

### Step 4. 실제 실행과 검증 (전원)
- 실제 API로 `python main.py`를 실행한다.
- 확인할 것:
  - 보고서가 생성되는지
  - PDF가 10장 이하인지
  - SUMMARY와 REFERENCE가 있는지
- LangSmith에서 확인할 것:
  - Supervisor 라우팅 사유(`last_decision.reason`)
  - 재작업 1회 이상
  - 품질 평가 루프
- 트레이스를 `tracing-1.png`, `tracing-2.png` … 형식으로 캡처한다.
- **실패를 일부러 넣는 조작은 금지한다.** 재작업이 안 생기면 규칙 기준을 설계서대로 엄격하게 적용했는지 먼저 점검한다.

### Step 5. 산출물 정리 (F 역할 없음 → 섹션별 담당)
- README 작성(6절 표 참고), 그래프 이미지 생성(`graph.get_graph().draw_mermaid_png()`)
- B가 새로 clone한 환경에서 재현성을 점검한다: `uv sync` → 인덱스 빌드 → `python main.py`
- `Agent_{캠퍼스}_9반_{이름들}.zip`(Git 링크 + PNG + PDF)을 반별 Slack 스레드에 제출한다. 마감은 DAY 2 퇴근 전이다.

---

## 4. 지시사항 필수 항목(Supervisor) 충족 방식

| 필수 항목 | 2안에서 충족하는 방식 | 확인 위치 |
|---|---|---|
| 하위 에이전트 간 직접 통신 금지 | 하위 노드 6개 → `supervisor` 엣지만 존재 | `src/graph.py`, 그래프 이미지 |
| State 기반 `add_conditional_edges` 분기, 순서 하드코딩 금지 | `decide()`가 `node_status`, Claim 상태, `audit`, `report_eval`만 보고 판단 | `src/supervisor/`, 트레이스의 reason |
| 근거 충분성 평가 후 보고서 작성, 스텝 수 고정 금지 | 충분성 게이트(우선순위 6~7). 재작업 횟수가 State에 따라 달라짐 | 트레이스 |
| 근거 부족 시 해당 에이전트에 재작업 요청 | `audit.issues[].target_agent` 표적 재작업, market 재작업 시 stakeholder를 stale로 연쇄 | 트레이스, `test_supervisor.py` |

---

## 5. 과제 지시사항 부합을 위한 추가 작업

### 5.1 지금 main 대비 추가·변경 목록

| 구분 | 작업 | 담당 | 지시사항 근거 |
|---|---|---|---|
| 신규 | Supervisor (`decide`, `supervisor_node`) | D | A. Agent Pattern, B. Mandatory |
| 신규 | 품질 평가 노드 (규칙 + Judge + 루프) | 김효민, B | D. 보고서 품질 평가 |
| 신규 | State 제어 필드 및 `track_node` | A | C. State Schema |
| 변경 | 그래프 재배선 (직접 엣지 삭제) | A | B. Mandatory |
| 변경 | 보고서 feedback 개정 | E | D. 미달 시 Loop |
| 변경 | synthesis를 Claim ID 기반 종합으로 | E | D. Groundedness |
| 변경 | `app.py` 이중 실행 제거, LangSmith 설정 | A | Deliverables 2. Tracing |
| 산출물 | README, 트레이스 PNG, PDF(10장 이하), zip | 전원 | Deliverables |

### 5.2 State Schema (지시사항 C의 7개 항목)

```python
def merge_dict(a: dict, b: dict) -> dict:
    return {**(a or {}), **(b or {})}

class OverallState(TypedDict):
    # ── 작업 페이로드 (기존 14개 중 12개 + report_eval)
    selected: dict; tech_sw: dict; tech_hw: dict; domain: dict
    market: dict; stakeholder: dict
    claims: Annotated[list[Claim], upsert_claims]
    evidence: Annotated[list[Evidence], upsert_evidence]
    sources: Annotated[list[Source], union_sources]
    trl: dict[str, TRL]; synthesis: dict; report: str
    report_eval: ReportEval | None

    # ── 제어 메타 (라우팅·종료·재개에 필요한 최소치)
    run_id: str                                          # 상관 키: LangSmith metadata, thread_id
    step_count: int                                      # 종료 가드 (Supervisor만 씀)
    node_status: Annotated[dict[str, str], merge_dict]   # pending|done|stale|failed|skipped
    retry_count: dict[str, int]                          # paper/market/stakeholder/report (Supervisor만 씀)
    audit: Audit                                         # 라우팅 입력 (overwrite)
    collect_seq: Annotated[int, operator.add]            # 수집 노드가 +1 (병렬 합산)
    audited_seq: int                                     # Supervisor가 검증 후 collect_seq로 맞춤
    last_decision: dict                                  # {next, reason} overwrite, 이력은 트레이스에 남김
    last_error: Annotated[dict[str, str], merge_dict]
```

> 병렬 실행(paper ∥ market)에서 같은 키에 동시에 쓰면 reducer가 없을 때 `InvalidUpdateError`가 난다. 그래서 `node_status`, `last_error`, `collect_seq`에 reducer를 둔다.
> 검증 필요 여부는 bool 플래그 대신 카운터 두 개로 판단한다(`collect_seq > audited_seq`). 플래그를 False로 되돌리는 쓰기가 reducer와 충돌하는 문제를 피하기 위해서다.

| 항목 | 설계 반영 (README에 그대로 옮김) |
|---|---|
| 제어 vs 페이로드 분리 | Supervisor는 제어 메타, `audit`, Claim 상태 집계만 읽는다. 본문(report, snippet)은 라우팅에 쓰지 않는다 |
| 관측성 위치 | State에는 직전 결정 `last_decision`(next + reason)만 둔다. 결정 이력과 사유는 Supervisor 실행마다 LangSmith 트레이스에 남는다 |
| 지속성 비용 | Claim/Evidence/Source는 ID upsert라 재실행해도 늘지 않는다. 웹 검색 원문은 State에 넣지 않고 선택한 snippet만 둔다. report와 audit는 overwrite한다 |
| 상관 | `run_id`를 LangSmith metadata, checkpointer `thread_id`, 로그에 같은 값으로 쓴다 |
| 재개/복구 | `node_status`, `retry_count`, `last_error`를 둔다. 재개하면 done인 노드는 다시 실행하지 않는다. 실패한 노드는 1회 재시도하고, 그래도 실패하면 skipped로 표시한다 |
| 동시 처리 | `claims`/`evidence`/`sources`는 upsert reducer, `node_status`/`last_error`는 `merge_dict`, `collect_seq`는 `operator.add`를 쓴다. `retry_count`, `step_count`, `audited_seq`는 Supervisor만 쓴다 |
| 종료 보장 | 관점별 재시도 2회, 보고서 개정 2회, `MAX_STEPS=30`, `recursion_limit=80`(정상 종료가 먼저 걸리도록 여유를 둠) |

### 5.3 보고서 품질 평가 (지시사항 D, 3안 Hybrid)

```python
class ReportEval(TypedDict):
    passed: bool
    items: dict[str, dict]   # groundedness|neutrality|bias|coverage|length → {passed, score, reason}
    target: str              # 재작업 대상 노드
    feedback: str            # report_generation에 전달할 수정 지시
```

| 항목 | 규칙 (김효민, `rules.py`) | LLM Judge (B, `judge.py`, gpt-4o, temp 0) | 미달 시 `target` |
|---|---|---|---|
| Groundedness | 3~5장 문단마다 인용 번호 또는 Claim ID가 있는지<br/>인용 ID가 State에 `ok`로 존재하는지<br/>polishing 전후 숫자 집합이 같은지 | 표본 문장과 근거 snippet의 일치 여부 | `report_generation` |
| 중립성 | 금지어 정규식: 우수, 승자, 추천, 권장, 도입해야, outperform, superior 등 | 미묘한 우열 뉘앙스, 비대칭 서술 | `report_generation` |
| 편향 통제 | 단일 출처가 인용의 40% 초과 금지<br/>관점마다 출처 2개 이상<br/>T4 단독 금지<br/>`counter_searched` 비율<br/>두 기술 분량 비율 0.5~2 | 불리한 근거 누락 여부 | 재시도 여유가 있으면 `market_research`/`stakeholder_research`, 없으면 `report_generation` |
| 관점 커버리지 | SUMMARY~REFERENCE 목차, 4관점 × 2기술 섹션, 4 Actor, 6축<br/>insufficient 항목은 Gap에 적혀 있으면 통과 | 섹션 내용의 실질성 | 비어 있는 관점의 수집 노드 |
| 분량 | PDF 10장 이하 (pypdf) | — | `report_generation` |

- **통과 기준**: 규칙 전부 통과, Judge 항목별 4/5 이상
- **루프**: 미달이면 Supervisor가 `target`으로 보낸다. `retry_count["report"]`는 최대 2회다.
- **한도 소진 시**: 미달 항목과 사유를 보고서 6장 한계점에 붙이고 END로 간다. 결과를 숨기지 않는다.

---

## 6. 최종 산출물 체크리스트

| 산출물 | 내용 | 담당 |
|---|---|---|
| GitHub 브랜치 | `feat/supervisor-pattern` | A |
| README: Overview | Pattern = Supervisor와 선정 이유, 동적 처리(고정 순서와 무엇이 다른지) | A |
| README: Selected Technologies | KIVI / CXL-PNM과 선정 이유 (설계서 2장) | E |
| README: Features | PDF 기반 추출, 확증 편향 방지 전략, 보고서 품질 평가 | 김효민, B |
| README: Tech Stack | LangGraph, Generator gpt-4o-mini, Judge gpt-4o, FAISS, `e5-small-v2`, Hit@5와 MRR (`benchmark_results.json`) | B |
| README: Agents | Supervisor와 하위 노드 6개의 책임 | D |
| README: State Schema | 5.2절 표 | A |
| README: Architecture | `draw_mermaid_png()` 이미지 | A |
| README: Directory / Usage | 실제 구조, `python main.py` | A |
| README: Contributors | 개인별 수행 역할 (PM, PL 역할은 쓰지 않음) | 전원 |
| LangSmith 트레이스 | `tracing-1.png` …: 라우팅, 재작업, 품질 루프가 보이게 | A |
| 평가 보고서 PDF | 지난 보고서와 같은 목차, 10장 이하, SUMMARY와 REFERENCE 포함 | E |
| 제출 | `Agent_{캠퍼스}_9반_{이름들}.zip` | 전원 |

### 채점 항목 대응

| 평가 항목 (배점) | 대응 |
|---|---|
| 패턴 적용 정합성 (20) | 4절 표, `test_supervisor.py` |
| 동적 동작 실증 (20) | 트레이스의 reason과 재작업 횟수 |
| State Schema 설계 (20) | 5.2절 코드와 README 표 |
| 품질 평가 노드 (15) | 5.3절, 미달 시 루프 코드 |
| 코드 구조 및 모듈 분리 (5) | `src/supervisor`, `src/quality`, 하위 노드 모듈 분리, README Directory와 일치 |
| 실행 결과 재현성 (10) | Step 3 종료 보장 테스트, Step 5 새 clone 점검 |
| 보고서 (10) | PDF 10장 이하, SUMMARY와 REFERENCE |
