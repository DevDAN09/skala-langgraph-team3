# 📋 [담당 A] 시스템 아키텍트 & LangGraph 오케스트레이션 가이드

> **담당자**: 담당 A (팀장 / 시스템 아키텍트)  
> **핵심 임무**: 전체 State 스키마 정의, 멱등성 보장 Upsert Reducer 작성, LangGraph StateGraph 조립, 조건부 라우터(Cascade Chaining) 구현, Mock 데이터 제공 및 통합 테스트 리딩  
> ⚠️ **필독 공통 개발 룰**: 코딩 시작 전 [`tasks/common.md`](common.md)의 LangGraph 안티패턴(1.2.12) 및 TDD 가이드를 반드시 숙지하세요!  
> ✅ **설계서 대조 체크리스트**: 이 문서 [§7](#7-설계서-checklist-이-파일에서만-체크) (공통 항목 포함). 인덱스는 [`design_checklist.md`](design_checklist.md)

---

## 🎯 1. 개발 목표 및 마일스톤 (10:00 ~ 14:00)
- **10:00 ~ 10:30 (Phase 1)**: 팀원 환경 셋업 확인, `tests/test_smoke.py` 정상 구동 리딩
- **10:30 ~ 12:30 (Phase 2)**: `src/graph.py` 조건부 라우터(`route_audit_decision`) 및 Cascade Chaining 예외 처리 튜닝, 1차 통합 브랜치 준비
- **12:30 ~ 13:15 (Phase 3)**: 팀원 B, C, D, E 모듈을 순차 Merge하고 End-to-End `main.py` 실행 디버깅 리딩
- **13:15 ~ 14:00 (Phase 4 & 5)**: 검증 루프 재실행 동작 검수, 최종 보고서 확인 및 GitHub Push 완료

---

## 📁 2. 전담 파일 목록
- `src/state.py`: 전체 시스템 공통 State 및 Custom Upsert Reducer 정의
- `src/graph.py`: LangGraph StateGraph 빌더, 조건부 라우터, Cascade Chaining
- `tests/mock_data.py`: 팀원들이 독립 단위 테스트를 돌릴 수 있는 가짜 State 데이터
- `main.py`: 전체 시스템 실행 엔트리포인트

---

## 📥 3. State Schema & Reducer 명세 (`src/state.py`)

이 코드는 모든 팀원의 모듈이 참조하는 최상위 계약(Contract)입니다.

```python
"""src/state.py - LangGraph Multi-Agent Global State Schema"""
from typing import Annotated, TypedDict, Literal

# 1. Custom Upsert Reducers (재실행 시 멱등성 보장)
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
    for new_s in (updates or []):
        src_map[new_s["source_id"]] = new_s
    return list(src_map.values())

# 2. Entity Schemas
class Source(TypedDict):
    source_id: str
    title: str
    publisher: str
    date: str
    url: str
    source_type: Literal["paper", "patent", "web"]
    source_tier: Literal["T1", "T2", "T3", "T4"]

class Evidence(TypedDict):
    evidence_id: str
    source_id: str
    snippet: str

class Claim(TypedDict):
    id: str  # e.g., "DOM-01", "MKT-02", "STK-01", "MAT-01"
    perspective: Literal["maturity", "market", "stakeholder", "domain"]
    tech: str  # "KIVI", "CXL-PNM", or family name
    statement: str
    kind: Literal["fact", "vendor_claim", "simulation", "estimate"]
    evidence_ids: list[str]
    counter_evidence_ids: list[str]
    counter_searched: bool
    status: Literal["ok", "flagged", "insufficient", "rejected"]

class AuditIssue(TypedDict):
    claim_id: str
    rule: Literal["R1", "R2", "R3", "R4", "R5"]
    issue: str
    target_agent: Literal["paper", "market", "stakeholder"]
    action: Literal["search_evidence", "search_counter_evidence", "re_extract", "relabel"]

class Audit(TypedDict):
    issues: list[AuditIssue]

class TRL(TypedDict):
    tech_trl: str
    family_trl: str
    confidence: Literal["high", "medium", "low", "none"]
    fallback_reason: str | None
    research_evidence: list[str]
    adoption_evidence: list[str]

# 3. Overall State
class OverallState(TypedDict):
    selected: dict
    tech_sw: dict
    tech_hw: dict
    domain: dict
    market: dict
    stakeholder: dict
    claims: Annotated[list[Claim], upsert_claims]
    evidence: Annotated[list[Evidence], upsert_evidence]
    sources: Annotated[list[Source], union_sources]
    audit: Audit
    retry_count: dict[str, int]
    trl: dict[str, TRL]
    synthesis: dict
    report: str
```

---

## 🔀 4. LangGraph 라우터 및 빌더 (`src/graph.py`)

```python
"""src/graph.py - LangGraph Assembly & Conditional Router"""
from langgraph.graph import StateGraph, START, END
from src.state import OverallState
from src.rag.agentic_rag import paper_analysis_node
from src.research.market import market_research_node
from src.research.stakeholder import stakeholder_research_node
from src.audit.auditor import evidence_audit_node
from src.synthesis.evaluator import evaluation_synthesis_node
from src.synthesis.report_gen import report_generation_node

def route_audit_decision(state: OverallState):
    """조건부 표적 라우팅 및 Cascade Chaining"""
    issues = state.get("audit", {}).get("issues", [])
    retry_count = state.get("retry_count", {"paper": 0, "market": 0, "stakeholder": 0})
    
    if not issues:
        return "evaluation_synthesis"
    
    targets = set(issue["target_agent"] for issue in issues)
    valid_targets = [t for t in targets if retry_count.get(t, 0) < 2]
    
    if not valid_targets:
        return "evaluation_synthesis"
    
    # Cascade Chaining: market 재실행 시 stakeholder 연쇄 실행
    if "market" in valid_targets:
        return "market_research"
    if "stakeholder" in valid_targets:
        return "stakeholder_research"
    if "paper" in valid_targets:
        return "paper_analysis"
    
    return "evaluation_synthesis"

def route_after_paper(state: OverallState):
    """첫 실행은 END. paper 이슈가 남은 재시도만 검증으로 보낸다."""
    issues = state.get("audit", {}).get("issues") or []
    if any(issue.get("target_agent") == "paper" for issue in issues):
        return "evidence_audit"
    return END

def build_graph():
    builder = StateGraph(OverallState)
    builder.add_node("paper_analysis", paper_analysis_node)
    builder.add_node("market_research", market_research_node)
    builder.add_node("stakeholder_research", stakeholder_research_node)
    builder.add_node("evidence_audit", evidence_audit_node)
    builder.add_node("evaluation_synthesis", evaluation_synthesis_node)
    builder.add_node("report_generation", report_generation_node)
    
    # Fan-out
    builder.add_edge(START, "paper_analysis")
    builder.add_edge(START, "market_research")
    
    # Context Chaining
    builder.add_edge("market_research", "stakeholder_research")
    
    # Fan-in. add_edge 두 번은 합류가 아니다 (common.md 안티패턴 7).
    builder.add_edge("stakeholder_research", "evidence_audit")
    builder.add_conditional_edges(
        "paper_analysis",
        route_after_paper,
        {"evidence_audit": "evidence_audit", END: END},
    )
    
    # Conditional Loop
    builder.add_conditional_edges(
        "evidence_audit",
        route_audit_decision,
        {
            "paper_analysis": "paper_analysis",
            "market_research": "market_research",
            "stakeholder_research": "stakeholder_research",
            "evaluation_synthesis": "evaluation_synthesis"
        }
    )
    
    builder.add_edge("evaluation_synthesis", "report_generation")
    builder.add_edge("report_generation", END)
    return builder.compile()
```

---

## 🧪 5. 팀원 배포용 Mock 데이터 (`tests/mock_data.py`)

이 코드를 바로 작성하여 팀원들에게 전달하세요.

```python
"""tests/mock_data.py - Parallel Development Mock State"""
MOCK_STATE = {
    "selected": {
        "sw": "KIVI", "hw": "CXL-PNM",
        "families": {"sw": "KV Quantization", "hw": "CXL Memory Expansion"}
    },
    "tech_sw": {"name": "KIVI", "mechanism": "Asymmetric 2bit quantization (Key per-channel, Value per-token)"},
    "tech_hw": {"name": "CXL-PNM", "mechanism": "Near-memory processing inside CXL controller"},
    "domain": {"memory_footprint": "KIVI: 2.6x reduction, CXL-PNM: offloads to CXL DRAM"},
    "market": {"adoption": "vLLM evaluating 2bit", "barriers": "CXL needs new hardware server"},
    "stakeholder": {"cloud_ops": "KIVI is zero CAPEX, CXL has high initial hardware cost"},
    "claims": [
        {
            "id": "DOM-01", "perspective": "domain", "tech": "KIVI",
            "statement": "KIVI reduces KV cache memory footprint by up to 2.6x with 2-bit quantization.",
            "kind": "fact", "evidence_ids": ["EV-01"], "counter_evidence_ids": [],
            "counter_searched": False, "status": "ok"
        },
        {
            "id": "MKT-01", "perspective": "market", "tech": "CXL-PNM",
            "statement": "Samsung and SK Hynix commercialized CXL 2.0 memory modules.",
            "kind": "fact", "evidence_ids": ["EV-02"], "counter_evidence_ids": [],
            "counter_searched": True, "status": "ok"
        }
    ],
    "evidence": [
        {"evidence_id": "EV-01", "source_id": "SRC-01", "snippet": "Under 2-bit quantization, KIVI reduces KV cache size by 2.6x on Llama-2-70B."},
        {"evidence_id": "EV-02", "source_id": "SRC-02", "snippet": "Samsung announces mass production of CXL 2.0 DRAM in 2024."}
    ],
    "sources": [
        {"source_id": "SRC-01", "title": "KIVI Paper", "publisher": "ICML", "date": "2024", "url": "https://arxiv.org/abs/2402.02750", "source_type": "paper", "source_tier": "T1"},
        {"source_id": "SRC-02", "title": "Samsung Press Release", "publisher": "Samsung", "date": "2024", "url": "https://semiconductor.samsung.com", "source_type": "web", "source_tier": "T2"}
    ],
    "audit": {"issues": []},
    "retry_count": {"paper": 0, "market": 0, "stakeholder": 0}
}
```

---

## 7. 설계서 Checklist (이 파일에서만 체크)

Phase 2에 [`design_checklist.md`](design_checklist.md) / [`common.md`](common.md) 체크박스를 건드리지 마세요. Git 충돌입니다.

### 충돌 방지 — 담당 A만 수정
- `src/state.py`, `src/graph.py`, `main.py`, `tests/mock_data.py`, `tests/test_smoke.py`, `README.md`
- `src/config.py`: API 키·`DEFAULT_LLM_MODEL` / `JUDGE_LLM_MODEL` / `POLISHING_LLM_MODEL` 만. **`EMBEDDING_MODEL`은 B 벤치 확정 후 B가 한 줄만 수정**
- `src/rag/`, `src/research/`, `src/audit/`, `src/synthesis/` 비즈니스 로직을 직접 고쳐 넣지 않음 (머지는 import·엣지 연결만)
- Mock Claim은 `DOM-01`, `MKT-01` 수준. B/C의 ID 대역(`DOM-02+`, `MAT-R*`, `MKT-02+`, `STK-*`)을 바꾸지 않음

### 공통 (설계 1.4 · 3.7 · 3.8) — A 적용 범위: graph / state / main / mock / README
- [ ] 라우터·README·mock statement에 우열 판정·승자·추천 문장을 넣지 않았다
- [ ] 미래 전망·근거 없는 추측을 mock/그래프 주석에 넣지 않는다
- [ ] State 스키마의 `kind`/`status` Literal이 설계 3.7과 같다
- [ ] mock의 CXL-PNM 수치는 `kind=simulation` (사실로 넣지 않음)
- [ ] mock에 `insufficient` Claim을 넣더라도 보고서 본문 예시로 쓰지 않는다
- [ ] `OverallState`에 없는 키를 노드가 반환하도록 유도하지 않는다 (Interface Freeze)
- [ ] mock 수치에 모델 크기 등 실험 맥락이 있으면 유지한다
- [ ] 평가 도메인을 클라우드 서빙으로 고정. 온디바이스를 `selected`에 넣지 않는다

### State (5.4 / 부록 B)
- [ ] OverallState 14키: `selected`, `tech_sw`, `tech_hw`, `domain`, `market`, `stakeholder`, `claims`, `evidence`, `sources`, `audit`, `retry_count`, `trl`, `synthesis`, `report`
- [ ] `selected` = `{sw, hw, families, rationale}`. 조사 노드가 덮어쓰지 않게 그래프를 유지
- [ ] `upsert_claims` / `upsert_evidence` / `union_sources`(id+url)
- [ ] `audit` = `{issues}`만. `targets`는 라우터 로컬
- [ ] `retry_count` overwrite, 검증 노드만 증가하도록 그래프 유지
- [ ] 엔티티 필드 = 부록 B

### Graph (5.1 / 5.2)
- [ ] 노드 6개 이름 불변
- [ ] Fan-out: START → paper ∥ market
- [ ] Chain: market → stakeholder
- [ ] Fan-in: 첫 검증은 `stakeholder → evidence_audit` 한 번. `paper`의 정적 엣지로 검증에 넣지 않는다. paper 재시도만 `route_after_paper`
- [ ] 조건부 `route_audit_decision` + 한도 2회 탈출
- [ ] Cascade: market 재실행 시 stakeholder 연쇄. paper/stakeholder 단독은 그 노드만
- [ ] `main.py` non-interactive, `final_evaluation_report.md` 기록

### 통합 · 제출 직전 (A 리딩, 13:45)
- [ ] mock_data가 OverallState 키를 모두 채움
- [ ] Graph/State가 설계 5.1·부록 B와 같다
- [ ] `python main.py`가 크래시 없이 비어 있지 않은 보고서를 만든다
- [ ] README 목적·구조·실행·Retrieval(B 숫자 이관) 존재
- [ ] 남의 feat 브랜치 파일을 직접 고치지 않고 순차 merge만 했다
