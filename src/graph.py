"""src/graph.py - Supervisor 패턴 StateGraph 조립

START → supervisor, 모든 하위 노드 → supervisor. 분기는 supervisor의 add_conditional_edges 하나뿐이고,
하위 노드끼리 직접 잇는 엣지는 없다.
"""
from functools import wraps
from langgraph.graph import StateGraph, START, END
from src.state import OverallState
from src.supervisor.supervisor import supervisor_node, COLLECTORS
from src.rag.agentic_rag import paper_analysis_node
from src.research.market import market_research_node
from src.research.stakeholder import stakeholder_research_node
from src.synthesis.evaluator import evaluation_synthesis_node
from src.synthesis.report_gen import report_generation_node


def track_node(name: str, fn):
    """하위 노드 래퍼: 성공/실패를 node_status·last_error에 남겨 Supervisor가 재시도·제외를 판단하게 한다."""
    @wraps(fn)
    def node(state: OverallState) -> dict:
        try:
            out = dict(fn(state) or {})
            out["node_status"] = {name: "done"}
        except Exception as error:
            print(f"❌ [{name}] 실행 실패: {error}")
            out = {"node_status": {name: "failed"}, "last_error": {name: f"{type(error).__name__}: {error}"}}
        if name in COLLECTORS:
            out["collect_seq"] = 1  # 새 수집 결과 → Supervisor가 다음 방문에서 검증
        return out
    return node


def route_from_supervisor(state: OverallState) -> list[str] | str:
    return state["last_decision"]["next"]


def build_evaluation_graph():
    builder = StateGraph(OverallState)
    workers = {
        "paper_analysis": paper_analysis_node,
        "market_research": market_research_node,
        "stakeholder_research": stakeholder_research_node,
        "evaluation_synthesis": evaluation_synthesis_node,
        "report_generation": report_generation_node,
    }

    builder.add_node("supervisor", supervisor_node)
    for name, fn in workers.items():
        builder.add_node(name, track_node(name, fn))
        builder.add_edge(name, "supervisor")

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges("supervisor", route_from_supervisor, {**{n: n for n in workers}, END: END})
    return builder.compile()
