"""Supervisor, dependency refresh, retry, recovery, and graph contract tests."""
from copy import deepcopy

from langgraph.graph import END, START
from langgraph.checkpoint.memory import InMemorySaver

from main import INITIAL_INPUT_STATE
from src.graph import WORKERS, build_evaluation_graph
from src.orchestration.supervisor import MAX_QUALITY_ROUNDS, decide_next, supervisor_node
from src.orchestration.worker import MAX_WORKER_ATTEMPTS, wrap_worker


def _issue(target="paper", claim_id="DOM-01"):
    return {"claim_id": claim_id, "rule": "R1", "issue": "missing",
            "target_agent": target, "action": "search_evidence"}


def _researched_state():
    state = deepcopy(INITIAL_INPUT_STATE)
    state["node_status"].update({
        "paper_analysis": "completed", "market_research": "completed",
        "stakeholder_research": "completed", "evidence_audit": "completed",
    })
    state.update({
        "tech_sw": {"name": "KIVI"}, "tech_hw": {"name": "CXL-PNM"},
        "domain": {"memory_footprint": {}}, "market": {"version": 1},
        "stakeholder": {"market_version": 1}, "audit": {"issues": []},
    })
    return state


def test_graph_is_strict_supervisor_hub_spoke():
    graph = build_evaluation_graph().get_graph()
    assert {edge.target for edge in graph.edges if edge.source == START} == {"supervisor"}
    for worker in WORKERS:
        assert {edge.target for edge in graph.edges if edge.source == worker} == {"supervisor"}
    assert not any(edge.source in WORKERS and edge.target in WORKERS for edge in graph.edges)


def test_graph_accepts_in_process_checkpointer():
    saver = InMemorySaver()
    assert build_evaluation_graph(checkpointer=saver).checkpointer is saver


def test_initial_paper_and_market_are_parallel_and_stakeholder_waits():
    assert decide_next(INITIAL_INPUT_STATE) == ["paper_analysis", "market_research"]
    state = deepcopy(INITIAL_INPUT_STATE)
    state["node_status"].update({"paper_analysis": "completed", "market_research": "completed"})
    assert decide_next(state) == ["stakeholder_research"]


def test_audit_detection_does_not_increment_retry_but_dispatch_does():
    state = _researched_state()
    state["audit"] = {"issues": [_issue()]}
    result = supervisor_node(state)
    assert result["next_nodes"] == ["paper_analysis"]
    assert result["retry_count"]["paper"] == 1
    assert result["route_reason"] == "audit_rework"


def test_retry_second_dispatch_is_two_and_third_is_blocked():
    state = _researched_state()
    state["audit"] = {"issues": [_issue()]}
    state["retry_count"]["paper"] = 1
    assert supervisor_node(state)["retry_count"]["paper"] == 2
    state["retry_count"]["paper"] = 2
    assert decide_next(state) == ["evaluation_synthesis"]


def test_market_retry_success_marks_stakeholder_stale():
    state = _researched_state()
    state["route_reason"] = "audit_rework"
    result = wrap_worker("market_research", lambda _: {"market": {"version": 2},
                                                       "claims": []})(state)
    assert result["node_status"]["stakeholder_research"] == "stale"


def test_market_retry_failure_does_not_mark_stakeholder_stale():
    state = _researched_state()
    state["route_reason"] = "audit_rework"
    result = wrap_worker("market_research", lambda _: (_ for _ in ()).throw(
        RuntimeError("network")))(state)
    assert result["node_status"] == {"market_research": "failed"}


def test_dependency_refresh_precedes_audit_and_does_not_consume_retry():
    state = _researched_state()
    state["node_status"].update({"stakeholder_research": "stale",
                                 "evidence_audit": "stale"})
    before = dict(state["retry_count"])
    result = supervisor_node(state)
    assert result["next_nodes"] == ["stakeholder_research"]
    assert result["route_reason"] == "dependency_refresh"
    assert result.get("retry_count", before) == before
    assert result["audit"] == {"issues": []}


def test_dependency_refresh_reads_latest_market_and_counts_attempt():
    state = _researched_state()
    state["market"] = {"version": 2}
    state["node_status"]["stakeholder_research"] = "stale"
    state["node_attempts"]["stakeholder_research"] = 1
    worker = wrap_worker("stakeholder_research", lambda s: {
        "stakeholder": {"market_version": s["market"]["version"]}})
    result = worker(state)
    assert result["stakeholder"]["market_version"] == 2
    assert result["node_attempts"]["stakeholder_research"] == 2
    assert result["node_status"]["evidence_audit"] == "stale"


def test_worker_failure_recovers_without_research_retry():
    state = _researched_state()
    state["node_status"]["market_research"] = "failed"
    state["node_attempts"]["market_research"] = 1
    result = supervisor_node(state)
    assert result["next_nodes"] == ["market_research"]
    assert result["route_reason"] == "worker_recovery"
    assert result.get("retry_count", state["retry_count"])["market"] == 0


def test_worker_failure_is_skipped_at_attempt_limit():
    state = _researched_state()
    state["node_status"]["paper_analysis"] = "failed"
    state["node_attempts"]["paper_analysis"] = MAX_WORKER_ATTEMPTS
    result = supervisor_node(state)
    assert result["node_status"]["paper_analysis"] == "skipped"
    assert result["next_nodes"] == ["evaluation_synthesis"]


def test_quality_research_failure_uses_shared_retry_budget():
    state = _researched_state()
    state["node_status"].update({
        "evaluation_synthesis": "completed", "report_generation": "completed",
        "quality_evaluation": "completed",
    })
    state["quality"] = {
        "passed": False, "research_rework_targets": ["market"],
        "research_rework_requests": [{
            "claim_id": "MKT-01", "target_agent": "market",
            "action": "search_evidence", "reason": "quality_groundedness"}],
        "report_rewrite_required": False,
    }
    result = supervisor_node(state)
    assert result["next_nodes"] == ["market_research"]
    assert result["retry_count"]["market"] == 1
    assert result["route_reason"] == "quality_rework"


def test_quality_report_failure_only_rewrites_report():
    state = _researched_state()
    state["node_status"].update({
        "evaluation_synthesis": "completed", "report_generation": "completed",
        "quality_evaluation": "completed",
    })
    state["quality"] = {
        "passed": False, "research_rework_targets": [],
        "report_rewrite_required": True,
    }
    result = supervisor_node(state)
    assert result["next_nodes"] == ["report_generation"]
    assert result["route_reason"] == "quality_report_rewrite"


def test_quality_and_max_step_limits_terminate():
    state = _researched_state()
    state["node_status"]["quality_evaluation"] = "completed"
    state["quality"] = {"passed": False, "report_rewrite_required": True}
    state["quality_round"] = MAX_QUALITY_ROUNDS
    assert decide_next(state) == [END]
    state["step_count"] = state["max_steps"]
    assert decide_next(state) == [END]


def _run_stub_graph(monkeypatch, market_issue=False):
    import src.graph as graph_module
    calls, audit_runs = [], {"count": 0}

    def record(name, output):
        def node(state):
            calls.append((name, state.get("route_reason"), state.get("market", {}).get("version")))
            return output(state) if callable(output) else output
        return node

    def audit(_):
        audit_runs["count"] += 1
        issues = [_issue("market", "MKT-01")] if market_issue and audit_runs["count"] == 1 else []
        return {"audit": {"issues": issues}}

    monkeypatch.setattr(graph_module, "WORKERS", {
        "paper_analysis": record("paper_analysis", {
            "claims": [], "tech_sw": {"name": "KIVI"}, "tech_hw": {"name": "CXL"},
            "domain": {}}),
        "market_research": record("market_research", lambda s: {
            "claims": [], "market": {"version": s.get("market", {}).get("version", 0) + 1}}),
        "stakeholder_research": record("stakeholder_research", lambda s: {
            "stakeholder": {"market_version": s["market"]["version"]}}),
        "evidence_audit": record("evidence_audit", audit),
        "evaluation_synthesis": record("evaluation_synthesis", {"synthesis": {"ok": True}}),
        "report_generation": record("report_generation", {
            "report": "# SUMMARY\nneutral\n# REFERENCE"}),
        "quality_evaluation": record("quality_evaluation", {
            "quality": {"passed": True, "dimension_results": {
                "groundedness": True, "neutrality": True, "bias_control": True,
                "perspective_coverage": True}}, "quality_round": 1}),
    })
    return calls, graph_module.build_evaluation_graph().invoke(deepcopy(INITIAL_INPUT_STATE))


def test_graph_normal_flow_and_market_dependency_refresh(monkeypatch):
    calls, final = _run_stub_graph(monkeypatch, market_issue=True)
    names = [name for name, _, _ in calls]
    assert sorted(names[:2]) == ["market_research", "paper_analysis"]
    assert names.count("market_research") == 2
    assert names.count("stakeholder_research") == 2
    stakeholder_calls = [call for call in calls if call[0] == "stakeholder_research"]
    assert stakeholder_calls[-1][1] == "dependency_refresh"
    assert stakeholder_calls[-1][2] == 2
    assert final["retry_count"] == {"paper": 0, "market": 1, "stakeholder": 0}
    assert final["node_attempts"]["stakeholder_research"] == 2
    assert final["quality"]["passed"] is True
