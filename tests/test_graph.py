"""tests/test_graph.py - Supervisor 패턴 그래프 조립·라우팅·흐름 테스트"""
import pytest
from langgraph.graph import END

from src.graph import SUB_AGENTS, build_evaluation_graph
from src.supervisor.supervisor import decide, retry_targets
from tests.mock_data import INITIAL_INPUT_STATE

RESEARCH_DONE = {"paper_analysis": "done", "market_research": "done", "stakeholder_research": "done"}


def _issue(target, claim_id="X"):
    return {"claim_id": claim_id, "rule": "R1", "issue": "", "target_agent": target, "action": "search_evidence"}


# ── 그래프 구조: 허브-스포크, 하위 에이전트 간 직접 엣지 없음 ──

def test_graph_compilation_and_hub_and_spoke():
    graph = build_evaluation_graph()
    assert {"supervisor", *SUB_AGENTS}.issubset(set(graph.nodes.keys()))
    edges = graph.get_graph().edges
    for edge in edges:
        if edge.source in SUB_AGENTS:
            assert edge.target == "supervisor"
        if edge.target in SUB_AGENTS:
            assert edge.source == "supervisor"
            assert edge.conditional


# ── Supervisor 결정 로직 (State 기반 동적 라우팅) ──

def test_first_turn_dispatches_independent_perspectives_in_parallel():
    nxt, _, _ = decide({}, step=1, max_steps=20)
    assert sorted(nxt) == ["market_research", "paper_analysis"]


def test_stakeholder_waits_for_market_context():
    state = {"node_status": {"paper_analysis": "done", "market_research": "done"}}
    assert decide(state, 2, 20)[0] == ["stakeholder_research"]


def test_audit_after_all_perspectives():
    assert decide({"node_status": RESEARCH_DONE}, 3, 20)[0] == ["evidence_audit"]


def test_sufficient_evidence_goes_to_synthesis():
    state = {"node_status": {**RESEARCH_DONE, "evidence_audit": "done"}, "audit": {"issues": []}}
    nxt, reason, _ = decide(state, 4, 20)
    assert nxt == ["evaluation_synthesis"]
    assert "근거 충분" in reason


def test_insufficient_evidence_requests_rework_from_target_agent():
    state = {
        "node_status": {**RESEARCH_DONE, "evidence_audit": "done"},
        "audit": {"issues": [_issue("paper", "DOM-01")]},
        "retry_count": {"paper": 1, "market": 0, "stakeholder": 0},
    }
    nxt, _, updates = decide(state, 4, 20)
    assert nxt == ["paper_analysis"]
    assert updates == {"paper_analysis": "pending", "evidence_audit": "pending"}


def test_market_rework_cascades_to_stakeholder_after_market():
    state = {
        "node_status": {**RESEARCH_DONE, "evidence_audit": "done"},
        "audit": {"issues": [_issue("market", "MKT-01")]},
        "retry_count": {"paper": 0, "market": 1, "stakeholder": 0},
    }
    nxt, _, updates = decide(state, 4, 20)
    assert nxt == ["market_research"]
    assert updates["stakeholder_research"] == "pending"


def test_retry_limit_exhausted_goes_to_synthesis():
    state = {
        "node_status": {**RESEARCH_DONE, "evidence_audit": "done"},
        "audit": {"issues": [_issue("market")]},
        "retry_count": {"paper": 0, "market": 2, "stakeholder": 0},
    }
    assert retry_targets(state) == set()
    nxt, reason, _ = decide(state, 9, 20)
    assert nxt == ["evaluation_synthesis"]
    assert "한도" in reason


def test_failed_worker_is_retried_then_skipped():
    state = {"node_status": {"paper_analysis": "failed", "market_research": "done"},
             "node_attempts": {"paper_analysis": 1}}
    assert "paper_analysis" in decide(state, 2, 20)[0]
    state["node_attempts"] = {"paper_analysis": 2}
    nxt, _, updates = decide(state, 3, 20)
    assert updates["paper_analysis"] == "skipped"
    assert nxt == ["stakeholder_research"]


def test_quality_fail_loops_back_to_report_then_stops_at_limit():
    status = {**RESEARCH_DONE, "evidence_audit": "done", "evaluation_synthesis": "done",
              "report_generation": "done", "quality_eval": "done"}
    failed = {"passed": False, "checks": {"neutrality": {"passed": False}}}
    nxt, _, updates = decide({"node_status": status, "quality": failed, "quality_round": 1}, 8, 20)
    assert nxt == ["report_generation"]
    assert updates == {"report_generation": "pending", "quality_eval": "pending"}
    assert decide({"node_status": status, "quality": failed, "quality_round": 3}, 12, 20)[0] == [END]
    assert decide({"node_status": status, "quality": {"passed": True}, "quality_round": 1}, 8, 20)[0] == [END]


def test_step_limit_forces_termination():
    assert decide({}, step=21, max_steps=20)[0] == ["evaluation_synthesis"]
    status = {"evaluation_synthesis": "done", "report_generation": "done"}
    assert decide({"node_status": status}, 22, 20)[0] == [END]


# ── 스텁 노드로 전체 흐름 검증 ──

def _run_with_stub_nodes(monkeypatch, first_audit_targets, quality_results=(True,), fail_once=()):
    import src.graph as graph_module

    calls = []
    audit_runs = {"n": 0}
    quality_runs = {"n": 0}
    failed = set()

    def recorder(name):
        def node(state):
            calls.append(name)
            if name in fail_once and name not in failed:
                failed.add(name)
                raise RuntimeError("boom")
            return {}
        return node

    def stub_audit(state):
        calls.append("evidence_audit")
        audit_runs["n"] += 1
        if audit_runs["n"] > 1:
            return {"audit": {"issues": []}}
        retry = dict(state["retry_count"])
        for target in first_audit_targets:
            retry[target] += 1
        return {"audit": {"issues": [_issue(t) for t in first_audit_targets]}, "retry_count": retry}

    def stub_quality(state):
        calls.append("quality_eval")
        passed = quality_results[min(quality_runs["n"], len(quality_results) - 1)]
        quality_runs["n"] += 1
        return {"quality": {"passed": passed, "checks": {}, "feedback": []},
                "quality_round": state.get("quality_round", 0) + 1}

    for attr, name in [
        ("paper_analysis_node", "paper_analysis"),
        ("market_research_node", "market_research"),
        ("stakeholder_research_node", "stakeholder_research"),
        ("evaluation_synthesis_node", "evaluation_synthesis"),
        ("report_generation_node", "report_generation"),
    ]:
        monkeypatch.setattr(graph_module, attr, recorder(name))
    monkeypatch.setattr(graph_module, "evidence_audit_node", stub_audit)
    monkeypatch.setattr(graph_module, "quality_eval_node", stub_quality)

    final = graph_module.build_evaluation_graph().invoke(INITIAL_INPUT_STATE)
    return calls, final


def test_flow_first_run_order(monkeypatch):
    calls, final = _run_with_stub_nodes(monkeypatch, [])
    assert sorted(calls[:2]) == ["market_research", "paper_analysis"]
    assert calls[2:] == ["stakeholder_research", "evidence_audit", "evaluation_synthesis",
                         "report_generation", "quality_eval"]
    assert final["step_count"] <= final["max_steps"]


def test_flow_market_retry_cascades_to_stakeholder(monkeypatch):
    calls, _ = _run_with_stub_nodes(monkeypatch, ["market"])
    assert calls[4:] == ["market_research", "stakeholder_research", "evidence_audit",
                         "evaluation_synthesis", "report_generation", "quality_eval"]


def test_flow_paper_only_retry(monkeypatch):
    calls, _ = _run_with_stub_nodes(monkeypatch, ["paper"])
    assert calls[4:] == ["paper_analysis", "evidence_audit", "evaluation_synthesis",
                         "report_generation", "quality_eval"]


def test_flow_parallel_market_and_paper_retry_audits_once_per_round(monkeypatch):
    calls, _ = _run_with_stub_nodes(monkeypatch, ["market", "paper"])
    assert calls.count("evidence_audit") == 2
    retry = calls[4:]
    assert sorted(retry[:2]) == ["market_research", "paper_analysis"]
    assert retry[2:] == ["stakeholder_research", "evidence_audit", "evaluation_synthesis",
                         "report_generation", "quality_eval"]


def test_flow_quality_fail_regenerates_report(monkeypatch):
    calls, final = _run_with_stub_nodes(monkeypatch, [], quality_results=(False, True))
    assert calls.count("report_generation") == 2
    assert calls.count("quality_eval") == 2
    assert final["quality"]["passed"] is True


def test_flow_quality_never_passes_terminates(monkeypatch):
    calls, _ = _run_with_stub_nodes(monkeypatch, [], quality_results=(False,))
    assert calls.count("quality_eval") == 3


def test_flow_worker_exception_is_retried(monkeypatch):
    calls, final = _run_with_stub_nodes(monkeypatch, [], fail_once=("market_research",))
    assert calls.count("market_research") == 2
    assert final["node_status"]["market_research"] == "done"
    assert "market_research" in final["last_error"]


@pytest.mark.slow
def test_graph_end_to_end_execution():
    graph = build_evaluation_graph()
    final_state = graph.invoke(INITIAL_INPUT_STATE)
    assert len(final_state["report"]) > 0
    assert "KIVI" in final_state["trl"] and "CXL-PNM" in final_state["trl"]
    assert len(final_state["claims"]) >= 4
    assert "quality" in final_state
