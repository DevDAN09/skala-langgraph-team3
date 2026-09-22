"""src/audit/rules.py - Step 1: 0ms Fast-Fail Static Rules (R1~R4)"""
from src.state import Claim, Source, AuditIssue, Evidence

# Claims whose status is already terminal must never be re-audited (issue #4 §2):
# a blank/unconfirmed slot from B's own gate (status="insufficient" from the start)
# or a claim D itself already finalized after the retry limit must be left alone.
TERMINAL_CLAIM_STATUSES = ("insufficient", "rejected")


def resolve_target_agent(claim_id: str | None, perspective: str | None) -> str:
    """Maps a Claim to the agent responsible for fixing it.

    Source of truth is the Claim ID prefix (design_checklist.md Claim ID table),
    since `perspective="maturity"` is shared by both B's `MAT-R*` and C's `MAT-A*`
    claims and cannot disambiguate on its own (issue #4 §3).

        DOM-*, MAT-R*  -> paper
        MKT-*, MAT-A*  -> market
        STK-*          -> stakeholder

    Falls back to `perspective` only for ids that don't follow that convention
    (e.g. ad-hoc ids used in unit tests).
    """
    cid = claim_id or ""
    if cid.startswith("DOM-") or cid.startswith("MAT-R"):
        return "paper"
    if cid.startswith("STK-"):
        return "stakeholder"
    if cid.startswith("MKT-") or cid.startswith("MAT-A"):
        return "market"

    if perspective == "domain":
        return "paper"
    if perspective == "stakeholder":
        return "stakeholder"
    return "market"


def run_static_rules(
    claims: list[Claim],
    sources: list[Source],
    evidence: list[Evidence] | None = None,
) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    source_tier_map = {s["source_id"]: s.get("source_tier", "T4") for s in sources}
    if evidence:
        for ev in evidence:
            sid = ev.get("source_id")
            eid = ev.get("evidence_id")
            if sid and eid and sid in source_tier_map and eid not in source_tier_map:
                source_tier_map[eid] = source_tier_map[sid]

    for c in claims:
        # Already finalized (limit exhausted or otherwise settled) -> never re-audit
        if c.get("status") in TERMINAL_CLAIM_STATUSES:
            continue

        claim_id = c["id"]
        perspective = c.get("perspective")
        target_agent = resolve_target_agent(claim_id, perspective)
        is_paper_side = perspective == "domain" or claim_id.startswith("MAT-R")
        is_market_side = perspective in ("market", "stakeholder") or claim_id.startswith("MAT-A")

        # R1: kind=fact인데 evidence_ids가 비어있는 경우
        if c.get("kind") == "fact" and not c.get("evidence_ids"):
            issues.append({
                "claim_id": claim_id,
                "rule": "R1",
                "issue": "Fact kind without supporting evidence_ids",
                "target_agent": target_agent,
                "action": "search_evidence",
            })
            continue

        # R2: 출처가 T4 단독인 경우. dedup 등으로 Source 참조가 끊겨 tier를 찾을 수
        # 없는 경우도 미검증 출처로 간주해 T4와 동일하게 취급한다 (issue #4 §4 R2).
        tiers = [source_tier_map.get(sid, "T4") for sid in c.get("evidence_ids", [])]
        if tiers and all(t == "T4" for t in tiers):
            issues.append({
                "claim_id": claim_id,
                "rule": "R2",
                "issue": "Solo Tier-4 unverified source citation",
                "target_agent": target_agent,
                "action": "search_evidence",
            })
            continue

        # R3: 외부 웹 조사(market/stakeholder)이거나 MAT 채택(MAT-A*)인데 반대 쿼리 미수행
        if is_market_side and not c.get("counter_searched"):
            issues.append({
                "claim_id": claim_id,
                "rule": "R3",
                "issue": "Missing counter-evidence search in market/stakeholder/MAT-adoption claim",
                "target_agent": target_agent,
                "action": "search_counter_evidence",
            })
            continue

        # R4a: CXL-PNM 논문/시뮬레이션 수치(B: domain, MAT-R*)를 fact로 표기한 경우
        if is_paper_side and c["tech"] == "CXL-PNM" and c.get("kind") == "fact":
            issues.append({
                "claim_id": claim_id,
                "rule": "R4",
                "issue": "CXL-PNM academic simulation numbers must use kind='simulation'",
                "target_agent": target_agent,
                "action": "relabel",
            })
            continue

        # R4b: 벤더 공식(T2) 수치(C: market/stakeholder, MAT-A*)를 fact로 표기한 경우
        if is_market_side and c.get("kind") == "fact":
            if "T2" in tiers:
                issues.append({
                    "claim_id": claim_id,
                    "rule": "R4",
                    "issue": "Vendor-sourced (T2) figures must use kind='vendor_claim'",
                    "target_agent": target_agent,
                    "action": "relabel",
                })
                continue

    return issues
