"""Paper only Agentic RAG: retrieve, check sufficiency, rewrite, and ground."""
from langchain_core.documents import Document

from src.config import DEFAULT_LLM_MODEL, EMBEDDING_MODEL
from src.rag.indexer import FAISS_INDEX_DIR
from src.state import Claim, Evidence, OverallState, Source

# Six cloud serving axes for each technology, plus paper research maturity.
AXES = (
    ("DOM-01", "KIVI", "memory_footprint", "What measured GPU memory footprint does KIVI report?"),
    ("DOM-02", "CXL-PNM", "memory_footprint", "How does CXL-PNM store the KV cache beyond GPU memory?"),
    ("DOM-03", "KIVI", "bandwidth_transfer", "How does KIVI affect KV cache memory transfer bandwidth?"),
    ("DOM-04", "CXL-PNM", "bandwidth_transfer", "How does CXL-PNM reduce KV cache recall transfers?"),
    ("DOM-05", "KIVI", "throughput_latency", "What throughput or latency measurements does KIVI report?"),
    ("DOM-06", "CXL-PNM", "throughput_latency", "What simulated throughput or latency does CXL-PNM report?"),
    ("DOM-07", "KIVI", "accuracy", "What accuracy degradation or limitations does KIVI acknowledge?"),
    ("DOM-08", "CXL-PNM", "accuracy", "What accuracy or retrieval limitations does CXL-PNM acknowledge?"),
    ("DOM-09", "KIVI", "infrastructure", "What is KIVI's key and value quantization mechanism and its GPU kernel requirements?"),
    ("DOM-10", "CXL-PNM", "infrastructure", "What is the CXL-PNM KV cache management mechanism and its required hardware?"),
    ("DOM-11", "KIVI", "operational_complexity", "What residual cache or quantization settings does KIVI require?"),
    ("DOM-12", "CXL-PNM", "operational_complexity", "What GPU and PNM coordination does the design require?"),
    ("MAT-R01", "KIVI", "research", "What experimental conditions are used to evaluate KIVI, including model, context, and hardware?"),
    ("MAT-R02", "CXL-PNM", "research", "What experimental conditions are used in the CXL-PNM simulation, including model, context, and hardware?"),
)
AXIS_BY_ID = {row[0]: row for row in AXES}
SOURCES: dict[str, Source] = {
    "KIVI": {"source_id": "SRC-PAPER-KIVI",
             "title": "KIVI: A Tuning-Free Asymmetric 2bit Quantization for KV Cache",
             "publisher": "ICML", "date": "2024",
             "url": "https://arxiv.org/abs/2402.02750",
             "source_type": "paper", "source_tier": "T1"},
    "CXL-PNM": {"source_id": "SRC-PAPER-CXL-PNM",
                "title": "Scalable Processing-Near-Memory for 1M-Token LLM Inference: CXL-Enabled KV-Cache Management Beyond GPU Limits",
                "publisher": "arXiv", "date": "2025",
                "url": "https://arxiv.org/abs/2511.00321",
                "source_type": "paper", "source_tier": "T1"},
}


def load_index():
    from langchain_community.vectorstores import FAISS
    from langchain_huggingface import HuggingFaceEmbeddings

    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL,
                                       encode_kwargs={"normalize_embeddings": True,
                                                      "prompt": "passage: "},
                                       query_encode_kwargs={"normalize_embeddings": True,
                                                            "prompt": "query: "})
    # This index is created locally by indexer.py from the two trusted project PDFs.
    return FAISS.load_local(FAISS_INDEX_DIR, embeddings,
                            allow_dangerous_deserialization=True)


def make_llm():
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=DEFAULT_LLM_MODEL, temperature=0)


def _ask(llm, prompt: str) -> str:
    try:
        return str(llm.invoke(prompt).content).strip()
    except Exception as exc:
        print(f"⚠️ [경고/Fallback] Paper LLM call failed: {exc}")
        return ""


def _grounded_quote(query: str, tech: str, db, llm) -> tuple[str, Document | None]:
    for attempt in range(3):
        try:
            docs = db.similarity_search(query, k=5, filter={"tech": tech})
        except Exception as exc:
            print(f"⚠️ [경고/Fallback] Paper retrieval failed: {exc}")
            docs = []
        for doc in docs:
            if doc.metadata.get("tech") != tech:
                continue
            gate = _ask(llm, "Answer YES or NO only. Does this passage explicitly answer "
                        f"the question?\nQuestion: {query}\nPassage: {doc.page_content}")
            if gate.upper() != "YES":
                continue
            quote = _ask(llm, "Copy an exact, contiguous passage of at most three sentences that "
                         "answers the question. Do not invent numbers, compare technologies, "
                         "or recommend anything. If context for a number (model size, context "
                         "length, hardware, measurement method) is missing, answer INSUFFICIENT.\n"
                         f"Question: {query}\nPassage: {doc.page_content}")
            if quote and quote != "INSUFFICIENT" and quote in doc.page_content:
                return quote, doc
        if attempt < 2:
            rewritten = _ask(llm, "Rewrite this English paper search query using technical "
                             "synonyms only. Return one English query, no answer or new facts.\n"
                             f"Query: {query}")
            if rewritten:
                query = rewritten
    return "", None


def _claim(axis, quote: str) -> Claim:
    claim_id, tech, _, _ = axis
    maturity = claim_id.startswith("MAT-")
    return {
        "id": claim_id, "perspective": "maturity" if maturity else "domain",
        "tech": tech, "statement": quote,
        "kind": "simulation" if tech == "CXL-PNM" else "fact",
        "evidence_ids": [f"EV-{claim_id}"] if quote else [],
        "counter_evidence_ids": [], "counter_searched": False,
        "status": "ok" if quote else "insufficient",
    }


def paper_analysis_node(state: OverallState) -> dict:
    print("📄 [원문 분석] 논문 기반 메커니즘 및 도메인 6대 축 분석 실행")
    paper_issues = [issue for issue in (state.get("audit") or {}).get("issues", [])
                    if issue.get("target_agent") == "paper"]
    retry = bool(paper_issues)
    axes = [AXIS_BY_ID[issue["claim_id"]] for issue in paper_issues
            if issue.get("claim_id") in AXIS_BY_ID] if retry else AXES
    # Keep one update per ID even if multiple audit rules target the same claim.
    axes = list(dict.fromkeys(axes))
    actions = {issue["claim_id"]: issue.get("action") for issue in paper_issues}
    needs_search = any(actions.get(axis[0]) != "relabel" for axis in axes)
    db = llm = None
    if needs_search:
        try:
            db = load_index()
            llm = make_llm()
        except Exception as exc:
            print(f"⚠️ [경고/Fallback] Paper index or LLM unavailable: {exc}")

    claims: list[Claim] = []
    evidence: list[Evidence] = []
    sources: dict[str, Source] = {}
    by_tech: dict[str, dict] = {"KIVI": {}, "CXL-PNM": {}}
    domain = {}
    for axis in axes:
        claim_id, tech, key, query = axis
        if actions.get(claim_id) == "relabel":
            old = next((claim for claim in state.get("claims", [])
                        if claim["id"] == claim_id), None)
            if old:
                claims.append({**old, "kind": "simulation" if tech == "CXL-PNM" else "fact",
                               "status": "ok" if old.get("statement") and old.get("evidence_ids")
                               else "insufficient"})
            continue
        quote, doc = _grounded_quote(query, tech, db, llm) if db and llm else ("", None)
        claim = _claim(axis, quote)
        if actions.get(claim_id) == "re_extract" and not quote:
            claim["status"] = "rejected"
        claims.append(claim)
        if doc:
            source = SOURCES[tech]
            sources[tech] = source
            evidence.append({"evidence_id": f"EV-{claim_id}",
                             "source_id": source["source_id"],
                             "snippet": doc.page_content})
            by_tech[tech].setdefault("locations", {})[claim_id] = {
                "page": doc.metadata.get("page"),
                "section": doc.metadata.get("section"),
            }
            if key == "research":
                by_tech[tech]["research_evidence"] = quote
                by_tech[tech]["research_trl_range"] = "3-4 (estimate from paper stage)"
                by_tech[tech]["experimental_conditions"] = quote
            else:
                domain.setdefault(key, {})[tech] = quote
                by_tech[tech].setdefault("evidence", {})[key] = quote
                if key == "infrastructure":
                    by_tech[tech]["mechanism"] = quote
                elif key == "accuracy":
                    by_tech[tech]["limitations"] = quote
                elif key in ("memory_footprint", "throughput_latency"):
                    by_tech[tech].setdefault("performance_numbers", []).append(quote)
        elif not retry:
            if key == "research":
                by_tech[tech]["research_evidence"] = "corpus 내 근거 미확인"
            else:
                domain.setdefault(key, {})[tech] = "corpus 내 근거 미확인"
    result = {"claims": claims, "evidence": evidence, "sources": list(sources.values())}
    if not retry:
        result.update({"tech_sw": {"name": "KIVI", **by_tech["KIVI"]},
                       "tech_hw": {"name": "CXL-PNM", **by_tech["CXL-PNM"]},
                       "domain": domain})
    return result
