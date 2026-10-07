"""LangGraph assembly for the state-based Supervisor workflow."""
from langgraph.graph import END, START, StateGraph

from src.audit.auditor import evidence_audit_node
from src.orchestration.supervisor import route_supervisor, supervisor_node
from src.orchestration.worker import wrap_worker
from src.quality.evaluator import quality_evaluation_node
from src.rag.agentic_rag import paper_analysis_node
from src.research.market import market_research_node
from src.research.stakeholder import stakeholder_research_node
from src.state import OverallState
from src.synthesis.evaluator import evaluation_synthesis_node
from src.synthesis.report_gen import report_generation_node


WORKERS = {
    "paper_analysis": paper_analysis_node,
    "market_research": market_research_node,
    "stakeholder_research": stakeholder_research_node,
    "evidence_audit": evidence_audit_node,
    "evaluation_synthesis": evaluation_synthesis_node,
    "report_generation": report_generation_node,
    "quality_evaluation": quality_evaluation_node,
}


def build_evaluation_graph(checkpointer=None):
    """Compile a graph where every worker is selected by and returns to Supervisor."""
    builder = StateGraph(OverallState)
    builder.add_node("supervisor", supervisor_node)
    for name, node in WORKERS.items():
        builder.add_node(name, wrap_worker(name, node))

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        route_supervisor,
        {**{name: name for name in WORKERS}, END: END},
    )
    for name in WORKERS:
        builder.add_edge(name, "supervisor")

    return builder.compile(checkpointer=checkpointer)
