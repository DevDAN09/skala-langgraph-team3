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


def test_market_retry_marks_completed_stakeholder_stale(monkeypatch):
    import src.supervisor as supervisor
    issue = {"claim_id": "MKT-01", "rule": "R1", "issue": "", "target_agent": "market", "action": "search_evidence"}
    monkeypatch.setattr(supervisor, "evidence_audit_node", lambda state: {"audit": {"issues": [issue]}})
    state = {**MOCK_STATE, "node_status": {"paper": "complete", "market": "complete", "stakeholder": "complete"}}
    result = supervisor_node(state)
    assert result["next_agent"] == "market_research"
    assert result["node_status"]["stakeholder"] == "stale"


def test_quality_reports_all_four_scores():
    from src.synthesis.quality import quality_evaluation_node
    result = quality_evaluation_node({**MOCK_STATE, "report": "# SUMMARY\n# REFERENCES"})["quality"]
    assert set(result["scores"]) == {"groundedness", "neutrality", "bias_control", "coverage"}


def test_quality_reference_and_neutrality_rules():
    from src.synthesis.quality import quality_evaluation_node
    base = {**MOCK_STATE, "claims": [], "report": "# SUMMARY\n# REFERENCE\n우열을 판정하지 않는다. 특정 기술을 추천하지 않는다."}
    assert quality_evaluation_node(base)["quality"]["scores"]["neutrality"] is True
    assert "REFERENCE" in quality_evaluation_node({**base, "report": "# SUMMARY"})["quality"]["failures"]
    assert quality_evaluation_node({**base, "report": "KIVI를 추천한다"})["quality"]["scores"]["neutrality"] is False


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


def _cell_claim(cid, perspective, tech, status="ok"):
    return {"id": cid, "perspective": perspective, "tech": tech, "statement": "s", "kind": "fact",
            "evidence_ids": [], "counter_evidence_ids": [], "counter_searched": True, "status": status}


def test_quality_coverage_is_per_technology_and_accepts_disclosed_gaps():
    from src.synthesis.quality import quality_evaluation_node
    claims = [_cell_claim(f"X-{p}-{t}", p, t) for p in ("domain", "maturity", "market", "stakeholder")
              for t in ("KIVI", "CXL-PNM") if (p, t) != ("market", "KIVI")]
    claims.append(_cell_claim("MKT-01", "market", "KIVI", status="insufficient"))
    report = "## SUMMARY\n## 6. 한계점 및 Evidence Gap\n- 없음\n## REFERENCE\n"
    quality = quality_evaluation_node({**MOCK_STATE, "claims": claims, "report": report})["quality"]
    assert quality["scores"]["coverage"] is False and quality["uncovered"] == ["KIVI/market"]
    assert "market" in quality["rework_targets"]

    disclosed = report.replace("- 없음", "- **[MKT-01]** 공개 근거 미확인 (상태: `insufficient`)")
    quality = quality_evaluation_node({**MOCK_STATE, "claims": claims, "report": disclosed})["quality"]
    assert quality["scores"]["coverage"] is True and quality["uncovered"] == []


def test_quality_format_failures_route_to_report_generation():
    from src.synthesis.quality import quality_evaluation_node
    base = {**MOCK_STATE, "claims": []}
    fenced = quality_evaluation_node({**base, "report": "```markdown\n## SUMMARY\n## REFERENCE\n[1] a\n```"})["quality"]
    assert "FORMAT_CODE_FENCE" in fenced["failures"]
    dangling = quality_evaluation_node({**base, "report": "## SUMMARY\n본문 [62]\n## REFERENCE\n[1] a\n"})["quality"]
    assert "DANGLING_CITATION" in dangling["failures"]
    assert route_quality({"quality": {"passed": False, "failures": ["DANGLING_CITATION"], "attempts": 1}}) == "report_generation"
