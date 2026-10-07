"""src/quality/quality_eval.py - 보고서 생성 후 품질 평가 노드 (3안: Hybrid)

1단계 정적 룰: 4개 항목의 형식·구조 충족 여부를 결정적으로 검사한다 (재현성).
2단계 LLM Judge: 내용 수준을 1~5점 루브릭으로 판정한다 (API 키가 없으면 정적 룰만 사용).
항목별로 두 단계를 모두 통과해야 passed. 하나라도 미달이면 Supervisor가 피드백과 함께 보고서 재작성을 요청한다.
"""
import re
from collections import Counter

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from src.config import JUDGE_LLM_MODEL, OPENAI_API_KEY
from src.state import OverallState

ITEMS = ("groundedness", "neutrality", "bias_control", "coverage")
PASS_SCORE = 3

# 기술 우열·추천으로 읽히는 표현 (평가 목적 = 우열 판정 아님)
NEUTRALITY_PATTERNS = [
    r"우월", r"열등", r"압도", r"승자", r"패자", r"더\s*(낫|우수|뛰어나)", r"보다\s*(낫|우수|뛰어나)",
    r"추천(한다|합니다|함)", r"권장(한다|합니다|함)", r"선택해야", r"best\b", r"superior", r"\bwinner\b",
    r"\brecommend",
]
COVERAGE_SECTIONS = {
    "maturity": "### 4.1",
    "market": "### 4.2",
    "stakeholder": "### 4.3",
    "domain": "### 4.4",
}
REQUIRED_SECTIONS = ("## SUMMARY", "## REFERENCE")


def _body_and_refs(report: str) -> tuple[str, str]:
    head, _, refs = report.partition("## REFERENCE")
    return head, refs


def check_groundedness(report: str, state: OverallState) -> dict:
    body, refs = _body_and_refs(report)
    ref_count = len(re.findall(r"^\[\d+\]", refs, flags=re.M))
    cite_count = len(re.findall(r"\[\d+\]", body))
    ok_claims = [c for c in state.get("claims", []) if c.get("status") == "ok"]
    unsupported = [c["id"] for c in ok_claims if not c.get("evidence_ids")]
    passed = ref_count > 0 and cite_count > 0 and not unsupported
    return {"passed": passed,
            "reason": f"REFERENCE {ref_count}건, 본문 인용 {cite_count}건, 근거 없는 ok claim {unsupported}"}


def check_neutrality(report: str, state: OverallState) -> dict:
    body, _ = _body_and_refs(report)
    hits = sorted({m.group(0) for p in NEUTRALITY_PATTERNS for m in re.finditer(p, body, flags=re.I)})
    return {"passed": not hits, "reason": f"우열/추천 표현 {hits}" if hits else "우열/추천 표현 없음"}


def check_bias_control(report: str, state: OverallState) -> dict:
    """기술별로 ok claim 근거가 단일 출처에 쏠려 있지 않은지(출처 2개 이상, 최대 점유율 70% 이하) 확인."""
    ev_source = {e["evidence_id"]: e["source_id"] for e in state.get("evidence", [])}
    problems = []
    for tech in ("KIVI", "CXL-PNM"):
        used = [ev_source[eid] for c in state.get("claims", [])
                if c.get("tech") == tech and c.get("status") == "ok"
                for eid in c.get("evidence_ids", []) if eid in ev_source]
        if not used:
            problems.append(f"{tech}: 근거 없음")
            continue
        counts = Counter(used)
        share = counts.most_common(1)[0][1] / len(used)
        if len(counts) < 2 or share > 0.7:
            problems.append(f"{tech}: 출처 {len(counts)}개, 최대 점유율 {share:.0%}")
    counter_searched = sum(1 for c in state.get("claims", []) if c.get("counter_searched"))
    return {"passed": not problems,
            "reason": f"편중 {problems}, 반대근거 탐색 claim {counter_searched}건" if problems
            else f"출처 분산 충족, 반대근거 탐색 claim {counter_searched}건"}


def check_coverage(report: str, state: OverallState) -> dict:
    missing_sections = [s for s in REQUIRED_SECTIONS if s not in report]
    missing_sections += [h for h in COVERAGE_SECTIONS.values() if h not in report]
    perspectives = {c.get("perspective") for c in state.get("claims", []) if c.get("status") == "ok"}
    missing_views = [p for p in COVERAGE_SECTIONS if p not in perspectives]
    return {"passed": not missing_sections and not missing_views,
            "reason": f"누락 목차 {missing_sections}, 검증된 claim 없는 관점 {missing_views}"}


class ItemScore(BaseModel):
    score: int = Field(ge=1, le=5, description="1(매우 미흡)~5(매우 우수)")
    reason: str = Field(description="판정 근거 한두 문장")
    fix: str = Field(description="미흡할 때 보고서에서 고쳐야 할 점. 충분하면 빈 문자열")


class QualityJudgement(BaseModel):
    groundedness: ItemScore = Field(description="주장이 본문 인용 [n]과 REFERENCE 출처로 추적되는가")
    neutrality: ItemScore = Field(description="특정 기술 추천·우열 판정 없이 서술하는가")
    bias_control: ItemScore = Field(description="단일 출처·유리한 근거 편중 없이 반대 근거와 한계를 함께 다루는가")
    coverage: ItemScore = Field(description="기술 성숙도·시장성·이해관계자·도메인 적용 4개 관점을 모두 다루는가")


JUDGE_PROMPT = """당신은 기술 평가 보고서의 품질 심사위원입니다. 아래 보고서를 4개 항목에 대해 1~5점으로 엄격하게 채점하십시오.
- groundedness: 주장이 본문 인용 번호와 REFERENCE 출처로 추적되는가 (Hallucination 통제)
- neutrality: 특정 기술을 추천하거나 우열을 판정하지 않는가 (평가 목적은 우열 판정이 아님)
- bias_control: 단일 출처나 유리한 근거에 편중되지 않고 반대 근거·한계를 함께 다루는가 (확증편향 방지)
- coverage: 기술 성숙도, 시장성, 이해관계자, 도메인 적용 4개 관점을 모두 포괄하는가
3점 미만이면 fix에 구체적인 수정 지시를 쓰십시오.

[보고서]
{report}"""


def llm_judge(report: str) -> QualityJudgement | None:
    if not OPENAI_API_KEY:
        return None
    try:
        llm = ChatOpenAI(model=JUDGE_LLM_MODEL, temperature=0).with_structured_output(QualityJudgement)
        return llm.invoke(JUDGE_PROMPT.format(report=report))
    except Exception as error:
        print(f"⚠️ [경고/Fallback] 품질 평가 LLM Judge 호출 실패, 정적 룰만 사용: {error}")
        return None


def quality_eval_node(state: OverallState) -> dict:
    round_no = state.get("quality_round", 0) + 1
    print(f"🔎 [품질 평가 #{round_no}] Groundedness·중립성·편향 통제·관점 커버리지 (정적 룰 + LLM Judge)")
    report = state.get("report") or ""
    rules = {item: globals()[f"check_{item}"](report, state) for item in ITEMS}
    # Fast-fail: a static miss does not spend a judge call.
    judgement = llm_judge(report) if all(rule["passed"] for rule in rules.values()) else None

    checks, feedback = {}, []
    for item in ITEMS:
        rule = rules[item]
        llm = getattr(judgement, item) if judgement else None
        passed = rule["passed"] and (llm is None or llm.score >= PASS_SCORE)
        checks[item] = {
            "passed": passed,
            "rule_passed": rule["passed"],
            "rule_reason": rule["reason"],
            "llm_score": llm.score if llm else None,
            "llm_reason": llm.reason if llm else None,
        }
        if not rule["passed"]:
            feedback.append(f"[{item}] {rule['reason']}")
        if llm and llm.score < PASS_SCORE and llm.fix:
            feedback.append(f"[{item}] {llm.fix}")

    passed = all(c["passed"] for c in checks.values())
    print(f"   → {'통과' if passed else '미달'}: " + ", ".join(f"{k}={'O' if v['passed'] else 'X'}" for k, v in checks.items()))
    return {
        "quality": {"passed": passed, "round": round_no, "judge": "hybrid" if judgement else "rule_only",
                    "checks": checks, "feedback": feedback},
        "quality_round": round_no,
    }
