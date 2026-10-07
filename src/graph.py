"""src/graph.py - Supervisor hub. Workers return only to evidence_audit."""
from langgraph.graph import StateGraph, START, END
from src.state import OverallState
from src.rag.agentic_rag import paper_analysis_node
from src.research.market import market_research_node
from src.research.stakeholder import stakeholder_research_node
from src.audit.auditor import evidence_audit_node
from src.synthesis.evaluator import evaluation_synthesis_node
from src.synthesis.report_gen import report_generation_node
from src.quality.quality_eval import quality_eval_node

MAX_QUALITY_ROUNDS = 3

_WORKER_NODES = {
    "paper": "paper_analysis",
    "market": "market_research",
    "stakeholder": "stakeholder_research",
}


def isolate_worker(agent: str, node):
    """워커 예외는 State에 남기고 Supervisor로 되돌린다."""
    def wrapped(state):
        try:
            result = node(state) or {}
        except Exception as exc:
            print(f"⚠️ [{agent}] 실행 실패, Supervisor로 격리: {exc}")
            return {"node_status": {agent: "failed"}, "last_error": {agent: str(exc)}}
        return {
            **result,
            "node_status": {agent: "complete"},
            "last_error": {agent: ""},
            "collect_seq": 1,
        }
    return wrapped


def route_quality(state: OverallState) -> str:
    """Rewrite the report while the hybrid gate fails and the round cap remains."""
    quality = state.get("quality") or {}
    if quality.get("passed") or (state.get("quality_round") or 0) >= MAX_QUALITY_ROUNDS:
        return END
    return "report_generation"


def route_supervisor(state: OverallState) -> list[str] | str:
    """Translate the Supervisor decision. This function does not choose the order."""
    decision = state.get("supervisor") or {}
    targets = [
        _WORKER_NODES[agent]
        for agent in ("paper", "market", "stakeholder")
        if agent in (decision.get("collect") or []) or agent in (decision.get("rework") or [])
    ]
    if targets:
        print(f"🔀 [라우터] Supervisor 판단 -> {targets}")
        return targets
    print("✅ [라우터] 근거 충분 -> 평가 종합으로 이동")
    return "evaluation_synthesis"


def build_evaluation_graph():
    """Workers communicate only with the evidence_audit Supervisor."""
    builder = StateGraph(OverallState)

    builder.add_node("paper_analysis", isolate_worker("paper", paper_analysis_node))
    builder.add_node("market_research", isolate_worker("market", market_research_node))
    builder.add_node("stakeholder_research", isolate_worker("stakeholder", stakeholder_research_node))
    builder.add_node("evidence_audit", evidence_audit_node)
    builder.add_node("evaluation_synthesis", evaluation_synthesis_node)
    builder.add_node("report_generation", report_generation_node)
    builder.add_node("quality_eval", quality_eval_node)

    builder.add_edge(START, "evidence_audit")
    builder.add_edge("paper_analysis", "evidence_audit")
    builder.add_edge("market_research", "evidence_audit")
    builder.add_edge("stakeholder_research", "evidence_audit")
    builder.add_conditional_edges(
        "evidence_audit",
        route_supervisor,
        {
            "paper_analysis": "paper_analysis",
            "market_research": "market_research",
            "stakeholder_research": "stakeholder_research",
            "evaluation_synthesis": "evaluation_synthesis",
        },
    )
    builder.add_edge("evaluation_synthesis", "report_generation")
    builder.add_edge("report_generation", "quality_eval")
    builder.add_conditional_edges(
        "quality_eval",
        route_quality,
        {"report_generation": "report_generation", END: END},
    )

    return builder.compile()
