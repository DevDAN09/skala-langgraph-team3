"""tests/test_synthesis.py - Tests for Role E Synthesis Evaluator & Jinja2 Report Generation"""
from tests.mock_data import MOCK_STATE
from src.synthesis.evaluator import evaluate_trl, evaluation_synthesis_node
import src.synthesis.report_gen as report_gen
from src.synthesis.report_gen import report_generation_node

def test_evaluate_trl_dual():
    kivi_trl = evaluate_trl("KIVI", MOCK_STATE["claims"])
    assert kivi_trl["tech_trl"] == "5-6"
    assert kivi_trl["family_trl"] == "6-7"
    assert kivi_trl["research_evidence"] == ["DOM-01"]
    assert kivi_trl["adoption_evidence"] == ["MKT-02"]

    cxl_trl = evaluate_trl("CXL-PNM", MOCK_STATE["claims"])
    assert cxl_trl["tech_trl"] == "3-4"
    assert cxl_trl["family_trl"] == "6-7"
    assert cxl_trl["research_evidence"] == ["DOM-02"]
    assert cxl_trl["adoption_evidence"] == ["MKT-01"]


def test_evaluate_trl_without_claims_uses_fallback():
    result = evaluate_trl("KIVI", [])
    assert result["tech_trl"] == "Unknown"
    assert result["family_trl"] == "Unknown"
    assert result["confidence"] == "none"

def test_report_generation_sections(monkeypatch):
    monkeypatch.setattr(report_gen, "OPENAI_API_KEY", "")
    synth_res = evaluation_synthesis_node(MOCK_STATE)
    merged_state = {**MOCK_STATE, **synth_res}
    report_res = report_generation_node(merged_state)
    report_text = report_res["report"]

    required_sections = [
        "## SUMMARY",
        "## 1. 분석 배경",
        "## 2. 기술 선정",
        "## 3. 기술 개요",
        "## 4. 관점별 평가",
        "## 5. 시사점",
        "## 6. 한계점",
        "## REFERENCE"
    ]
    for sec in required_sections:
        assert sec in report_text
    assert "더 우수하다" not in report_text
    assert "[DOM-01]" in report_text
    assert "[MKT-02]" in report_text
    assert "simulation" in report_text
    assert "[Tier: T1]" in report_text
