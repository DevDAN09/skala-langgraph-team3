"""src/graph.py - Supervisor 패턴 StateGraph 조립

허브-스포크 구조: START → supervisor, 모든 하위 에이전트 → supervisor.
supervisor → 하위 에이전트는 add_conditional_edges 하나로만 연결되며, 실행 순서는 State에 따라 동적으로 정해진다.
하위 에이전트끼리는 엣지가 없다 (직접 통신 금지).
"""
from langgraph.graph import StateGraph, START, END
from src.state import OverallState
from src.rag.agentic_rag import paper_analysis_node
from src.research.market import market_research_node
from src.research.stakeholder import stakeholder_research_node
from src.audit.auditor import evidence_audit_node
from src.synthesis.evaluator import evaluation_synthesis_node
from src.synthesis.report_gen import report_generation_node
from src.quality.quality_eval import quality_eval_node
from src.supervisor.supervisor import supervisor_node, route_from_supervisor
from src.supervisor.worker import as_worker

SUB_AGENTS = (
    "paper_analysis",
    "market_research",
    "stakeholder_research",
    "evidence_audit",
    "evaluation_synthesis",
    "report_generation",
    "quality_eval",
)


def _node_functions() -> dict:
    # 모듈 전역에서 매번 조회해 테스트에서 monkeypatch로 노드를 바꿀 수 있게 한다.
    return {
        "paper_analysis": paper_analysis_node,
        "market_research": market_research_node,
        "stakeholder_research": stakeholder_research_node,
        "evidence_audit": evidence_audit_node,
        "evaluation_synthesis": evaluation_synthesis_node,
        "report_generation": report_generation_node,
        "quality_eval": quality_eval_node,
    }


def build_evaluation_graph(checkpointer=None):
    builder = StateGraph(OverallState)

    builder.add_node("supervisor", supervisor_node)
    for name, fn in _node_functions().items():
        builder.add_node(name, as_worker(name, fn))
        builder.add_edge(name, "supervisor")

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {**{name: name for name in SUB_AGENTS}, END: END},
    )

    return builder.compile(checkpointer=checkpointer)
