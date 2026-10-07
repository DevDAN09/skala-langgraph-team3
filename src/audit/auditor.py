"""src/audit/auditor.py - evidence_audit_node"""
from src.state import OverallState, AuditIssue
from src.audit.rules import run_static_rules, TERMINAL_CLAIM_STATUSES
from src.audit import judge

# Retry is counted by Supervisor only when it dispatches actual rework.
RETRY_LIMIT = 2

# Terminal status a violated Claim is confirmed to once its target agent's retry_count
# reaches RETRY_LIMIT in this pass (issue #4 "작업 목표"): R1/R2 -> insufficient
# (근거 부족), R5 -> rejected (사실 불일치). R3/R4 have no design-specified limit
# status, so D adopts the issue's proposal of `insufficient`.
_LIMIT_STATUS_BY_RULE = {
    "R1": "insufficient",
    "R2": "insufficient",
    "R3": "insufficient",
    "R4": "insufficient",
    "R5": "rejected",
}


def evidence_audit_node(state: OverallState) -> dict:
    """Audits claims using 2-step Fast-Fail: R1~R4 static rules, then R5 Judge."""
    print("🛡️ [근거 검증] 1단계 정적 룰(R1~R4) 및 2단계 R5 검증 수행")

    claims = state.get("claims", [])
    sources = state.get("sources", [])
    evidence = state.get("evidence", [])

    # 1단계: 0ms 정적 룰 검사 (이미 insufficient/rejected로 확정된 Claim은 rules.py가 스킵)
    issues: list[AuditIssue] = run_static_rules(claims, sources, evidence)

    # 2단계: 1단계 정적 룰(R1~R4) 결함이 없는 정상 Claim들에 대해 R5 LLM Judge 사실성 검증 수행 (Claim 단위 Fast-Fail)
    flagged_claim_ids = {issue["claim_id"] for issue in issues}
    active_claims = [
        c for c in claims
        if c.get("status") not in TERMINAL_CLAIM_STATUSES and c.get("id") not in flagged_claim_ids
    ]
    if active_claims:
        stage2_issues = judge.run_llm_judge(active_claims, evidence)
        issues.extend(stage2_issues)

    result = {"audit": {"issues": issues}}

    # Audit detects problems but does not consume retry budget. Supervisor finalizes
    # unresolved claims only after two actual rework dispatches.
    if issues:
        issue_by_claim = {issue["claim_id"]: issue for issue in issues}
        updated_claims = []
        for c in claims:
            issue = issue_by_claim.get(c.get("id"))
            if not issue or c.get("status") in TERMINAL_CLAIM_STATUSES:
                continue
            updated_claims.append({**c, "status": "flagged"})
        if updated_claims:
            result["claims"] = updated_claims

    return result


def finalize_retry_statuses(claims: list[dict], issues: list[AuditIssue],
                            retry_count: dict[str, int]) -> list[dict]:
    """Finalize only issues whose responsible agent exhausted two dispatches."""
    by_claim = {issue["claim_id"]: issue for issue in issues}
    updates = []
    for claim in claims:
        issue = by_claim.get(claim.get("id"))
        if not issue or claim.get("status") in TERMINAL_CLAIM_STATUSES:
            continue
        if retry_count.get(issue["target_agent"], 0) >= RETRY_LIMIT:
            updates.append({**claim, "status": _LIMIT_STATUS_BY_RULE.get(
                issue["rule"], "insufficient")})
    return updates
