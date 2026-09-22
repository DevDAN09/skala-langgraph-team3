"""tests/test_synthesis.py - Tests for Role E Synthesis Evaluator & Jinja2 Report Generation"""
from tests.mock_data import MOCK_STATE
from src.synthesis.evaluator import evaluate_trl, evaluation_synthesis_node
import src.synthesis.report_gen as report_gen
from src.synthesis.report_gen import report_generation_node


def test_domain_axis_value_formats_dict_and_normalizes_internal_fallback():
    rendered = report_gen.domain_axis_value(
        {"memory_footprint": {"KIVI": "2.6x 감소", "CXL-PNM": "corpus 내 근거 미확인"}},
        "memory_footprint",
    )
    assert rendered == "**KIVI**: 2.6x 감소<br>**CXL-PNM**: 공개 근거 미확인"
    assert "{" not in rendered

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
    assert "### 4.1 기술 성숙도 (TRL 이원화)" in report_text
    assert "### 4.2 시장성 및 생태계" in report_text
    assert "### 4.3 이해관계자 영향" in report_text
    assert "### 4.4 도메인 6대 축 적합성" in report_text
    assert "### 5.1 관점별 평가가 엇갈리는 지점" in report_text
    assert "### 5.5 종합 의견" in report_text
    assert "### 6.2 분석 범위와 해석 제약" in report_text
    assert "더 우수하다" not in report_text
    assert "[DOM-01]" in report_text
    assert "[MKT-02]" in report_text
    assert "특정 기술의 우열을 결론내리지 않는다." in report_text
    assert "| **KIVI** | 5-6 | 6-7 |" in report_text
    assert "| **CXL-PNM** | 3-4 | 6-7 |" in report_text
    assert "[1]" in report_text
    assert "[4]" in report_text
    assert "simulation" in report_text
    assert "저자 미상(2024). KIVI: A Tuning-Free Asymmetric 2bit Quantization for KV Cache. *ICML*." in report_text
    assert "Samsung Semiconductor(2024)." in report_text
    assert "[1] 저자 미상(2024)." in report_text
    assert "특허 :" not in report_text
    assert "논문 :" not in report_text
    assert "기타 (웹페이지) :" not in report_text
    assert "Tier:" not in report_text
