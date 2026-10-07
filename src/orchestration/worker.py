"""Small worker boundary for status, attempts, and recoverable failures."""
from collections.abc import Callable

from src.state import OverallState


MAX_WORKER_ATTEMPTS = 3  # first call plus two recovery attempts

EXPECTED_OUTPUT = {
    "paper_analysis": "claims",
    "market_research": "claims",
    "stakeholder_research": "stakeholder",
    "evidence_audit": "audit",
    "evaluation_synthesis": "synthesis",
    "report_generation": "report",
    "quality_evaluation": "quality",
}


def wrap_worker(name: str, node: Callable[[OverallState], dict]):
    """Convert worker exceptions/invalid output into State for Supervisor recovery."""
    def wrapped(state: OverallState) -> dict:
        attempts = (state.get("node_attempts") or {}).get(name, 0) + 1
        try:
            result = node(state)
            if not isinstance(result, dict) or EXPECTED_OUTPUT[name] not in result:
                raise ValueError(f"missing required output: {EXPECTED_OUTPUT[name]}")
            control = {
                "node_status": {name: "completed"},
                "node_attempts": {name: attempts},
                "last_errors": {name: ""},
            }
            if name in {"paper_analysis", "market_research", "stakeholder_research"}:
                control["node_status"].update({
                    "evidence_audit": "stale",
                    "evaluation_synthesis": "stale",
                    "report_generation": "stale",
                    "quality_evaluation": "stale",
                })
            if (name == "market_research"
                    and state.get("route_reason") in {"audit_rework", "quality_rework"}
                    and (state.get("node_status") or {}).get("stakeholder_research") == "completed"):
                control["node_status"]["stakeholder_research"] = "stale"
            elif name == "evaluation_synthesis":
                control["node_status"].update({
                    "report_generation": "stale", "quality_evaluation": "stale"})
            elif name == "report_generation":
                control["node_status"]["quality_evaluation"] = "stale"
            return {**result, **control}
        except Exception as error:
            return {
                "node_status": {name: "failed"},
                "node_attempts": {name: attempts},
                "last_errors": {name: str(error)},
            }

    return wrapped
