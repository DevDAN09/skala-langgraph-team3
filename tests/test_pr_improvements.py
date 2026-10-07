"""개선 작업별 회귀 테스트. 커밋마다 해당 작업 테스트를 추가한다."""
from langgraph.graph import END

from src.audit.auditor import build_supervisor_decision, evidence_audit_node
from src.graph import MAX_QUALITY_ROUNDS, route_quality
from src.quality.quality_eval import check_groundedness, quality_eval_node
from tests.mock_data import INITIAL_INPUT_STATE


def test_quality_hybrid_static_fail_short_circuits_without_llm(monkeypatch):
    monkeypatch.setattr("src.quality.quality_eval.llm_judge", lambda _report: (_ for _ in ()).throw(AssertionError("llm")))
    result = quality_eval_node({**INITIAL_INPUT_STATE, "report": "짧은 보고서"})
    assert result["quality"]["judge"] == "rule_only"
    assert result["quality"]["passed"] is False
    assert result["quality"]["checks"]["groundedness"]["passed"] is False
    assert result["quality_round"] == 1


def test_quality_hybrid_passes_only_when_rule_and_judge_pass(monkeypatch):
    class Score:
        def __init__(self, score, fix=""):
            self.score = score
            self.reason = "ok"
            self.fix = fix

    class Judgement:
        groundedness = Score(4)
        neutrality = Score(2, fix="우열 표현 삭제")
        bias_control = Score(4)
        coverage = Score(4)

    monkeypatch.setattr("src.quality.quality_eval.llm_judge", lambda _report: Judgement())
    report = "본문 [1]\n### 4.1\n### 4.2\n### 4.3\n### 4.4\n## SUMMARY\n## REFERENCE\n[1] src"
    state = {
        **INITIAL_INPUT_STATE,
        "report": report,
        "claims": [
            {"id": "DOM-01", "status": "ok", "tech": "KIVI", "perspective": "maturity", "evidence_ids": ["E1"], "counter_searched": True},
            {"id": "MKT-01", "status": "ok", "tech": "KIVI", "perspective": "market", "evidence_ids": ["E2"], "counter_searched": True},
            {"id": "STK-01", "status": "ok", "tech": "CXL-PNM", "perspective": "stakeholder", "evidence_ids": ["E3"], "counter_searched": True},
            {"id": "DOM-02", "status": "ok", "tech": "CXL-PNM", "perspective": "domain", "evidence_ids": ["E4"], "counter_searched": True},
        ],
        "evidence": [
            {"evidence_id": "E1", "source_id": "S1"},
            {"evidence_id": "E2", "source_id": "S2"},
            {"evidence_id": "E3", "source_id": "S3"},
            {"evidence_id": "E4", "source_id": "S4"},
        ],
    }
    monkeypatch.setattr("src.quality.quality_eval.check_bias_control", lambda *_a, **_k: {"passed": True, "reason": "stub"})
    monkeypatch.setattr("src.quality.quality_eval.check_groundedness", lambda *_a, **_k: {"passed": True, "reason": "stub"})
    result = quality_eval_node(state)
    assert result["quality"]["judge"] == "hybrid"
    assert result["quality"]["checks"]["neutrality"]["passed"] is False
    assert result["quality"]["passed"] is False
    assert any("우열" in item for item in result["quality"]["feedback"])


def test_route_quality_rewrites_until_cap():
    assert route_quality({"quality": {"passed": False}, "quality_round": 1}) == "report_generation"
    assert route_quality({"quality": {"passed": True}, "quality_round": 1}) == END
    assert route_quality({"quality": {"passed": False}, "quality_round": MAX_QUALITY_ROUNDS}) == END


def _issue(agent="market"):
    return {
        "claim_id": "MKT-01",
        "rule": "R1",
        "issue": "missing evidence",
        "target_agent": agent,
        "action": "search_evidence",
    }


def test_market_rework_marks_stakeholder_stale_and_defers_it():
    state = {
        **INITIAL_INPUT_STATE,
        "tech_sw": {"name": "KIVI"},
        "market": {"vendors": ["A"]},
        "stakeholder": {"actors": ["cloud"]},
        "node_status": {"paper": "complete", "market": "complete", "stakeholder": "complete"},
    }
    decision, _, extra = build_supervisor_decision(state, [_issue()])
    assert decision["rework"] == ["market"]
    assert "stakeholder" not in decision["collect"]
    assert extra["node_status"]["stakeholder"] == "stale"

    refreshed = {
        **state,
        "node_status": {"paper": "complete", "market": "complete", "stakeholder": "stale"},
        "retry_count": {"paper": 0, "market": 1, "stakeholder": 0},
    }
    decision2, _, _ = build_supervisor_decision(refreshed, [])
    assert decision2["collect"] == ["stakeholder"]
    assert decision2["rework"] == []


def test_audit_skips_rules_when_collect_seq_not_newer(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("audit should be cached")

    monkeypatch.setattr("src.audit.auditor.run_static_rules", boom)
    monkeypatch.setattr("src.audit.auditor.judge.run_llm_judge", boom)
    state = {
        **INITIAL_INPUT_STATE,
        "tech_sw": {"name": "KIVI"},
        "market": {"vendors": ["A"]},
        "stakeholder": {"actors": ["cloud"]},
        "collect_seq": 2,
        "audited_seq": 2,
        "audit": {"issues": []},
        "node_status": {"paper": "complete", "market": "complete", "stakeholder": "complete"},
    }
    result = evidence_audit_node(state)
    assert result["supervisor"]["sufficient"] is True
    assert result["audited_seq"] == 2


def test_groundedness_requires_citation():
    assert check_groundedness("본문만", INITIAL_INPUT_STATE)["passed"] is False
