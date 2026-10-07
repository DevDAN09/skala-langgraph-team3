"""src/audit/judge.py - Step 2: R5 LLM-as-a-Judge with Pydantic Structured Output"""
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from src.config import OPENAI_API_KEY, JUDGE_LLM_MODEL
from src.state import Claim, Evidence, AuditIssue
from src.audit.rules import resolve_target_agent, TERMINAL_CLAIM_STATUSES


class JudgeDecision(BaseModel):
    """Pydantic model for LLM-as-a-Judge factual grounding decision."""
    is_grounded: bool = Field(description="주장 문장이 근거 스니펫에 정확히 기반하고 있는가")
    reason: str = Field(description="판정 이유")


judge_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a rigorous but fair academic fact-checker. "
        "Judge whether the statement is FACTUALLY grounded in the evidence snippet — "
        "judge substance, not wording.\n\n"
        "Do NOT mark is_grounded=false for surface-level differences that preserve the "
        "same fact: paraphrasing, synonyms, word order, unit/format differences "
        "(e.g. '2.6x' vs '260%' vs 'reduced by more than half'), or minor rounding.\n"
        "DO mark is_grounded=false when the statement contains a number, entity, or "
        "claim that is materially different from, absent in, or contradicted by the "
        "snippet, or when it asserts something the snippet does not state. "
        "Do not make assumptions or extrapolate beyond what is explicitly stated in the "
        "snippet.",
    ),
    (
        "human",
        "Statement: {statement}\n"
        "Evidence Snippet: {snippet}\n\n"
        "Verify factual grounding:",
    ),
])


# Supervisor는 worker가 돌아올 때마다 근거 검증을 다시 실행한다. 바뀌지 않은 Claim을 매번 다시
# 판정하면 호출 비용이 늘고 같은 입력의 판정이 흔들릴 수 있어, 성공한 판정만 입력 기준으로 재사용한다 (#77).
_verdict_cache: dict[tuple[str, str, str], JudgeDecision] = {}


def clear_judge_cache() -> None:
    _verdict_cache.clear()


def run_llm_judge(claims: list[Claim], evidence_list: list[Evidence]) -> list[AuditIssue]:
    """Runs Step 2 LLM-as-a-Judge on claims that passed Step 1 static rules."""
    issues: list[AuditIssue] = []
    if not OPENAI_API_KEY:
        return issues

    ev_map = {e["evidence_id"]: e["snippet"] for e in evidence_list}
    try:
        llm = ChatOpenAI(model=JUDGE_LLM_MODEL, temperature=0.0, api_key=OPENAI_API_KEY).with_structured_output(JudgeDecision)
    except Exception as e:
        print(f"⚠️ [Judge Fallback] LLM judge init skipped: {e}")
        return issues

    for c in claims:
        # Already finalized (limit exhausted or otherwise settled) -> never re-audit
        if c.get("status") in TERMINAL_CLAIM_STATUSES:
            continue

        # Skip claims with missing statement or evidence_ids
        if not c.get("statement") or not c.get("evidence_ids"):
            continue

        snippet = "\n".join(filter(None, (ev_map.get(eid, "") for eid in c["evidence_ids"])))
        if not snippet:
            continue

        key = (JUDGE_LLM_MODEL, c["statement"], snippet)
        try:
            result = _verdict_cache.get(key)
            if result is None:
                prompt_val = judge_prompt.format_messages(statement=c["statement"], snippet=snippet)
                result = llm.invoke(prompt_val)
                if isinstance(result, JudgeDecision):
                    _verdict_cache[key] = result
            if result and not result.is_grounded:
                issues.append({
                    "claim_id": c["id"],
                    "rule": "R5",
                    "issue": f"스니펫과 사실 불일치: {result.reason}",
                    "target_agent": resolve_target_agent(c.get("id"), c.get("perspective")),
                    "action": "re_extract",
                })
        except Exception as e:
            print(f"⚠️ [Judge Fallback] LLM judge invocation skipped for claim {c.get('id')}: {e}")
            continue

    return issues


def judge_claim_consistency(statement: str, snippet: str) -> bool:
    """Verifies that statement is strictly grounded in evidence snippet (backward-compatible)."""
    if not OPENAI_API_KEY or not statement or not snippet:
        return True
    try:
        llm = ChatOpenAI(model=JUDGE_LLM_MODEL, temperature=0.0, api_key=OPENAI_API_KEY).with_structured_output(JudgeDecision)
        prompt_val = judge_prompt.format_messages(statement=statement, snippet=snippet)
        result = llm.invoke(prompt_val)
        return result.is_grounded if result else True
    except Exception as e:
        print(f"⚠️ [Judge Fallback] LLM judge skipped: {e}")
        return True
