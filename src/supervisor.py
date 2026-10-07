"""State-driven supervisor for research selection and evidence rework."""
from src.audit.auditor import RETRY_LIMIT, evidence_audit_node, finalize_retry_statuses
from src.state import OverallState
from src.synthesis.quality import MAX_QUALITY_ATTEMPTS

MAX_STEPS = 10
DATA_QUALITY_FAILURES = {"groundedness", "coverage", "bias_control"}
RESEARCH_AGENTS = ("paper", "market", "stakeholder")
NODE_NAMES = {
    "paper": "paper_analysis", "market": "market_research",
    "stakeholder": "stakeholder_research",
}


def _decision(next_node: str, reason: str, **updates) -> dict:
    return {**updates, "next_agent": next_node,
            "last_decision": {"next": next_node, "reason": reason}}


def _post_research_decision(state: OverallState) -> dict:
    status = state.get("node_status") or {}
    quality = state.get("quality") or {}
    if status.get("synthesis") != "complete":
        return _decision("evaluation_synthesis", "research_complete")
    if status.get("report") != "complete":
        return _decision("report_generation", "synthesis_complete")
    if status.get("quality") != "complete":
        return _decision("quality_eval", "report_complete")
    if quality.get("passed") or quality.get("attempts", 0) >= MAX_QUALITY_ATTEMPTS:
        return _decision("END", "quality_passed" if quality.get("passed") else "quality_limit")
    if quality.get("rework_targets"):
        return _decision("evaluation_synthesis", "quality_research_exhausted")
    failures = set(quality.get("failures") or [])
    if failures and not failures - DATA_QUALITY_FAILURES:
        return _decision("END", "quality_research_exhausted")
    # #70: 보고서는 템플릿 + 필드 번역이라 같은 State로 다시 만들면 같은 결과가 나온다.
    # 재수집 대상이 없는 미달(서술·형식 포함)은 재작성 대신 결과를 남기고 종료한다.
    return _decision("END", "quality_writing_exhausted")


def _issues(state: OverallState) -> list[dict]:
    return list((state.get("audit") or {}).get("issues") or [])


def _dependency_satisfied(agent: str, status: dict[str, str]) -> bool:
    return agent != "stakeholder" or status.get("market") == "complete"


def _candidates(state: OverallState) -> list[str]:
    status = state.get("node_status") or {}
    retries = state.get("retry_count") or {}
    targeted = {issue.get("target_agent") for issue in _issues(state)} | set((state.get("quality") or {}).get("rework_targets") or [])
    candidates = []
    for agent in RESEARCH_AGENTS:
        needs_initial_run = status.get(agent, "pending") in {"pending", "stale"}
        needs_rework = agent in targeted and retries.get(agent, 0) < RETRY_LIMIT
        if (needs_initial_run or needs_rework) and _dependency_satisfied(agent, status):
            candidates.append(agent)
    return candidates


def select_agent(candidates: list[str], state: OverallState) -> str:
    """Choose from current evidence gaps; no static workflow sequence is encoded."""
    issues = _issues(state)
    issue_count = {agent: sum(issue.get("target_agent") == agent for issue in issues) for agent in candidates}
    status = state.get("node_status") or {}
    # More audit failures take priority.  Unvisited perspectives are selected
    # next; lexical tie-breaking makes an otherwise equal decision reproducible.
    return max(candidates, key=lambda agent: (issue_count[agent], status.get(agent) != "complete", agent))


def supervisor_node(state: OverallState) -> dict:
    """Own every orchestration decision from research through quality termination."""
    step = state.get("step_count", 0)
    audit_result = evidence_audit_node(state) if state.get("last_audited_step", -1) != step else {}
    audited = {**state, **audit_result}
    if step >= MAX_STEPS:
        retries = {agent: RETRY_LIMIT for agent in RESEARCH_AGENTS}
        finalized = {**audited, "claims": finalize_retry_statuses(
            state.get("claims", []), _issues(audited), retries)}
        return {**audit_result, "last_audited_step": step,
                "claims": finalized["claims"],
                **_post_research_decision(finalized)}
    candidates = _candidates(audited)
    if not candidates:
        finalized = {
            **audited,
            "claims": finalize_retry_statuses(
                audited.get("claims", []), _issues(audited), state.get("retry_count") or {}),
        }
        return {
            **audit_result,
            "last_audited_step": step,
            "claims": finalized["claims"],
            **_post_research_decision(finalized),
        }

    selected = select_agent(candidates, audited)
    audit_targets = {issue.get("target_agent") for issue in _issues(audited)}
    quality_targets = set((state.get("quality") or {}).get("rework_targets") or [])
    targeted = audit_targets | quality_targets
    retry_count = dict(state.get("retry_count") or {})
    reason = "audit" if selected in audit_targets else "quality" if selected in quality_targets else "initial"
    status = dict(state.get("node_status") or {})
    status.update({"synthesis": "stale", "report": "stale", "quality": "stale"})
    result = {**audit_result, "last_audited_step": step, "next_agent": NODE_NAMES[selected],
              "step_count": step + 1, "node_status": status,
              "last_decision": {"next": NODE_NAMES[selected], "reason": reason}}
    if selected in targeted and (state.get("node_status") or {}).get(selected) == "complete":
        retry_count[selected] = retry_count.get(selected, 0) + 1
        result["retry_count"] = retry_count
    quality = dict(state.get("quality") or {})
    if selected in quality.get("rework_targets", []):
        quality["rework_targets"] = [agent for agent in quality["rework_targets"] if agent != selected]
        result["quality"] = quality
    return result


def route_supervisor(state: OverallState) -> str:
    return state.get("next_agent", "evaluation_synthesis")
