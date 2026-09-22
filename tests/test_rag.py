from tests.mock_data import INITIAL_INPUT_STATE
from src.rag.agentic_rag import paper_analysis_node
from src.rag.indexer import build_faiss_index
from src.rag.benchmark import evaluate_embedding
from pathlib import Path


def test_paper_analysis_node_output_contract():
    result = paper_analysis_node(INITIAL_INPUT_STATE)
    assert "tech_sw" in result
    assert "tech_hw" in result
    assert "domain" in result
    assert "claims" in result
    assert len(result["claims"]) >= 2
    for claim in result["claims"]:
        assert claim["id"].startswith("DOM-")
        assert claim["perspective"] == "domain"
        if claim["tech"] == "CXL-PNM":
            assert claim["kind"] == "simulation"
        assert claim["status"] == "ok"


def test_build_faiss_index_fallback():
    # If papers_dir does not exist or has no pdfs, returns False
    res = build_faiss_index(papers_dir=Path("/non/existent/path"))
    assert res is False


def test_evaluate_embedding():
    score_empty = evaluate_embedding("BAAI/bge-small-en-v1.5", [])
    assert isinstance(score_empty, float)
    assert score_empty == 0.85

    score_queries = evaluate_embedding("BAAI/bge-small-en-v1.5", [{"query": "test"}])
    assert isinstance(score_queries, float)
    assert score_queries == 0.90
