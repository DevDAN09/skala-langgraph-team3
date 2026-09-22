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
    id: str  # e.g., "DOM-01", "MKT-01", "STK-01", "MAT-01"
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

# 3. Overall State (14개 키)
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
