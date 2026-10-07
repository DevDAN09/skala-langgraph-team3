"""main.py - Non-interactive Multi-Agent System Entry Point"""
import sys
import time
import uuid
from langgraph.checkpoint.memory import InMemorySaver
from src.config import REPORT_OUTPUT_PATH, REPORT_MD_PATH, REPORT_PDF_PATH
from src.graph import build_evaluation_graph
from src.synthesis.pdf_export import convert_markdown_to_pdf

# 설계 5.1: START에서 selected만 주입. 나머지 키는 빈 값, retry_count는 관점별 0으로 시작한다.
def make_initial_state(trace_id: str | None = None):
    return {
    "selected": {
        "sw": "KIVI",
        "hw": "CXL-PNM",
        "families": {"sw": "KV Quantization", "hw": "CXL Memory Expansion"},
        "rationale": "KIVI represents algorithmic 2-bit quantization while CXL-PNM represents hardware near-memory acceleration.",
    },
    "tech_sw": {},
    "tech_hw": {},
    "domain": {},
    "market": {},
    "stakeholder": {},
    "claims": [],
    "evidence": [],
    "sources": [],
    "audit": {"issues": []},
    "retry_count": {"paper": 0, "market": 0, "stakeholder": 0},
    "trl": {},
    "synthesis": {},
    "report": "",
    "quality": {},
    "trace_id": trace_id or str(uuid.uuid4()),
    "next_nodes": [],
    "route_reason": "",
    "step_count": 0,
    "max_steps": 40,
    "node_status": {
        "paper_analysis": "pending",
        "market_research": "pending",
        "stakeholder_research": "pending",
        "evidence_audit": "pending",
        "evaluation_synthesis": "pending",
        "report_generation": "pending",
        "quality_evaluation": "pending",
    },
    "node_attempts": {},
    "last_errors": {},
    "quality_round": 0,
    }


INITIAL_INPUT_STATE = make_initial_state("initial")

def main():
    print("=" * 70)
    print("🚀 KV Cache 최적화 기술 다관점 평가 멀티 에이전트 시스템 시작")
    print("   대상: KIVI (SW 2-bit 양자화) vs CXL-PNM (HW CXL 근접 처리)")
    print("=" * 70)

    start_time = time.time()
    try:
        trace_id = str(uuid.uuid4())
        initial_state = make_initial_state(trace_id)
        graph = build_evaluation_graph(checkpointer=InMemorySaver())
        config = {
            "configurable": {"thread_id": trace_id},
            "run_name": f"supervisor-evaluation-{trace_id}",
            "metadata": {"trace_id": trace_id, "pattern": "supervisor"},
            "recursion_limit": 100,
        }
        print(f"🔗 StateGraph 컴파일 완료. trace_id={trace_id}")
        final_state = graph.invoke(initial_state, config=config)

        # Markdown 원본 보존
        REPORT_MD_PATH.write_text(final_state["report"], encoding="utf-8")

        # PDF 변환 및 산출물 생성 (Graceful Fallback 지원)
        pdf_success = False
        if REPORT_OUTPUT_PATH.suffix.lower() == ".pdf":
            pdf_success = convert_markdown_to_pdf(final_state["report"], REPORT_OUTPUT_PATH)
        else:
            REPORT_OUTPUT_PATH.write_text(final_state["report"], encoding="utf-8")

        elapsed = time.time() - start_time

        print("=" * 70)
        print(f"✅ 파이프라인 실행 완료! 소요 시간: {elapsed:.2f}초")
        if pdf_success or REPORT_OUTPUT_PATH.suffix.lower() != ".pdf":
            print(f"📄 최종 보고서 생성 경로: {REPORT_OUTPUT_PATH}")
        else:
            print(f"⚠️ [Fallback] PDF 생성 실패로 마크다운 보고서가 유지됩니다: {REPORT_MD_PATH}")
        print(f"📝 마크다운 원본 경로: {REPORT_MD_PATH}")
        quality = final_state.get("quality") or {}
        print(f"🔎 Quality: {quality.get('dimension_results', {})}, "
              f"overall={quality.get('passed')}, round={final_state.get('quality_round', 0)}")
        print("=" * 70)
        return 0
    except Exception as e:
        print(f"❌ [치명적 오류] 파이프라인 실행 실패: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
