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
    assert "### 5.1 관점 간 해석 차이" in report_text
    assert "### 5.4 종합 의견" in report_text
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
    assert "기관 또는 작성자 미상(2024). KIVI: A Tuning-Free Asymmetric 2bit Quantization for KV Cache. *ICML*." in report_text
    assert "Samsung Semiconductor(발행일 미상)." in report_text
    assert "[1] 기관 또는 작성자 미상(2024)." in report_text
    assert "특허 :" not in report_text
    assert "논문 :" not in report_text
    assert "기타 (웹페이지) :" not in report_text
    assert "Tier:" not in report_text


# ── 보고서 생성 정비: 코드펜스·수치 보존·4대 Actor ──

class _FakeLLM:
    """invoke 호출마다 미리 정한 응답을 순서대로 돌려준다."""
    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return type("Msg", (), {"content": self.replies.pop(0)})()


def _skeleton(state):
    import src.synthesis.report_gen as rg
    original = rg.OPENAI_API_KEY
    rg.OPENAI_API_KEY = ""
    try:
        return report_generation_node(state)["report"]
    finally:
        rg.OPENAI_API_KEY = original


def _patch_llm(monkeypatch, replies):
    import src.synthesis.report_gen as rg
    fake = _FakeLLM(replies)
    monkeypatch.setattr(rg, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(rg, "ChatOpenAI", lambda **_: fake)
    return fake


def test_strip_code_fence_only_removes_outer_fence():
    from src.synthesis.report_gen import strip_code_fence
    assert strip_code_fence("```markdown\n# 제목\n\n본문\n```") == "# 제목\n\n본문"
    inner = "# 제목\n```python\nx = 1\n```\n끝"
    assert strip_code_fence(inner) == inner


def test_report_generation_strips_fence_from_polished_report(monkeypatch):
    skeleton = _skeleton(MOCK_STATE)
    _patch_llm(monkeypatch, [f"```markdown\n{skeleton}\n```"])
    assert report_generation_node(MOCK_STATE)["report"] == skeleton


def test_report_generation_falls_back_to_skeleton_when_numbers_change(monkeypatch):
    skeleton = _skeleton(MOCK_STATE)
    altered = skeleton.replace("### 3.1", "### 3.1\n수치 999,999가 새로 생겼다.", 1)
    fake = _patch_llm(monkeypatch, [altered, altered])
    assert report_generation_node(MOCK_STATE)["report"] == skeleton
    assert len(fake.prompts) == 2  # 1회 재시도 후 골격으로 대체


def test_number_diff_flags_unit_conversion():
    from src.synthesis.report_gen import number_diff
    skeleton = "## 3. 개요\n- **[MKT-04]** $20B by 2030 [3]\n"
    assert number_diff(skeleton, skeleton.replace("$20B", "200억 달러")) == ({"200"}, {"20"})
    assert number_diff(skeleton, skeleton.replace("by", "까지")) == (set(), set())


def test_report_lists_all_four_stakeholder_actors_and_drops_rejected(monkeypatch):
    state = {**MOCK_STATE, "stakeholder": {
        "cloud_serving_operator": "[A 계열] Benefit: 운영자 근거 | Concern: - | Barrier: - (근거: STK-01, EV-STK-01)",
        "framework_developer": "개발자 근거", "end_user": "사용자 근거", "memory_vendor": "공급자 근거"},
        "claims": [*MOCK_STATE["claims"], {"id": "STK-01", "perspective": "stakeholder", "tech": "KIVI",
                                            "statement": "x", "kind": "fact", "evidence_ids": [],
                                            "counter_evidence_ids": [], "counter_searched": True, "status": "rejected"}]}
    section = _skeleton(state).split("### 4.3", 1)[1].split("###", 1)[0]
    for label in ("서빙 운영자", "프레임워크 개발자", "End User", "공급자"):
        assert label in section
    assert "운영자 근거" not in section and "[A 계열] 근거 미확인" in section
