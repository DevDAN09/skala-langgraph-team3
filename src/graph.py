"""src/graph.py - LangGraph StateGraph assembly, anti-pattern 7 fix, and conditional routing"""
from langgraph.graph import StateGraph, START, END
from src.state import OverallState
from src.rag.agentic_rag import paper_analysis_node
from src.research.market import market_research_node
from src.research.stakeholder import stakeholder_research_node
from src.audit.auditor import evidence_audit_node
from src.synthesis.evaluator import evaluation_synthesis_node
from src.synthesis.report_gen import report_generation_node


def _retry_targets(state: OverallState) -> set[str]:
    """audit.issues의 target_agent 중 재시도 한도(2회)가 남은 관점만 반환한다."""
    issues = (state.get("audit") or {}).get("issues") or []
    retry_count = state.get("retry_count") or {}
    return {
        issue["target_agent"]
        for issue in issues
        if "target_agent" in issue and retry_count.get(issue["target_agent"], 0) < 2
    }


def route_after_paper(state: OverallState) -> str:
    """첫 실행은 END. paper 재시도는 market/stakeholder가 함께 재실행되지 않을 때만 검증으로 보낸다.
    함께 재실행되면 stakeholder → evidence_audit 엣지가 검증을 한 번만 연다 (안티패턴 7)."""
    targets = _retry_targets(state)
    if "paper" in targets and not targets & {"market", "stakeholder"}:
        return "evidence_audit"
    return END


def route_audit_decision(state: OverallState) -> list[str] | str:
    """Targeted retry and Cascade Chaining router. Escapes to synthesis when retry_count >= 2."""
    issues = (state.get("audit") or {}).get("issues") or []

    if not issues:
        print("✅ [라우터] 검증 통과 -> 평가 종합으로 이동")
        return "evaluation_synthesis"

    valid_targets = _retry_targets(state)

    if not valid_targets:
        print("⚠️ [라우터] 재시도 한도(2회) 소진 -> 미해결 항목 격리 후 평가 종합으로 이동")
        return "evaluation_synthesis"

    ret = []
    if "market" in valid_targets:
        ret.append("market_research")
    elif "stakeholder" in valid_targets:
        ret.append("stakeholder_research")
    if "paper" in valid_targets:
        ret.append("paper_analysis")
    return ret if ret else "evaluation_synthesis"


def build_evaluation_graph():
    """Builds compiled StateGraph conforming to LangGraph 1.2.12 anti-pattern rules."""
    builder = StateGraph(OverallState)

    # 1. Register 6 core nodes
    builder.add_node("paper_analysis", paper_analysis_node)
    builder.add_node("market_research", market_research_node)
    builder.add_node("stakeholder_research", stakeholder_research_node)
    builder.add_node("evidence_audit", evidence_audit_node)
    builder.add_node("evaluation_synthesis", evaluation_synthesis_node)
    builder.add_node("report_generation", report_generation_node)

    # 2. Parallel Fan-out
    builder.add_edge(START, "paper_analysis")
    builder.add_edge(START, "market_research")

    # 3. Context Chaining
    builder.add_edge("market_research", "stakeholder_research")

    # 4. Correct Fan-in (Anti-pattern 7 Fix)
    builder.add_edge("stakeholder_research", "evidence_audit")
    builder.add_conditional_edges(
        "paper_analysis",
        route_after_paper,
        {"evidence_audit": "evidence_audit", END: END},
    )

    # 5. Conditional Feedback Loop
    builder.add_conditional_edges(
        "evidence_audit",
        route_audit_decision,
        {
            "paper_analysis": "paper_analysis",
            "market_research": "market_research",
            "stakeholder_research": "stakeholder_research",
            "evaluation_synthesis": "evaluation_synthesis",
        },
    )

    # 6. Report Pipeline
    builder.add_edge("evaluation_synthesis", "report_generation")
    builder.add_edge("report_generation", END)

    return builder.compile()
