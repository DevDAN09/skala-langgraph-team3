"""tests/test_graph.py - Supervisor 패턴 그래프 조립, decide() 라우팅, 흐름 테스트"""
import pytest
from langgraph.graph import END
from src.graph import build_evaluation_graph
from src.supervisor import supervisor as sup
from src.supervisor.supervisor import decide, supervisor_node, MAX_STEPS
from tests.mock_data import INITIAL_INPUT_STATE

WORKERS = {"paper_analysis", "market_research", "stakeholder_research",
           "evaluation_synthesis", "report_generation", "quality_eval"}
REPORTED = {**{"paper_analysis": "done", "market_research": "done", "stakeholder_research": "done"},
            "evaluation_synthesis": "done", "report_generation": "done", "quality_eval": "done"}
COLLECTED = {"paper_analysis": "done", "market_research": "done", "stakeholder_research": "done"}


def _issue(target, claim_id="X", rule="R1"):
    return {"claim_id": claim_id, "rule": rule, "issue": "", "target_agent": target, "action": "search_evidence"}


def _state(status=None, issues=(), retry=None, **kw):
    return {**INITIAL_INPUT_STATE, "node_status": dict(status or {}), "audit": {"issues": list(issues)},
            "retry_count": {"paper": 0, "market": 0, "stakeholder": 0, **(retry or {})}, **kw}


# ── 그래프 구조 ─────────────────────────────────────────

def test_graph_compilation():
    graph = build_evaluation_graph()
    assert set(graph.nodes) - {"__start__"} == WORKERS | {"supervisor"}


def test_no_direct_edges_between_workers():
    """하위 에이전트 간 직접 통신 금지: 모든 엣지의 한쪽 끝은 supervisor다."""
    for edge in build_evaluation_graph().get_graph().edges:
        assert "supervisor" in (edge.source, edge.target), edge


# ── decide(): State 기반 라우팅 ──────────────────────────

def test_decide_initial_dispatches_paper_and_market_in_parallel():
    nxt, _, _ = decide(_state())
    assert nxt == ["paper_analysis", "market_research"]


def test_decide_stakeholder_after_market():
    nxt, _, _ = decide(_state({"paper_analysis": "done", "market_research": "done"}))
    assert nxt == ["stakeholder_research"]


def test_decide_clear_audit_goes_to_synthesis_report_quality_then_end():
    assert decide(_state(COLLECTED))[0] == ["evaluation_synthesis"]
    assert decide(_state({**COLLECTED, "evaluation_synthesis": "done"}))[0] == ["report_generation"]
    assert decide(_state({**COLLECTED, "evaluation_synthesis": "done", "report_generation": "done"}))[0] == ["quality_eval"]
    assert decide(_state(REPORTED))[0] == END


def _eval(passed, target=None):
    return {"passed": passed, "stage": "rules", "target": target, "feedback": "",
            "items": {"neutrality": {"passed": passed, "score": None, "failures": [], "quotes": []}}}


def test_decide_quality_pass_ends():
    nxt, reason, _ = decide(_state(REPORTED, report_eval=_eval(True)))
    assert nxt == END and "통과" in reason


def test_decide_quality_fail_rewrites_report():
    nxt, _, extra = decide(_state(REPORTED, report_eval=_eval(False, "report_generation")))
    assert nxt == ["report_generation"]
    assert extra["retry_count"]["report"] == 1
    assert extra["node_status"] == {"quality_eval": "stale"}


def test_decide_quality_fail_recollects_with_downstream_stale():
    nxt, _, extra = decide(_state(REPORTED, report_eval=_eval(False, "market_research")))
    assert nxt == ["market_research"]
    assert extra["retry_count"]["market"] == 1
    assert extra["node_status"] == {"evaluation_synthesis": "stale", "report_generation": "stale",
                                    "quality_eval": "stale", "stakeholder_research": "stale"}


def test_decide_quality_fail_without_target_ends():
    nxt, reason, _ = decide(_state(REPORTED, report_eval=_eval(False, None)))
    assert nxt == END and "6.3" in reason


def test_decide_market_retry_marks_stakeholder_stale():
    nxt, reason, extra = decide(_state(COLLECTED, [_issue("market", "MKT-01"), _issue("stakeholder")],
                                       retry={"market": 1, "stakeholder": 1}))
    assert nxt == ["market_research"]
    assert extra["node_status"] == {"stakeholder_research": "stale"}
    assert "MKT-01" in reason


def test_decide_stale_stakeholder_reruns_after_market():
    nxt, _, _ = decide(_state({**COLLECTED, "stakeholder_research": "stale"}, [_issue("market")], retry={"market": 1}))
    assert nxt == ["stakeholder_research"]


def test_decide_stakeholder_only_and_paper_only():
    assert decide(_state(COLLECTED, [_issue("stakeholder")], retry={"stakeholder": 1}))[0] == ["stakeholder_research"]
    assert decide(_state(COLLECTED, [_issue("paper")], retry={"paper": 1}))[0] == ["paper_analysis"]


def test_decide_market_and_paper_retry_in_parallel():
    nxt, _, _ = decide(_state(COLLECTED, [_issue("market"), _issue("paper")], retry={"market": 1, "paper": 1}))
    assert nxt == ["market_research", "paper_analysis"]


def test_decide_retries_exhausted_isolates_gap_and_synthesizes():
    nxt, reason, _ = decide(_state(COLLECTED, [_issue("market")], retry={"market": 2}))
    assert nxt == ["evaluation_synthesis"]
    assert "Evidence Gap" in reason


def test_decide_failed_node_retries_then_skips():
    nxt, _, extra = decide(_state({**COLLECTED, "market_research": "failed"}))
    assert nxt == ["market_research"]
    assert extra["retry_count"]["market"] == 1

    nxt, _, extra = decide(_state({**COLLECTED, "market_research": "failed"}, retry={"market": 2}))
    assert extra["node_status"] == {"market_research": "skipped"}
    assert nxt == ["evaluation_synthesis"]


def test_decide_step_limit_terminates():
    assert decide(_state(step_count=MAX_STEPS))[0] == ["report_generation"]
    assert decide(_state({"report_generation": "done"}, step_count=MAX_STEPS))[0] == END


# ── supervisor_node(): 검증 시점 ─────────────────────────

def test_supervisor_audits_only_after_collection_settles(monkeypatch):
    runs = []
    monkeypatch.setattr(sup, "evidence_audit_node", lambda s: runs.append(1) or {"audit": {"issues": []}})

    # 이해관계자가 아직 남아 있으면 검증하지 않는다
    supervisor_node(_state({"paper_analysis": "done", "market_research": "done"}, collect_seq=2))
    assert runs == []

    out = supervisor_node(_state(COLLECTED, collect_seq=3))
    assert runs == [1] and out["audited_seq"] == 3
    assert out["last_decision"]["next"] == ["evaluation_synthesis"]

    # 새 수집 결과가 없으면 다시 검증하지 않는다
    supervisor_node(_state({**COLLECTED, "evaluation_synthesis": "done"}, collect_seq=3, audited_seq=3))
    assert runs == [1]


# ── 흐름: 실제 그래프 + 스텁 노드 ───────────────────────

def _run_with_stub_nodes(monkeypatch, audit_targets_per_pass, fail=(), quality=None):
    """하위 노드를 호출 순서만 기록하는 스텁으로, 검증을 지정한 이슈를 내는 스텁으로 바꿔 흐름만 검증한다."""
    import src.graph as graph_module

    calls, audits = [], []

    def recorder(name):
        def node(state):
            calls.append(name)
            if name in fail:
                raise RuntimeError("boom")
            return {}
        return node

    def stub_audit(state):
        targets = audit_targets_per_pass[len(audits)] if len(audits) < len(audit_targets_per_pass) else []
        audits.append(targets)
        retry = dict(state["retry_count"])
        for t in set(targets):
            retry[t] = retry.get(t, 0) + 1
        return {"audit": {"issues": [_issue(t) for t in targets]}, "retry_count": retry}

    for name in WORKERS:
        monkeypatch.setattr(graph_module, f"{name}_node", recorder(name))
    if quality:
        def stub_quality(state):
            calls.append("quality_eval")
            return {"report_eval": quality(state)}
        monkeypatch.setattr(graph_module, "quality_eval_node", stub_quality)
    monkeypatch.setattr(sup, "evidence_audit_node", stub_audit)

    final = graph_module.build_evaluation_graph().invoke(INITIAL_INPUT_STATE)
    return calls, audits, final


def test_flow_first_run_order(monkeypatch):
    calls, audits, _ = _run_with_stub_nodes(monkeypatch, [])
    assert sorted(calls[:2]) == ["market_research", "paper_analysis"]
    assert calls[2:] == ["stakeholder_research", "evaluation_synthesis", "report_generation", "quality_eval"]
    assert len(audits) == 1


def test_flow_market_retry_cascades_to_stakeholder(monkeypatch):
    calls, audits, _ = _run_with_stub_nodes(monkeypatch, [["market"]])
    assert calls[3:] == ["market_research", "stakeholder_research", "evaluation_synthesis", "report_generation", "quality_eval"]
    assert len(audits) == 2


def test_flow_paper_only_retry(monkeypatch):
    calls, audits, _ = _run_with_stub_nodes(monkeypatch, [["paper"]])
    assert calls[3:] == ["paper_analysis", "evaluation_synthesis", "report_generation", "quality_eval"]
    assert len(audits) == 2


def test_flow_parallel_market_and_paper_retry_audits_once(monkeypatch):
    calls, audits, _ = _run_with_stub_nodes(monkeypatch, [["market", "paper"]])
    retry = calls[3:]
    assert sorted(retry[:2]) == ["market_research", "paper_analysis"]
    assert retry[2:] == ["stakeholder_research", "evaluation_synthesis", "report_generation", "quality_eval"]
    assert len(audits) == 2


def test_flow_parallel_stakeholder_and_paper_retry(monkeypatch):
    calls, audits, _ = _run_with_stub_nodes(monkeypatch, [["stakeholder", "paper"]])
    retry = calls[3:]
    assert sorted(retry[:2]) == ["paper_analysis", "stakeholder_research"]
    assert retry[2:] == ["evaluation_synthesis", "report_generation", "quality_eval"]
    assert len(audits) == 2


def test_flow_always_failing_audit_terminates(monkeypatch):
    calls, audits, final = _run_with_stub_nodes(monkeypatch, [["market"]] * 10)
    assert calls.count("report_generation") == 1
    assert calls.count("market_research") == 2  # 최초 1 + 재작업 1 (RETRY_LIMIT=2, audit가 먼저 +1)
    assert final["last_decision"]["next"] == END


def test_flow_failing_node_is_retried_then_skipped(monkeypatch):
    calls, _, final = _run_with_stub_nodes(monkeypatch, [], fail={"market_research"})
    assert calls.count("market_research") == 3  # 최초 1 + 재시도 2
    assert final["node_status"]["market_research"] == "skipped"
    assert "market_research" in final["last_error"]
    assert calls[-1] == "quality_eval"


@pytest.mark.deprecated
@pytest.mark.skip(reason="deprecated: 외부 API 요청")
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


def _quality_fail(target_fn, passes_after=None):
    seen = {"n": 0}

    def judge(state):
        seen["n"] += 1
        if passes_after is not None and seen["n"] > passes_after:
            return _eval(True)
        return _eval(False, target_fn(state))
    return judge


def test_flow_quality_fail_rewrites_then_passes(monkeypatch):
    calls, _, final = _run_with_stub_nodes(
        monkeypatch, [], quality=_quality_fail(lambda s: "report_generation", passes_after=1))
    assert calls[5:] == ["quality_eval", "report_generation", "quality_eval"]
    assert final["last_decision"]["reason"].startswith("품질 평가 통과")


def test_flow_quality_always_failing_stops_at_revision_limit(monkeypatch):
    from src.quality.node import pick_target
    from src.quality.criteria import REPORT_REVISION_LIMIT
    calls, _, final = _run_with_stub_nodes(monkeypatch, [], quality=_quality_fail(lambda s: pick_target(s, [])))
    assert calls.count("report_generation") == 1 + REPORT_REVISION_LIMIT
    assert calls.count("quality_eval") == 1 + REPORT_REVISION_LIMIT
    assert final["last_decision"]["next"] == END


def test_flow_quality_fail_recollects_market_and_cascades(monkeypatch):
    calls, audits, _ = _run_with_stub_nodes(
        monkeypatch, [], quality=_quality_fail(lambda s: "market_research", passes_after=1))
    assert calls[6:] == ["market_research", "stakeholder_research", "evaluation_synthesis",
                         "report_generation", "quality_eval"]
    assert len(audits) == 2
