from copy import deepcopy

from src.quality.evaluator import quality_evaluation_node
from tests.mock_data import MOCK_STATE


def _state(report="# SUMMARY\n중립적인 비교다.\n# REFERENCE"):
    state = {**deepcopy(MOCK_STATE), "report": report, "quality_round": 0}
    state["claims"].extend([
        {**state["claims"][0], "id": "MAT-R01", "perspective": "maturity"},
        {**state["claims"][1], "id": "MAT-R02", "perspective": "maturity"},
        {**state["claims"][0], "id": "DOM-03"},
        {**state["claims"][0], "id": "DOM-05"},
        {**state["claims"][1], "id": "DOM-04"},
        {**state["claims"][1], "id": "DOM-06"},
        *[{**state["claims"][2], "id": f"STK-0{i}", "perspective": "stakeholder",
           "tech": "KIVI", "counter_searched": True} for i in range(1, 5)],
    ])
    return state


def test_quality_passes_all_four_dimensions(monkeypatch):
    monkeypatch.setattr("src.quality.evaluator._semantic_check", lambda *_: None)
    result = quality_evaluation_node(_state())["quality"]
    assert result["passed"] is True
    assert all(result["dimension_results"].values())


def test_groundedness_fails_for_dangling_evidence(monkeypatch):
    monkeypatch.setattr("src.quality.evaluator._semantic_check", lambda *_: None)
    state = _state()
    state["claims"][0]["evidence_ids"] = ["MISSING"]
    result = quality_evaluation_node(state)["quality"]
    assert result["dimension_results"]["groundedness"] is False
    assert "paper" in result["research_rework_targets"]


def test_neutrality_ignores_negation_but_rejects_recommendation(monkeypatch):
    monkeypatch.setattr("src.quality.evaluator._semantic_check", lambda *_: None)
    neutral = quality_evaluation_node(_state(
        "# SUMMARY\n특정 기술을 추천하지 않는다.\n# REFERENCE"))["quality"]
    assert neutral["dimension_results"]["neutrality"] is True
    biased = quality_evaluation_node(_state(
        "# SUMMARY\nKIVI를 추천한다.\n# REFERENCE"))["quality"]
    assert biased["dimension_results"]["neutrality"] is False
    assert biased["report_rewrite_required"] is True


def test_bias_requires_counter_search_not_counter_result(monkeypatch):
    monkeypatch.setattr("src.quality.evaluator._semantic_check", lambda *_: None)
    state = _state()
    market = next(claim for claim in state["claims"] if claim["perspective"] == "market")
    market["counter_searched"] = True
    market["counter_evidence_ids"] = []
    assert quality_evaluation_node(state)["quality"]["dimension_results"]["bias_control"] is True
    market["counter_searched"] = False
    result = quality_evaluation_node(state)["quality"]
    assert result["dimension_results"]["bias_control"] is False
    assert "market" in result["research_rework_targets"]


def test_coverage_requires_valid_claim_in_all_perspectives(monkeypatch):
    monkeypatch.setattr("src.quality.evaluator._semantic_check", lambda *_: None)
    state = _state()
    state["claims"] = [claim for claim in state["claims"]
                       if claim["perspective"] != "stakeholder"]
    result = quality_evaluation_node(state)["quality"]
    assert result["dimension_results"]["perspective_coverage"] is False
    assert "stakeholder" in result["research_rework_targets"]


def test_coverage_requires_each_tech_and_each_stakeholder_actor(monkeypatch):
    monkeypatch.setattr("src.quality.evaluator._semantic_check", lambda *_: None)
    state = _state()
    for claim in state["claims"]:
        if claim["id"] in {"MAT-R02", "MKT-01", "STK-02"}:
            claim["status"] = "insufficient"
    result = quality_evaluation_node(state)["quality"]
    assert result["dimension_results"]["perspective_coverage"] is False
    assert set(result["research_rework_targets"]) >= {"paper", "market", "stakeholder"}


def test_required_report_sections_and_round_increment(monkeypatch):
    monkeypatch.setattr("src.quality.evaluator._semantic_check", lambda *_: None)
    result = quality_evaluation_node(_state("# body"))
    assert result["quality"]["report_rewrite_required"] is True
    assert result["quality_round"] == 1
