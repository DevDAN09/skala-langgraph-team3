"""src/supervisor/supervisor.py - Supervisor 노드와 라우터

Supervisor는 현재 State(수집된 관점, 근거 검증 결과, 실패/재시도 현황, 품질 평가 결과)만 보고
다음에 호출할 하위 에이전트를 정한다. 실행 순서는 코드에 고정되어 있지 않고 node_status / audit / quality
값에 따라 add_conditional_edges로 분기한다. 하위 에이전트는 모두 Supervisor로만 돌아오며 서로 직접 연결되지 않는다.
"""
from langgraph.graph import END

from src.audit.auditor import RETRY_LIMIT
from src.state import OverallState
from src.supervisor.observability import log_decision

# 관점 수집 하위 에이전트
RESEARCH_AGENTS = ("paper_analysis", "market_research", "stakeholder_research")
AGENT_BY_TARGET = {
    "paper": "paper_analysis",
    "market": "market_research",
    "stakeholder": "stakeholder_research",
}
# stakeholder는 market.key_vendors 컨텍스트로 쿼리를 구체화하므로 market 이후에만 보낼 수 있다.
DEPENDS_ON = {"stakeholder_research": "market_research"}

DEFAULT_MAX_STEPS = 20       # Supervisor 턴 상한 (종료 가드)
MAX_NODE_ATTEMPTS = 2        # 하위 에이전트 예외 시 재시도 상한, 초과 시 제외(skip)하고 진행
MAX_QUALITY_ROUNDS = 3       # 보고서 품질 평가 횟수 상한 (최초 1회 + 재작성 2회)

DONE = {"done", "skipped"}


def _done(status: dict, name: str) -> bool:
    return status.get(name) in DONE


def _ready(agents, status: dict) -> list[str]:
    """의존 에이전트가 끝난 것만 이번 턴에 보낸다. 서로 독립인 관점은 병렬로 보낸다."""
    return [a for a in agents if a not in DEPENDS_ON or _done(status, DEPENDS_ON[a])]


def retry_targets(state: OverallState) -> set[str]:
    """audit.issues의 target_agent 중 재시도 한도가 남은 관점만 반환한다."""
    issues = (state.get("audit") or {}).get("issues") or []
    retry_count = state.get("retry_count") or {}
    return {
        issue["target_agent"]
        for issue in issues
        if "target_agent" in issue and retry_count.get(issue["target_agent"], 0) < RETRY_LIMIT
    }


def decide(state: OverallState, step: int, max_steps: int) -> tuple[list[str], str, dict]:
    """(다음 노드 목록, 결정 사유, node_status 갱신분)을 반환한다."""
    status = dict(state.get("node_status") or {})
    attempts = state.get("node_attempts") or {}
    updates: dict[str, str] = {}

    # 1. Fallback 정책: 예외로 실패한 하위 에이전트는 MAX_NODE_ATTEMPTS까지 재시도, 초과 시 제외하고 진행
    for name, st in list(status.items()):
        if st == "failed" and attempts.get(name, 0) >= MAX_NODE_ATTEMPTS:
            status[name] = updates[name] = "skipped"

    # 2. 종료 가드: 턴 상한을 넘으면 남은 종합/보고서만 마무리하고 끝낸다
    if step > max_steps:
        for name in ("evaluation_synthesis", "report_generation"):
            if not _done(status, name):
                return [name], f"step 상한({max_steps}) 초과 → 강제 마무리: {name}", updates
        return [END], f"step 상한({max_steps}) 초과 → 종료", updates

    # 3. 보고서 품질 평가 결과 반영 (미달 시 재작성 루프)
    if _done(status, "quality_eval"):
        quality = state.get("quality") or {}
        if quality.get("passed"):
            return [END], "보고서 품질 평가 통과 → 종료", updates
        failed = [k for k, v in (quality.get("checks") or {}).items() if not v.get("passed")]
        if state.get("quality_round", 0) < MAX_QUALITY_ROUNDS and status.get("quality_eval") == "done":
            status["report_generation"] = updates["report_generation"] = "pending"
            status["quality_eval"] = updates["quality_eval"] = "pending"
            return ["report_generation"], f"품질 미달 {failed} → 피드백 반영해 보고서 재작성 요청", updates
        return [END], f"품질 평가 상한 도달(미달 {failed}) → 한계점으로 남기고 종료", updates

    # 4. 관점 수집: 아직 수집되지 않았거나 재작업 요청된 관점을 의존성에 맞춰 보낸다
    pending = [a for a in RESEARCH_AGENTS if not _done(status, a)]
    if pending:
        ready = _ready(pending, status)
        return ready, f"미수집/재작업 관점 {pending} 중 의존성 충족된 {ready} 호출", updates

    # 5. 근거 충분성 검증
    if not _done(status, "evidence_audit"):
        return ["evidence_audit"], "모든 관점 수집 완료 → 근거 충분성 검증 요청", updates

    # 6. 검증 결과에 따라 재작업 요청 또는 종합 진행
    if not _done(status, "evaluation_synthesis"):
        issues = (state.get("audit") or {}).get("issues") or []
        targets = retry_targets(state)
        if targets:
            agents = {AGENT_BY_TARGET[t] for t in targets}
            if "market_research" in agents:
                # market 컨텍스트가 바뀌면 이를 읽는 stakeholder도 다시 조사해야 한다
                agents.add("stakeholder_research")
            for a in agents:
                status[a] = updates[a] = "pending"
            status["evidence_audit"] = updates["evidence_audit"] = "pending"
            claim_ids = sorted({i["claim_id"] for i in issues if i.get("target_agent") in targets})
            ready = _ready([a for a in RESEARCH_AGENTS if a in agents], status)
            return ready, (f"근거 부족 claim {claim_ids} → {sorted(targets)} 재작업 요청 "
                           f"(retry_count={state.get('retry_count')})"), updates
        if issues:
            return ["evaluation_synthesis"], "재시도 한도 소진 → 미해결 claim 격리 후 평가 종합", updates
        return ["evaluation_synthesis"], "근거 충분 → 평가 종합", updates

    if not _done(status, "report_generation"):
        return ["report_generation"], "평가 종합 완료 → 보고서 생성", updates
    if not _done(status, "quality_eval"):
        return ["quality_eval"], "보고서 생성 완료 → 품질 평가 요청", updates
    return [END], "모든 단계 완료 → 종료", updates


def supervisor_node(state: OverallState) -> dict:
    step = state.get("step_count", 0) + 1
    max_steps = state.get("max_steps") or DEFAULT_MAX_STEPS
    next_nodes, reason, status_updates = decide(state, step, max_steps)
    print(f"🧭 [Supervisor #{step}] → {next_nodes} | {reason}")
    log_decision(state.get("trace_id", "-"), "supervisor", next_nodes, reason, step=step)
    return {
        "step_count": step,
        "max_steps": max_steps,
        "next": next_nodes,
        "route_reason": reason,
        "node_status": status_updates,
    }


def route_from_supervisor(state: OverallState) -> list[str] | str:
    next_nodes = state.get("next") or [END]
    return END if next_nodes == [END] else next_nodes
