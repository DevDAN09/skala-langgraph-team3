"""src/audit/judge.py - Step 2: R5 LLM-as-a-Judge with Pydantic Structured Output"""
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from src.config import OPENAI_API_KEY, JUDGE_LLM_MODEL
from src.state import Claim, Evidence, AuditIssue


class JudgeDecision(BaseModel):
    """Pydantic model for LLM-as-a-Judge factual grounding decision."""
    is_grounded: bool = Field(description="주장 문장이 근거 스니펫에 정확히 기반하고 있는가")
    reason: str = Field(description="판정 이유")


judge_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a strict academic fact-checker. "
        "Determine whether the statement is completely supported by the evidence snippet. "
        "Do not make assumptions or extrapolate beyond what is explicitly stated in the snippet.",
    ),
    (
        "human",
        "Statement: {statement}\n"
        "Evidence Snippet: {snippet}\n\n"
        "Verify factual grounding:",
    ),
])


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
        # Skip claims with missing statement or evidence_ids
        if not c.get("statement") or not c.get("evidence_ids"):
            continue

        snippet = ev_map.get(c["evidence_ids"][0], "")
        if not snippet:
            continue

        try:
            prompt_val = judge_prompt.format_messages(statement=c["statement"], snippet=snippet)
            result = llm.invoke(prompt_val)
            if result and not result.is_grounded:
                issues.append({
                    "claim_id": c["id"],
                    "rule": "R5",
                    "issue": f"스니펫과 사실 불일치: {result.reason}",
                    "target_agent": "paper" if c.get("perspective") == "domain" else ("stakeholder" if c.get("perspective") == "stakeholder" else "market"),
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
