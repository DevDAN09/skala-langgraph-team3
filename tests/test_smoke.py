import os
import main
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


def test_main_writes_report_from_state(monkeypatch, tmp_path):
    """보고서 파일은 main.py가 State의 report 문자열로 기록한다 (E 노드는 문자열만 반환)."""
    import src.graph as graph_module

    out = tmp_path / "final_evaluation_report.md"
    monkeypatch.setattr(main, "REPORT_OUTPUT_PATH", out)
    monkeypatch.setattr(graph_module, "report_generation_node", lambda state: {"report": "# stub report"})

    assert main.main() == 0
    assert out.read_text(encoding="utf-8") == "# stub report"


def test_main_initial_state_matches_contract():
    """main.py는 tests 패키지에 의존하지 않고, 초기 State는 팀 공용 mock과 같다."""
    with open(main.__file__, encoding="utf-8") as f:
        assert "from tests" not in f.read()
    assert main.INITIAL_INPUT_STATE == INITIAL_INPUT_STATE
