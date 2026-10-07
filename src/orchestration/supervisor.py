"""Deterministic Supervisor decisions for the multi-agent evaluation workflow."""
from langgraph.graph import END

from src.audit.auditor import RETRY_LIMIT
from src.state import OverallState

_RETRY_NODE = {
    "paper": "paper_analysis",
    "market": "market_research",
    "stakeholder": "stakeholder_research",
}
_RESEARCH_NODES = set(_RETRY_NODE.values())


def _paper_ready(state: OverallState) -> bool:
    return bool(state.get("tech_sw") and state.get("tech_hw") and state.get("domain"))


def _retry_routes(state: OverallState) -> list[str]:
    issues = (state.get("audit") or {}).get("issues") or []
    counts = state.get("retry_count") or {}
    targets = {issue.get("target_agent") for issue in issues}
    available = {target for target in targets
                 if target in _RETRY_NODE and counts.get(target, 0) < RETRY_LIMIT}

    routes = []
    if "market" in available:
        routes.append("market_research")
    elif "stakeholder" in available:
        routes.append("stakeholder_research")
    if "paper" in available:
        routes.append("paper_analysis")
    return routes


def decide_next(state: OverallState) -> list[str]:
    """Choose the next worker(s) from current payload, audit result, and retry budget."""
    if state.get("report"):
        return [END]
    if state.get("synthesis"):
        return ["report_generation"]

    initial = []
    if not _paper_ready(state):
        initial.append("paper_analysis")
    if not state.get("market"):
        initial.append("market_research")
    if initial:
        return initial
    if not state.get("stakeholder"):
        return ["stakeholder_research"]

    audit = state.get("audit") or {}
    previous = set(state.get("supervisor_route") or [])
    if "issues" not in audit:
        return ["evidence_audit"]

    # Market refreshes the context consumed by stakeholder research.
    if audit.get("issues") and "market_research" in previous:
        return ["stakeholder_research"]
    if previous & _RESEARCH_NODES:
        return ["evidence_audit"]

    if not audit.get("issues"):
        return ["evaluation_synthesis"]
    return _retry_routes(state) or ["evaluation_synthesis"]


def supervisor_node(state: OverallState) -> dict:
    routes = decide_next(state)
    print(f"🧭 [Supervisor] 다음 실행: {', '.join(routes)}")
    return {"supervisor_route": routes}


def route_supervisor(state: OverallState) -> list[str] | str:
    routes = state["supervisor_route"]
    return routes[0] if len(routes) == 1 else routes
