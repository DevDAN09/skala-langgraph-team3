"""Role B tests use small fakes instead of downloading models or calling an LLM."""
from copy import deepcopy

import pytest
from langchain_core.documents import Document

from tests.mock_data import INITIAL_INPUT_STATE
from src.rag import agentic_rag, benchmark, indexer
from src.config import DATA_DIR


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


def test_kivi_numbered_section_heading_is_recorded():
    page = Document(
        page_content="3.2. Why Key and Value Cache Should Quantize Along Different Dimensions\n"
                     + "KIVI section content. " * 25,
        metadata={"page": 3, "tech": "KIVI"},
    )
    chunks = indexer.chunk_pages([page], lambda text: len(text.split()))
    assert chunks[0].metadata["section"].startswith("3.2. Why Key and Value Cache")


def test_wrapped_sentence_is_not_section_heading():
    page = Document(
        page_content="4.2. Accuracy and Efficiency Analysis\n"
                     "The results are summarised in Table\n"
                     "4. We apply KIVI to Llama2-7B, Llama2-13B-\n"
                     "Chat, Falcon and Mistral.",
        metadata={"page": 5, "tech": "KIVI"},
    )
    chunks = indexer.chunk_pages([page], lambda text: len(text.split()))
    assert {chunk.metadata["section"] for chunk in chunks} == {
        "4.2. Accuracy and Efficiency Analysis"}


def test_chunk_pages_joins_same_section_across_pages_without_false_heading():
    pages = [
        Document(page_content="4.2 Results\n" + "A complete result sentence. " * 85
                 + "The cache improves effi-\n1", metadata={"page": 0, "tech": "CXL-PNM"}),
        Document(page_content="ciency across devices.\n"
                 "32 VPU tiles. Each VPU instance integrates a 128-wide multiplier\n"
                 + "Another result sentence. " * 100,
                 metadata={"page": 1, "tech": "CXL-PNM"}),
    ]
    chunks = indexer.chunk_pages(pages, lambda text: len(text.split()))
    assert all(chunk.metadata["section"] == "4.2 Results" for chunk in chunks)
    assert any("efficiency across devices." in chunk.page_content for chunk in chunks)
    assert any(chunk.metadata["page"] == 2 for chunk in chunks)


def test_chunk_pages_keeps_section_boundaries_and_reference_tail():
    pages = [
        Document(page_content="1 Introduction\n" + "Intro sentence. " * 220,
                 metadata={"page": 0, "tech": "KIVI"}),
        Document(page_content="References\n" + "A cited paper title. " * 210,
                 metadata={"page": 1, "tech": "KIVI"}),
        Document(page_content="Another cited paper title. " * 110,
                 metadata={"page": 2, "tech": "KIVI"}),
    ]
    chunks = indexer.chunk_pages(pages, lambda text: len(text.split()))
    assert all("Intro" not in c.page_content or c.metadata["section"] == "1 Introduction"
               for c in chunks)
    assert all(c.metadata["section"] == "References" for c in chunks
               if "cited paper" in c.page_content)
    assert any("Another cited paper title." in c.page_content for c in chunks)


def test_kivi_author_footnote_is_not_indexed():
    page = Document(page_content=(
        "Abstract\n" + "KIVI reduces cache memory. " * 100
        + "\n*Equal contribution . The order of authors is determined by flipping a coin.\n"
        + "1Rice University 2Texas A&M University\n"
        + "1. Introduction\n" + "The cache matters. " * 100),
        metadata={"page": 0, "tech": "KIVI"})
    chunks = indexer.chunk_pages([page], lambda text: len(text.split()))
    assert not any("Equal contribution" in c.page_content for c in chunks)
    assert any("KIVI reduces cache memory" in c.page_content for c in chunks)
    assert any("The cache matters" in c.page_content for c in chunks)


def test_short_table_tail_carries_its_caption():
    page = Document(page_content=(
        "D. More Experimental Results\n"
        "Table 10: LongChat results on LongBench with KIVI and the baseline\n"
        "under the stated experimental conditions.\n"
        + "w./ KIVI-2 20.79 28.69 41.02 32.91\n" * 90),
        metadata={"page": 14, "tech": "KIVI"})
    chunks = indexer.chunk_pages([page], lambda text: len(text.split()))
    tails = [c for c in chunks if len(c.page_content.split()) < 400
             and "KIVI-2" in c.page_content]
    assert tails and all("Table 10:" in c.page_content for c in tails)


def test_faiss_path_is_project_root_data_directory():
    expected = str(DATA_DIR / "faiss_index")
    assert indexer.FAISS_INDEX_DIR == expected
    assert agentic_rag.FAISS_INDEX_DIR == expected


def test_benchmark_main_uses_one_corpus_for_both_small_models(monkeypatch):
    rows = [{"query": "grounded", "corpus": ["paper chunk"], "target_index": 0}]
    prepared = []
    measured = []
    monkeypatch.setattr(benchmark, "prepare_queries", lambda: prepared.append(True) or rows)
    monkeypatch.setattr(benchmark, "evaluate_embedding",
                        lambda model, data: measured.append((model, data)) or
                        {"hit_at_5": 0.9 if model == benchmark.SMALL_MODELS[0] else 0.5,
                         "mrr": 0.5})
    monkeypatch.setattr(benchmark.Path, "write_text", lambda *args, **kwargs: None)
    benchmark.main()
    assert len(prepared) == 1
    assert [data for _, data in measured] == [rows, rows]


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


def test_numeric_quote_with_full_context_is_accepted():
    doc = Document(page_content=(
        "For OPT-66B at 2048 tokens on a V100 GPU, measured throughput improved by 2.6×."),
                   metadata={"tech": "KIVI", "page": 1, "section": "Abstract"})

    class DB:
        def similarity_search(self, query, k, filter):
            return [doc]

    class LLM:
        def invoke(self, prompt):
            return type("Response", (), {"content": "YES" if "Answer YES" in prompt
                         else doc.page_content})()

    quote, selected = agentic_rag._grounded_quote("What throughput?", "KIVI", DB(), LLM())
    assert quote == doc.page_content
    assert selected is doc


def test_re_extract_without_matching_evidence_is_rejected(monkeypatch):
    monkeypatch.setattr(agentic_rag, "load_index", lambda: object())
    monkeypatch.setattr(agentic_rag, "make_llm", lambda: object())
    monkeypatch.setattr(agentic_rag, "_grounded_quote", lambda *args: ("", None))
    state = deepcopy(INITIAL_INPUT_STATE)
    state["audit"] = {"issues": [{"target_agent": "paper", "claim_id": "DOM-01",
                                   "action": "re_extract"}]}
    result = agentic_rag.paper_analysis_node(state)
    assert result["claims"][0]["status"] == "rejected"
    assert result["claims"][0]["statement"] == ""


def test_summary_fields_use_matching_paper_questions(monkeypatch):
    from src.rag.agentic_rag import AXES

    by_id = {claim_id: query for claim_id, _, _, query in AXES}
    assert "mechanism" in by_id["DOM-09"].lower()
    assert "mechanism" in by_id["DOM-10"].lower()
    assert "limitation" in by_id["DOM-07"].lower()
    assert "limitation" in by_id["DOM-08"].lower()
    assert "experimental conditions" in by_id["MAT-R01"].lower()
    assert "experimental conditions" in by_id["MAT-R02"].lower()
