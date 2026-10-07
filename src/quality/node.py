"""src/quality/node.py - quality_eval 노드: 2단계 Fast-Fail 보고서 품질 평가

1단계 규칙에서 실패하면 Judge를 부르지 않는다. 판정과 재작업 대상(target)을 report_eval에 쓰고,
실제 라우팅은 Supervisor가 한다. 재작업 한도를 소진하면 미통과 항목을 보고서 6.3절에 붙인다.
설계: docs/plans/2026-10-07-report-quality-eval-design.md 6절
"""
from src.state import OverallState, QualityItem, ReportEval
from src.audit.auditor import RETRY_LIMIT
from src.quality import criteria
from src.quality.rules import run_quality_rules
from src.quality.judge import run_quality_judge
from src.synthesis.report_gen import render_skeleton

COLLECTOR_NODE = {"paper": "paper_analysis", "market": "market_research", "stakeholder": "stakeholder_research"}


def _merge(rule_item: QualityItem, judge_item: QualityItem) -> QualityItem:
    return {"passed": rule_item["passed"] and judge_item["passed"], "score": judge_item["score"],
            "failures": rule_item["failures"] + judge_item["failures"], "quotes": judge_item["quotes"]}


def pick_target(state: OverallState, collect_agents: list[str]) -> str | None:
    """근거 부족(C5·B2)이면 수집 노드, 그 밖에는 report_generation. 한도를 다 쓰면 None."""
    retry = state.get("retry_count") or {}
    for agent in collect_agents:
        if retry.get(agent, 0) < RETRY_LIMIT:
            return COLLECTOR_NODE[agent]
    if retry.get("report", 0) < criteria.REPORT_REVISION_LIMIT:
        return "report_generation"
    return None


def build_feedback(items: dict[str, QualityItem], revision: int) -> str:
    lines = [f"[품질 평가 미달 · 개정 {revision + 1}/{criteria.REPORT_REVISION_LIMIT}]"]
    for name, item in items.items():
        if item["passed"]:
            continue
        lines += [f"- {f}" for f in item["failures"]]
        lines += [f'  · 문제 문장: "{q[:120]}"' for q in item["quotes"]]
    return "\n".join(lines)[:criteria.FEEDBACK_MAX_CHARS]


def append_failures(report: str, items: dict[str, QualityItem]) -> str:
    """한도 소진 시 미통과 항목을 6장 끝(REFERENCE 앞)에 공개한다."""
    section = "### 6.3 품질 평가 미통과 항목\n" + "\n".join(
        f"- {f}" for item in items.values() if not item["passed"] for f in item["failures"]) + "\n\n"
    marker = "## REFERENCE"
    if marker in report:
        head, tail = report.split(marker, 1)
        return f"{head.rstrip()}\n\n{section}---\n\n{marker}{tail}"
    return f"{report.rstrip()}\n\n{section}"


def quality_eval_node(state: OverallState) -> dict:
    print("🔎 [품질 평가] 1단계 규칙 검사 → (통과 시) 2단계 LLM Judge")
    report = state.get("report") or ""
    items, collect_agents = run_quality_rules(report, render_skeleton(state), state)

    stage = "rules"
    if all(item["passed"] for item in items.values()):
        judge = run_quality_judge(report, state)
        if judge is not None:
            stage = "judge"
            items = {k: _merge(v, judge[k]) if k in judge else v for k, v in items.items()}

    passed = all(item["passed"] for item in items.values())
    target = None if passed else pick_target(state, collect_agents)
    revision = (state.get("retry_count") or {}).get("report", 0)
    report_eval: ReportEval = {
        "passed": passed, "stage": stage, "items": items, "target": target,
        "feedback": "" if passed else build_feedback(items, revision),
    }
    failed = [k for k, v in items.items() if not v["passed"]]
    verdict = "통과" if passed else f"미달 {failed} → {target or '한도 소진'}"
    print(f"🔎 [품질 평가] {verdict} (stage={stage})")

    out: dict = {"report_eval": report_eval}
    if not passed and target is None:
        out["report"] = append_failures(report, items)
    return out
