"""Deterministic post-generation report quality gate."""
import re
from src.state import OverallState

MAX_QUALITY_ATTEMPTS = 2
TECHS = ("KIVI", "CXL-PNM")
OWNER = {"maturity": "paper", "domain": "paper", "market": "market", "stakeholder": "stakeholder"}


def _uncovered_cells(report: str, claims: list[dict]) -> list[str]:
    """(기술 × 관점) 8칸 중 검증된 근거도 없고 6장 Evidence Gap 공개도 없는 칸.
    공개 근거가 없는 것 자체는 편향이 아니라 한계이므로, 6장에 공개했으면 커버리지를 충족한 것으로 본다."""
    gap_text = report.split("## 6", 1)[1].split("## REFERENCE", 1)[0] if "## 6" in report else ""
    uncovered = []
    for perspective in OWNER:
        for tech in TECHS:
            cell = [c for c in claims if c.get("perspective") == perspective and c.get("tech") == tech]
            if any(c.get("status") == "ok" for c in cell) or any(c.get("id", "") in gap_text for c in cell if c.get("id")):
                continue
            uncovered.append(f"{tech}/{perspective}")
    return uncovered


def _format_failures(report: str) -> list[str]:
    """보고서 형식 오류: 전체가 코드블록으로 감싸짐, REFERENCE에 없는 인용 번호. 서술 문제라 보고서 재작성으로 보낸다."""
    failures = []
    if report.lstrip().startswith("```"):
        failures.append("FORMAT_CODE_FENCE")
    body, _, refs = report.partition("## REFERENCE")
    listed = set(re.findall(r"^\[(\d+)\]", refs, re.M))
    if refs and set(re.findall(r"\[(\d+)\]", body)) - listed:
        failures.append("DANGLING_CITATION")
    return failures


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
    uncovered = _uncovered_cells(report, claims)
    coverage = not uncovered
    neutrality = _neutral(report)
    counter_required = [claim for claim in claims if claim.get("perspective") in {"market", "stakeholder"} or claim.get("id", "").startswith("MAT-A")]
    bias_control = all(claim.get("counter_searched") for claim in counter_required)
    scores = {"groundedness": grounded, "neutrality": neutrality, "bias_control": bias_control, "coverage": coverage}
    failures = [key for key, passed in scores.items() if not passed] + missing + _format_failures(report)
    rework_targets = set()
    owner = OWNER
    for claim in verified:
        if not claim.get("evidence_ids") or not all(evidence.get(eid, {}).get("source_id") in sources for eid in claim["evidence_ids"]): rework_targets.add(owner.get(claim.get("perspective"), "paper"))
    for claim in counter_required:
        if not claim.get("counter_searched"): rework_targets.add(owner.get(claim.get("perspective"), "market"))
    for cell in uncovered:
        rework_targets.add(owner[cell.split("/")[1]])
    attempts = (state.get("quality") or {}).get("attempts", 0)
    return {"quality": {"passed": not failures, "scores": scores, "failures": failures, "rework_targets": sorted(rework_targets), "uncovered": uncovered, "attempts": attempts + 1}}


def route_quality(state: OverallState) -> str:
    quality = state.get("quality") or {}
    if quality.get("passed") or quality.get("attempts", 0) >= MAX_QUALITY_ATTEMPTS:
        return "END"
    failures = set(quality.get("failures") or [])
    return "supervisor" if quality.get("rework_targets") or set(quality.get("failures", [])) & {"groundedness", "coverage", "bias_control"} else "report_generation"
