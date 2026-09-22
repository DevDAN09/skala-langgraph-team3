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


def _run_with_stub_nodes(monkeypatch, first_audit_targets):
    """노드 6개를 실행 순서만 기록하는 스텁으로 바꿔 그래프 흐름만 검증한다."""
    import src.graph as graph_module

    calls = []
    audit_runs = {"n": 0}

    def recorder(name):
        def node(state):
            calls.append(name)
            return {}
        return node

    def stub_audit(state):
        calls.append("evidence_audit")
        audit_runs["n"] += 1
        if audit_runs["n"] > 1:
            return {"audit": {"issues": []}}
        retry = dict(state["retry_count"])
        issues = []
        for target in first_audit_targets:
            retry[target] += 1
            issues.append({"claim_id": "X", "rule": "R1", "issue": "",
                           "target_agent": target, "action": "search_evidence"})
        return {"audit": {"issues": issues}, "retry_count": retry}

    for attr, name in [
        ("paper_analysis_node", "paper_analysis"),
        ("market_research_node", "market_research"),
        ("stakeholder_research_node", "stakeholder_research"),
        ("evaluation_synthesis_node", "evaluation_synthesis"),
        ("report_generation_node", "report_generation"),
    ]:
        monkeypatch.setattr(graph_module, attr, recorder(name))
    monkeypatch.setattr(graph_module, "evidence_audit_node", stub_audit)

    graph_module.build_evaluation_graph().invoke(INITIAL_INPUT_STATE)
    return calls


def test_flow_first_run_order(monkeypatch):
    calls = _run_with_stub_nodes(monkeypatch, [])
    assert sorted(calls[:2]) == ["market_research", "paper_analysis"]
    assert calls[2:] == ["stakeholder_research", "evidence_audit",
                         "evaluation_synthesis", "report_generation"]


def test_flow_market_retry_cascades_to_stakeholder(monkeypatch):
    calls = _run_with_stub_nodes(monkeypatch, ["market"])
    assert calls[4:] == ["market_research", "stakeholder_research", "evidence_audit",
                         "evaluation_synthesis", "report_generation"]


def test_flow_paper_only_retry_goes_to_audit(monkeypatch):
    calls = _run_with_stub_nodes(monkeypatch, ["paper"])
    assert calls[4:] == ["paper_analysis", "evidence_audit",
                         "evaluation_synthesis", "report_generation"]


def test_flow_parallel_market_and_paper_retry_audits_once(monkeypatch):
    calls = _run_with_stub_nodes(monkeypatch, ["market", "paper"])
    assert calls.count("evidence_audit") == 2
    assert calls.count("report_generation") == 1
    retry = calls[4:]
    assert sorted(retry[:2]) == ["market_research", "paper_analysis"]
    assert retry[2:] == ["stakeholder_research", "evidence_audit",
                         "evaluation_synthesis", "report_generation"]


def test_flow_parallel_stakeholder_and_paper_retry_audits_once(monkeypatch):
    calls = _run_with_stub_nodes(monkeypatch, ["stakeholder", "paper"])
    assert calls.count("evidence_audit") == 2
    assert calls.count("report_generation") == 1
    retry = calls[4:]
    assert sorted(retry[:2]) == ["paper_analysis", "stakeholder_research"]
    assert retry[2:] == ["evidence_audit", "evaluation_synthesis", "report_generation"]


def test_route_after_paper_defers_to_stakeholder_edge_when_market_also_retries():
    issue = {"rule": "R1", "action": "search_evidence", "claim_id": "X", "issue": ""}
    state = {
        **MOCK_STATE,
        "audit": {"issues": [{**issue, "target_agent": "paper"}, {**issue, "target_agent": "market"}]},
        "retry_count": {"paper": 1, "market": 1, "stakeholder": 0},
    }
    assert route_after_paper(state) == END
    state["retry_count"] = {"paper": 1, "market": 2, "stakeholder": 0}
    assert route_after_paper(state) == "evidence_audit"
