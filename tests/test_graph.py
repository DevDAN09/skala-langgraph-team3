"""tests/test_graph.py - Supervisor hub routing. Workers talk only to evidence_audit."""
from src.graph import build_evaluation_graph, route_supervisor
from tests.mock_data import MOCK_STATE, INITIAL_INPUT_STATE


def _decision(**overrides):
    decision = {
        "sufficient": False,
        "collect": [],
        "rework": [],
        "reason": "",
        "dispatched": [],
    }
    decision.update(overrides)
    return decision


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


def test_graph_has_no_worker_to_worker_edges():
    edges = {(edge.source, edge.target) for edge in build_evaluation_graph().get_graph().edges}
    assert ("market_research", "stakeholder_research") not in edges
    assert ("__start__", "paper_analysis") not in edges
    assert ("__start__", "market_research") not in edges
    assert ("__start__", "evidence_audit") in edges
    for worker in ("paper_analysis", "market_research", "stakeholder_research"):
        assert (worker, "evidence_audit") in edges


def test_route_supervisor_reads_only_decision():
    state = {
        **MOCK_STATE,
        "audit": {"issues": [{"target_agent": "market", "claim_id": "MKT-01", "rule": "R1", "action": "search_evidence", "issue": ""}]},
        "retry_count": {"paper": 0, "market": 2, "stakeholder": 0},
        "supervisor": _decision(sufficient=True, reason="evidence sufficient"),
    }
    assert route_supervisor(state) == "evaluation_synthesis"


def test_route_supervisor_collects_missing_perspectives_in_parallel():
    state = {**INITIAL_INPUT_STATE, "supervisor": _decision(collect=["paper", "market"])}
    assert route_supervisor(state) == ["paper_analysis", "market_research"]


def test_route_supervisor_reworks_only_named_agent():
    state = {**MOCK_STATE, "supervisor": _decision(rework=["paper"])}
    assert route_supervisor(state) == ["paper_analysis"]


def test_route_supervisor_can_collect_and_rework_together():
    state = {**MOCK_STATE, "supervisor": _decision(collect=["stakeholder"], rework=["market"])}
    assert route_supervisor(state) == ["market_research", "stakeholder_research"]


def test_route_supervisor_missing_decision_goes_to_synthesis():
    assert route_supervisor({}) == "evaluation_synthesis"


def _run_supervisor_flow(monkeypatch, market_claims):
    import src.graph as graph_module

    calls = []

    def paper(state):
        calls.append("paper_analysis")
        return {"tech_sw": {"name": "KIVI"}, "domain": {"ok": True}}

    def market(state):
        calls.append("market_research")
        claims = market_claims(state, calls.count("market_research"))
        return {"market": {"vendors": ["A"]}, "claims": claims}

    def stakeholder(state):
        calls.append("stakeholder_research")
        return {"stakeholder": {"actors": ["cloud"]}}

    def synthesis(state):
        calls.append("evaluation_synthesis")
        return {}

    def report(state):
        calls.append("report_generation")
        return {"report": "ok"}

    real_audit = graph_module.evidence_audit_node

    def audit(state):
        calls.append("evidence_audit")
        return real_audit(state)

    monkeypatch.setattr(graph_module, "paper_analysis_node", paper)
    monkeypatch.setattr(graph_module, "market_research_node", market)
    monkeypatch.setattr(graph_module, "stakeholder_research_node", stakeholder)
    monkeypatch.setattr(graph_module, "evaluation_synthesis_node", synthesis)
    monkeypatch.setattr(graph_module, "report_generation_node", report)
    monkeypatch.setattr(graph_module, "evidence_audit_node", audit)
    graph_module.build_evaluation_graph().invoke(INITIAL_INPUT_STATE)
    return calls


def test_flow_starts_at_supervisor_and_does_not_chain_workers(monkeypatch):
    calls = _run_supervisor_flow(monkeypatch, lambda state, n: [])
    assert calls[0] == "evidence_audit"
    assert sorted(calls[1:3]) == ["market_research", "paper_analysis"]
    assert calls[3] == "evidence_audit"
    assert calls[4] == "stakeholder_research"
    assert calls[5:] == ["evidence_audit", "evaluation_synthesis", "report_generation"]


def test_flow_rework_does_not_call_other_workers(monkeypatch):
    bad = {
        "id": "MKT-ERR",
        "perspective": "market",
        "tech": "KIVI",
        "statement": "unsupported",
        "kind": "fact",
        "evidence_ids": [],
        "counter_evidence_ids": [],
        "counter_searched": False,
        "status": "ok",
    }

    def market_claims(state, nth):
        if nth == 1:
            return [bad]
        return [{**bad, "kind": "estimate", "counter_searched": True, "status": "ok"}]

    calls = _run_supervisor_flow(monkeypatch, market_claims)
    assert calls[0] == "evidence_audit"
    assert sorted(calls[1:3]) == ["market_research", "paper_analysis"]
    assert calls[3] == "evidence_audit"
    assert sorted(calls[4:6]) == ["market_research", "stakeholder_research"]
    assert calls[6:] == ["evidence_audit", "evaluation_synthesis", "report_generation"]
