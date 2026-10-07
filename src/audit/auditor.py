"""src/audit/auditor.py - evidence_audit_node, promoted to Supervisor."""
from src.state import OverallState, AuditIssue, SupervisorDecision
from src.audit.rules import run_static_rules, TERMINAL_CLAIM_STATUSES
from src.audit import judge

_AGENTS = ("paper", "market", "stakeholder")
RETRY_LIMIT = 2
_EMPTY_RETRY = {"paper": 0, "market": 0, "stakeholder": 0}

# R5 is a factual mismatch; every other rule is missing or unfit evidence.
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


def build_supervisor_decision(state: OverallState, issues: list[AuditIssue]) -> tuple[SupervisorDecision, list[dict], dict]:
    """Write the sufficiency judgment. The router reads only this decision."""
    collected = _collected(state)
    status = dict(state.get("node_status") or {})
    retry = {**_EMPTY_RETRY, **(state.get("retry_count") or {})}
    prior = list(((state.get("supervisor") or {}).get("dispatched")) or [])
    dispatched = list(prior)
    rework_agents: set[str] = set()
    closed: dict[str, AuditIssue] = {}
    status_updates: dict[str, str] = {}

    def can_retry(agent: str) -> bool:
        return retry.get(agent, 0) < RETRY_LIMIT

    def dispatch(agent: str) -> None:
        if agent in rework_agents or not can_retry(agent):
            return
        rework_agents.add(agent)
        retry[agent] = retry.get(agent, 0) + 1

    for agent in _AGENTS:
        if status.get(agent) != "failed":
            continue
        if can_retry(agent):
            dispatch(agent)
        else:
            status[agent] = status_updates[agent] = "skipped"

    for issue in issues:
        agent = issue["target_agent"]
        if not collected.get(agent) or status.get(agent) == "skipped":
            continue
        fingerprint = _fingerprint(issue)
        if agent in rework_agents:
            if fingerprint not in dispatched:
                dispatched.append(fingerprint)
            continue
        if can_retry(agent):
            dispatch(agent)
            if fingerprint not in dispatched:
                dispatched.append(fingerprint)
        else:
            closed[issue["claim_id"]] = issue

    # market 재수집 전에 stakeholder를 돌리면 이전 벤더 컨텍스트를 본다. 이 턴은 stale만 남기고 다음 감사에서 갱신한다.
    defer_stakeholder = "market" in rework_agents and status.get("stakeholder") != "skipped"
    if defer_stakeholder:
        if "stakeholder" in rework_agents:
            rework_agents.remove("stakeholder")
            retry["stakeholder"] = max(0, retry.get("stakeholder", 0) - 1)
        status["stakeholder"] = status_updates["stakeholder"] = "stale"

    def needs_collect(agent: str) -> bool:
        if status.get(agent) in {"skipped", "failed"} or agent in rework_agents:
            return False
        if agent == "stakeholder" and defer_stakeholder:
            return False
        if status.get(agent) == "stale":
            return True
        return not collected[agent]

    collect = []
    if needs_collect("paper"):
        collect.append("paper")
    if needs_collect("market"):
        collect.append("market")
    elif collected["market"] and needs_collect("stakeholder"):
        collect.append("stakeholder")
    rework = [agent for agent in _AGENTS if agent in rework_agents]

    if collect and rework:
        reason = "collect missing perspectives and rework open issues"
    elif collect:
        reason = "missing perspectives"
    elif rework:
        reason = "rework open issues"
    elif closed or status_updates:
        reason = "retry limit reached"
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
        if claim["id"] in closed:
            claim_status = _CLOSED_STATUS_BY_RULE.get(issue["rule"], "insufficient")
        elif issue["target_agent"] in rework_agents:
            claim_status = "flagged"
        else:
            continue
        claims.append({**claim, "status": claim_status})

    extra = {"retry_count": retry}
    if status_updates:
        extra["node_status"] = status_updates
    return decision, claims, extra


def evidence_audit_node(state: OverallState) -> dict:
    """Supervisor: audit claims, then record which workers to call or whether to report."""
    print("🛡️ [Supervisor] 관점·근거 충분성 판단")

    claims = state.get("claims", [])
    sources = state.get("sources", [])
    evidence = state.get("evidence", [])
    seq = state.get("collect_seq") or 0
    audited = state.get("audited_seq", -1)
    if seq > audited:
        issues: list[AuditIssue] = run_static_rules(claims, sources, evidence)
        flagged_claim_ids = {issue["claim_id"] for issue in issues}
        active_claims = [
            c for c in claims
            if c.get("status") not in TERMINAL_CLAIM_STATUSES and c.get("id") not in flagged_claim_ids
        ]
        if active_claims:
            issues.extend(judge.run_llm_judge(active_claims, evidence))
    else:
        print(f"⏭️ [Supervisor] 신규 근거 없음 (collect_seq={seq}) → R1~R5 재감사 생략")
        issues = list((state.get("audit") or {}).get("issues") or [])

    decision, updated_claims, extra = build_supervisor_decision(state, issues)
    result = {"audit": {"issues": issues}, "supervisor": decision, "audited_seq": seq, **extra}
    if updated_claims:
        result["claims"] = updated_claims
    return result
