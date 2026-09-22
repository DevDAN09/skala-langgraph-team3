import os
from tests.mock_data import INITIAL_INPUT_STATE
from src.graph import build_evaluation_graph
from src.config import REPORT_OUTPUT_PATH

def test_full_pipeline_smoke():
    graph = build_evaluation_graph()
    result = graph.invoke(INITIAL_INPUT_STATE)

    assert result is not None
    assert "report" in result
    assert len(result["report"]) > 100
    assert os.path.exists(REPORT_OUTPUT_PATH)
    with open(REPORT_OUTPUT_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    assert "KV Cache 최적화 기술 다관점 평가 보고서" in content
