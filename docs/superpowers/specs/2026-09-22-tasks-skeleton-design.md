# [설계서] LangGraph 1.2.12 기반 멀티 에이전트 스켈레톤 아키텍처

> **문서 ID**: SPEC-2026-09-22-SKELETON  
> **날짜**: 2026-09-22  
> **대상 저장소**: `skala-langgraph-team3`  
> **목적**: SKALA 4기 4시간 스프린트 멀티 에이전트 평가 시스템(KV Cache 최적화 기술 평가: KIVI vs CXL-PNM)을 위한 uv 및 LangGraph 1.2.12 기반의 고신뢰성 스켈레톤 구축  

---

## 1. 개요 및 배경

본 프로젝트는 대규모 언어 모델(LLM)의 긴 문맥 서빙 시 발생하는 핵심 병목인 **KV Cache 메모리 오버헤드**를 해결하기 위한 두 가지 대표 접근법을 비교 평가하는 멀티 에이전트 시스템을 구축한다:
1. **소프트웨어/알고리즘 접근**: KIVI (비대칭 2-bit 양자화, Key 채널별/Value 토큰별)
2. **하드웨어/CXL 근접 처리 접근**: CXL-PNM (CXL 메모리 컨트롤러 내 PIM/PNM 가속)

평가 도메인은 **클라우드 서빙 환경**으로 고정하며, 5개 역할(A~E)이 병렬 개발할 수 있도록 단일 진실 공급원인 State 계약과 LangGraph 1.2.12 오케스트레이션 스켈레톤을 완성한다.

---

## 2. 핵심 설계 원칙 및 LangGraph 1.2.12 안티패턴 방지

`tasks/common.md`에 명시된 7대 안티패턴을 철저히 차단한다:

1. **State In-place Mutation 방지**: 노드 함수는 전달받은 state 객체를 직접 수정하지 않고, 갱신할 키만 담은 새로운 딕셔너리를 반환한다. 리듀서가 없는 딕셔너리(`market`, `tech_sw` 등)는 부분 병합이 아닌 통째 교체이므로 언팩 연산자(`{**state["market"], ...}`)를 사용한다.
2. **단일 책임 노드 분리**: `paper_analysis`, `market_research`, `stakeholder_research`, `evidence_audit`, `evaluation_synthesis`, `report_generation`의 6개 독립 노드로 철저히 분리한다.
3. **Upsert Reducer 적용**: `claims`, `evidence`, `sources`에는 단순 `operator.add` 대신 고유 ID 기반의 멱등 Reducer(`upsert_claims`, `upsert_evidence`, `union_sources`)를 사용한다.
4. **루프 탈출 보장**: `retry_count < 2` 조건을 통해 최대 2회까지만 재시도하며, 한도 초과 시 즉시 `evaluation_synthesis`로 빠져 `status="insufficient"`로 격리한다.
5. **동시 쓰기 충돌(`InvalidUpdateError`) 방지**: 병렬 실행 노드(`paper_analysis`와 `market_research`)는 서로 다른 키(`tech_sw`/`domain` vs `market`)만 갱신하며, 공통 키는 리듀서가 있는 `claims`, `evidence`, `sources`에만 각자의 ID 대역을 사용하여 기록한다.
6. **스키마 무결성 (Interface Freeze)**: `OverallState`에 선언된 14개 키 외의 임의 키는 반환하지 않는다.
7. **안티패턴 7 완전 해결 (정확한 Fan-in / Fan-out 토폴로지)**:
   - `paper_analysis`(1홉)와 `stakeholder_research`(2홉)의 합류 시, `evidence_audit`로 각각 정적 엣지를 연결하면 검증 노드가 조기 실행/중복 실행된다.
   - 첫 실행의 검증 진입점은 `stakeholder_research → evidence_audit` 정적 엣지 하나로 고정한다.
   - `paper_analysis` 뒤에는 조건부 엣지 `route_after_paper`를 두어 첫 실행 시에는 `END`로 분기를 닫고, 검증 노드에 의해 `paper`가 재실행된 경우에만 `evidence_audit`로 재진입하도록 제어한다.

---

## 3. 디렉토리 구조 및 파일 전담 매핑

```text
skala-langgraph-team3/
├── .env.example                     # 환경변수 템플릿
├── .gitignore                       # 가상환경, 캐시, 인덱스 제외 설정
├── pyproject.toml                   # uv 기반 프로젝트 메타데이터 및 의존성
├── requirements.txt                 # 의존성 목록
├── README.md                        # 담당 A 전담: 목적, 구조, 실행 가이드
├── main.py                          # 파이프라인 진입점 (non-interactive 실행)
├── KV_cache_최적화_기술_평가_설계서_최종.md # 기준 설계 문서
├── tasks/                           # 팀 헌장 및 역할별 가이드
├── data/
│   ├── eval_queries.json            # 벤치마크 평가 질의셋 20선
│   └── papers/                      # (B 담당) 논문 원문 PDF 저장소
├── src/
│   ├── __init__.py
│   ├── config.py                    # 모델명, API 키, 경로 상수
│   ├── state.py                     # [A 전담] OverallState 및 3대 Reducer
│   ├── graph.py                     # [A 전담] StateGraph 조립 및 조건부 라우터
│   ├── rag/                         # [B 전담] Agentic RAG
│   │   ├── __init__.py
│   │   ├── agentic_rag.py           # paper_analysis_node
│   │   ├── indexer.py               # PDF 청킹 및 FAISS 인덱서
│   │   └── benchmark.py             # 임베딩 Hit@5/MRR 평가기
│   ├── research/                    # [C 전담] 웹 조사
│   │   ├── __init__.py
│   │   ├── client.py                # Tavily 래퍼 및 Tier 분류기
│   │   ├── market.py                # market_research_node
│   │   └── stakeholder.py           # stakeholder_research_node
│   ├── audit/                       # [D 전담] Fast-Fail 검증
│   │   ├── __init__.py
│   │   ├── rules.py                 # 1단계 정적 룰 R1~R4 (0ms)
│   │   ├── judge.py                 # 2단계 R5 LLM-as-a-Judge
│   │   └── auditor.py               # evidence_audit_node
│   └── synthesis/                   # [E 전담] 평가 종합 및 보고서
│       ├── __init__.py
│       ├── evaluator.py             # evaluation_synthesis_node (TRL 이원화)
│       ├── report_gen.py            # report_generation_node (Polishing)
│       └── templates/
│           └── report.md.j2         # 8대 필수 장 Jinja2 템플릿
└── tests/
    ├── __init__.py
    ├── mock_data.py                 # [A 전담] 14개 키 완비 MOCK_STATE
    ├── test_smoke.py                # [A 전담] 전체 파이프라인 스모크 테스트
    ├── test_rag.py                  # [B 전담] RAG 단위 테스트
    ├── test_research.py             # [C 전담] 웹 조사 단위 테스트
    ├── test_audit.py                # [D 전담] 검증 단위 테스트
    └── test_synthesis.py            # [E 전담] 종합/보고서 단위 테스트
```

---

## 4. State 계약 명세 (`src/state.py`)

### 4.1 Custom Reducers
```python
def upsert_claims(existing: list["Claim"], updates: list["Claim"]) -> list["Claim"]:
    claim_map = {c["id"]: c for c in (existing or [])}
    for new_c in (updates or []):
        claim_map[new_c["id"]] = new_c
    return list(claim_map.values())

def upsert_evidence(existing: list["Evidence"], updates: list["Evidence"]) -> list["Evidence"]:
    ev_map = {e["evidence_id"]: e for e in (existing or [])}
    for new_e in (updates or []):
        ev_map[new_e["evidence_id"]] = new_e
    return list(ev_map.values())

def union_sources(existing: list["Source"], updates: list["Source"]) -> list["Source"]:
    src_map = {s["source_id"]: s for s in (existing or [])}
    url_index = {
        (s.get("url") or "").strip(): s["source_id"]
        for s in src_map.values()
        if (s.get("url") or "").strip()
    }
    for new_s in (updates or []):
        url = (new_s.get("url") or "").strip()
        if url and url in url_index:
            canonical_id = url_index[url]
            if new_s["source_id"] == canonical_id:
                src_map[canonical_id] = new_s
            continue
        sid = new_s["source_id"]
        src_map[sid] = new_s
        if url:
            url_index[url] = sid
    return list(src_map.values())
```

### 4.2 Entity Types
- `Source`: `source_id`, `title`, `publisher`, `date`, `url`, `source_type` (`paper`|`patent`|`web`), `source_tier` (`T1`|`T2`|`T3`|`T4`)
- `Evidence`: `evidence_id`, `source_id`, `snippet`
- `Claim`:
  - `id`: `{관점}-{번호}` (`DOM-01`~`12`, `MKT-01`~`08`, `STK-01`~`04`, `MAT-R01`~`R02`, `MAT-A01`~`A02`)
  - `perspective`: `maturity` | `market` | `stakeholder` | `domain`
  - `tech`: `"KIVI"` | `"CXL-PNM"`
  - `statement`: 문자열 (미확인 시 `""`)
  - `kind`: `fact` | `vendor_claim` | `simulation` | `estimate` (CXL-PNM은 반드시 `simulation`)
  - `evidence_ids`: `list[str]`
  - `counter_evidence_ids`: `list[str]`
  - `counter_searched`: `bool`
  - `status`: `ok` | `flagged` | `insufficient` | `rejected`
- `AuditIssue`: `claim_id`, `rule` (`R1`~`R5`), `issue`, `target_agent` (`paper`|`market`|`stakeholder`), `action` (`search_evidence`|`search_counter_evidence`|`re_extract`|`relabel`)
- `Audit`: `issues: list[AuditIssue]`
- `TRL`: `tech_trl`, `family_trl`, `confidence`, `fallback_reason`, `research_evidence`, `adoption_evidence`

### 4.3 OverallState (14개 키 및 담당 Writer 매핑)
```python
class OverallState(TypedDict):
    selected: dict                                 # [A] 입력 {sw, hw, families, rationale}
    tech_sw: dict                                  # [B] KIVI 메커니즘/수치/한계
    tech_hw: dict                                  # [B] CXL-PNM 메커니즘/수치/한계
    domain: dict                                   # [B] 도메인 6대 축 분석
    market: dict                                   # [C] 시장성 4대 축
    stakeholder: dict                              # [C] 4대 Actor 분석
    claims: Annotated[list[Claim], upsert_claims]  # [B, C, D(status)]
    evidence: Annotated[list[Evidence], upsert_evidence] # [B, C]
    sources: Annotated[list[Source], union_sources]      # [B, C]
    audit: Audit                                   # [D] 이슈 목록
    retry_count: dict[str, int]                    # [D] 관점별 재시도 카운터 (Overwrite)
    trl: dict[str, TRL]                            # [E] TRL 이원화
    synthesis: dict                                # [E] 일치/불일치, Gap, 트레이드오프
    report: str                                    # [E] 최종 보고서
```

---

## 5. LangGraph 토폴로지 및 라우팅 (`src/graph.py`)

### 5.1 그래프 구조
1. **Fan-out**: `START → paper_analysis` & `START → market_research` (병렬)
2. **Context Chaining**: `market_research → stakeholder_research`
3. **Fan-in**:
   - `stakeholder_research → evidence_audit` (정적 엣지)
   - `paper_analysis → route_after_paper`:
     - 첫 실행: `END` (paper 분기 정상 종료, market-stakeholder를 통해 합류)
     - 재시도 실행: `evidence_audit` (paper 이슈 처리 후 검증 재진입)
4. **Conditional Feedback Loop**:
   - `evidence_audit → route_audit_decision`:
     - 이슈 없음: `evaluation_synthesis`
     - 재시도 한도(2회) 소진: `evaluation_synthesis` (insufficient 확정)
     - `market` 대상: `market_research` (Cascade: market → stakeholder → audit)
     - `stakeholder` 단독: `stakeholder_research`
     - `paper` 대상: `paper_analysis`
5. **Report Pipeline**: `evaluation_synthesis → report_generation → END`

---

## 6. 역할별 모듈 스텁 및 방어적 Fallback 구현

- **Graceful Degradation**: OpenAI, Tavily API 키 부재 또는 네트워크 장애 시에도 파이프라인 Crash 없이 신뢰성 있는 Fallback 반환.
- **표준 로깅**: 모든 노드는 첫 줄에 표준 이모지 태그(`📄 [원문 분석]`, `📈 [시장성 조사]`, `👥 [이해관계자]`, `🛡️ [근거 검증]`, `⚖️ [평가 종합]`, `📝 [보고서 생성]`, `⚠️ [경고/Fallback]`, `✅ [성공/통과]`)를 출력.
- **보고서 8대 필수 목차 보장**:
  - `SUMMARY` (0.5페이지 이내, 승자 지정 금지)
  - `1. 분석 배경`
  - `2. 기술 선정`
  - `3. 기술 개요`
  - `4. 관점별 평가` (TRL 이원화 표 필수)
  - `5. 시사점` (트레이드오프 분석)
  - `6. 한계점` (Evidence Gap)
  - `REFERENCE` (실제 인용 출처)

---

## 7. 검증 및 테스트 계획 (TDD DoD)

스켈레톤 완성 시 아래 명령이 100% 통과(GREEN)되어야 한다:
```bash
# 가상환경 활성화 및 pytest 실행
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
pytest tests/ -v
python main.py
test -s final_evaluation_report.md
```

- `tests/test_smoke.py`: 6개 노드 조립 및 `main.py` 파이프라인 무결성 검증
- `tests/test_rag.py`: Claim 생성 및 KIVI/CXL-PNM kind/tier 검증
- `tests/test_research.py`: URL Tier 자동 분류 및 counter_searched 보장 검증
- `tests/test_audit.py`: R1~R4 정적 룰 결함 감지 및 action 매핑 검증
- `tests/test_synthesis.py`: TRL 이원화 계산 및 Jinja2 템플릿 8대 목차 검증
