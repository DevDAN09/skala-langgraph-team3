"""src/quality/node.py - quality_eval 노드: 2단계 Fast-Fail 보고서 품질 평가

1단계 규칙에서 실패하면 Judge를 부르지 않는다. 이 노드는 판정과 재수집 힌트(collect_agents)만 쓰고,
재작업 대상·한도 판단은 Supervisor(decide ⑧)가 한다. 미달이면 매번 6.3절에 미통과 항목을 붙인다:
재작성으로 가면 보고서가 골격부터 다시 만들어져 사라지고, 종료되면 남는다. 그래서 이 노드는 한도를 몰라도 된다.
설계: docs/plans/2026-10-07-report-quality-eval-design.md 6절
"""
from src.state import OverallState, QualityItem, ReportEval
from src.quality import criteria
from src.quality.rules import run_quality_rules
from src.quality.judge import run_quality_judge
from src.synthesis.report_gen import render_skeleton

def _merge(rule_item: QualityItem, judge_item: QualityItem) -> QualityItem:
    return {"passed": rule_item["passed"] and judge_item["passed"], "score": judge_item["score"],
            "failures": rule_item["failures"] + judge_item["failures"], "quotes": judge_item["quotes"]}


def build_feedback(items: dict[str, QualityItem]) -> str:
    lines = ["[품질 평가 미달]"]
    for name, item in items.items():
        if item["passed"]:
            continue
        lines += [f"- {f}" for f in item["failures"]]
        lines += [f'  · 문제 문장: "{q[:120]}"' for q in item["quotes"]]
    return "\n".join(lines)[:criteria.FEEDBACK_MAX_CHARS]


def append_failures(report: str, items: dict[str, QualityItem]) -> str:
    """미통과 항목을 6장 끝(REFERENCE 앞)에 공개한다."""
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
    report_eval: ReportEval = {
        "passed": passed, "stage": stage, "items": items,
        "collect_agents": [] if passed else collect_agents,
        "feedback": "" if passed else build_feedback(items),
    }
    failed = [k for k, v in items.items() if not v["passed"]]
    print(f"🔎 [품질 평가] {'통과' if passed else f'미달 {failed}'} (stage={stage})")

    out: dict = {"report_eval": report_eval}
    if not passed:
        out["report"] = append_failures(report, items)
    return out
