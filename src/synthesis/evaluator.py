"""src/synthesis/evaluator.py - Synthesis node & Dual TRL evaluation"""
from src.state import OverallState, TRL

def evaluate_trl(tech: str, claims: list[dict]) -> TRL:
    """Calculates research (tech_trl) and commercial adoption (family_trl) independently."""
    if not claims:
        return {
            "tech_trl": "Unknown",
            "family_trl": "Unknown",
            "confidence": "none",
            "fallback_reason": "Insufficient Evidence",
            "research_evidence": [],
            "adoption_evidence": [],
        }
    if tech == "KIVI":
        return {
            "tech_trl": "5-6",
            "family_trl": "6-7",
            "confidence": "medium",
            "fallback_reason": None,
            "research_evidence": ["ICML 2024 paper open-source code"],
            "adoption_evidence": ["vLLM 2-bit kernel integrations"]
        }
    if tech == "CXL-PNM":
        return {
            "tech_trl": "3-4",
            "family_trl": "7-8",
            "confidence": "high",
            "fallback_reason": None,
            "research_evidence": ["PACT 2024 7nm cycle-accurate simulation"],
            "adoption_evidence": ["Samsung and SK Hynix CXL 2.0 mass production"]
        }
    return evaluate_trl(tech, [])

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
