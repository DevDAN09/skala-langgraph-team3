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


def test_nonverbatim_llm_quote_selects_only_contiguous_source_sentences():
    text = ("CXL-PNM stores the KV cache in external CXL memory. "
            "The near-memory accelerator selects token pages.")
    doc = Document(page_content=text, metadata={"tech": "CXL-PNM"})

    class DB:
        def similarity_search(self, query, k, filter):
            return [doc]

    class LLM:
        def invoke(self, prompt):
            if prompt.startswith("Answer YES"):
                content = "YES"
            elif prompt.startswith("Copy an exact"):
                content = "CXL-PNM keeps the KV cache in CXL memory."
            elif prompt.startswith("Select one"):
                content = "1"
            else:
                content = ""
            return type("Response", (), {"content": content})()

    quote, selected = agentic_rag._grounded_quote(
        "Where is the KV cache stored?", "CXL-PNM", DB(), LLM())
    assert quote == "CXL-PNM stores the KV cache in external CXL memory."
    assert selected is doc


def test_bandwidth_query_cannot_be_rewritten_to_throughput_evidence():
    doc = Document(page_content="KIVI allows 3.47× throughput.",
                   metadata={"tech": "KIVI"})
    gate_questions = []

    class DB:
        def similarity_search(self, query, k, filter):
            return [doc]

    class LLM:
        def invoke(self, prompt):
            if prompt.startswith("Answer YES"):
                gate_questions.append(prompt)
                content = "YES"
            elif prompt.startswith("Copy an exact"):
                content = doc.page_content
            else:
                content = "How does KIVI affect throughput?"
            return type("Response", (), {"content": content})()

    quote, selected = agentic_rag._grounded_quote(
        "How does KIVI affect KV cache memory transfer bandwidth?",
        "KIVI", DB(), LLM())
    assert (quote, selected) == ("", None)
    assert len(gate_questions) == 3
    assert all("memory transfer bandwidth?" in prompt for prompt in gate_questions)


def test_dom08_query_stays_on_accuracy_axis():
    _, _, axis, query = agentic_rag.AXIS_BY_ID["DOM-08"]
    assert axis == "accuracy"
    assert "accuracy" in query.lower()
    assert "capacity" not in query.lower()
    assert "overhead" not in query.lower()


@pytest.mark.parametrize(("claim_id", "drifted"), [
    ("DOM-01", "What throughput increase does KIVI report?"),
    ("DOM-03", "What throughput increase does KIVI report?"),
    ("DOM-03", "What bandwidth and throughput increase does KIVI report?"),
    ("DOM-05", "What memory footprint does KIVI report?"),
    ("DOM-08", "What memory capacity does CXL-PNM report?"),
    ("DOM-08", "What accuracy and memory capacity does CXL-PNM report?"),
    ("DOM-09", "What accuracy degradation does KIVI report?"),
    ("DOM-12", "What throughput increase does CXL-PNM report?"),
])
def test_rewrite_does_not_change_evaluation_axis(claim_id, drifted):
    _, tech, _, original = agentic_rag.AXIS_BY_ID[claim_id]
    searches = []

    class DB:
        def similarity_search(self, query, k, filter):
            searches.append(query)
            return []

    class LLM:
        def invoke(self, prompt):
            return type("Response", (), {"content": drifted})()

    assert agentic_rag._grounded_quote(original, tech, DB(), LLM()) == ("", None)
    assert searches == [original] * 3


def test_rewrite_accepts_bandwidth_synonym_with_same_axis():
    original = agentic_rag.AXIS_BY_ID["DOM-03"][3]
    rewritten = "How does KIVI affect KV cache transfer traffic?"
    searches = []

    class DB:
        def similarity_search(self, query, k, filter):
            searches.append(query)
            return []

    class LLM:
        def invoke(self, prompt):
            return type("Response", (), {"content": rewritten})()

    assert agentic_rag._grounded_quote(original, "KIVI", DB(), LLM()) == ("", None)
    assert searches == [original, rewritten, rewritten]


def test_partial_experimental_conditions_quote_is_rejected():
    partial = Document(page_content="We evaluated Llama3.1-8B on A100 GPUs.",
                       metadata={"tech": "CXL-PNM"})
    complete = Document(page_content=(
        "We evaluated Llama3.1-8B with 128K-token contexts on A100 GPUs."),
        metadata={"tech": "CXL-PNM"})

    class DB:
        def similarity_search(self, query, k, filter):
            return [partial, complete]

    class LLM:
        def invoke(self, prompt):
            if prompt.startswith("Answer YES"):
                content = "YES"
            elif "Passage: " + partial.page_content in prompt:
                content = partial.page_content
            else:
                content = complete.page_content
            return type("Response", (), {"content": content})()

    quote, selected = agentic_rag._grounded_quote(
        "What experimental conditions include model, context length, and GPU hardware?",
        "CXL-PNM", DB(), LLM())
    assert quote == complete.page_content
    assert selected is complete


def test_interleaved_figure_caption_is_not_used_as_claim():
    broken = Document(page_content=(
        "Throughput improved while the GPU and Figure 12: Energy comparison. "
        "PNM were active."), metadata={"tech": "CXL-PNM"})
    clean = Document(page_content=(
        "PNM-KV and PnG-KV achieve up to 21.9× throughput improvement."),
        metadata={"tech": "CXL-PNM"})

    class DB:
        def similarity_search(self, query, k, filter):
            return [broken, clean]

    class LLM:
        def invoke(self, prompt):
            if prompt.startswith("Answer YES"):
                content = "YES"
            elif "Passage: " + broken.page_content in prompt:
                content = broken.page_content
            else:
                content = clean.page_content
            return type("Response", (), {"content": content})()

    quote, selected = agentic_rag._grounded_quote(
        "What throughput improvement is reported?", "CXL-PNM", DB(), LLM())
    assert quote == clean.page_content
    assert selected is clean


def test_dom11_rejects_memory_result_without_configuration():
    _, tech, axis, question = agentic_rag.AXIS_BY_ID["DOM-11"]
    assert axis == "operational_complexity"
    assert "residual length" in question.lower()
    assert "group size" in question.lower()
    unrelated = Document(page_content=(
        "KIVI reduces peak memory usage with little to no accuracy drop."),
        metadata={"tech": tech})
    settings = Document(page_content=(
        "We use a 32 group size and 128 residual length for KIVI-2."),
        metadata={"tech": tech})

    class DB:
        def similarity_search(self, query, k, filter):
            return [unrelated, settings]

    class LLM:
        def invoke(self, prompt):
            if prompt.startswith("Answer YES"):
                content = "YES"
            elif "Passage: " + unrelated.page_content in prompt:
                content = unrelated.page_content
            else:
                content = settings.page_content
            return type("Response", (), {"content": content})()

    quote, selected = agentic_rag._grounded_quote(question, tech, DB(), LLM())
    assert quote == settings.page_content
    assert selected is settings


def test_mat_r02_links_conditions_from_two_retrieved_chunks(monkeypatch):
    setup = Document(page_content=(
        "For performance evaluation, we use a cycle-level simulator. "
        "Evaluation uses an NVIDIA DGX system with A100 GPUs. "
        "We use Llama models for evaluation."),
        metadata={"tech": "CXL-PNM", "page": 8,
                  "section": "4.1 Evaluation Settings"})
    workload = Document(page_content=(
        "Workloads span long-context inference with 128K–1M tokens."),
        metadata={"tech": "CXL-PNM", "page": 8,
                  "section": "4.1 Evaluation Settings"})

    class DB:
        def similarity_search(self, query, k, filter):
            assert k == 5 and filter == {"tech": "CXL-PNM"}
            return [setup] if "simulator" in query else [workload]

    monkeypatch.setattr(agentic_rag, "load_index", lambda: DB())
    class LLM:
        def invoke(self, prompt):
            assert "model, context length, hardware, and simulation setup" in prompt
            return type("Response", (), {"content": "YES"})()

    monkeypatch.setattr(agentic_rag, "make_llm", lambda: LLM())
    state = deepcopy(INITIAL_INPUT_STATE)
    state["audit"] = {"issues": [{"target_agent": "paper", "claim_id": "MAT-R02",
                                   "action": "search_evidence"}]}
    result = agentic_rag.paper_analysis_node(state)
    claim = result["claims"][0]
    assert claim["id"] == "MAT-R02" and claim["status"] == "ok"
    assert claim["kind"] == "simulation"
    assert len(claim["evidence_ids"]) == 2
    assert {e["snippet"] for e in result["evidence"]} == {
        setup.page_content, workload.page_content}
    assert {e["evidence_id"] for e in result["evidence"]} == set(claim["evidence_ids"])
    assert all(sentence in claim["statement"] for sentence in (
        "cycle-level simulator", "NVIDIA DGX", "Llama models", "128K–1M tokens"))


def test_mat_r02_stays_insufficient_if_a_condition_is_missing(monkeypatch):
    setup = Document(page_content=(
        "For performance evaluation, we use a cycle-level simulator. "
        "Evaluation uses an NVIDIA DGX system with A100 GPUs. "
        "We use Llama models for evaluation."),
        metadata={"tech": "CXL-PNM", "page": 8,
                  "section": "4.1 Evaluation Settings"})

    class DB:
        def similarity_search(self, query, k, filter):
            return [setup]

    monkeypatch.setattr(agentic_rag, "load_index", lambda: DB())
    monkeypatch.setattr(agentic_rag, "make_llm", lambda: object())
    state = deepcopy(INITIAL_INPUT_STATE)
    state["audit"] = {"issues": [{"target_agent": "paper", "claim_id": "MAT-R02",
                                   "action": "search_evidence"}]}
    result = agentic_rag.paper_analysis_node(state)
    assert result["claims"][0]["status"] == "insufficient"
    assert result["claims"][0]["statement"] == ""
    assert result["claims"][0]["evidence_ids"] == []
    assert result["evidence"] == []


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
