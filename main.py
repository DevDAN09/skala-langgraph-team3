"""main.py - Non-interactive Multi-Agent System Entry Point"""
import sys
import time
from src.config import REPORT_OUTPUT_PATH
from src.graph import build_evaluation_graph
from tests.mock_data import INITIAL_INPUT_STATE

def main():
    print("=" * 70)
    print("🚀 KV Cache 최적화 기술 다관점 평가 멀티 에이전트 시스템 시작")
    print("   대상: KIVI (SW 2-bit 양자화) vs CXL-PNM (HW CXL 근접 처리)")
    print("=" * 70)

    start_time = time.time()
    try:
        graph = build_evaluation_graph()
        print("🔗 StateGraph 컴파일 완료. 파이프라인 실행 시작...")
        final_state = graph.invoke(INITIAL_INPUT_STATE)
        REPORT_OUTPUT_PATH.write_text(final_state["report"], encoding="utf-8")
        elapsed = time.time() - start_time

        print("=" * 70)
        print(f"✅ 파이프라인 실행 완료! 소요 시간: {elapsed:.2f}초")
        print(f"📄 최종 보고서 생성 경로: {REPORT_OUTPUT_PATH}")
        print("=" * 70)
        return 0
    except Exception as e:
        print(f"❌ [치명적 오류] 파이프라인 실행 실패: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
