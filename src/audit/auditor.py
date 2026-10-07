"""src/audit/auditor.py - evidence_audit_node, promoted to Supervisor."""
from src.state import OverallState, AuditIssue, SupervisorDecision
from src.audit.rules import run_static_rules, TERMINAL_CLAIM_STATUSES
from src.audit import judge

_AGENTS = ("paper", "market", "stakeholder")

# A repeated issue fingerprint is closed without a step count. R5 is a factual
# mismatch; every other rule is missing or unfit evidence.
_CLOSED_STATUS_BY_RULE = {
    "R1": "insufficient",
    "R2": "insufficient",
    "R3": "insufficient",
    "R4": "insufficient",
    "R5": "rejected",
}


def _collected(state: OverallState) -> dict[str, bool]:
    return {
        "paper": bool(state.get("tech_sw") or state.get("tech_hw") or state.get("domain")),
        "market": bool(state.get("market")),
        "stakeholder": bool(state.get("stakeholder")),
    }


def _fingerprint(issue: AuditIssue) -> str:
    return f"{issue['claim_id']}|{issue['rule']}|{issue['action']}"


def build_supervisor_decision(state: OverallState, issues: list[AuditIssue]) -> tuple[SupervisorDecision, list[dict]]:
    """Write the sufficiency judgment. The router reads only this decision."""
    collected = _collected(state)
    prior = list(((state.get("supervisor") or {}).get("dispatched")) or [])
    seen = set(prior)
    rework_agents: set[str] = set()
    repeated: dict[str, AuditIssue] = {}
    dispatched = list(prior)

    for issue in issues:
        agent = issue["target_agent"]
        if not collected.get(agent):
            continue
        fingerprint = _fingerprint(issue)
        if fingerprint in seen:
            repeated[issue["claim_id"]] = issue
            continue
        rework_agents.add(agent)
        if fingerprint not in dispatched:
            dispatched.append(fingerprint)

    collect = []
    if not collected["paper"]:
        collect.append("paper")
    if not collected["market"]:
        collect.append("market")
    elif not collected["stakeholder"]:
        collect.append("stakeholder")
    rework = [agent for agent in _AGENTS if agent in rework_agents]

    if collect and rework:
        reason = "collect missing perspectives and rework open issues"
    elif collect:
        reason = "missing perspectives"
    elif rework:
        reason = "rework open issues"
    elif repeated:
        reason = "repeated issue closed"
    else:
        reason = "evidence sufficient"

    decision: SupervisorDecision = {
        "sufficient": not collect and not rework,
        "collect": collect,
        "rework": rework,
        "reason": reason,
        "dispatched": dispatched,
    }

    issue_by_claim = {issue["claim_id"]: issue for issue in issues}
    claims = []
    for claim in state.get("claims", []):
        issue = issue_by_claim.get(claim.get("id"))
        if not issue or claim.get("status") in TERMINAL_CLAIM_STATUSES:
            continue
        if claim["id"] in repeated:
            status = _CLOSED_STATUS_BY_RULE.get(issue["rule"], "insufficient")
        elif issue["target_agent"] in rework_agents:
            status = "flagged"
        else:
            continue
        claims.append({**claim, "status": status})
    return decision, claims


def evidence_audit_node(state: OverallState) -> dict:
    """Supervisor: audit claims, then record which workers to call or whether to report."""
    print("🛡️ [Supervisor] 관점·근거 충분성 판단")

    claims = state.get("claims", [])
    sources = state.get("sources", [])
    evidence = state.get("evidence", [])
    issues: list[AuditIssue] = run_static_rules(claims, sources, evidence)
    flagged_claim_ids = {issue["claim_id"] for issue in issues}
    active_claims = [
        c for c in claims
        if c.get("status") not in TERMINAL_CLAIM_STATUSES and c.get("id") not in flagged_claim_ids
    ]
    if active_claims:
        issues.extend(judge.run_llm_judge(active_claims, evidence))

    decision, updated_claims = build_supervisor_decision(state, issues)
    result = {"audit": {"issues": issues}, "supervisor": decision}
    if updated_claims:
        result["claims"] = updated_claims
    return result
