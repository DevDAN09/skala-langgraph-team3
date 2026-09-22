"""src/audit/auditor.py - evidence_audit_node"""
from src.state import OverallState, AuditIssue
from src.audit.rules import run_static_rules
from src.audit import judge


def evidence_audit_node(state: OverallState) -> dict:
    """Audits claims using 2-step Fast-Fail: R1~R4 static rules, then R5 Judge."""
    print("🛡️ [근거 검증] 1단계 정적 룰(R1~R4) 및 2단계 R5 검증 수행")

    claims = state.get("claims", [])
    sources = state.get("sources", [])
    evidence = state.get("evidence", [])

    # 1단계: 0ms 정적 룰 검사
    issues: list[AuditIssue] = run_static_rules(claims, sources, evidence)

    # 1단계 위반이 없을 때만 2단계 R5 LLM Judge 실행 (Fast-Fail)
    if not issues:
        active_claims = [c for c in claims if c.get("status") == "ok"]
        stage2_issues = judge.run_llm_judge(active_claims, evidence)
        issues.extend(stage2_issues)

    # Update retry count for targeted agents
    retry_count = dict(state.get("retry_count", {"paper": 0, "market": 0, "stakeholder": 0}))
    for tgt in {issue["target_agent"] for issue in issues}:
        retry_count[tgt] = retry_count.get(tgt, 0) + 1

    result = {
        "audit": {"issues": issues},
        "retry_count": retry_count,
    }

    # Patch claim status for flagged claims
    if issues:
        flagged_ids = {issue["claim_id"] for issue in issues}
        updated_claims = []
        for c in claims:
            if c.get("id") in flagged_ids and c.get("status") == "ok":
                updated_claims.append({**c, "status": "flagged"})
        if updated_claims:
            result["claims"] = updated_claims

    return result
