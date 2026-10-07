"""State-driven control plane for the Hub-Spoke evaluation graph."""
from langgraph.graph import END

from src.audit.auditor import RETRY_LIMIT, finalize_retry_statuses
from src.orchestration.worker import MAX_WORKER_ATTEMPTS
from src.state import OverallState


DEFAULT_MAX_STEPS = 40
MAX_QUALITY_ROUNDS = 3
AGENT_NODE = {
    "paper": "paper_analysis",
    "market": "market_research",
    "stakeholder": "stakeholder_research",
}
DOWNSTREAM = {"evaluation_synthesis": "stale", "report_generation": "stale",
              "quality_evaluation": "stale"}


def _route(nodes: list[str], reason: str, updates: dict | None = None):
    updates = dict(updates or {})
    updates.update({"next_nodes": nodes, "route_reason": reason})
    status = dict(updates.get("node_status") or {})
    for node in nodes:
        if node != END:
            status[node] = "running"
    if status:
        updates["node_status"] = status
    return nodes, reason, updates


def _quality_issue(request: dict) -> dict:
    action = request.get("action", "search_evidence")
    return {
        "claim_id": request.get("claim_id", ""),
        "rule": "R3" if action == "search_counter_evidence" else "R1",
        "issue": request.get("reason", "quality rework"),
        "target_agent": request["target_agent"],
        "action": action,
    }


def _decide(state: OverallState):
    status = dict(state.get("node_status") or {})
    attempts = state.get("node_attempts") or {}
    retries = dict(state.get("retry_count") or {})

    if state.get("step_count", 0) >= state.get("max_steps", DEFAULT_MAX_STEPS):
        return _route([END], "max_steps_exhausted")

    skipped = {}
    for node, node_state in status.items():
        if node_state != "failed":
            continue
        if attempts.get(node, 0) < MAX_WORKER_ATTEMPTS:
            return _route([node], "worker_recovery")
        skipped[node] = "skipped"
        status[node] = "skipped"

    initial = [node for node in ("paper_analysis", "market_research")
               if status.get(node, "pending") == "pending"]
    if initial:
        return _route(initial, "initial_run", {"node_status": skipped})
    if (status.get("stakeholder_research", "pending") == "pending"
            and status.get("market_research") == "completed"):
        return _route(["stakeholder_research"], "initial_run", {"node_status": skipped})

    if (status.get("stakeholder_research") == "stale"
            and status.get("market_research") == "completed"):
        return _route(["stakeholder_research"], "dependency_refresh", {
            "node_status": {**skipped, "evidence_audit": "stale", **DOWNSTREAM},
            "audit": {"issues": []},
        })

    if status.get("evidence_audit", "pending") in {"pending", "stale"}:
        return _route(["evidence_audit"], "normal_progression",
                      {"node_status": skipped})

    issues = list((state.get("audit") or {}).get("issues") or [])
    if status.get("evidence_audit") == "completed" and issues:
        targets = [agent for agent in ("market", "paper", "stakeholder")
                   if any(issue.get("target_agent") == agent for issue in issues)]
        target = next((agent for agent in targets if retries.get(agent, 0) < RETRY_LIMIT), None)
        if target:
            retries[target] = min(RETRY_LIMIT, retries.get(target, 0) + 1)
            return _route([AGENT_NODE[target]], "audit_rework", {
                "retry_count": retries,
                "node_status": {**skipped, "evidence_audit": "stale", **DOWNSTREAM},
            })
        finalized = finalize_retry_statuses(state.get("claims") or [], issues, retries)
        terminal_updates = {"claims": finalized, "node_status": skipped}
    else:
        terminal_updates = {"node_status": skipped}

    if status.get("quality_evaluation") == "completed":
        quality = state.get("quality") or {}
        if quality.get("passed"):
            return _route([END], "quality_passed", terminal_updates)
        if state.get("quality_round", 0) >= MAX_QUALITY_ROUNDS:
            return _route([END], "quality_round_exhausted", terminal_updates)

        targets = quality.get("research_rework_targets") or []
        target = next((agent for agent in ("market", "paper", "stakeholder")
                       if agent in targets and retries.get(agent, 0) < RETRY_LIMIT), None)
        if target:
            retries[target] = min(RETRY_LIMIT, retries.get(target, 0) + 1)
            requests = [_quality_issue(request) for request in
                        quality.get("research_rework_requests", [])
                        if request.get("target_agent") == target]
            return _route([AGENT_NODE[target]], "quality_rework", {
                "retry_count": retries,
                "audit": {"issues": requests},
                "node_status": {**DOWNSTREAM, "evidence_audit": "stale"},
            })
        if quality.get("report_rewrite_required"):
            return _route(["report_generation"], "quality_report_rewrite", {
                "node_status": {"quality_evaluation": "stale"}})
        return _route([END], "quality_rework_exhausted", terminal_updates)

    if status.get("evaluation_synthesis", "pending") in {"pending", "stale"}:
        return _route(["evaluation_synthesis"], "normal_progression", terminal_updates)
    if status.get("report_generation", "pending") in {"pending", "stale"}:
        return _route(["report_generation"], "normal_progression", terminal_updates)
    if status.get("quality_evaluation", "pending") in {"pending", "stale"}:
        return _route(["quality_evaluation"], "normal_progression", terminal_updates)
    return _route([END], "workflow_complete", terminal_updates)


def decide_next(state: OverallState) -> list[str]:
    return _decide(state)[0]


def supervisor_node(state: OverallState) -> dict:
    routes, reason, updates = _decide(state)
    updates["step_count"] = state.get("step_count", 0) + 1
    print(f"🧭 [Supervisor] {reason}: {', '.join(routes)}")
    return updates


def route_supervisor(state: OverallState) -> list[str] | str:
    routes = state["next_nodes"]
    return routes[0] if len(routes) == 1 else routes
