"""Deterministic post-generation report quality gate."""
from src.state import OverallState

MAX_QUALITY_REWRITES = 1


def quality_evaluation_node(state: OverallState) -> dict:
    report = state.get("report", "")
    required_sections = ("SUMMARY", "REFERENCES")
    missing = [section for section in required_sections if section not in report.upper()]
    grounded = bool(state.get("claims")) and bool(state.get("evidence"))
    coverage = all((state.get("node_status") or {}).get(agent) == "complete" for agent in ("paper", "market", "stakeholder"))
    failures = ([] if grounded else ["groundedness"]) + ([] if coverage else ["coverage"]) + missing
    attempts = (state.get("quality") or {}).get("attempts", 0)
    return {"quality": {"passed": not failures, "failures": failures, "attempts": attempts + 1}}


def route_quality(state: OverallState) -> str:
    quality = state.get("quality") or {}
    if quality.get("passed") or quality.get("attempts", 0) > MAX_QUALITY_REWRITES:
        return "END"
    failures = set(quality.get("failures") or [])
    return "supervisor" if failures & {"groundedness", "coverage"} else "report_generation"
