"""tests/test_quality_judge.py - 보고서 품질 평가 3안 Hybrid (#72) · 일관성 (#76)"""
from unittest.mock import MagicMock

import pytest

from tests.mock_data import MOCK_STATE
import src.synthesis.quality as quality
import src.synthesis.quality_judge as quality_judge
from src.synthesis.quality_judge import JudgeItem, ReportVerdict, run_report_judge

REPORT = "## SUMMARY\nKIVI는 메모리를 2.6배 줄인다.\nKIVI는 CXL-PNM에 비해 압도적으로 실용적인 선택지다.\n## REFERENCE"


def _verdict(**overrides) -> ReportVerdict:
    items = {name: JudgeItem(score=5, reason="ok") for name in quality_judge.JUDGE_ITEMS}
    items.update(overrides)
    return ReportVerdict(**items)


@pytest.fixture
def judge_llm(monkeypatch):
    llm = MagicMock()
    chat = MagicMock()
    chat.return_value.with_structured_output.return_value = llm
    monkeypatch.setattr(quality_judge, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(quality_judge.langchain_openai, "ChatOpenAI", chat)
    return llm


@pytest.fixture
def rules_pass(monkeypatch):
    """1단계 규칙을 모두 통과한 상태를 만든다 (커버리지 Gap 없음)."""
    monkeypatch.setattr(quality, "_coverage_gaps", lambda verified: [])
    return {**MOCK_STATE, "report": REPORT}


def test_judge_scores_five_items_including_consistency(judge_llm):
    judge_llm.invoke.return_value = _verdict()
    result = run_report_judge(REPORT, MOCK_STATE)
    assert set(result) == {"groundedness", "neutrality", "bias_control", "coverage", "consistency"}
    assert all(item["passed"] for item in result.values())


def test_judge_fails_item_with_quote_from_report(judge_llm):
    judge_llm.invoke.return_value = _verdict(
        consistency=JudgeItem(score=2, reason="SUMMARY와 4.1 수치 불일치", quotes=["KIVI는 메모리를 2.6배 줄인다."]))
    result = run_report_judge(REPORT, MOCK_STATE)
    assert result["consistency"]["passed"] is False
    assert result["consistency"]["quotes"] == ["KIVI는 메모리를 2.6배 줄인다."]


def test_judge_voids_failure_whose_quote_is_not_in_report(judge_llm):
    """보고서에 없는 문장을 인용한 미달 판정은 1회 재질의 후에도 그대로면 무효 처리한다."""
    fabricated = _verdict(neutrality=JudgeItem(score=1, reason="추천", quotes=["CXL-PNM을 도입해야 한다."]))
    judge_llm.invoke.return_value = fabricated
    result = run_report_judge(REPORT, MOCK_STATE)
    assert judge_llm.invoke.call_count == 2
    assert result["neutrality"] == {"score": 1, "passed": True, "reason": "추천", "quotes": [], "voided": True}


def test_judge_returns_none_without_api_key(monkeypatch):
    monkeypatch.setattr(quality_judge, "OPENAI_API_KEY", "")
    assert run_report_judge(REPORT, MOCK_STATE) is None


def test_judge_returns_none_on_call_failure(judge_llm):
    judge_llm.invoke.side_effect = RuntimeError("timeout")
    assert run_report_judge(REPORT, MOCK_STATE) is None


def test_quality_node_runs_judge_after_rules_pass(judge_llm, rules_pass, monkeypatch):
    import src.supervisor as supervisor

    judge_llm.invoke.return_value = _verdict(
        neutrality=JudgeItem(score=2, reason="정규식 밖 우열 뉘앙스", quotes=["KIVI는 CXL-PNM에 비해 압도적으로 실용적인 선택지다."]))
    result = quality.quality_evaluation_node(rules_pass)["quality"]
    assert result["method"] == "hybrid"
    assert result["passed"] is False
    assert result["failures"] == ["judge_neutrality"]
    assert result["rework_targets"] == []  # 서술 문제는 재수집 대상이 아니다
    monkeypatch.setattr(supervisor, "evidence_audit_node", lambda state: {"audit": {"issues": []}})
    state = {**rules_pass, "quality": result, "node_status": {
        "paper": "complete", "market": "complete", "stakeholder": "complete",
        "synthesis": "complete", "report": "complete", "quality": "complete"}}
    assert supervisor.supervisor_node(state)["next_agent"] == "report_generation"


def test_quality_node_passes_when_rules_and_judge_pass(judge_llm, rules_pass):
    judge_llm.invoke.return_value = _verdict()
    result = quality.quality_evaluation_node(rules_pass)["quality"]
    assert result["passed"] is True and result["method"] == "hybrid"


def test_quality_node_skips_judge_when_rules_fail(judge_llm):
    """Fast-Fail: 규칙 미달이면 LLM Judge를 호출하지 않는다."""
    result = quality.quality_evaluation_node({**MOCK_STATE, "report": REPORT})["quality"]
    assert "coverage" in result["failures"]
    assert result["method"] == "rules" and result["judge"] is None
    judge_llm.invoke.assert_not_called()


def test_quality_node_falls_back_to_rules_when_judge_unavailable(monkeypatch, rules_pass):
    monkeypatch.setattr(quality_judge, "OPENAI_API_KEY", "")
    result = quality.quality_evaluation_node(rules_pass)["quality"]
    assert result["method"] == "rules" and result["passed"] is True
