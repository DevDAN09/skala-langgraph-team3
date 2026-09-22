"""Role B tests use small fakes instead of downloading models or calling an LLM."""
from copy import deepcopy

import pytest
from langchain_core.documents import Document

from tests.mock_data import INITIAL_INPUT_STATE
from src.rag import agentic_rag, benchmark, indexer


def test_benchmark_scores_real_ranks(monkeypatch):
    class FakeModel:
        def encode(self, texts, normalize_embeddings=True):
            values = {"query: good": [1.0, 0.0], "passage: target": [1.0, 0.0],
                      "passage: other": [0.0, 1.0]}
            return [values[t] for t in texts] if isinstance(texts, list) else values[texts]

    monkeypatch.setattr(benchmark, "SentenceTransformer", lambda _: FakeModel())
    rows = [{"query": "good", "corpus": ["other", "target"], "target_index": 1}]
    assert benchmark.evaluate_embedding("intfloat/e5-small-v2", rows) == {
        "hit_at_5": 1.0, "mrr": 1.0}
    with pytest.raises(ValueError):
        benchmark.evaluate_embedding("intfloat/e5-small-v2", [])


def test_chunk_pages_keeps_source_metadata_and_caption():
    page = Document(page_content="1 Introduction\n" + "KIVI cache data. " * 650
                    + "\nFigure 1: KV cache layout.", metadata={"page": 0, "tech": "KIVI"})
    chunks = indexer.chunk_pages([page], lambda text: len(text.split()))
    assert len(chunks) > 1
    assert all(chunk.metadata["tech"] == "KIVI" and chunk.metadata["page"] == 1
               and chunk.metadata["section"] for chunk in chunks)
    assert all(len(chunk.page_content.split()) <= 500 for chunk in chunks)
    assert any(400 <= len(chunk.page_content.split()) <= 500 for chunk in chunks)
    assert any("Figure 1: KV cache layout." in chunk.page_content for chunk in chunks)


def test_missing_papers_do_not_build_index(tmp_path):
    assert indexer.build_faiss_index(papers_dir=tmp_path) is False


def test_paper_node_uses_retrieved_chunk_and_preserves_other_claims(monkeypatch):
    content = "KIVI quantizes key cache per-channel."
    doc = Document(page_content=content, metadata={"tech": "KIVI", "page": 1,
                                                    "section": "Introduction"})

    class DB:
        def similarity_search(self, query, k, filter):
            assert k == 5
            return [doc] if filter == {"tech": "KIVI"} else []

    class LLM:
        def invoke(self, prompt):
            return type("Response", (), {
                "content": "YES" if "Answer YES" in prompt else content})()

    monkeypatch.setattr(agentic_rag, "load_index", lambda: DB())
    monkeypatch.setattr(agentic_rag, "make_llm", lambda: LLM())
    state = deepcopy(INITIAL_INPUT_STATE)
    state["claims"] = [{"id": "MKT-01", "statement": "external"}]
    before = deepcopy(state)
    result = agentic_rag.paper_analysis_node(state)
    assert state == before
    assert set(result) == {"tech_sw", "tech_hw", "domain", "claims", "evidence", "sources"}
    assert len(result["claims"]) == 14
    assert set(result["domain"]) == {"memory_footprint", "bandwidth_transfer",
                                     "throughput_latency", "accuracy", "infrastructure",
                                     "operational_complexity"}
    assert not any(c["id"].startswith("MKT") for c in result["claims"])
    claim = next(c for c in result["claims"] if c["id"] == "DOM-01")
    assert claim["statement"] == content
    assert claim["evidence_ids"] == ["EV-DOM-01"]
    assert next(e for e in result["evidence"] if e["evidence_id"] == "EV-DOM-01")["snippet"] == content
    assert result["tech_sw"]["locations"]["DOM-01"] == {
        "page": 1, "section": "Introduction"}
    assert all(c["statement"] == "" and c["status"] == "insufficient"
               for c in result["claims"] if c["tech"] == "CXL-PNM")


def test_paper_node_rewrites_at_most_twice_and_retries_one_claim(monkeypatch):
    calls = []

    class DB:
        def similarity_search(self, query, k, filter):
            calls.append(query)
            return []

    class LLM:
        def invoke(self, prompt):
            class Response:
                content = "rewritten query"
            return Response()

    monkeypatch.setattr(agentic_rag, "load_index", lambda: DB())
    monkeypatch.setattr(agentic_rag, "make_llm", lambda: LLM())
    state = deepcopy(INITIAL_INPUT_STATE)
    state["audit"] = {"issues": [{"target_agent": "paper", "claim_id": "DOM-02",
                                   "action": "search_evidence"},
                                  {"target_agent": "market", "claim_id": "MKT-01",
                                   "action": "search_evidence"}]}
    result = agentic_rag.paper_analysis_node(state)
    assert len(calls) == 3
    assert [c["id"] for c in result["claims"]] == ["DOM-02"]
    assert result["claims"][0]["status"] == "insufficient"
    assert result["claims"][0]["statement"] == ""
    assert not result["evidence"]


def test_relabel_patches_only_paper_claim(monkeypatch):
    monkeypatch.setattr(agentic_rag, "load_index", lambda: (_ for _ in ()).throw(
        AssertionError("relabel must not retrieve")))
    state = deepcopy(INITIAL_INPUT_STATE)
    state["claims"] = [{"id": "DOM-02", "tech": "CXL-PNM", "kind": "fact",
                        "statement": "quoted statement", "evidence_ids": ["EV-DOM-02"],
                        "status": "flagged"}]
    state["audit"] = {"issues": [{"target_agent": "paper", "claim_id": "DOM-02",
                                   "action": "relabel"}]}
    result = agentic_rag.paper_analysis_node(state)
    assert [claim["id"] for claim in result["claims"]] == ["DOM-02"]
    assert result["claims"][0]["kind"] == "simulation"
    assert result["claims"][0]["status"] == "ok"


def test_numeric_claim_without_experiment_context_is_insufficient(monkeypatch):
    doc = Document(page_content="KIVI improved throughput by 2.6×.",
                   metadata={"tech": "KIVI", "page": 1, "section": "Abstract"})

    class DB:
        def similarity_search(self, query, k, filter):
            return [doc]

    class LLM:
        def invoke(self, prompt):
            return type("Response", (), {"content": "YES" if "Answer YES" in prompt
                         else doc.page_content})()

    quote, selected = agentic_rag._grounded_quote("What throughput?", "KIVI", DB(), LLM())
    assert quote == ""
    assert selected is None
