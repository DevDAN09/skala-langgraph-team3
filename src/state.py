"""src/state.py - LangGraph Multi-Agent Global State Schema & Reducers"""
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

def merge_dict(existing: dict | None, updates: dict | None) -> dict:
    """병렬 하위 에이전트가 같은 dict 키(node_status 등)에 동시에 써도 깨지지 않도록 key 단위 병합."""
    return {**(existing or {}), **(updates or {})}

def keep_latest(existing: str | None, update: str | None) -> str | None:
    """병렬 실패 시 동시 쓰기 충돌 방지: None이 아닌 마지막 값만 남긴다."""
    return update if update is not None else existing

# 3. Layered State
# ── 제어 계층 (Supervisor 라우팅·종료·재개에 필요한 최소치) ──
# 결정 로그(사유 포함) 본문은 State에 쌓지 않고 외부 로거/LangSmith로 내보낸다.
# State에는 trace_id(상관 키)와 마지막 결정 사유 한 줄(route_reason)만 둔다.
class ControlState(TypedDict, total=False):
    trace_id: str                                         # 외부 로그·LangSmith trace와 잇는 상관 키
    next: list[str]                                       # Supervisor가 이번 턴에 보낼 하위 에이전트
    route_reason: str                                     # 마지막 라우팅 결정 사유 (덮어쓰기, 무한 증식 X)
    step_count: int                                       # Supervisor 턴 수 (종료 가드)
    max_steps: int                                        # Supervisor 턴 상한
    node_status: Annotated[dict[str, str], merge_dict]    # 하위 에이전트별 pending/done/failed/skipped
    node_attempts: Annotated[dict[str, int], merge_dict]  # 하위 에이전트 실패 재시도 횟수
    last_error: Annotated[str | None, keep_latest]
    quality_round: int                                    # 보고서 품질 평가 루프 횟수

# ── 페이로드 계층 (하위 에이전트 작업 결과) ──
class PayloadState(TypedDict, total=False):
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
    quality: dict                                         # 품질 평가 verdict (구조화)

class OverallState(PayloadState, ControlState, total=False):
    """그래프 전체 State = 페이로드 계층 + 제어 계층."""
