"""src/graph.py - LangGraph StateGraph assembly, anti-pattern 7 fix, and conditional routing"""
from langgraph.graph import StateGraph, START, END
from src.state import OverallState
from src.rag.agentic_rag import paper_analysis_node
from src.research.market import market_research_node
from src.research.stakeholder import stakeholder_research_node
from src.supervisor import supervisor_node, route_supervisor
from src.synthesis.evaluator import evaluation_synthesis_node
from src.synthesis.report_gen import report_generation_node
from src.synthesis.quality import quality_evaluation_node, route_quality


def _supervised(node, agent: str):
    """Mark the specialist's payload as available before returning to Supervisor."""
    def wrapped(state: OverallState) -> dict:
        result = node(state)
        status = dict(state.get("node_status") or {})
        status[agent] = "complete"
        return {**result, "node_status": status}
    return wrapped


def build_evaluation_graph():
    """Builds compiled StateGraph conforming to LangGraph 1.2.12 anti-pattern rules."""
    builder = StateGraph(OverallState)

    # Research agents never communicate directly; Supervisor owns all selection.
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("paper_analysis", _supervised(paper_analysis_node, "paper"))
    builder.add_node("market_research", _supervised(market_research_node, "market"))
    builder.add_node("stakeholder_research", _supervised(stakeholder_research_node, "stakeholder"))
    builder.add_node("evaluation_synthesis", evaluation_synthesis_node)
    builder.add_node("report_generation", report_generation_node)
    builder.add_node("quality_eval", quality_evaluation_node)

    builder.add_edge(START, "supervisor")
    for agent in ("paper_analysis", "market_research", "stakeholder_research"):
        builder.add_edge(agent, "supervisor")
    builder.add_conditional_edges(
        "supervisor", route_supervisor,
        {
            "paper_analysis": "paper_analysis",
            "market_research": "market_research",
            "stakeholder_research": "stakeholder_research",
            "evaluation_synthesis": "evaluation_synthesis",
        },
    )

    builder.add_edge("evaluation_synthesis", "report_generation")
    builder.add_edge("report_generation", "quality_eval")
    builder.add_conditional_edges("quality_eval", route_quality, {
        "supervisor": "supervisor", "report_generation": "report_generation", "END": END,
    })

    return builder.compile()
