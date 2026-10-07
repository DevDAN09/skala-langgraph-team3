"""State-driven supervisor for research selection and evidence rework."""
from src.audit.auditor import RETRY_LIMIT, evidence_audit_node, finalize_retry_statuses
from src.state import OverallState

MAX_STEPS = 10
RESEARCH_AGENTS = ("paper", "market", "stakeholder")
NODE_NAMES = {
    "paper": "paper_analysis", "market": "market_research",
    "stakeholder": "stakeholder_research",
}


def _issues(state: OverallState) -> list[dict]:
    return list((state.get("audit") or {}).get("issues") or [])


def _dependency_satisfied(agent: str, status: dict[str, str]) -> bool:
    return agent != "stakeholder" or status.get("market") == "complete"


def _candidates(state: OverallState) -> list[str]:
    status = state.get("node_status") or {}
    retries = state.get("retry_count") or {}
    targeted = {issue.get("target_agent") for issue in _issues(state)} | set((state.get("quality") or {}).get("rework_targets") or [])
    candidates = []
    for agent in RESEARCH_AGENTS:
        needs_initial_run = status.get(agent, "pending") != "complete"
        needs_rework = agent in targeted and retries.get(agent, 0) < RETRY_LIMIT
        if (needs_initial_run or needs_rework) and _dependency_satisfied(agent, status):
            candidates.append(agent)
    return candidates


def select_agent(candidates: list[str], state: OverallState) -> str:
    """Choose from current evidence gaps; no static workflow sequence is encoded."""
    issues = _issues(state)
    issue_count = {agent: sum(issue.get("target_agent") == agent for issue in issues) for agent in candidates}
    status = state.get("node_status") or {}
    # More audit failures take priority.  Unvisited perspectives are selected
    # next; lexical tie-breaking makes an otherwise equal decision reproducible.
    return max(candidates, key=lambda agent: (issue_count[agent], status.get(agent) != "complete", agent))


def supervisor_node(state: OverallState) -> dict:
    """Audit evidence and select one eligible research agent or synthesis."""
    if state.get("step_count", 0) >= MAX_STEPS:
        return {"next_agent": "evaluation_synthesis"}

    audit_result = evidence_audit_node(state)
    audited = {**state, **audit_result}
    candidates = _candidates(audited)
    if not candidates:
        return {**audit_result, "next_agent": "evaluation_synthesis"}

    selected = select_agent(candidates, audited)
    targeted = {issue.get("target_agent") for issue in _issues(audited)}
    retry_count = dict(state.get("retry_count") or {})
    result = {**audit_result, "next_agent": NODE_NAMES[selected], "step_count": state.get("step_count", 0) + 1}
    if selected in targeted and (state.get("node_status") or {}).get(selected) == "complete":
        retry_count[selected] = retry_count.get(selected, 0) + 1
        result["retry_count"] = retry_count
        result["claims"] = finalize_retry_statuses(state.get("claims", []), _issues(audited), retry_count)
    quality = dict(state.get("quality") or {})
    if selected in quality.get("rework_targets", []):
        quality["rework_targets"] = [agent for agent in quality["rework_targets"] if agent != selected]
        result["quality"] = quality
    status = dict(state.get("node_status") or {})
    if selected == "market" and status.get("stakeholder") == "complete":
        status["stakeholder"] = "stale"
        result["node_status"] = status
    return result


def route_supervisor(state: OverallState) -> str:
    return state.get("next_agent", "evaluation_synthesis")
