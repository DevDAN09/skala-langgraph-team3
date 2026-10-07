"""Supervisor graph topology and routing contracts."""
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from src.graph import build_evaluation_graph
from src.supervisor import MAX_STEPS, route_supervisor, supervisor_node
from src.synthesis.quality import route_quality
from tests.mock_data import INITIAL_INPUT_STATE, MOCK_STATE


def test_graph_compilation_includes_supervisor_and_quality_gate():
    graph = build_evaluation_graph()
    assert {"supervisor", "paper_analysis", "market_research", "stakeholder_research",
            "evaluation_synthesis", "report_generation", "quality_eval"} <= set(graph.nodes)


def test_graph_accepts_in_process_checkpointer():
    saver = InMemorySaver()
    assert build_evaluation_graph(checkpointer=saver).checkpointer is saver


def test_compiled_topology_routes_research_only_through_supervisor():
    edges = {(edge.source, edge.target) for edge in build_evaluation_graph().get_graph().edges}
    research = {"paper_analysis", "market_research", "stakeholder_research"}
    assert ("__start__", "supervisor") in edges
    assert {(agent, "supervisor") for agent in research} <= edges
    assert not {(source, target) for source, target in edges if source in research and target in research}
    assert ("evaluation_synthesis", "report_generation") in edges
    assert ("report_generation", "quality_eval") in edges


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
    assert result["next_agent"] == "evaluation_synthesis"
    assert route_supervisor(result) == "evaluation_synthesis"


def test_dispatch_retry_counts_only_selected_agent(monkeypatch):
    import src.supervisor as supervisor
    issues = [{"claim_id": "DOM-01", "rule": "R1", "issue": "", "target_agent": agent, "action": "search_evidence"} for agent in ("paper", "market")]
    monkeypatch.setattr(supervisor, "evidence_audit_node", lambda state: {"audit": {"issues": issues}})
    state = {**MOCK_STATE, "retry_count": {"paper": 0, "market": 0, "stakeholder": 0}}
    result = supervisor_node(state)
    selected = result["next_agent"].removesuffix("_analysis").removesuffix("_research")
    assert result["retry_count"][selected] == 1
    assert sum(result["retry_count"].values()) == 1


def test_market_retry_marks_stakeholder_stale_only_after_success(monkeypatch):
    import src.supervisor as supervisor
    issue = {"claim_id": "MKT-01", "rule": "R1", "issue": "", "target_agent": "market", "action": "search_evidence"}
    monkeypatch.setattr(supervisor, "evidence_audit_node", lambda state: {"audit": {"issues": [issue]}})
    state = {**MOCK_STATE, "node_status": {"paper": "complete", "market": "complete", "stakeholder": "complete"}}
    result = supervisor_node(state)
    assert result["next_agent"] == "market_research"
    assert "node_status" not in result or result["node_status"]["stakeholder"] == "complete"
    import src.graph as graph_module
    completed = graph_module._supervised(lambda _: {"market": {"version": 2}}, "market")(
        {**state, **result})
    assert completed["node_status"]["stakeholder"] == "stale"


def test_market_retry_failure_does_not_stale_stakeholder(monkeypatch):
    import src.graph as graph_module
    state = {**MOCK_STATE,
             "last_decision": {"reason": "audit"},
             "node_status": {"paper": "complete", "market": "complete", "stakeholder": "complete"},
             "node_attempts": {"paper": 0, "market": 0, "stakeholder": 0}}
    result = graph_module._supervised(
        lambda _: (_ for _ in ()).throw(RuntimeError("network")), "market")(state)
    assert result["node_status"]["stakeholder"] == "complete"


def test_stakeholder_dependency_refresh_does_not_consume_retry_and_counts_attempt(monkeypatch):
    import src.graph as graph_module
    import src.supervisor as supervisor
    monkeypatch.setattr(supervisor, "evidence_audit_node", lambda state: {"audit": {"issues": []}})
    state = {**MOCK_STATE,
             "market": {"version": 2},
             "node_status": {"paper": "complete", "market": "complete", "stakeholder": "stale"},
             "node_attempts": {"paper": 1, "market": 2, "stakeholder": 1},
             "retry_count": {"paper": 0, "market": 1, "stakeholder": 0}}
    decision = supervisor_node(state)
    assert decision["next_agent"] == "stakeholder_research"
    assert decision.get("retry_count", state["retry_count"])["stakeholder"] == 0
    refreshed = graph_module._supervised(
        lambda current: {"stakeholder": {"market_version": current["market"]["version"]}},
        "stakeholder")({**state, **decision})
    assert refreshed["stakeholder"]["market_version"] == 2
    assert refreshed["node_attempts"]["stakeholder"] == 2


def test_quality_rework_dispatch_increments_only_target_retry(monkeypatch):
    import src.supervisor as supervisor
    monkeypatch.setattr(supervisor, "evidence_audit_node", lambda state: {"audit": {"issues": []}})
    state = {**MOCK_STATE,
             "quality": {"passed": False, "rework_targets": ["market"], "attempts": 1},
             "node_status": {"paper": "complete", "market": "complete", "stakeholder": "complete"}}
    result = supervisor_node(state)
    assert result["next_agent"] == "market_research"
    assert result["retry_count"] == {"paper": 0, "market": 1, "stakeholder": 0}
    assert result["last_decision"]["reason"] == "quality"


def test_quality_reports_all_four_scores():
    from src.synthesis.quality import quality_evaluation_node
    result = quality_evaluation_node({**MOCK_STATE, "report": "# SUMMARY\n# REFERENCES"})["quality"]
    assert set(result["scores"]) == {"groundedness", "neutrality", "bias_control", "coverage"}


def test_quality_coverage_uses_only_valid_claims_and_reports_target():
    from src.synthesis.quality import quality_evaluation_node
    claims = [{**claim, "status": "insufficient"} for claim in MOCK_STATE["claims"]]
    result = quality_evaluation_node({**MOCK_STATE, "claims": claims,
                                      "report": "# SUMMARY\n# REFERENCE"})["quality"]
    assert result["scores"]["coverage"] is False
    assert {"paper", "market", "stakeholder"} <= set(result["rework_targets"])
    assert "maturity:KIVI" in result["coverage_gaps"]


def test_quality_reference_and_neutrality_rules():
    from src.synthesis.quality import quality_evaluation_node
    base = {**MOCK_STATE, "claims": [], "report": "# SUMMARY\n# REFERENCE\n우열을 판정하지 않는다. 특정 기술을 추천하지 않는다."}
    assert quality_evaluation_node(base)["quality"]["scores"]["neutrality"] is True
    assert "REFERENCE" in quality_evaluation_node({**base, "report": "# SUMMARY"})["quality"]["failures"]
    assert quality_evaluation_node({**base, "report": "KIVI를 추천한다"})["quality"]["scores"]["neutrality"] is False


def test_quality_bias_control_requires_diverse_sources_for_multiple_external_claims():
    from src.synthesis.quality import quality_evaluation_node
    claims = [claim for claim in MOCK_STATE["claims"] if claim["id"] in {"MKT-01", "MKT-02"}]
    evidence = [item for item in MOCK_STATE["evidence"] if item["evidence_id"] in {"EV-MKT-01", "EV-MKT-02"}]
    evidence[1] = {**evidence[1], "source_id": "SRC-MKT-01"}
    result = quality_evaluation_node({**MOCK_STATE, "claims": claims, "evidence": evidence, "sources": [MOCK_STATE["sources"][2]], "report": "# SUMMARY\n# REFERENCE"})["quality"]
    assert result["scores"]["bias_control"] is False


def test_quality_bias_control_allows_diverse_or_single_external_claims_without_counter_evidence():
    from src.synthesis.quality import quality_evaluation_node
    claims = [claim for claim in MOCK_STATE["claims"] if claim["id"] in {"MKT-01", "MKT-02"}]
    evidence = [item for item in MOCK_STATE["evidence"] if item["evidence_id"] in {"EV-MKT-01", "EV-MKT-02"}]
    sources = [item for item in MOCK_STATE["sources"] if item["source_id"] in {"SRC-MKT-01", "SRC-MKT-02"}]
    state = {**MOCK_STATE, "claims": claims, "evidence": evidence, "sources": sources, "report": "# SUMMARY\n# REFERENCE"}
    assert quality_evaluation_node(state)["quality"]["scores"]["bias_control"] is True
    assert quality_evaluation_node({**state, "claims": claims[:1]})["quality"]["scores"]["bias_control"] is True


def test_quality_bias_control_does_not_require_counter_search_for_paper_claims():
    from src.synthesis.quality import quality_evaluation_node
    claim = next(claim for claim in MOCK_STATE["claims"] if claim["id"] == "DOM-01")
    result = quality_evaluation_node({**MOCK_STATE, "claims": [claim], "report": "# SUMMARY\n# REFERENCE"})["quality"]
    assert result["scores"]["bias_control"] is True


def test_supervisor_audits_once_per_research_step(monkeypatch):
    import src.supervisor as supervisor
    calls = []
    monkeypatch.setattr(supervisor, "evidence_audit_node", lambda state: calls.append(state["step_count"]) or {"audit": {"issues": []}})
    state = {**MOCK_STATE, "last_audited_step": MOCK_STATE["step_count"]}
    supervisor_node(state)
    assert calls == []


def test_worker_error_isolated_and_returns_to_supervisor(monkeypatch):
    import src.graph as graph_module
    wrapped = graph_module._supervised(lambda state: (_ for _ in ()).throw(RuntimeError("boom")), "paper")
    result = wrapped(INITIAL_INPUT_STATE)
    assert result["node_status"]["paper"] == "pending"
    assert result["node_attempts"]["paper"] == 1
    assert "paper: boom" in result["last_error"]
    assert result["last_errors"]["paper"] == result["last_error"]


def test_successful_worker_attempt_is_counted():
    import src.graph as graph_module
    result = graph_module._supervised(lambda _: {}, "paper")(INITIAL_INPUT_STATE)
    assert result["node_attempts"]["paper"] == 1


def test_worker_repeated_error_becomes_failed_without_further_retry():
    import src.graph as graph_module
    wrapped = graph_module._supervised(lambda state: (_ for _ in ()).throw(RuntimeError("boom")), "paper")
    first = wrapped(INITIAL_INPUT_STATE)
    second = wrapped({**INITIAL_INPUT_STATE, **first})
    assert second["node_status"]["paper"] == "failed"
    assert second["node_attempts"]["paper"] == 2


def test_supervisor_terminalizes_only_after_second_retry_returns_and_fails(monkeypatch):
    import src.supervisor as supervisor
    issue = {"claim_id": "DOM-01", "rule": "R1", "issue": "", "target_agent": "paper", "action": "search_evidence"}
    monkeypatch.setattr(supervisor, "evidence_audit_node", lambda state: {"audit": {"issues": [issue]}})
    state = {**MOCK_STATE, "node_status": {"paper": "complete", "market": "complete", "stakeholder": "complete"}}
    retry_one = supervisor_node(state)
    assert retry_one["retry_count"]["paper"] == 1
    retry_two = supervisor_node({**state, **retry_one, "node_status": {"paper": "complete", "market": "complete", "stakeholder": "complete"}})
    assert retry_two["retry_count"]["paper"] == 2
    assert "claims" not in retry_two or all(claim["status"] == "flagged" for claim in retry_two["claims"])
    final = supervisor_node({**state, **retry_two, "node_status": {"paper": "complete", "market": "complete", "stakeholder": "complete"}})
    assert final["next_agent"] == "evaluation_synthesis"
    assert next(claim for claim in final["claims"] if claim["id"] == "DOM-01")["status"] == "insufficient"


def test_second_retry_can_restore_ok_before_terminalization(monkeypatch):
    import src.supervisor as supervisor
    issue = {"claim_id": "DOM-01", "rule": "R1", "issue": "", "target_agent": "paper", "action": "search_evidence"}
    monkeypatch.setattr(supervisor, "evidence_audit_node", lambda state: {"audit": {"issues": [issue]} if state["retry_count"]["paper"] < 2 else []})
    state = {**MOCK_STATE, "node_status": {"paper": "complete", "market": "complete", "stakeholder": "complete"}}
    retry_one = supervisor_node(state)
    retry_two = supervisor_node({**state, **retry_one, "node_status": state["node_status"]})
    resolved_claims = [{**claim, "status": "ok"} if claim["id"] == "DOM-01" else claim for claim in MOCK_STATE["claims"]]
    final = supervisor_node({**state, **retry_two, "claims": resolved_claims, "node_status": state["node_status"]})
    assert next(claim for claim in final["claims"] if claim["id"] == "DOM-01")["status"] == "ok"


def test_compiled_graph_mocked_e2e(monkeypatch):
    import src.graph as graph_module
    calls = []
    def worker(name):
        return lambda state: calls.append(name) or {}
    monkeypatch.setattr(graph_module, "paper_analysis_node", worker("paper_analysis"))
    monkeypatch.setattr(graph_module, "market_research_node", worker("market_research"))
    monkeypatch.setattr(graph_module, "stakeholder_research_node", worker("stakeholder_research"))
    monkeypatch.setattr(graph_module, "evaluation_synthesis_node", worker("evaluation_synthesis"))
    monkeypatch.setattr(graph_module, "report_generation_node", lambda state: calls.append("report_generation") or {"report": "# SUMMARY\n# REFERENCE"})
    monkeypatch.setattr(graph_module, "quality_evaluation_node", lambda state: calls.append("quality_eval") or {"quality": {"passed": True, "attempts": 1}})
    final_state = graph_module.build_evaluation_graph().invoke(INITIAL_INPUT_STATE)
    assert {"paper_analysis", "market_research", "stakeholder_research", "evaluation_synthesis", "report_generation", "quality_eval"} <= set(calls)
    assert final_state["report"] and final_state["quality"]["attempts"] == 1
    assert final_state["step_count"] <= MAX_STEPS and final_state["next_agent"] == "evaluation_synthesis"


def test_compiled_graph_quality_research_rework_returns_through_supervisor(monkeypatch):
    import src.graph as graph_module
    calls = []
    monkeypatch.setattr(graph_module, "paper_analysis_node", lambda state: calls.append("paper") or {})
    monkeypatch.setattr(graph_module, "market_research_node", lambda state: calls.append("market") or {})
    monkeypatch.setattr(graph_module, "stakeholder_research_node", lambda state: calls.append("stakeholder") or {})
    monkeypatch.setattr(graph_module, "evaluation_synthesis_node", lambda state: calls.append("synthesis") or {})
    monkeypatch.setattr(graph_module, "report_generation_node", lambda state: calls.append("report") or {"report": "# SUMMARY\n# REFERENCE"})
    outcomes = iter(({"quality": {"passed": False, "failures": ["groundedness"], "rework_targets": ["paper"], "attempts": 1}}, {"quality": {"passed": True, "failures": [], "attempts": 2}}))
    monkeypatch.setattr(graph_module, "quality_evaluation_node", lambda state: calls.append("quality") or next(outcomes))
    final = graph_module.build_evaluation_graph().invoke(INITIAL_INPUT_STATE)
    assert calls.count("paper") == 2 and calls.count("quality") == 2
    assert calls.index("synthesis") < calls.index("report") < calls.index("quality")
    assert final["quality"]["passed"] is True and final["step_count"] <= MAX_STEPS


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
