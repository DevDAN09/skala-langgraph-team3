"""Deterministic post-generation report quality gate."""
import re
from src.audit.auditor import RETRY_LIMIT
from src.state import OverallState

MAX_QUALITY_ATTEMPTS = 2


def _neutral(report: str) -> bool:
    text = report.lower()
    forbidden = (r"\b\w+\s+is\s+(?:better|the best)\b", r"\bthe winner is\b", r"\w+를 추천한다", r"\w+(?:가|이).{0,12}더 우수하다")
    return not any(re.search(pattern, text) for pattern in forbidden)


def _source_diversity_ok(claims: list[dict], evidence: dict, sources: dict) -> bool:
    """Require two verified external claims in one perspective to cite >1 source."""
    groups: dict[str, list[dict]] = {}
    for claim in claims:
        if claim.get("status") != "ok":
            continue
        if claim.get("id", "").startswith("MAT-A"):
            key = "MAT-A"
        elif claim.get("perspective") in {"market", "stakeholder"}:
            key = claim["perspective"]
        else:
            continue
        groups.setdefault(key, []).append(claim)
    for group in groups.values():
        if len(group) < 2:
            continue
        source_ids = {
            evidence[eid].get("source_id")
            for claim in group for eid in claim.get("evidence_ids", [])
            if eid in evidence and evidence[eid].get("source_id") in sources
        }
        if len(source_ids) <= 1:
            return False
    return True


def _coverage_gaps(verified: list[dict]) -> list[str]:
    gaps: list[str] = []
    for tech in ("KIVI", "CXL-PNM"):
        if not any(c.get("perspective") == "maturity" and c.get("tech") == tech for c in verified):
            gaps.append(f"maturity:{tech}")
        if not any(c.get("perspective") == "market" and c.get("tech") == tech for c in verified):
            gaps.append(f"market:{tech}")
        count = sum(c.get("perspective") == "domain" and c.get("tech") == tech for c in verified)
        if count < 3:
            gaps.append(f"domain:{tech}({count}/3)")
    valid_ids = {c.get("id") for c in verified}
    for actor, claim_ids in _ACTOR_CLAIMS.items():
        if not valid_ids.intersection(claim_ids):
            gaps.append(f"stakeholder:{actor}")
    return gaps


_GAP_OWNER = {"maturity": "paper", "market": "market", "domain": "paper", "stakeholder": "stakeholder"}
_ACTOR_CLAIMS = {
    "cloud_serving_operator": {"STK-01", "STK-05"},
    "framework_developer": {"STK-02", "STK-06"},
    "end_user": {"STK-03", "STK-07"},
    "memory_vendor": {"STK-04", "STK-08"},
}


def _claim_owner(claim_id: str) -> str | None:
    """MAT-A(채택 성숙도)는 market이, MAT-R(연구 성숙도)·DOM은 paper가 만든다."""
    for prefix, agent in (("MAT-A", "market"), ("MKT-", "market"), ("STK-", "stakeholder"), ("MAT-R", "paper"), ("DOM-", "paper")):
        if claim_id.startswith(prefix):
            return agent
    return None


def _gap_claim_ids(gap: str, claims: list[dict]) -> set[str]:
    """coverage gap 문자열(maturity:KIVI, domain:KIVI(2/3), stakeholder:end_user)에 해당하는 Claim ID."""
    perspective, _, rest = gap.partition(":")
    if perspective == "stakeholder":
        return _ACTOR_CLAIMS.get(rest, set())
    tech = rest.split("(")[0]
    return {c.get("id") for c in claims if c.get("perspective") == perspective and c.get("tech") == tech}


def _gap_owners(gap: str, claims: list[dict]) -> set[str]:
    """빈 칸을 채울 수 있는 연구 에이전트. 해당 칸의 Claim을 만든 에이전트를 우선한다."""
    owners = {_claim_owner(cid) for cid in _gap_claim_ids(gap, claims) if cid} - {None}
    return owners or {_GAP_OWNER[gap.partition(":")[0]]}


def _disclosed_after_retries(gaps: list[str], claims: list[dict], report: str, retry_count: dict) -> list[str]:
    """재수집 기회를 다 쓰고도 근거가 없어 6장 Evidence Gap에 공개된 칸.
    공개 근거가 없는 것은 편향이 아니라 한계이므로, 이 칸은 coverage 미달로 보지 않는다."""
    gap_text = report.split("## 6", 1)[1].split("## REFERENCE", 1)[0] if "## 6" in report else ""
    return [gap for gap in gaps
            if all(retry_count.get(owner, 0) >= RETRY_LIMIT for owner in _gap_owners(gap, claims))
            and any(cid and cid in gap_text for cid in _gap_claim_ids(gap, claims))]


def quality_evaluation_node(state: OverallState) -> dict:
    report = state.get("report", "")
    required_sections = ("SUMMARY", "REFERENCE")
    missing = [section for section in required_sections if section not in report.upper()]
    evidence = {item.get("evidence_id"): item for item in state.get("evidence", [])}
    sources = {item.get("source_id"): item for item in state.get("sources", [])}
    claims = state.get("claims", [])
    verified = [claim for claim in claims if claim.get("status") == "ok"]
    grounded = bool(verified) and all(claim.get("evidence_ids") and all(evidence.get(eid, {}).get("source_id") in sources for eid in claim["evidence_ids"]) for claim in verified)
    retry_count = state.get("retry_count") or {}
    coverage_gaps = _coverage_gaps(verified)
    disclosed_gaps = _disclosed_after_retries(coverage_gaps, claims, report, retry_count)
    coverage_gaps = [gap for gap in coverage_gaps if gap not in disclosed_gaps]
    coverage = not coverage_gaps
    neutrality = _neutral(report)
    # 반대 쿼리 수행(counter_searched)은 Supervisor 근거 검증 R3가 이미 보장한다. 여기서는 출처 다양성만 본다.
    diverse = _source_diversity_ok(claims, evidence, sources)
    scores = {"groundedness": grounded, "neutrality": neutrality, "bias_control": diverse, "coverage": coverage}
    failures = [key for key, passed in scores.items() if not passed] + missing
    rework_targets = set()
    owner = {"maturity": "paper", "domain": "paper", "market": "market", "stakeholder": "stakeholder"}
    for claim in verified:
        if not claim.get("evidence_ids") or not all(evidence.get(eid, {}).get("source_id") in sources for eid in claim["evidence_ids"]):
            rework_targets.add(_claim_owner(claim.get("id", "")) or owner.get(claim.get("perspective"), "paper"))
    if not diverse:
        rework_targets.update(_claim_owner(c.get("id", "")) or owner[c["perspective"]] for c in verified
                              if c.get("perspective") in {"market", "stakeholder"} or c.get("id", "").startswith("MAT-A"))
    for gap in coverage_gaps:
        rework_targets.update(_gap_owners(gap, claims))
    # 재시도 한도를 다 쓴 에이전트는 Supervisor가 고를 수 없으므로 재수집 요청에서 뺀다.
    exhausted = sorted(agent for agent in rework_targets if retry_count.get(agent, 0) >= RETRY_LIMIT)
    rework_targets -= set(exhausted)
    attempts = (state.get("quality") or {}).get("attempts", 0)
    return {"quality": {"passed": not failures, "scores": scores, "failures": failures,
                        "coverage_gaps": coverage_gaps, "disclosed_gaps": disclosed_gaps,
                        "rework_targets": sorted(rework_targets), "exhausted_targets": exhausted,
                        "attempts": attempts + 1}}
