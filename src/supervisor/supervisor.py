"""src/supervisor/supervisor.py - Supervisor: 근거 검증(evidence_audit) + State 기반 다음 노드 결정

하위 노드는 모두 Supervisor로만 돌아온다. Supervisor는 수집이 끝났을 때만 근거를 검증하고,
State(node_status · audit · retry_count · step_count)만 보고 다음 노드를 고른다. 스텝 번호로 분기하지 않는다.
"""
from langgraph.graph import END
from src.state import OverallState
from src.audit.auditor import evidence_audit_node, RETRY_LIMIT

MAX_STEPS = 30  # Supervisor 방문 상한. 재시도 한도와 별개인 최종 종료 가드

# 수집 노드 → audit.issues[].target_agent / retry_count 키
COLLECTORS = {"paper_analysis": "paper", "market_research": "market", "stakeholder_research": "stakeholder"}
WORKERS = [*COLLECTORS, "evaluation_synthesis", "report_generation"]


def _retry_key(node: str) -> str:
    return COLLECTORS.get(node, node)


def _can_retry(state: OverallState, node: str) -> bool:
    return (state.get("retry_count") or {}).get(_retry_key(node), 0) < RETRY_LIMIT


def _collecting(state: OverallState) -> bool:
    """아직 돌아야 할 수집 노드가 있으면 True. 검증은 수집이 모두 끝난 뒤 한 번만 한다."""
    status = state.get("node_status") or {}
    for node in COLLECTORS:
        st = status.get(node, "pending")
        if st in ("pending", "stale") or (st == "failed" and _can_retry(state, node)):
            return True
    return False


def decide(state: OverallState) -> tuple[list[str] | str, str, dict]:
    """(다음 노드 목록 또는 END, 결정 사유, 함께 쓸 State 갱신)을 반환한다. 위 규칙부터 먼저 적용한다."""
    status = dict(state.get("node_status") or {})
    retry = dict(state.get("retry_count") or {})
    extra: dict = {}

    def st(node: str) -> str:
        return status.get(node, "pending")

    # 1. 종료 가드
    if state.get("step_count", 0) >= MAX_STEPS:
        if st("report_generation") == "pending":
            return ["report_generation"], f"step 상한({MAX_STEPS}) 도달 → 보고서만 생성하고 종료", extra
        return END, f"step 상한({MAX_STEPS}) 도달 → 종료", extra

    # 2. 실패한 노드: 한도 안이면 재시도, 소진하면 skipped로 확정하고 진행
    failed = [n for n in WORKERS if st(n) == "failed"]
    rerun = [n for n in failed if _can_retry(state, n)]
    if rerun:
        for n in rerun:
            retry[_retry_key(n)] = retry.get(_retry_key(n), 0) + 1
        return rerun, f"실행 실패 노드 재시도: {rerun}", {"retry_count": retry}
    if failed:
        extra["node_status"] = {n: "skipped" for n in failed}
        status.update(extra["node_status"])

    # 3. 미수집 관점 (원문 · 시장성은 서로 독립이라 병렬)
    pending = [n for n in ("paper_analysis", "market_research") if st(n) == "pending"]
    if pending:
        return pending, f"미수집 관점 수집: {pending}", extra

    # 4. 이해관계자는 시장성 컨텍스트(key_vendors)가 있어야 한다
    if st("stakeholder_research") in ("pending", "stale"):
        why = "시장성 재수집으로 이해관계자 갱신 필요" if st("stakeholder_research") == "stale" else "시장성 컨텍스트 확보"
        return ["stakeholder_research"], f"{why} → 이해관계자 조사", extra

    # 5. 근거 부족 → 해당 하위 에이전트에 재작업 요청 (관점별 RETRY_LIMIT)
    issues = (state.get("audit") or {}).get("issues") or []
    targets = {i["target_agent"] for i in issues if retry.get(i["target_agent"], 0) < RETRY_LIMIT}
    if targets:
        nodes = []
        if "market" in targets:
            nodes.append("market_research")
            # market이 바뀌면 이를 입력으로 쓰는 stakeholder도 다시 돌아야 한다 (Cascade)
            extra["node_status"] = {**extra.get("node_status", {}), "stakeholder_research": "stale"}
        elif "stakeholder" in targets:
            nodes.append("stakeholder_research")
        if "paper" in targets:
            nodes.append("paper_analysis")
        claim_ids = sorted({i["claim_id"] for i in issues if i["target_agent"] in targets})
        return nodes, f"근거 부족 재작업 요청 {sorted(targets)}: {claim_ids}", extra

    # 6. 근거 충분(이슈 없음) 또는 재작업 한도 소진 → 평가 종합
    if st("evaluation_synthesis") == "pending":
        if issues:
            exhausted = sorted({i["target_agent"] for i in issues})
            return ["evaluation_synthesis"], f"재작업 한도 소진 {exhausted} → 미해결 Claim은 Evidence Gap으로 격리하고 평가 종합", extra
        return ["evaluation_synthesis"], "검증 이슈 없음, 근거 충분 → 평가 종합", extra

    if st("report_generation") == "pending":
        return ["report_generation"], "평가 종합 완료 → 보고서 생성", extra

    return END, "보고서 생성 완료 → 종료", extra


def supervisor_node(state: OverallState) -> dict:
    """수집이 끝났고 새 결과가 있으면 근거 검증(R1~R5)을 하고, 그 결과로 다음 노드를 결정한다."""
    update: dict = {}
    if not _collecting(state) and state.get("collect_seq", 0) > state.get("audited_seq", 0):
        update = evidence_audit_node(state)
        update["audited_seq"] = state.get("collect_seq", 0)

    view = {**state, **{k: update[k] for k in ("audit", "retry_count") if k in update}}
    next_nodes, reason, extra = decide(view)

    step = state.get("step_count", 0) + 1
    print(f"🧭 [Supervisor #{step}] {reason} → {next_nodes}")
    return {**update, **extra, "step_count": step, "last_decision": {"next": next_nodes, "reason": reason}}
