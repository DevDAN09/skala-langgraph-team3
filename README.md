# Subject
본 프로젝트는 KV cache 최적화 기술을 소프트웨어(SW)와 하드웨어(HW) 두 진영에서 하나씩 선정하여, 기술 성숙도(TRL)·시장성·이해관계자·도메인 적합성 관점에서 평가하는 **Supervisor 패턴** 기반 멀티 에이전트 시스템을 LangGraph로 설계·개발하는 프로젝트이다.

> SKALA 4기 판교 9반 · 팀 3 · 평가 도메인: **클라우드 LLM 서빙**  
> 기술 비교: **KIVI** (SW, 2-bit KV 양자화) vs **CXL-PNM** (HW, CXL 메모리 내 근접 연산)  
> 원칙: 두 기술의 우열을 판정하지 않고, 관점 간 일치·불일치와 워크로드별 트레이드오프를 근거와 함께 기록한다.


## Overview
- **Objective** : KV cache 병목을 다루는 SW·HW 대표 기술을 4개 관점(TRL · 시장성 · 이해관계자 · 도메인 적합성)에서 근거 기반으로 비교 평가
- **Pattern** : Supervisor — Worker 수 확장보다 수집 근거의 충분성을 판단하고 부족한 관점만 재조사하는 품질 제어가 핵심이다. 기존 evidence audit/retry를 Supervisor의 중앙 제어로 확장해 specialized research role을 유지한 채 State 기반 targeted rework를 수행한다.
- **동적 처리** : Supervisor가 매 step의 current State를 확인하여 audit issue, quality rework target, `node_status`, `retry_count`, dependency에 따라 다음 Agent를 runtime에 결정한다. `paper → market → stakeholder` 고정 순서를 사용하지 않으므로 실행마다 방문 Agent·순서·retry 횟수가 달라질 수 있다.
- **Tools** : LangGraph, FAISS, Tavily Search, Jinja2, Streamlit, xhtml2pdf


## Selected Technologies
- **SW : KIVI** (Liu et al., ICML 2024, arXiv:2402.02750) — Key는 채널 단위, Value는 토큰 단위로 비대칭 2-bit 양자화한다. 재학습 없이 기존 GPU·HBM 위에서 소프트웨어만으로 적용할 수 있는 KV cache 전용 기법이다.
- **HW : CXL-PNM** (Kim et al., PACT 2025, arXiv:2511.00321) — 전체 KV를 CXL 메모리에 보관하고, 모듈 내 PNM 가속기가 중요 토큰 선택과 어텐션을 수행해 GPU recall을 제거한다. 성능 수치는 7nm 설계 기반 사이클 단위 **시뮬레이션** 결과다.
- **선정 이유** : 같은 병목(KV cache 메모리 용량)을 "데이터를 줄이는 방식(SW)"과 "저장 공간·연산 위치를 옮기는 방식(HW)"이라는 상반된 방법으로 해결해, 관점별로 장단점이 뚜렷하게 갈린다. 두 기술 모두 KV cache를 직접 다루는 정식 학회 논문이라 원문 분석이 가능하다. 후보 6개(TurboQuant, DeepSeek-V2 MLA, InfiniGen, ITME 제외)의 검토 과정은 설계서 2장에 있다.


## Features
- **PDF 원문 기반 정보 추출** : KIVI·CXL-PNM 논문 PDF를 청킹·임베딩해 FAISS로 검색하고, 검색된 원문 청크를 Evidence snippet으로 Claim에 연결
- **Agentic RAG Loop** : `tech` 필터 top-5 검색 → 충분성 게이트 → Query Rewrite(최대 2회, 평가 축이 바뀐 Rewrite는 거부) → 실패 시 `insufficient`(corpus 내 근거 미확인)
- **외부 웹 조사** : Tavily로 시장성(채택·배포·생태계·도입 장벽)과 이해관계자(4대 Actor × 기술 계열)를 조사한다. 시장성 결과는 State에 저장되며 Supervisor가 dependency를 확인한 뒤 이해관계자를 선택한다.
- **Supervisor 기반 근거 검증** : Supervisor가 R1~R5 감사 결과, 재시도 상태, 시장→이해관계자 의존성을 보고 다음 Research Agent를 동적으로 선택(관점별 최대 2회, 전체 최대 10 step)
- **TRL 이원화** : 개별 기술 성숙도(`tech_trl`)와 기술 계열 생태계 성숙도(`family_trl`)를 분리 산출
- **보고서 자동 생성** : 검증된 Claim으로 보고서 view를 만들고 Jinja2 템플릿으로 결정적으로 렌더링한다. LLM(`gpt-4o`)은 근거 문장 필드만 한국어로 번역하고, 인용 번호·Claim ID·수치 표기는 템플릿이 결정한다 → `final_evaluation_report.md` / `.pdf`, Streamlit 대시보드 제공
- **보고서 품질 평가** : `report_generation` 뒤 `quality_eval`이 **3안 Hybrid**로 판정한다. 1단계 규칙(결정적)이 아래 항목을 검사하고, 통과한 보고서만 2단계 LLM Judge가 본문을 채점한다. 미달이면 원인에 따라 loop한다 (최대 2회 평가).

  | 항목 | 판정 기준 (`src/synthesis/quality.py`) |
  | :--- | :--- |
  | Groundedness | 검증된(`ok`) Claim 전부가 Evidence → Source로 연결되는가 |
  | 중립성 | 보고서에 우열·추천 표현(예: "~를 추천한다", "~가 더 우수하다", "the winner is")이 없는가 |
  | 편향 통제 | 외부 조사 Claim(market·stakeholder·MAT-A) 전부 반대 쿼리를 수행했는가, 같은 관점의 검증 Claim이 2건 이상이면 출처가 2개 이상인가 |
  | 관점 커버리지 | 기술별로 성숙도 ≥1, 시장성 ≥1, 도메인 ≥3 검증 Claim, 이해관계자 4대 Actor별 ≥1 검증 Claim. 재수집 한도를 다 쓰고 6장 Evidence Gap에 공개한 칸은 통과 |
  | 필수 목차 | `SUMMARY`, `REFERENCE` 포함 |
  | **LLM Judge** (`src/synthesis/quality_judge.py`) | 규칙 통과 보고서의 본문을 Groundedness·중립성·편향 통제·커버리지·**일관성(내부 모순)** 5개 항목 1–5점 기준표로 채점 (4점 이상 통과) |
  - 근거 부족(Groundedness·편향·커버리지)이면 재작업 대상 관점과 함께 Supervisor로, 서술 문제(중립성·목차·Judge 미달)만이면 `report_generation`으로 돌아간다.
  - **3안 선정 이유** : 1안(규칙만)은 형식만 검사해 보고서 생성 단계의 근거 없는 서술, 정규식 밖 우열 뉘앙스, 절 사이 모순을 놓친다. 2안(Judge만)은 비결정적이고 매번 호출 비용이 든다. 규칙 미달이면 Judge를 부르지 않는 Fast-Fail로 비용을 줄이고, Judge 미달 판정에는 보고서 원문 인용을 요구해(없으면 1회 재질의 후 무효) 지어낸 지적을 막는다. API 키가 없거나 호출이 실패하면 규칙 판정만 사용한다.
- **확증 편향 방지 전략** :
  - 모든 외부 조사 항목에 지지 쿼리와 반대 쿼리를 병행(R3). 반대 근거가 없으면 `counter-evidence not found`로 기록하고 상충을 만들지 않음
  - 출처 Tier(T1~T4) 부여, T4(커뮤니티·개인 블로그) 단독 근거 금지(R2)
  - 벤더 발표는 `vendor_claim`, 논문 시뮬레이션 수치는 `simulation`으로 구분(R4)
  - 우열·승자·추천 문장 금지, 근거가 부족한 Claim은 결론에서 제외하고 한계점(Evidence Gap)에만 기록
  - verified market/stakeholder/MAT-A Claim이 관점별 2건 이상이면 하나의 `source_id`에만 의존하지 않는지 최소 diversity 검사


## Tech Stack
| 구분 | 사용 기술 |
| :--- | :--- |
| Framework | LangGraph 1.2.12 (Python 3.11, uv) |
| LLM / Generator | `gpt-4o-mini` (질의 생성·Query Rewrite·웹 근거 요약·Claim 추출), `gpt-4o` (보고서 근거 문장 번역) |
| LLM / Judge | `gpt-4o` (근거 검증 R5: Claim–Evidence 일치 판정, Pydantic Structured Output). 보고서 품질 평가 2단계 Judge: 규칙 통과 보고서 본문 5개 항목 채점 |
| Retrieval | FAISS (로컬 인덱스, top-k 5, `tech` 메타데이터 필터) — **Hit@5 0.80, MRR 0.596** (코퍼스 기반 20개 질의) |
| Embedding | `intfloat/e5-small-v2` (비교: `BAAI/bge-small-en-v1.5` Hit@5 0.75, MRR 0.548 → Hit@5 ≥ 0.8 기준으로 채택) |
| Web Search | Tavily Search |
| Report | Jinja2, xhtml2pdf (한글 폰트 `NanumGothic`) |

### Embedding 모델 선정
논문 원문에서 만든 질의 20개(KIVI·CXL-PNM 각 10개)로 코퍼스 청크 검색 성능을 측정했다. **Hit@5 ≥ 0.8을 만족하는 소형 모델 중 MRR이 가장 높은 모델**을 채택하고, 소형 모델이 모두 미달하면 `BAAI/bge-m3`로 전환한다.

| 모델 | 규모 | Hit@5 | MRR | Hit@5 ≥ 0.8 | 결과 |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `BAAI/bge-small-en-v1.5` | 33M | 0.75 | 0.548 | 미달 | — |
| `intfloat/e5-small-v2` | 33M | **0.80** | **0.596** | 충족 | **채택** |
| `BAAI/bge-m3` | 568M | — | — | — | 소형 모델이 기준을 충족해 미측정 |

> 근거: `src/rag/benchmark.py`, `src/rag/benchmark_results.json` (`python -m src.rag.benchmark`로 재현)


## Agents
| Agent / Node | 담당 | 역할 | 출력 State |
| :--- | :---: | :--- | :--- |
| `paper_analysis` | B | 논문 원문 Agentic RAG로 메커니즘·수치·한계·도메인 6대 축 추출, 연구 단계 TRL 근거(`MAT-R*`) 기록 | `tech_sw`, `tech_hw`, `domain`, `claims(DOM-*, MAT-R*)` |
| `market_research` | C | 기술 계열별 채택·배포·생태계·도입 장벽 조사, 채택 단계 TRL 근거(`MAT-A*`) 기록 | `market`, `claims(MKT-*, MAT-A*)` |
| `stakeholder_research` | C | 시장성 컨텍스트(`key_vendors`)를 이어받아 4대 Actor × 기술 계열의 Benefit·Concern·Barrier·Evidence 조사 | `stakeholder`, `claims(STK-01~08)` |
| `supervisor` | A/D | 조정 계층. 새 수집 결과가 있으면 내부에서 근거 검증(R1~R4 규칙 → R5 Judge)을 실행하고, audit issue·품질 재작업 대상·`node_status`·의존성으로 다음 Research Agent 1개 또는 평가 종합을 선택한다. 실제 재작업 dispatch 때만 `retry_count` 증가 | `audit`, `claims[*].status`, `next_agent`, `retry_count`, `step_count`, `last_decision` |
| `evaluation_synthesis` | E | 관점 간 일치·불일치 정리, TRL 이원화 확정(0건 Fallback) | `trl`, `synthesis` |
| `report_generation` | E | 검증된 Claim으로 보고서 view 구성 → 근거 문장 필드 번역 → Jinja2 렌더링 | `report` |
| `quality_eval` | E | 보고서 품질 평가(Groundedness·중립성·편향 통제·관점 커버리지·필수 목차), 미달 원인별 재작업 대상 산출 | `quality` |


## Architecture
![Architecture](docs/images/architecture.png)

> `build_evaluation_graph().get_graph().draw_mermaid_png()`로 실제 코드에서 생성한 그래프 (`docs/images/architecture.png`). 실선은 고정 엣지, 점선은 조건부 분기다.

| 엣지 | 종류 | 결정 주체 |
| :--- | :--- | :--- |
| `START → supervisor` | 고정 | — |
| `supervisor → paper_analysis / market_research / stakeholder_research / evaluation_synthesis` | 조건부 (`route_supervisor`) | Supervisor가 State로 선택한 `next_agent` |
| `paper_analysis / market_research / stakeholder_research → supervisor` | 고정 | Research Agent는 항상 Supervisor로 복귀 (Agent 간 직접 통신 없음) |
| `evaluation_synthesis → report_generation → quality_eval` | 고정 | — |
| `quality_eval → supervisor / report_generation / END` | 조건부 (`route_quality`) | 품질 판정 결과: 근거 부족 → Supervisor, 서술 문제 → 재작성, 통과 또는 평가 2회 → 종료 |

### 데이터 흐름 (End-to-End Data Flow)
파이프라인은 24개 State field(Payload 13 + Control 11)를 사용하며, Research Agent 간 직접 통신 없이 Supervisor를 통해서만 제어된다.

| 단계 | 실행 노드 (담당) | 입력 State | 처리 내용 | 출력/누적 State |
| :---: | :--- | :--- | :--- | :--- |
| **Step 1<br/>초기화 & 동적 선택** | `START` → `supervisor` (A/D) | `INITIAL_INPUT_STATE` | • 대상 기술 및 제어 metadata 주입<br/>• audit/coverage/retry/dependency를 읽어 다음 Research Agent를 한 개 선택 | `selected`, `node_status`, `retry_count`, `step_count` |
| **Step 2<br/>논문 RAG 분석** | `paper_analysis` (B) | `selected` | • KIVI/CXL-PNM 원문 PDF 청킹 및 E5 임베딩 벡터 검색<br/>• 정량 실험 수치(실측/시뮬레이션 구분) 및 6대 축 적합성 추출 | `tech_sw`, `tech_hw`, `domain`,<br/>`claims(DOM-*, MAT-R*)`, `evidence`, `sources` |
| **Step 3<br/>시장성 및 이해관계자** | `market_research` 또는<br/>`stakeholder_research` (C) | `selected`<br/>(stakeholder는 `market` State 의존) | • Tavily Web Search 기반 최신 시장 동향 및 배포 장벽 조사<br/>• 4대 Actor(서빙 운영자, 프레임워크 개발자, End User, HW·메모리 공급자) × 기술 계열 2개 관점 영향도 분석<br/>• 시장 결과 저장 뒤 Supervisor가 dependency를 확인하여 이해관계자 작업을 선택 | `market`, `stakeholder`,<br/>`claims(MKT-*, STK-*)`, `evidence`, `sources` |
| **Step 4<br/>Supervisor audit & routing** | `supervisor` (A/D) | `claims`, `evidence`, `sources`, control State | • R1~R5 audit 후 current State에서 한 Agent만 선택<br/>• 실제 retry dispatch만 count하며 market refresh는 stakeholder를 stale 처리 | `audit.issues`, `next_agent`, `retry_count`, `node_status` |
| **Step 5<br/>TRL 이원화 & 종합** | `evaluation_synthesis` (E) | `claims`, `evidence`, `tech_*`, `market`, `stakeholder` | • 개별 기술 TRL(5-6 / Unknown) vs 계열 산업 TRL(7-8) 이원화 평가<br/>• 기술별 트레이드오프 및 상호 보완적 하이브리드 결합 가능성 도출 | `trl`, `synthesis` |
| **Step 6<br/>보고서 생성 & 산출** | `report_generation` (E)<br/>→ `main.py` / `app.py` (A) | 전체 누적 State | • 검증된 Claim으로 보고서 view 구성, 본문 인용 번호와 REFERENCE를 일치시킴<br/>• LLM(`gpt-4o`)은 근거 문장 필드만 번역, Jinja2 템플릿이 최종 마크다운 렌더링<br/>• 한국어 폰트 임베딩 기반 PDF(`final_evaluation_report.pdf`) 변환 | `report` (Markdown 텍스트),<br/>`final_evaluation_report.md`, `final_evaluation_report.pdf` |
| **Step 7<br/>보고서 품질 평가** | `quality_eval` | `report`, `claims`, `evidence`, `sources`, `retry_count` | • Groundedness·중립성·편향 통제·관점 커버리지·필수 목차 판정<br/>• 근거 부족 → Supervisor(재작업 대상 관점), 서술 문제 → `report_generation`, 통과 또는 2회 평가 → 종료 | `quality` |


## State Schema
`src/state.py`의 `OverallState`는 `PayloadState`(13)와 `ControlState`(11)를 결합한 24개 field다.

- **제어 vs 페이로드 분리** : `PayloadState`는 Agent가 만든 작업 결과(`selected`, `tech_sw`, `tech_hw`, `domain`, `market`, `stakeholder`, `claims`, `evidence`, `sources`, `audit`, `trl`, `synthesis`, `report`)이고, `ControlState`는 Supervisor 조정·종료·재개에 필요한 최소 상태(`retry_count`, `next_agent`, `node_status`, `step_count`, `trace_id`, `quality`, `last_audited_step`, `last_decision`, `last_error`, `last_errors`, `node_attempts`)다. 라우팅은 `audit.issues`, `quality.rework_targets`, `node_status`, `retry_count`만 읽는다.
- **관측성 위치** : 결정 로그 본문은 State에 쌓지 않는다. State에는 최신 결정 `last_decision`(`next`, `reason`)만 덮어쓰고, 전체 결정 이력은 LangSmith trace에서 확인한다.
- **지속성 비용** : 대용량 로그·검색 원문을 State에 누적하지 않는다. `claims`/`evidence`/`sources`는 ID·URL 기준 reducer로 최신 구조화 결과만 유지해, 재작업을 반복해도 checkpoint마다 무한히 늘지 않는다.
- **상관** : `make_initial_state()`가 실행마다 UUID `trace_id`를 만들고, `main.py`가 이를 LangGraph `thread_id`로 전달해 State·checkpoint·LangSmith trace를 같은 키로 잇는다.
- **재개/복구** : `node_status`(`pending`/`complete`/`stale`/`failed`), `node_attempts`, `last_error`/`last_errors`, `retry_count`, `step_count`, `last_audited_step`으로 중단·실패·재시도 상태를 판단한다. Worker 첫 실패는 `pending`으로 되돌려 1회 재시도하고, 반복 실패는 `failed`로 둔다. `main.py`는 `InMemorySaver` checkpointer로 실행한다.
- **동시 처리** : Supervisor는 한 번에 Research Agent 하나만 dispatch해 제어 field의 동시 쓰기를 없앴다. 재작업으로 같은 Claim이 다시 들어와도 `upsert_claims`(Claim ID), `upsert_evidence`(Evidence ID), `union_sources`(Source ID·URL 중복 제거) reducer가 덮어써 오염을 막는다. market → stakeholder 의존은 엣지가 아니라 `node_status`로 표현하고, market 재작업 시 stakeholder를 `stale`로 바꿔 다시 수집한다.
- **종료 보장** : 관점별 재작업 `RETRY_LIMIT=2`, Research dispatch `MAX_STEPS=10`, 보고서 품질 평가 `MAX_QUALITY_ATTEMPTS=2`, Worker 실패 1회 재시도로 모든 루프를 제한한다. 마지막 재작업 후에도 검증 이슈가 남은 Claim만 `insufficient`/`rejected`로 확정해 6장 Evidence Gap에 공개한다.

## Evaluation Results
최종 평가 보고서(`final_evaluation_report.pdf`, 2026-10-07 실행 결과) 기준이다. LLM·웹 검색 결과에 따라 실행마다 일부 Claim은 달라질 수 있다.

### TRL 추정 결과 (TRL 이원화)
| 기술 | 개별 기술 성숙도 (`tech_trl`) | 계열 생태계 성숙도 (`family_trl`) | 신뢰도 | 근거 Claim |
| :--- | :---: | :---: | :---: | :--- |
| **KIVI** (SW) | 5-6 | 7-8 | high | 연구: DOM-01, DOM-05, DOM-09, DOM-11, MAT-R01 / 채택: MKT-02 |
| **CXL-PNM** (HW) | 3-4 | 7-8 | high | 연구: DOM-02, DOM-04, DOM-06, DOM-10, DOM-12, MAT-R02 / 채택: MKT-03, MKT-04, MKT-06, MAT-A02 |

> 판정 규칙(`src/synthesis/evaluator.py`): 연구 근거(domain·MAT-R)에 `fact`가 있으면 `tech_trl` 5-6, `simulation`만 있으면 3-4. 채택 근거(market·MAT-A)에 `fact`가 있으면 `family_trl` 7-8, `vendor_claim`만 있으면 6-7.

- 두 기술 모두 계열 생태계(KV 양자화 / CXL 메모리 확장)는 7-8 수준이지만, 개별 기술은 KIVI가 오픈소스 구현 단계(5-6), CXL-PNM이 시뮬레이션 연구 단계(3-4)로 **개별 기술과 계열 사이의 성숙도 간극**이 드러난다.

## Directory Structure
```
├── data/
│   ├── papers/              # 문서 풀: KIVI·CXL-PNM 논문 PDF
│   ├── fonts/               # PDF 보고서용 한글 폰트
│   ├── eval_queries.json    # 임베딩 벤치마크 질의 20개
│   └── faiss_index/         # FAISS 로컬 인덱스 (indexer.py로 생성, git 제외)
├── src/
│   ├── supervisor.py        # [조정 계층] Supervisor: 근거 검증 호출 · State 기반 다음 Agent 선택
│   ├── graph.py             # StateGraph 조립 (Supervisor 허브 · 품질 평가 loop)
│   ├── state.py             # OverallState 24개 field (Payload 13 + Control 11) + Custom Reducer
│   ├── config.py            # 모델명 · 경로 · API 키
│   ├── rag/                 # [B] indexer · benchmark · agentic_rag (paper_analysis)
│   ├── research/            # [C] client · market · stakeholder
│   ├── audit/               # [D] 근거 검증 로직 rules(R1~R4) · judge(R5) · auditor (Supervisor 내부에서 호출)
│   └── synthesis/           # [E] evaluator · report_gen · quality(quality_eval) · pdf_export
│       └── templates/       # 보고서 템플릿 (report.md.j2)
├── tests/                   # 모듈별 단위 테스트 + mock_data.py (외부 API mock)
├── scripts/                 # OpenWiki 리포트 생성 스크립트
├── tasks/                   # 역할별 개발 가이드 · 공통 규칙 · 코드 리뷰 프롬프트
├── docs/                    # 구현 계획 · 명세 · 아키텍처 이미지(images/)
├── KV_cache_최적화_기술_평가_설계서_최종.md   # 설계서
├── main.py                  # 실행 스크립트 (non-interactive)
├── app.py                   # Streamlit 대시보드
├── final_evaluation_report.md / .pdf   # 평가 결과 (실행 시 생성, git 제외)
└── README.md
```


## Usage
### 1. 환경 변수 설정
`.env.example`을 복사해 `.env`를 만들고 키를 입력한다. API 키가 없어도 Fallback으로 크래시 없이 동작하지만, 실제 검색·RAG 결과를 얻으려면 `OPENAI_API_KEY`와 `TAVILY_API_KEY`가 필요하다.

```bash
cp .env.example .env
```

```dotenv
OPENAI_API_KEY=
LANGCHAIN_API_KEY=
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_PROJECT=RAG-PROJECT
HF_TOKEN=
TAVILY_API_KEY=
```

| 환경 변수 | 필수 여부 | 기본/예시 값 | 설명 |
| :--- | :---: | :--- | :--- |
| `OPENAI_API_KEY` | 선택 (권장) | `sk-...` | **OpenAI API Key**: 2단계 Fast-Fail 검증 심사(`JudgeDecision` - `gpt-4o`), 최종 보고서 윤문(Polishing - `gpt-4o`), 리서치 쿼리 생성 등에 사용됩니다. (미설정 시 Rule-based Mock/Fallback 모드로 자동 전환) |
| `LANGCHAIN_API_KEY` | 선택 | `lsv2_pt_...` | **LangSmith API Key**: LangGraph 멀티 에이전트 실행 흐름, 노드 간 State 전이 및 LLM 호출 트레이싱 모니터링에 사용됩니다. |
| `LANGCHAIN_TRACING_V2` | 선택 | `true` | **LangSmith V2 트레이싱 활성화**: 실행 로그 및 그래프 트레이스를 LangSmith로 전송할지 여부 (`true` / `false`). |
| `LANGCHAIN_ENDPOINT` | 선택 | `https://api.smith.langchain.com` | **LangSmith 엔드포인트 URL**: 트레이싱 데이터를 수신하는 LangSmith 서버 주소. |
| `LANGCHAIN_PROJECT` | 선택 | `RAG-PROJECT` | **LangSmith 프로젝트명**: LangSmith 대시보드에서 트레이스를 그룹화하여 확인할 프로젝트 이름. |
| `HF_TOKEN` | 선택 | `hf_...` | **Hugging Face Token**: RAG 임베딩 모델(`intfloat/e5-small-v2`) 다운로드 속도 향상 및 Hugging Face API Rate Limit 완화용. |
| `TAVILY_API_KEY` | 선택 (권장) | `tvly-...` | **Tavily Search API Key**: 시장성 조사(`market_research`) 및 이해관계자 리서치(`stakeholder_research`) 노드의 실시간 웹 검색에 사용됩니다. (미설정 시 검색 결과 없이 진행하며, 해당 Claim은 `insufficient`로 처리) |

### LangSmith 제출 캡처

- **Trace A (정상)**: `Supervisor → research agents → Supervisor → synthesis → report → quality pass` 순서, conditional routing·방문 순서·`trace_id`·최종 종료를 캡처한다.
- **Trace B (재작업)**: `Supervisor → targeted research agent → Supervisor → audit issue → targeted rework → Supervisor → synthesis → report → quality` 순서와 retry/rework 또는 quality loop를 캡처한다.
- 캡처 파일명은 순서대로 `tracing-1.png`, `tracing-2.png`, …로 저장한다 (긴 경로는 여러 장으로 나눔).
- 최종 실행 뒤 `final_evaluation_report.pdf`가 **10p 이하**이며 `SUMMARY`, `REFERENCE` 목차를 포함하는지 확인한다.

### 2. 설치 및 테스트
```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
pytest tests/ -v
```

### 3. 실행
```bash
python main.py                  # 평가 파이프라인 실행 → final_evaluation_report.md / .pdf 생성
```

대시보드(선택)는 `streamlit`이 `requirements.txt`에 포함되어 있지 않아 별도 설치 후 실행한다.
```bash
uv pip install streamlit
streamlit run app.py
```

### 4. RAG 인덱스 재생성 (필요 시)
```bash
python -m src.rag.indexer       # data/papers/*.pdf → data/faiss_index/
python -m src.rag.benchmark     # 임베딩 모델 Hit@5 · MRR 측정
```


## Contributors
Agent 과제(Multi-Agent Orchestration) 기준 개인별 수행 역할이다. 근거는 각 PR·커밋이다.

| 이름 (가나다순) | 담당 영역 | 주요 수행 내용 |
| :--- | :--- | :--- |
| **강건호** | 코드 정리 · 리뷰 기준 | • **AI 생성 코드 정리**: 덮어써진 중복 정의 삭제, `market`·`stakeholder`에 복사된 `_build_source`를 `client.build_source`로 통합, 미사용 import·상수 제거 (동작 변경 없이 정리, #62 → 통합 브랜치 #64)<br/>• **Supervisor 브랜치 잔여 코드 정리** (#58)<br/>• **코드 리뷰 프롬프트** 작성 (`tasks/code_review_prompt.md`) |
| **김효민** | 패턴 설계 · 보고서 품질 평가 · 통합 검증 | • **패턴 선정 분석**: Supervisor vs Orchestrator-Workers를 과제 필수 항목 기준으로 비교, 근거 검증(`evidence_audit`) 확장형 Supervisor 전환안 설계·구현 (#45)<br/>• **보고서 품질 평가 설계**: 평가 항목별 규칙·LLM Judge 2단계 Fast-Fail 설계 문서와 구현, 재작업 판단을 Supervisor로 분리 (#60)<br/>• **통합 브랜치 검증**: 실제 파이프라인 실행 검증, 코드 리뷰와 문제별 이슈 분리 (#67~#75), 산출물 체크리스트 (#61), README 정비 (#78) |
| **윤영민** | Supervisor 승격 설계 | • **근거 검증의 Supervisor 승격**: `evidence_audit`를 Supervisor로 승격하고 `market → stakeholder` 직접 엣지와 고정 라우팅 제거, 비어 있는 관점만 호출하고 열린 issue의 워커만 재작업하는 State 기반 분기 (#56)<br/>• **Hybrid 품질 게이트·재작성 루프 시안** (`feat/supervisor-audit-promotion`) |
| **전경호** | Supervisor 시안 · 품질 게이트 보완 | • **Supervisor 패턴 + Layered State + 품질 평가 루프 시안**: 허브-스포크 구조, 근거 부족 시 해당 에이전트 재작업, 워커 예외 1회 재시도 후 제외 (#47)<br/>• **품질 게이트 커버리지 보완**: 재수집 후 6장 Evidence Gap에 공개한 칸을 통과로 인정하는 예외 (#65) |
| **정은희** | Supervisor 통합 구현 · 보고서 | • **통합 브랜치 구현** (`jeh_restructure-pdf-guided-architecture`): State 기반 Supervisor 연구 흐름과 라우팅 계약, 규칙 기반 품질 게이트, 워커 실패 1회 재시도<br/>• **보고서 재구성**: 검증된 Claim 기반 섹션 구성, 본문 인용과 REFERENCE 일치, 근거 문장 필드 단위 번역, PDF 출력 개선<br/>• **통합 머지·실행 오류 수정** (checkpointer import 등) |
| **최지윤** | Supervisor 실행 정책 · RAG | • **Supervisor Hub-Spoke 시안**: State 기반 동적 라우팅, Agent별 Retry와 Worker Recovery 계약 (#46)<br/>• **통합 구조 실행 정책 반영**: `PayloadState`/`ControlState` 분리, `node_attempts`·`last_errors`, `InMemorySaver` checkpoint와 `trace_id` thread, 실제 재작업 dispatch에만 retry 증가, market 성공 후 stakeholder `stale` 처리, RAG 개선 (#66) |

### 평가 보고서의 핵심 포인트
| 이름 (가나다순) | 담당 | 평가 보고서 핵심 포인트 (Key Takeaway) | 비고 |
| :--- | :---: | :--- | :--- |
| **강건호** | 담당 D | • 엄격한 Fast-Fail 2단계 검증(Rule + LLM Judge)을 통해 환각(Hallucination) 및 출처 없는 주장을 사전 차단하여 보고서의 신뢰도와 객관성을 극대화함.<br/>• 수치 왜곡 방지 및 Claim-Evidence 일치성 검증으로 학술 논문/웹 출처에 기반한 사실 검증 체계 확립. | Fast-Fail 검증 |
| **김효민** | 담당 C | • 서빙 운영자, 프레임워크 개발자, End User, HW·메모리 공급자 4대 Actor × 기술 계열(KV Quantization / CXL Memory Expansion) 관점의 분석 반영.<br/>• KIVI는 기존 GPU·HBM에서 소프트웨어만으로 적용 가능한 반면 정확도·운영 위험이, CXL-PNM은 새 인프라 도입 비용·지연·호환성이 도입 장벽으로 나타남을 대조. | 이해관계자 리서치 |
| **윤영민** | 담당 A | • SW 양자화(KIVI)와 HW 메모리 확장(CXL-PNM)의 상호 배타적 경쟁이 아닌 '하이브리드 결합 가능성'을 도출.<br/>• Fast-Fail 피드백 루프와 TRL 이원화 체계를 결합한 안정적 엔드투엔드 파이프라인 완성. | 오케스트레이션 |
| **전경호** | 담당 C | • 글로벌 데이터센터 현장 관점에서의 최신 시장 동향 및 배포 장벽(Latency 오버헤드, CXL 상용화 성숙도) 발굴.<br/>• 단기적 실용성(SW 압축)과 장기적 메모리 풀링(HW 확장)의 시장 수용 주기 차이를 규명. | 웹 시장성 조사 |
| **정은희** | 담당 E | • 개별 기술 TRL과 계열 산업 TRL을 분리하는 TRL 이원화 평가를 통해 시뮬레이션 지표와 실증 기술의 성숙도 간극을 체계적으로 조명.<br/>• 학술·시장·검증 데이터를 통합한 고품질 기술 평가 보고서 템플릿 완성. | 다관점 종합 보고서 |
| **최지윤** | 담당 B | • E5 임베딩 기반 논문 Agentic RAG를 통해 KIVI 2.6× peak memory 절감(모델 가중치 포함), 최대 4× 배치 확장 등 핵심 정량 데이터를 논문 원문으로부터 오차 없이 추출·제공. | Agentic RAG |

### Lessons Learned
| 이름 (가나다순) | 담당 | 잘된 점 (Keep) | 아쉬웠던 점 및 시도해볼 점 (Problem / Try) | 핵심 배운 점 (Lesson Learned) |
| :--- | :---: | :--- | :--- | :--- |
| **강건호** | 담당 D | • 규칙 기반 4대 룰과 LLM 판정의 2단계 파이프라인으로 검증 속도와 정밀도를 동시에 달성함.<br/>• 팀 합의로 설계한 "근거 감사관 + 표적 피드백(Auditor Loop)" 구조(규칙 + LLM Judge 검사 → 문제 있는 에이전트에만 표적 피드백 → 최대 2회 재시도)가 실제 구현에 거의 그대로 반영됨. | • LLM 심사 프롬프트의 미세한 문맥 차이로 정상 Claim이 오탐되는 케이스가 있어 정밀 튜닝이 필요했음.<br/>• 초반 설계 방향을 잡을 때 팀원 전원의 의견을 반영하느라 소통에 시간이 꽤 걸림. | 엄격한 근거 검증 루프가 멀티 에이전트 시스템 전체의 출력 신뢰도를 지탱하는 핵심 안전장치임을 체감함.<br/>• RAG를 직접 설계·구현하며 청킹, 임베딩, 검색 필터링, LLM Judge 프롬프트 튜닝 같은 디테일이 결과 품질을 좌우함을 체감함.<br/>• 여러 팀원이 같은 코드베이스를 병렬로 다루는 협업(브랜치 전략, merge conflict, 역할 경계)에서 설계 문서와 코드의 정합성을 계속 맞추는 습관을 기름. |
| **김효민** | 담당 C | • 4대 액터별 Benefit, Concern, Barrier, Evidence를 일관된 계약 구조로 성공적으로 정형화함.<br/>• (#3) State 리듀서 `union_sources`를 LangGraph 1.2.12에서 실제로 실행해 참조 끊김을 재현하고, 공통 계약(Interface Freeze)인 리듀서는 그대로 둔 채 조사 노드가 기존 `source_id`를 재사용하도록 해 해결함.<br/>• (#4) 라우터 기준(`retry_count < 2`)에 맞춰 검증 노드가 한도 도달 Claim의 최종 상태를 확정하도록 합의하고, 재실행 대상을 소유권이 분명한 Claim ID 접두어로 판단하게 함. | • 웹 검색 API의 응답 속도 및 비정형 텍스트 파싱 과정의 예외 처리를 더욱 강화할 필요가 있음.<br/>• (#3) URL은 같고 `source_id`가 다른 Source가 들어오면 Evidence가 존재하지 않는 Source를 가리켜, R2 검사를 경고 없이 통과하고 REFERENCE에서도 빠짐.<br/>• (#4) 재시도 한도를 소진한 Claim이 `flagged`로 남아 보고서 본문과 한계점 어디에도 나오지 않았고, 공란 슬롯의 R1 오탐으로 재시도가 낭비되며 관계없는 노드가 재실행됨. | 다양한 이해관계자의 상충되는 요구사항을 정량적 근거(Claim-Evidence)와 연결하여 다각도로 분석하는 방법론을 습득함.<br/>• 리듀서는 필드 단위로 병합할 뿐 엔티티 간 참조 무결성까지는 보장하지 않으므로, 공통 State 계약에는 "참조 무결성을 어느 쪽이 책임지는가"까지 정의해야 함.<br/>• 조건부 루프는 탈출 조건만으로는 수렴하지 않으며, 라우터는 State를 쓸 수 없으므로 종료 상태를 누가 기록하는지까지 노드 간 계약으로 정해야 결과가 보고서에 올바르게 반영됨. |
| **윤영민** | 담당 A | • State 스키마 엄격 분리 및 병렬 브랜치/피드백 루프 설계를 통해 팀원 간 병렬 개발 충돌을 최소화함. | • 실시간 웹 검색 및 RAG 간 레이턴시 차이로 인한 비동기 동기화 처리 최적화 여지 존재.<br/>• Agent 구성을 먼저 정한 뒤 보고서를 구성하는 탑다운 방식으로 진행했으나, 경험 부족과 기한 내 Volume 선정 근거가 부족했던 점이 아쉬움.<br/>• (Try) 산출물(보고서) 형식을 먼저 정하고 Agent와 LangGraph를 선정하는 바텀업 방식, 다른 LangGraph 패턴을 활용한 더 정교한 Agent 시스템 구축 | LangGraph의 유연한 State 분기와 조건부 라우팅을 통해 복잡한 오케스트레이션을 견고하게 제어할 수 있음을 배움.<br/>• 보고서 형식을 우선 정의하고 LangGraph를 설계하면 더 나은 결과와 효율적인 개발이 가능하다는 점을 깨달음. |
| **전경호** | 담당 C | • 자연어 질문형 질의 생성 및 카테고리별 분리 수집으로 시장성 조사 결과의 품질을 높임.<br/>• 키가 없을 때 가짜 URL을 돌려주던 fallback을 "빈 결과 + insufficient"로 바꿔 시스템의 신뢰성을 확보함.<br/>• 키워드 나열을 자연어 질문으로, 자르는 글자 수를 넉넉하게 바꾸는 것만으로 결과 품질이 확연히 개선됨. | • Tavily API Rate Limit 및 키 누락 상황에 대응하는 모의 데이터와 실제 데이터 간 편차 최소화 필요.<br/>• 각자의 유닛 테스트는 통과했지만 서로 다른 전제(같은 출처를 다르게 분류)로 코드를 엮자 좋은 데이터가 버려지는 통합 문제가 발생함.<br/>• 브랜치를 나눠도 공용 파일을 같은 이유로 동시에 고치면 충돌이 생기므로 사전 조율이 필요함. | 외부 검색 도구를 에이전트 파이프라인에 결합할 때, 견고한 Fallback과 구조화된 쿼리 전략이 필수적임을 깨달음.<br/>• 가짜보다 정직한 실패가 낫다.<br/>• State 충돌 버그(#3)는 직접 재현 코드를 짜봐야 완전히 이해된다.<br/>• LLM에 "보여준 것"과 "저장한 근거"는 항상 일치해야 하며, 이런 버그는 실제 API로 돌려봐야 드러난다.<br/>• 유닛 테스트 초록불 ≠ 통합 정합성. |
| **정은희** | 담당 E | • Jinja2 기반 템플릿과 TRL 이원화 매핑을 결합하여 가독성 높고 학술적 깊이가 있는 보고서를 도출함.<br/>• 출처를 논문·특허·기업 발표·웹페이지로 구분하고 신뢰도 Tier를 부여해 Claim의 근거 수준을 관리하는 구조를 적용함.<br/>• Claim·Evidence·Source를 분리하고, 근거가 부족한 항목은 억지로 채우지 않도록 상태와 fallback 규칙을 설계함.<br/>• 중간 데이터와 최종 보고서 표현을 분리해 딕셔너리·내부 상태값이 보고서에 노출되지 않도록 정규화하고, 출처 메타데이터 기반 인용, LLM 거절 응답 검증, 실패 상황을 포함한 테스트를 보완함. | • 다양한 노드에서 취합된 비정형 텍스트의 톤앤매너를 완전히 균일하게 맞추는 데 추가 튜닝이 필요했음. | 다관점 평가 체계에서 이원화된 TRL 및 근거 연결(Citation)이 보고서의 설득력을 결정짓는다는 점을 깊이 이해함.<br/>• 다중 에이전트 평가 시스템은 기능을 나누는 것보다 각 모듈이 어떤 근거를 받고 어떤 형식으로 반환하는지를 명확히 정하는 일이 더 중요함.<br/>• 검색 실패, 근거 부족, 메타데이터 누락을 예외가 아닌 정상 상태로 처리해야 최종 보고서의 품질을 지킬 수 있음. |
| **최지윤** | 담당 B | • 임베딩 벤치마크를 통해 최적 모델(`intfloat/e5-small-v2`)을 선정하고 고품질 청킹/검색 파이프라인을 구축함.<br/>• 평가 축이 바뀐 Query Rewrite는 거부하고 원문에 근거가 없으면 insufficient로 남기도록 보완했으며, 필요한 정보가 여러 청크에 나뉜 경우 원문이 확인된 여러 Evidence를 하나의 Claim에 연결함. | • 논문 내 표/수식 등 비텍스트 데이터 추출 및 정밀도 향상을 위한 멀티모달 파서 도입 고려.<br/>• 관련 청크가 Top-k에 포함되더라도 현재 평가 축에 직접 답하는지 검증하지 않으면, 대역폭 질문에 처리량 수치가 연결되는 것처럼 잘못된 Claim이 만들어짐.<br/>• 단위 테스트 통과만으로는 충분하지 않아, 실제 PDF·FAISS·LLM을 함께 실행하며 Retrieval → Gate → 인용 → Rewrite 순으로 실패 지점을 나눠 검증함. | RAG 시스템에서 도메인에 특화된 청킹 및 임베딩 모델 선정이 다운스트림 에이전트의 근거 품질에 미치는 막대한 영향을 확인함.<br/>• 검색된 문장과 실제로 사용할 수 있는 근거는 다르며, Agentic RAG는 검색 결과를 그대로 답으로 쓰는 것이 아니라 질문에 맞는 원문 근거인지 반복해서 확인하는 과정임.<br/>• Query Rewrite는 검색 성공률만 높이는 것이 아니라 원래 질문의 의미를 유지해야 함. |
