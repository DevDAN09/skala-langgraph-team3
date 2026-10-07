"""Supervisor architecture tests for the LangGraph workflow."""
from copy import deepcopy

import pytest
from langgraph.graph import END, START

from main import INITIAL_INPUT_STATE
from src.graph import build_evaluation_graph
from src.orchestration.supervisor import decide_next


WORKERS = {
    "paper_analysis",
    "market_research",
    "stakeholder_research",
    "evidence_audit",
    "evaluation_synthesis",
    "report_generation",
}


def _researched_state() -> dict:
    state = deepcopy(INITIAL_INPUT_STATE)
    state.update({
        "tech_sw": {"name": "KIVI"},
        "tech_hw": {"name": "CXL-PNM"},
        "domain": {"memory_footprint": {}},
        "market": {"key_vendors": []},
        "stakeholder": {"actors_surveyed": []},
    })
    return state


def _issue(target: str) -> dict:
    return {"claim_id": "X", "rule": "R1", "issue": "missing",
            "target_agent": target, "action": "search_evidence"}


def test_graph_starts_at_supervisor_only():
    edges = build_evaluation_graph().get_graph().edges
    assert {edge.target for edge in edges if edge.source == START} == {"supervisor"}


def test_supervisor_selects_initial_independent_research():
    assert decide_next(INITIAL_INPUT_STATE) == ["paper_analysis", "market_research"]


def test_supervisor_waits_for_market_before_stakeholder():
    paper_only = deepcopy(INITIAL_INPUT_STATE)
    paper_only.update({"tech_sw": {"name": "KIVI"},
                       "tech_hw": {"name": "CXL-PNM"},
                       "domain": {"memory_footprint": {}}})
    assert decide_next(paper_only) == ["market_research"]

    state = deepcopy(paper_only)
    state["market"] = {"key_vendors": []}
    assert decide_next(state) == ["stakeholder_research"]


def test_supervisor_routes_audit_issue_to_target_agent():
    state = _researched_state()
    state.update({"audit": {"issues": [_issue("paper")]},
                  "retry_count": {"paper": 1, "market": 0, "stakeholder": 0},
                  "supervisor_route": ["evidence_audit"]})
    assert decide_next(state) == ["paper_analysis"]


def test_supervisor_cascades_market_retry_through_stakeholder_then_audit():
    state = _researched_state()
    state.update({"audit": {"issues": [_issue("market")]},
                  "retry_count": {"paper": 0, "market": 1, "stakeholder": 0},
                  "supervisor_route": ["evidence_audit"]})
    assert decide_next(state) == ["market_research"]
    state["supervisor_route"] = ["market_research"]
    assert decide_next(state) == ["stakeholder_research"]
    state["supervisor_route"] = ["stakeholder_research"]
    assert decide_next(state) == ["evidence_audit"]


def test_supervisor_stops_retrying_at_limit():
    state = _researched_state()
    state.update({"audit": {"issues": [_issue("paper")]},
                  "retry_count": {"paper": 2, "market": 0, "stakeholder": 0},
                  "supervisor_route": ["evidence_audit"]})
    assert decide_next(state) == ["evaluation_synthesis"]


def test_supervisor_progresses_from_clean_audit_to_report_and_end():
    state = _researched_state()
    state.update({"audit": {"issues": []},
                  "supervisor_route": ["evidence_audit"]})
    assert decide_next(state) == ["evaluation_synthesis"]
    state["synthesis"] = {"tradeoffs": {}}
    assert decide_next(state) == ["report_generation"]
    state["report"] = "# report"
    assert decide_next(state) == [END]


def test_every_worker_returns_only_to_supervisor():
    edges = build_evaluation_graph().get_graph().edges
    for worker in WORKERS:
        assert {edge.target for edge in edges if edge.source == worker} == {"supervisor"}
    assert not any(edge.source in WORKERS and edge.target in WORKERS for edge in edges)


def _run_with_stub_nodes(monkeypatch, audit_targets=()):
    import src.graph as graph_module

    calls = []
    audit_runs = 0

    def paper(_):
        calls.append("paper_analysis")
        return {"tech_sw": {"name": "KIVI"}, "tech_hw": {"name": "CXL-PNM"},
                "domain": {"memory_footprint": {}}}

    def market(_):
        calls.append("market_research")
        return {"market": {"key_vendors": []}}

    def stakeholder(_):
        calls.append("stakeholder_research")
        return {"stakeholder": {"actors_surveyed": []}}

    def audit(state):
        nonlocal audit_runs
        calls.append("evidence_audit")
        audit_runs += 1
        if audit_runs > 1 or not audit_targets:
            return {"audit": {"issues": []}}
        counts = dict(state["retry_count"])
        for target in audit_targets:
            counts[target] += 1
        return {"audit": {"issues": [_issue(target) for target in audit_targets]},
                "retry_count": counts}

    def synthesis(_):
        calls.append("evaluation_synthesis")
        return {"synthesis": {"tradeoffs": {}}}

    def report(_):
        calls.append("report_generation")
        return {"report": "# report"}

    monkeypatch.setattr(graph_module, "WORKERS", {
        "paper_analysis": paper,
        "market_research": market,
        "stakeholder_research": stakeholder,
        "evidence_audit": audit,
        "evaluation_synthesis": synthesis,
        "report_generation": report,
    })
    result = graph_module.build_evaluation_graph().invoke(deepcopy(INITIAL_INPUT_STATE))
    return calls, result


def test_graph_normal_flow_is_supervisor_driven(monkeypatch):
    calls, result = _run_with_stub_nodes(monkeypatch)
    assert sorted(calls[:2]) == ["market_research", "paper_analysis"]
    assert calls[2:] == ["stakeholder_research", "evidence_audit",
                         "evaluation_synthesis", "report_generation"]
    assert result["report"] == "# report"


def test_graph_market_retry_returns_via_supervisor(monkeypatch):
    calls, _ = _run_with_stub_nodes(monkeypatch, ("market",))
    assert calls[4:] == ["market_research", "stakeholder_research", "evidence_audit",
                         "evaluation_synthesis", "report_generation"]


@pytest.mark.deprecated
@pytest.mark.skip(reason="deprecated: 외부 API 요청")
def test_graph_end_to_end_execution():
    final_state = build_evaluation_graph().invoke(INITIAL_INPUT_STATE)
    assert final_state["report"]
