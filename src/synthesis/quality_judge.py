"""보고서 품질 평가 2단계: LLM Judge (#72 3안 Hybrid, #76 일관성).

1단계 규칙(quality.py)은 State의 Claim·Evidence·Source만 본다. 보고서 생성 단계에서 생긴
근거 없는 서술, 정규식 밖의 우열 뉘앙스, 서술 편중, 절 사이의 모순은 본문을 읽어야 드러나므로
규칙을 통과한 보고서만 Judge가 기준표로 채점한다.
"""
import re

import langchain_openai
from pydantic import BaseModel, Field

from src.config import JUDGE_LLM_MODEL, OPENAI_API_KEY
from src.state import OverallState

JUDGE_ITEMS = ("groundedness", "neutrality", "bias_control", "coverage", "consistency")
PASS_SCORE = 4


class JudgeItem(BaseModel):
    score: int = Field(ge=1, le=5, description="기준표에 따른 1–5점")
    reason: str = Field(description="판정 이유 (한국어 1–2문장)")
    quotes: list[str] = Field(default_factory=list,
                              description="score < 4이면 문제 문장을 보고서에서 글자 그대로 인용")


class ReportVerdict(BaseModel):
    groundedness: JudgeItem
    neutrality: JudgeItem
    bias_control: JudgeItem
    coverage: JudgeItem
    consistency: JudgeItem


SYSTEM = """당신은 기술 평가 보고서의 품질 심사관이다. 이 보고서의 목적은 두 기술의 우열 판정이 아니라
관점별 근거 대조다. 보고서와 검증된 Claim 근거표를 보고 5개 항목을 1–5점으로 채점한다. 4점 이상이 통과다.

- groundedness: 5=모든 주장이 근거표 범위 안 / 4=근거를 살짝 넘는 일반화 1건 / ≤3=근거표에 없는 사실·수치·인과 주장
- neutrality: 5=우열·추천 뉘앙스 없음 / 4=한쪽에만 긍정 형용사 등 경미한 뉘앙스 1건 / ≤3=명시적 추천, 결론이 한쪽으로 기움, 워크로드 조건 없는 단정
- bias_control: 5=두 기술 모두 장점과 한계를 근거와 함께 제시 / 4=한쪽 한계 서술이 상대적으로 얕음 / ≤3=근거표에 있는 불리한 근거를 누락·축소
- coverage: 5=기술 성숙도·시장성·이해관계자·도메인 4관점 모두 두 기술에 실질 내용 / 4=한 관점이 Gap 공개 위주 / ≤3=관점이 형식만 있거나 Gap 공개 없이 빠짐
- consistency: 5=절 사이 모순 없음 / 4=표현 차이 수준의 경미한 불일치 1건 / ≤3=SUMMARY와 본문의 TRL·수치 불일치, 같은 기술에 대한 상반된 서술, simulation 수치를 실측처럼 서술

"근거 미확인", Evidence Gap 공개는 한계의 정직한 공개이므로 감점하지 않는다.
4점 미만 항목은 quotes에 문제 문장을 보고서에서 글자 그대로 복사해 넣는다. 보고서에 없는 문장을 지어내지 않는다."""


def _claim_table(state: OverallState) -> str:
    snippets = {e["evidence_id"]: e.get("snippet", "") for e in state.get("evidence", [])}
    rows = ["ID | tech | perspective | kind | statement | snippet"]
    for c in state.get("claims", []):
        if c.get("status") != "ok":
            continue
        ev = (c.get("evidence_ids") or [""])[0]
        rows.append(" | ".join([c["id"], c.get("tech", ""), c.get("perspective", ""), c.get("kind", ""),
                                c.get("statement", ""), snippets.get(ev, "")[:300]]))
    return "\n".join(rows)


def _norm(text: str) -> str:
    return re.sub(r"[\s*_`>#|-]+", " ", text).strip()


def _unquoted_failures(verdict: ReportVerdict, report: str) -> list[str]:
    """미달 판정인데 인용이 없거나, 인용 문장이 보고서에 실제로 없는 항목."""
    body = _norm(report)
    return [name for name in JUDGE_ITEMS
            if getattr(verdict, name).score < PASS_SCORE
            and (not getattr(verdict, name).quotes
                 or any(_norm(q) not in body for q in getattr(verdict, name).quotes))]


def run_report_judge(report: str, state: OverallState) -> dict | None:
    """항목별 Judge 결과. API 키가 없거나 호출이 실패하면 None (규칙 판정만 사용)."""
    if not OPENAI_API_KEY:
        return None
    messages = [("system", SYSTEM), ("human", f"[검증된 Claim 근거표]\n{_claim_table(state)}\n\n[보고서]\n{report}")]
    try:
        llm = langchain_openai.ChatOpenAI(model=JUDGE_LLM_MODEL, temperature=0, seed=0,
                                          api_key=OPENAI_API_KEY).with_structured_output(ReportVerdict)
        verdict = llm.invoke(messages)
        if not isinstance(verdict, ReportVerdict):
            return None
        unquoted = _unquoted_failures(verdict, report)
        if unquoted:  # 원문 인용 없는 미달 판정은 1회만 다시 묻는다
            retried = llm.invoke(messages + [(
                "human", f"{unquoted} 항목의 미달 판정 quotes가 보고서 원문에 없다. 원문을 그대로 인용해 다시 채점하라.")])
            if isinstance(retried, ReportVerdict):
                verdict = retried
                unquoted = _unquoted_failures(verdict, report)
    except Exception as error:
        print(f"⚠️ [품질 평가 Judge Fallback] 호출 실패, 규칙 판정만 사용: {error}")
        return None

    result = {}
    for name in JUDGE_ITEMS:
        item = getattr(verdict, name)
        voided = name in unquoted  # 재질의 후에도 인용이 없으면 지어낸 지적으로 보고 무효
        result[name] = {"score": item.score, "passed": voided or item.score >= PASS_SCORE,
                        "reason": item.reason, "quotes": [] if voided else item.quotes, "voided": voided}
    return result
