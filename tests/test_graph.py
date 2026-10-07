"""Supervisor graph topology and routing contracts."""
import pytest
from src.graph import build_evaluation_graph
from src.supervisor import MAX_STEPS, route_supervisor, supervisor_node
from src.synthesis.quality import route_quality
from tests.mock_data import INITIAL_INPUT_STATE, MOCK_STATE


def test_graph_compilation_includes_supervisor_and_quality_gate():
    graph = build_evaluation_graph()
    assert {"supervisor", "paper_analysis", "market_research", "stakeholder_research",
            "evaluation_synthesis", "report_generation", "quality_eval"} <= set(graph.nodes)


def test_supervisor_selects_an_initial_research_agent():
    result = supervisor_node(INITIAL_INPUT_STATE)
    assert result["next_agent"] in {"paper_analysis", "market_research"}
    assert result["step_count"] == 1


def test_supervisor_respects_market_before_stakeholder():
    state = {**INITIAL_INPUT_STATE, "node_status": {"paper": "complete", "market": "pending", "stakeholder": "pending"}}
    assert supervisor_node(state)["next_agent"] == "market_research"


def test_supervisor_routes_targeted_audit_rework_only():
    claims = [{**claim, "evidence_ids": []} if claim["id"] == "DOM-01" else claim for claim in MOCK_STATE["claims"]]
    state = {**MOCK_STATE, "claims": claims, "retry_count": {"paper": 0, "market": 0, "stakeholder": 0}}
    assert supervisor_node(state)["next_agent"] == "paper_analysis"


def test_supervisor_ends_research_at_step_limit():
    result = supervisor_node({**INITIAL_INPUT_STATE, "step_count": MAX_STEPS})
    assert result == {"next_agent": "evaluation_synthesis"}
    assert route_supervisor(result) == "evaluation_synthesis"


def test_quality_routes_evidence_gaps_to_supervisor_and_writing_to_report():
    assert route_quality({"quality": {"passed": False, "failures": ["coverage"], "attempts": 1}}) == "supervisor"
    assert route_quality({"quality": {"passed": False, "failures": ["REFERENCES"], "attempts": 1}}) == "report_generation"
    assert route_quality({"quality": {"passed": True, "failures": [], "attempts": 1}}) == "END"


@pytest.mark.deprecated
@pytest.mark.skip(reason="deprecated: 외부 API 요청")
def test_graph_end_to_end_execution():
    final_state = build_evaluation_graph().invoke(INITIAL_INPUT_STATE)
    assert final_state["report"]
    assert final_state["quality"]["attempts"] >= 1
    assert final_state["step_count"] <= MAX_STEPS
