"""src/synthesis/evaluator.py - Synthesis node & Dual TRL evaluation"""
from src.state import OverallState, TRL

def evaluate_trl(tech: str, claims: list[dict]) -> TRL:
    """Derive dual TRL from verified research and adoption claims for one technology."""
    verified = [claim for claim in claims if claim.get("tech") == tech and claim.get("status") == "ok"]
    research = [claim for claim in verified if claim.get("perspective") in {"domain", "maturity"}]
    adoption = [claim for claim in verified if claim.get("perspective") == "market"]

    if not verified:
        return {
            "tech_trl": "Unknown",
            "family_trl": "Unknown",
            "confidence": "none",
            "fallback_reason": "Insufficient Evidence",
            "research_evidence": [],
            "adoption_evidence": [],
        }

    research_kinds = {claim.get("kind") for claim in research}
    adoption_kinds = {claim.get("kind") for claim in adoption}
    tech_trl = "5-6" if "fact" in research_kinds else "3-4" if "simulation" in research_kinds else "Unknown"
    family_trl = "7-8" if "fact" in adoption_kinds else "6-7" if "vendor_claim" in adoption_kinds else "Unknown"
    confidence = "high" if research and adoption else "medium" if research or adoption else "none"
    return {
        "tech_trl": tech_trl,
        "family_trl": family_trl,
        "confidence": confidence,
        "fallback_reason": None if confidence != "none" else "Insufficient Evidence",
        "research_evidence": [claim["id"] for claim in research],
        "adoption_evidence": [claim["id"] for claim in adoption],
    }

def evaluation_synthesis_node(state: OverallState) -> dict:
    """Synthesizes cross-perspective findings, calculates dual TRL, and extracts trade-offs."""
    print("⚖️ [평가 종합] TRL 이원화 산출 및 워크로드별 트레이드오프 종합 실행")
    claims = state.get("claims", [])
    
    trl = {
        tech: evaluate_trl(tech, [claim for claim in claims if claim.get("tech") == tech])
        for tech in ("KIVI", "CXL-PNM")
    }

    gaps = [claim for claim in claims if claim.get("status") in {"insufficient", "rejected"}]

    synthesis = {
        "tradeoffs": "KIVI는 기존 GPU 환경에서 압축을 적용할 수 있고, CXL-PNM은 메모리 확장 인프라를 전제로 근접 연산을 활용합니다.",
        "synergy": "CXL 메모리 계층과 KIVI 압축을 함께 검토할 수 있습니다.",
        "evidence_gaps": gaps
    }

    return {
        "trl": trl,
        "synthesis": synthesis
    }
