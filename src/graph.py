"""src/graph.py - Supervisor hub. Workers return only to evidence_audit."""
from langgraph.graph import StateGraph, START, END
from src.state import OverallState
from src.rag.agentic_rag import paper_analysis_node
from src.research.market import market_research_node
from src.research.stakeholder import stakeholder_research_node
from src.audit.auditor import evidence_audit_node
from src.synthesis.evaluator import evaluation_synthesis_node
from src.synthesis.report_gen import report_generation_node

_WORKER_NODES = {
    "paper": "paper_analysis",
    "market": "market_research",
    "stakeholder": "stakeholder_research",
}


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

    builder.add_node("paper_analysis", paper_analysis_node)
    builder.add_node("market_research", market_research_node)
    builder.add_node("stakeholder_research", stakeholder_research_node)
    builder.add_node("evidence_audit", evidence_audit_node)
    builder.add_node("evaluation_synthesis", evaluation_synthesis_node)
    builder.add_node("report_generation", report_generation_node)

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
    builder.add_edge("report_generation", END)

    return builder.compile()
