"""src/audit/rules.py - Step 1: 0ms Fast-Fail Static Rules (R1~R4)"""
from src.state import Claim, Source, AuditIssue, Evidence


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
        # R1: kind=fact인데 evidence_ids가 비어있는 경우
        if c.get("kind") == "fact" and not c.get("evidence_ids"):
            issues.append({
                "claim_id": c["id"],
                "rule": "R1",
                "issue": "Fact kind without supporting evidence_ids",
                "target_agent": "paper" if c["perspective"] == "domain" else "market",
                "action": "search_evidence",
            })
            continue

        # R2: 출처가 T4 단독인 경우
        tiers = [source_tier_map.get(sid) for sid in c.get("evidence_ids", [])]
        if tiers and all(t == "T4" for t in tiers):
            issues.append({
                "claim_id": c["id"],
                "rule": "R2",
                "issue": "Solo Tier-4 unverified source citation",
                "target_agent": "stakeholder" if c["perspective"] == "stakeholder" else "market",
                "action": "search_evidence",
            })
            continue

        # R3: 외부 웹 조사인데 반대 쿼리 미수행
        if c["perspective"] in ["market", "stakeholder"] and not c.get("counter_searched"):
            issues.append({
                "claim_id": c["id"],
                "rule": "R3",
                "issue": "Missing counter-evidence search in market/stakeholder claim",
                "target_agent": "market" if c["perspective"] == "market" else "stakeholder",
                "action": "search_counter_evidence",
            })
            continue

        # R4: CXL-PNM 논문/시뮬레이션 수치를 fact로 표기한 경우
        if c["tech"] == "CXL-PNM" and c["perspective"] == "domain" and c.get("kind") == "fact":
            issues.append({
                "claim_id": c["id"],
                "rule": "R4",
                "issue": "CXL-PNM academic simulation numbers must use kind='simulation'",
                "target_agent": "paper",
                "action": "relabel",
            })
            continue

    return issues
