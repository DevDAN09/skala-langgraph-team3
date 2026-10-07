"""src/state.py - LangGraph Multi-Agent Global State Schema & Reducers"""
import operator
from typing import Annotated, TypedDict, Literal

# 1. Entity Schemas
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
    id: str  # e.g., "DOM-01", "MKT-01", "STK-01", "MAT-R01", "MAT-A01"
    perspective: Literal["maturity", "market", "stakeholder", "domain"]
    tech: str  # "KIVI" | "CXL-PNM"
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

class QualityItem(TypedDict):
    passed: bool
    score: int | None        # LLM Judge 점수 1–5. 규칙만 본 항목은 None
    failures: list[str]      # "G1: …" 형식의 실패 규칙과 사유
    quotes: list[str]        # Judge가 지목한 문제 문장 원문

class ReportEval(TypedDict):
    passed: bool
    stage: Literal["rules", "judge"]   # 판정이 끝난 단계 (규칙 실패 시 Judge 생략)
    items: dict[str, QualityItem]      # groundedness | neutrality | bias | coverage | format
    collect_agents: list[str]          # 근거 부족(C5·B2)으로 재수집이 필요한 관점. 재작업 대상 결정은 Supervisor가 한다
    feedback: str                      # report_generation 프롬프트에 넣을 수정 지시

# 2. Custom Upsert Reducers (멱등성 보장)
def upsert_claims(existing: list[Claim], updates: list[Claim]) -> list[Claim]:
    claim_map = {c["id"]: c for c in (existing or [])}
    for new_c in (updates or []):
        claim_map[new_c["id"]] = new_c
    return list(claim_map.values())

def upsert_evidence(existing: list[Evidence], updates: list[Evidence]) -> list[Evidence]:
    ev_map = {e["evidence_id"]: e for e in (existing or [])}
    for new_e in (updates or []):
        ev_map[new_e["evidence_id"]] = new_e
    return list(ev_map.values())

def union_sources(existing: list[Source], updates: list[Source]) -> list[Source]:
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

def merge_dict(existing: dict, updates: dict) -> dict:
    """병렬 노드가 같은 dict 키(node_status, last_error)에 동시에 써도 InvalidUpdateError 없이 병합한다."""
    return {**(existing or {}), **(updates or {})}

# 3. Overall State (페이로드 15개 + 제어 메타 7개)
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
    report_eval: ReportEval | None     # 보고서 품질 평가 최신 판정 (overwrite, 이력은 트레이스)

    # ── 제어 메타 (Supervisor 라우팅·종료·재개용 최소 상태. 본문 데이터는 넣지 않는다)
    run_id: str                                          # 외부 트레이스(LangSmith)와 잇는 상관 키
    step_count: int                                      # Supervisor 방문 횟수, 종료 가드 (Supervisor만 씀)
    node_status: Annotated[dict[str, str], merge_dict]   # pending|done|stale|failed|skipped
    collect_seq: Annotated[int, operator.add]            # 수집 노드가 끝날 때마다 +1 (병렬 합산)
    audited_seq: int                                     # Supervisor가 검증한 시점의 collect_seq
    last_decision: dict                                  # {"next", "reason"} 직전 라우팅 결정. 이력은 트레이스에 남는다
    last_error: Annotated[dict[str, str], merge_dict]    # 노드별 마지막 실패 사유
