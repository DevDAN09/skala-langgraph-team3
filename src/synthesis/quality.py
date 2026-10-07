"""Deterministic post-generation report quality gate."""
from src.state import OverallState

MAX_QUALITY_REWRITES = 1


def quality_evaluation_node(state: OverallState) -> dict:
    report = state.get("report", "")
    required_sections = ("SUMMARY", "REFERENCES")
    missing = [section for section in required_sections if section not in report.upper()]
    evidence = {item.get("evidence_id"): item for item in state.get("evidence", [])}
    sources = {item.get("source_id"): item for item in state.get("sources", [])}
    claims = state.get("claims", [])
    grounded = bool(claims) and all(all(evidence.get(eid, {}).get("source_id") in sources for eid in claim.get("evidence_ids", [])) and claim.get("evidence_ids") for claim in claims)
    coverage = {p for p in (claim.get("perspective") for claim in claims)} >= {"maturity", "market", "stakeholder", "domain"}
    neutrality = not any(word in report.lower() for word in ("winner", "recommend", "better", "best", "우월", "추천"))
    bias_control = all(claim.get("counter_searched") and (claim.get("counter_evidence_ids") or len({evidence[eid].get("source_id") for eid in claim.get("evidence_ids", []) if eid in evidence}) > 1) for claim in claims)
    scores = {"groundedness": grounded, "neutrality": neutrality, "bias_control": bias_control, "coverage": coverage}
    failures = [key for key, passed in scores.items() if not passed] + missing
    rework_targets = []
    if not grounded: rework_targets.append("paper")
    if not bias_control or not coverage: rework_targets.append("market")
    attempts = (state.get("quality") or {}).get("attempts", 0)
    return {"quality": {"passed": not failures, "scores": scores, "failures": failures, "rework_targets": rework_targets, "attempts": attempts + 1}}


def route_quality(state: OverallState) -> str:
    quality = state.get("quality") or {}
    if quality.get("passed") or quality.get("attempts", 0) > MAX_QUALITY_REWRITES:
        return "END"
    failures = set(quality.get("failures") or [])
    return "supervisor" if quality.get("rework_targets") or set(quality.get("failures", [])) & {"groundedness", "coverage", "bias_control"} else "report_generation"
