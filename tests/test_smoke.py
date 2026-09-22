from tests.mock_data import INITIAL_INPUT_STATE
from src.graph import build_evaluation_graph
import main

def test_full_pipeline_smoke():
    graph = build_evaluation_graph()
    result = graph.invoke(INITIAL_INPUT_STATE)

    assert result is not None
    assert "report" in result
    assert len(result["report"]) > 100
    assert "KV Cache 최적화 기술 다관점 평가 보고서" in result["report"]


def test_main_writes_graph_report(monkeypatch, tmp_path):
    class Graph:
        def invoke(self, state):
            return {"report": "test report"}

    output_path = tmp_path / "report.md"
    monkeypatch.setattr(main, "build_evaluation_graph", lambda: Graph())
    monkeypatch.setattr(main, "REPORT_OUTPUT_PATH", output_path)

    assert main.main() == 0
    assert output_path.read_text(encoding="utf-8") == "test report"
