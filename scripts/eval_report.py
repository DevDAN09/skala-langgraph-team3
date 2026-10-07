"""scripts/eval_report.py - 저장된 State로 보고서 품질 평가만 다시 돌린다 (설계 문서 9·11절 기준값 보정용)

먼저 `python main.py`로 final_state.json을 만든 뒤:
    python scripts/eval_report.py                          # final_state.json의 보고서 평가
    python scripts/eval_report.py --report biased.md       # 같은 State로 다른 보고서(편향본·환각본) 평가
    python scripts/eval_report.py --rules-only             # LLM Judge 생략
    python scripts/eval_report.py --judge-repeat 3         # Judge를 3번 돌려 점수 흔들림 확인
그래프 안에서는 규칙 실패 시 Judge를 생략하지만, 이 스크립트는 보정용이라 규칙 결과와 관계없이 Judge를 돌린다.
"""
import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.quality.judge import run_quality_judge  # noqa: E402
from src.quality.rules import run_quality_rules  # noqa: E402
from src.synthesis.report_gen import render_skeleton  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state", default=str(ROOT / "final_state.json"))
    parser.add_argument("--report", help="평가할 마크다운 (기본: State의 report)")
    parser.add_argument("--rules-only", action="store_true")
    parser.add_argument("--judge-repeat", type=int, default=1)
    args = parser.parse_args()

    logging.disable(logging.WARNING)  # PDF 변환 경고 억제
    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    report = Path(args.report).read_text(encoding="utf-8") if args.report else state.get("report", "")

    items, agents = run_quality_rules(report, render_skeleton(state), state)
    print("== 1단계 규칙 ==")
    for name, item in items.items():
        print(f"[{'PASS' if item['passed'] else 'FAIL'}] {name}")
        for f in item["failures"]:
            print(f"    {f}")
    print(f"재수집 필요 관점: {agents or '없음'}")

    if args.rules_only:
        return 0
    print("\n== 2단계 LLM Judge ==")
    for i in range(args.judge_repeat):
        judged = run_quality_judge(report, state)
        if judged is None:
            print("Judge 미실행 (OPENAI_API_KEY 없음 또는 호출 실패)")
            break
        scores = {name: item["score"] for name, item in judged.items()}
        print(f"#{i + 1} {scores}")
        for name, item in judged.items():
            for q in item["quotes"]:
                print(f"    {name}: \"{q[:100]}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
