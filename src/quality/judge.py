"""src/quality/judge.py - 보고서 품질 평가 2단계: LLM Judge (1단계 규칙 통과 시에만 실행)

설계: docs/plans/2026-10-07-report-quality-eval-design.md 5절
"""
import re
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

from src.config import OPENAI_API_KEY
from src.state import OverallState, QualityItem
from src.quality import criteria

JUDGE_ITEMS = ("groundedness", "neutrality", "bias", "coverage")


class JudgeItem(BaseModel):
    score: int = Field(ge=1, le=5, description="기준표에 따른 1–5점")
    reason: str = Field(description="판정 이유 (한국어 1–2문장)")
    quotes: list[str] = Field(default_factory=list,
                              description="score < 5이면 문제 문장을 보고서에서 글자 그대로 인용")


class JudgeVerdict(BaseModel):
    groundedness: JudgeItem
    neutrality: JudgeItem
    bias: JudgeItem
    coverage: JudgeItem


RUBRIC = """채점 기준 (각 항목 1–5점, 4점 이상이 통과):
- groundedness: 5=모든 주장이 근거표 snippet 범위 안 / 4=근거 범위를 살짝 넘는 일반화 1건 / ≤3=근거표에 없는 사실·수치·인과 주장
- neutrality: 5=우열·추천 뉘앙스 0건 / 4=경미한 뉘앙스 1건(한쪽에만 긍정 형용사 등) / ≤3=명시적 추천, 결론이 한쪽으로 기움, 워크로드 조건 없는 단정
- bias: 5=두 기술 모두 장점과 한계를 근거와 함께 제시 / 4=한쪽 기술의 한계 서술이 상대적으로 얕음 / ≤3=근거표에 있는 불리한 근거(한계·반대 근거)를 누락·축소
- coverage: 5=기술 성숙도·시장성·이해관계자·도메인 4관점 모두 두 기술에 실질 내용 / 4=한 관점이 Gap 표기 위주지만 한계로 공개 / ≤3=관점이 형식만 있거나 Gap 공개 없이 빠짐"""

SYSTEM = f"""당신은 기술 평가 보고서의 품질 심사관이다. 이 보고서의 목적은 두 기술의 우열 판정이 아니라
관점별 근거 대조다. 보고서와 Claim 근거표를 보고 4개 항목을 채점한다.
3–4장은 템플릿이 Claim을 1:1로 옮긴 구간이므로 표본만 확인하고, LLM이 서술한 SUMMARY와 5장을 중점적으로 본다.
5점이 아닌 항목은 quotes에 문제 문장을 보고서에서 글자 그대로 복사해 넣는다. 보고서에 없는 문장을 지어내지 않는다.

{RUBRIC}"""


def _claim_table(state: OverallState) -> str:
    snippets = {e["evidence_id"]: e.get("snippet", "") for e in state.get("evidence", [])}
    ev_source = {e["evidence_id"]: e["source_id"] for e in state.get("evidence", [])}
    tier = {s["source_id"]: s.get("source_tier", "") for s in state.get("sources", [])}
    rows = ["ID | tech | perspective | kind | statement | snippet | tier"]
    for c in state.get("claims", []):
        if c.get("status") != "ok":
            continue
        ev = (c.get("evidence_ids") or [""])[0]
        rows.append(" | ".join([c["id"], c.get("tech", ""), c.get("perspective", ""), c.get("kind", ""),
                                c.get("statement", ""), snippets.get(ev, "")[:300], tier.get(ev_source.get(ev), "")]))
    return "\n".join(rows)


def _norm(text: str) -> str:
    return re.sub(r"[\s*_`>#-]+", " ", text).strip()


def _invalid_items(verdict: JudgeVerdict, report: str) -> list[str]:
    """미달 판정인데 인용이 없거나, 인용 문장이 보고서에 실제로 없는 항목."""
    body = _norm(report)
    bad = []
    for name in JUDGE_ITEMS:
        item = getattr(verdict, name)
        if item.score < criteria.JUDGE_PASS_SCORE and (
                not item.quotes or any(_norm(q) not in body for q in item.quotes)):
            bad.append(name)
    return bad


def run_quality_judge(report: str, state: OverallState) -> dict[str, QualityItem] | None:
    """항목별 Judge 결과. API 키가 없거나 호출이 실패하면 None (규칙 판정만 사용)."""
    if not OPENAI_API_KEY:
        return None
    messages = [("system", SYSTEM), ("human", f"[Claim 근거표]\n{_claim_table(state)}\n\n[보고서]\n{report}")]
    try:
        llm = ChatOpenAI(model=criteria.JUDGE_MODEL, temperature=0, seed=criteria.JUDGE_SEED,
                         api_key=OPENAI_API_KEY).with_structured_output(JudgeVerdict)
        verdict = llm.invoke(messages)
        invalid = _invalid_items(verdict, report)
        if invalid:  # 근거 인용 없는 미달 판정은 1회만 다시 묻는다
            verdict = llm.invoke(messages + [(
                "human", f"{invalid} 항목은 미달 판정의 quotes가 보고서 원문에 없다. 원문을 그대로 인용해 다시 채점하라.")])
            invalid = _invalid_items(verdict, report)
    except Exception as error:
        print(f"⚠️ [품질 평가 Judge Fallback] 호출 실패, 규칙 판정만 사용: {error}")
        return None

    items: dict[str, QualityItem] = {}
    for name in JUDGE_ITEMS:
        item = getattr(verdict, name)
        if name in invalid:  # 재질의 후에도 인용이 없으면 지어낸 지적으로 보고 무효 처리
            items[name] = {"passed": True, "score": item.score, "quotes": [],
                           "failures": [f"Judge/{name}: 인용 근거 없는 미달 판정({item.score}점)이라 무효 처리"]}
            continue
        passed = item.score >= criteria.JUDGE_PASS_SCORE
        items[name] = {"passed": passed, "score": item.score, "quotes": item.quotes if not passed else [],
                       "failures": [] if passed else [f"Judge/{name}({item.score}점): {item.reason}"]}
    return items
