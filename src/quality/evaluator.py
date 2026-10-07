"""Deterministic report checks with an optional semantic LLM judge."""
import re

from pydantic import BaseModel, Field

from src.audit.rules import resolve_target_agent
from src.config import JUDGE_LLM_MODEL, OPENAI_API_KEY
from src.state import OverallState


class SemanticQuality(BaseModel):
    grounded: bool = Field(description="Report statements remain grounded in supplied claims")
    neutral: bool = Field(description="Report avoids winner or recommendation conclusions")
    problem_claim_ids: list[str] = Field(
        default_factory=list, description="Verified Claim IDs whose meaning is not preserved")
    feedback: list[str] = Field(default_factory=list)


def _neutral(report: str) -> bool:
    prohibited = (
        r"\b(?:the )?winner is\b",
        r"\b(?:KIVI|CXL-PNM)\s+is\s+(?:better|best|superior)\b",
        r"(?:KIVI|CXL-PNM)(?:을|를|이|가).{0,16}(?:추천한다|더 우수하다|승자다)",
    )
    return not any(re.search(pattern, report, re.I) for pattern in prohibited)


def _semantic_check(report: str, claims: list[dict]) -> SemanticQuality | None:
    if not OPENAI_API_KEY:
        return None


def _coverage_gaps(verified: list[dict]) -> tuple[set[str], list[str]]:
    """Require useful breadth while allowing evidence-backed gaps to remain gaps."""
    gaps: list[str] = []
    targets: set[str] = set()
    for tech in ("KIVI", "CXL-PNM"):
        if not any(c.get("perspective") == "maturity" and c.get("tech") == tech
                   for c in verified):
            gaps.append(f"maturity:{tech}")
            targets.add("paper")
        if not any(c.get("perspective") == "market" and c.get("tech") == tech
                   for c in verified):
            gaps.append(f"market:{tech}")
            targets.add("market")
        domain_count = sum(c.get("perspective") == "domain" and c.get("tech") == tech
                           for c in verified)
        if domain_count < 3:
            gaps.append(f"domain:{tech}({domain_count}/3)")
            targets.add("paper")

    actor_pairs = {
        "cloud_serving_operator": {"STK-01", "STK-05"},
        "framework_developer": {"STK-02", "STK-06"},
        "end_user": {"STK-03", "STK-07"},
        "memory_vendor": {"STK-04", "STK-08"},
    }
    valid_ids = {c.get("id") for c in verified}
    for actor, claim_ids in actor_pairs.items():
        if not valid_ids.intersection(claim_ids):
            gaps.append(f"stakeholder:{actor}")
            targets.add("stakeholder")
    return targets, gaps
    try:
        from langchain_openai import ChatOpenAI

        claim_text = "\n".join(
            f"[{claim.get('id')}] {claim.get('statement')}"
            for claim in claims if claim.get("status") == "ok"
        )
        prompt = (
            "Evaluate only semantic groundedness and neutrality. A neutral comparison may "
            "describe trade-offs, but must not declare a winner or recommendation. Return "
            "grounded=false only when the report adds factual conclusions absent from the "
            f"verified claims.\nVERIFIED CLAIMS:\n{claim_text}\nREPORT:\n{report}"
        )
        return ChatOpenAI(model=JUDGE_LLM_MODEL, temperature=0).with_structured_output(
            SemanticQuality).invoke(prompt)
    except Exception as error:
        print(f"⚠️ [Quality Fallback] semantic judge skipped: {error}")
        return None


def quality_evaluation_node(state: OverallState) -> dict:
    """Evaluate groundedness, neutrality, bias control, and perspective coverage."""
    report = state.get("report") or ""
    claims = state.get("claims") or []
    evidence = {item.get("evidence_id"): item for item in state.get("evidence") or []}
    sources = {item.get("source_id"): item for item in state.get("sources") or []}
    verified = [claim for claim in claims if claim.get("status") == "ok"]

    broken = [claim for claim in verified if not claim.get("evidence_ids") or any(
        evidence.get(eid, {}).get("source_id") not in sources
        for eid in claim.get("evidence_ids", [])
    )]
    grounded = bool(verified) and not broken

    coverage_targets, coverage_gaps = _coverage_gaps(verified)
    coverage = not coverage_gaps

    counter_required = [claim for claim in verified if claim.get("perspective") in {
        "market", "stakeholder"
    } or claim.get("id", "").startswith("MAT-A")]
    missing_counter = [claim for claim in counter_required if not claim.get("counter_searched")]
    bias_control = not missing_counter
    neutrality = _neutral(report)
    missing_sections = [name for name in ("SUMMARY", "REFERENCE") if name not in report.upper()]

    requests = []
    for claim in broken:
        requests.append({
            "claim_id": claim["id"], "target_agent": resolve_target_agent(
                claim.get("id"), claim.get("perspective")),
            "action": "search_evidence", "reason": "quality_groundedness",
        })
    for claim in missing_counter:
        requests.append({
            "claim_id": claim["id"], "target_agent": resolve_target_agent(
                claim.get("id"), claim.get("perspective")),
            "action": "search_counter_evidence", "reason": "quality_bias_control",
        })
    targets = {request["target_agent"] for request in requests}
    targets.update(coverage_targets)

    semantic = _semantic_check(report, verified)
    feedback = []
    if broken:
        feedback.append("ok Claim의 Evidence→Source 참조가 끊겨 있다.")
    if missing_counter:
        feedback.append("일부 시장/이해관계자 Claim에 반대 검색 기록이 없다.")
    if coverage_gaps:
        feedback.append(f"유효 Claim 범위 부족: {', '.join(coverage_gaps)}")
    if not neutrality:
        feedback.append("보고서에 승자·추천·우수성 표현이 있다.")
    if missing_sections:
        feedback.append(f"필수 섹션 누락: {', '.join(missing_sections)}")
    if semantic:
        grounded = grounded and semantic.grounded
        neutrality = neutrality and semantic.neutral
        feedback.extend(semantic.feedback)
        for claim_id in semantic.problem_claim_ids:
            claim = next((item for item in verified if item.get("id") == claim_id), None)
            if not claim:
                continue
            target = resolve_target_agent(claim_id, claim.get("perspective"))
            targets.add(target)
            requests.append({
                "claim_id": claim_id, "target_agent": target,
                "action": "re_extract", "reason": "quality_semantic_groundedness",
            })

    dimensions = {
        "groundedness": grounded,
        "neutrality": neutrality,
        "bias_control": bias_control,
        "perspective_coverage": coverage,
    }
    report_rewrite = not neutrality or bool(missing_sections)
    passed = all(dimensions.values()) and not missing_sections
    return {
        "quality": {
            "passed": passed,
            "dimension_results": dimensions,
            "research_rework_targets": sorted(targets),
            "research_rework_requests": requests,
            "report_rewrite_required": report_rewrite,
            "feedback": feedback,
            "judge": "hybrid" if semantic else "static_fallback",
        },
        "quality_round": state.get("quality_round", 0) + 1,
    }
