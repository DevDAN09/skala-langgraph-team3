"""src/audit/auditor.py - evidence_audit_node"""
from src.state import OverallState, AuditIssue
from src.audit.rules import run_static_rules, TERMINAL_CLAIM_STATUSES
from src.audit import judge

# common.md §7①.4: "에이전트당 재시도 2회". The router (graph.py, owned by A) enforces
# this for re-routing, but it cannot write State — so D's audit node is the only place
# that can finalize a Claim's status once its target agent has exhausted the limit
# (issue #4 §1).
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

    # Kept in the return shape for reducer compatibility; Supervisor alone owns
    # increments when it dispatches a rework agent.
    result = {"audit": {"issues": issues}, "retry_count": dict(state.get("retry_count") or {})}

    # Patch claim status: `flagged` while the target agent still has retries left,
    # finalized to `insufficient`/`rejected` once that agent's retry_count (just
    # incremented above) has reached the limit (issue #4 §1).
    if issues:
        issue_by_claim = {issue["claim_id"]: issue for issue in issues}
        updated_claims = []
        for c in claims:
            issue = issue_by_claim.get(c.get("id"))
            if not issue or c.get("status") in TERMINAL_CLAIM_STATUSES:
                continue
            agent = issue["target_agent"]
            updated_claims.append({**c, "status": "flagged"})
        if updated_claims:
            result["claims"] = updated_claims

    return result


def finalize_retry_statuses(claims: list[dict], issues: list[dict], retry_count: dict[str, int]) -> list[dict]:
    """Finalize only after Supervisor actually dispatches the last retry."""
    issue_by_claim = {issue["claim_id"]: issue for issue in issues}
    return [
        {**claim, "status": _LIMIT_STATUS_BY_RULE.get(issue_by_claim[claim["id"]]["rule"], "insufficient")}
        if claim.get("id") in issue_by_claim and retry_count.get(issue_by_claim[claim["id"]]["target_agent"], 0) >= RETRY_LIMIT
        else claim
        for claim in claims
    ]
