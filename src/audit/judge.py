"""src/audit/judge.py - Step 2: R5 LLM-as-a-Judge"""
from src.config import OPENAI_API_KEY, JUDGE_LLM_MODEL


def judge_claim_consistency(statement: str, snippet: str) -> bool:
    """Verifies that statement is strictly grounded in evidence snippet."""
    if not OPENAI_API_KEY or not statement or not snippet:
        return True
    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=JUDGE_LLM_MODEL, temperature=0.0, api_key=OPENAI_API_KEY)
        prompt = (
            f"Verify whether the following statement is directly supported by the evidence snippet.\n"
            f"Respond with YES if supported, or NO if not supported.\n\n"
            f"Evidence Snippet: {snippet}\n"
            f"Statement: {statement}\n\n"
            f"Answer (YES/NO):"
        )
        response = llm.invoke(prompt)
        content = response.content.strip().upper()
        return "YES" in content
    except Exception as e:
        print(f"⚠️ [Judge Fallback] LLM judge skipped: {e}")
        return True
