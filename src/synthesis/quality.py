"""Deterministic post-generation report quality gate."""
import re
from src.state import OverallState

MAX_QUALITY_ATTEMPTS = 2


def _neutral(report: str) -> bool:
    text = report.lower()
    forbidden = (r"\b\w+\s+is\s+(?:better|the best)\b", r"\bthe winner is\b", r"\w+를 추천한다", r"\w+(?:가|이).{0,12}더 우수하다")
    return not any(re.search(pattern, text) for pattern in forbidden)


def quality_evaluation_node(state: OverallState) -> dict:
    report = state.get("report", "")
    required_sections = ("SUMMARY", "REFERENCE")
    missing = [section for section in required_sections if section not in report.upper()]
    evidence = {item.get("evidence_id"): item for item in state.get("evidence", [])}
    sources = {item.get("source_id"): item for item in state.get("sources", [])}
    claims = state.get("claims", [])
    verified = [claim for claim in claims if claim.get("status") == "ok"]
    grounded = bool(verified) and all(claim.get("evidence_ids") and all(evidence.get(eid, {}).get("source_id") in sources for eid in claim["evidence_ids"]) for claim in verified)
    perspectives = {claim.get("perspective") for claim in claims}
    coverage = perspectives >= {"maturity", "market", "stakeholder", "domain"}
    neutrality = _neutral(report)
    counter_required = [claim for claim in claims if claim.get("perspective") in {"market", "stakeholder"} or claim.get("id", "").startswith("MAT-A")]
    bias_control = all(claim.get("counter_searched") for claim in counter_required)
    scores = {"groundedness": grounded, "neutrality": neutrality, "bias_control": bias_control, "coverage": coverage}
    failures = [key for key, passed in scores.items() if not passed] + missing
    rework_targets = set()
    owner = {"maturity": "paper", "domain": "paper", "market": "market", "stakeholder": "stakeholder"}
    for claim in verified:
        if not claim.get("evidence_ids") or not all(evidence.get(eid, {}).get("source_id") in sources for eid in claim["evidence_ids"]): rework_targets.add(owner.get(claim.get("perspective"), "paper"))
    for claim in counter_required:
        if not claim.get("counter_searched"): rework_targets.add(owner.get(claim.get("perspective"), "market"))
    for perspective, agent in owner.items():
        if perspective not in perspectives: rework_targets.add(agent)
    attempts = (state.get("quality") or {}).get("attempts", 0)
    return {"quality": {"passed": not failures, "scores": scores, "failures": failures, "rework_targets": sorted(rework_targets), "attempts": attempts + 1}}


def route_quality(state: OverallState) -> str:
    quality = state.get("quality") or {}
    if quality.get("passed") or quality.get("attempts", 0) >= MAX_QUALITY_ATTEMPTS:
        return "END"
    failures = set(quality.get("failures") or [])
    return "supervisor" if quality.get("rework_targets") or set(quality.get("failures", [])) & {"groundedness", "coverage", "bias_control"} else "report_generation"
