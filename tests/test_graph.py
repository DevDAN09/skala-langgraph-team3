"""tests/test_graph.py - Unit and integration tests for LangGraph StateGraph assembly and routers"""
from langgraph.graph import END
from src.graph import build_evaluation_graph, route_audit_decision, route_after_paper
from tests.mock_data import MOCK_STATE, INITIAL_INPUT_STATE


def test_graph_compilation():
    graph = build_evaluation_graph()
    assert graph is not None
    node_keys = set(graph.nodes.keys())
    expected_nodes = {
        "paper_analysis",
        "market_research",
        "stakeholder_research",
        "evidence_audit",
        "evaluation_synthesis",
        "report_generation",
    }
    assert expected_nodes.issubset(node_keys)


def test_route_after_paper_first_run():
    # On initial run, audit.issues is empty -> routes to END
    state = {**MOCK_STATE, "audit": {"issues": []}}
    assert route_after_paper(state) == END


def test_route_after_paper_with_issue():
    # On targeted retry, routes back to evidence_audit
    state = {
        **MOCK_STATE,
        "audit": {
            "issues": [
                {
                    "target_agent": "paper",
                    "rule": "R1",
                    "action": "search_evidence",
                    "claim_id": "DOM-01",
                    "issue": "",
                }
            ]
        },
    }
    assert route_after_paper(state) == "evidence_audit"


def test_route_after_paper_non_paper_issue():
    # When issue is for market or stakeholder, paper branch still closes to END
    state = {
        **MOCK_STATE,
        "audit": {
            "issues": [
                {
                    "target_agent": "market",
                    "rule": "R3",
                    "action": "search_counter_evidence",
                    "claim_id": "MKT-01",
                    "issue": "",
                }
            ]
        },
    }
    assert route_after_paper(state) == END


def test_route_after_paper_none_or_missing_audit():
    assert route_after_paper({}) == END
    assert route_after_paper({"audit": None}) == END
    assert route_after_paper({"audit": {"issues": None}}) == END


def test_route_audit_decision_clear():
    state = {**MOCK_STATE, "audit": {"issues": []}}
    assert route_audit_decision(state) == "evaluation_synthesis"


def test_route_audit_decision_cascade_market():
    state = {
        **MOCK_STATE,
        "audit": {
            "issues": [
                {
                    "target_agent": "market",
                    "rule": "R3",
                    "action": "search_counter_evidence",
                    "claim_id": "MKT-01",
                    "issue": "",
                },
                {
                    "target_agent": "stakeholder",
                    "rule": "R1",
                    "action": "search_evidence",
                    "claim_id": "STK-01",
                    "issue": "",
                },
            ]
        },
        "retry_count": {"paper": 0, "market": 0, "stakeholder": 0},
    }
    assert route_audit_decision(state) == ["market_research"]


def test_route_audit_decision_stakeholder_only():
    state = {
        **MOCK_STATE,
        "audit": {
            "issues": [
                {
                    "target_agent": "stakeholder",
                    "rule": "R1",
                    "action": "search_evidence",
                    "claim_id": "STK-01",
                    "issue": "",
                },
            ]
        },
        "retry_count": {"paper": 0, "market": 0, "stakeholder": 0},
    }
    assert route_audit_decision(state) == ["stakeholder_research"]


def test_route_audit_decision_paper_only():
    state = {
        **MOCK_STATE,
        "audit": {
            "issues": [
                {
                    "target_agent": "paper",
                    "rule": "R1",
                    "action": "search_evidence",
                    "claim_id": "DOM-01",
                    "issue": "",
                },
            ]
        },
        "retry_count": {"paper": 0, "market": 0, "stakeholder": 0},
    }
    assert route_audit_decision(state) == ["paper_analysis"]


def test_route_audit_decision_parallel_market_and_paper():
    state = {
        **MOCK_STATE,
        "audit": {
            "issues": [
                {
                    "target_agent": "market",
                    "rule": "R3",
                    "action": "search_counter_evidence",
                    "claim_id": "MKT-01",
                    "issue": "",
                },
                {
                    "target_agent": "paper",
                    "rule": "R1",
                    "action": "search_evidence",
                    "claim_id": "DOM-01",
                    "issue": "",
                },
            ]
        },
        "retry_count": {"paper": 0, "market": 0, "stakeholder": 0},
    }
    assert route_audit_decision(state) == ["market_research", "paper_analysis"]


def test_route_audit_decision_retries_exhausted():
    state = {
        **MOCK_STATE,
        "audit": {
            "issues": [
                {
                    "target_agent": "market",
                    "rule": "R3",
                    "action": "search_counter_evidence",
                    "claim_id": "MKT-01",
                    "issue": "",
                },
            ]
        },
        "retry_count": {"paper": 0, "market": 2, "stakeholder": 0},
    }
    assert route_audit_decision(state) == "evaluation_synthesis"


def test_graph_end_to_end_execution():
    graph = build_evaluation_graph()
    final_state = graph.invoke(INITIAL_INPUT_STATE)
    assert final_state is not None
    assert "report" in final_state
    assert len(final_state["report"]) > 0
    assert "trl" in final_state
    assert "KIVI" in final_state["trl"]
    assert "CXL-PNM" in final_state["trl"]
    assert "claims" in final_state
    assert len(final_state["claims"]) >= 4
