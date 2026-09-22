"""Paper only Agentic RAG: retrieve, check sufficiency, rewrite, and ground."""
import re

from langchain_core.documents import Document

from src.config import DEFAULT_LLM_MODEL, EMBEDDING_MODEL
from src.rag.indexer import FAISS_INDEX_DIR
from src.state import Claim, Evidence, OverallState, Source

# Six cloud serving axes for each technology, plus paper research maturity.
AXES = (
    ("DOM-01", "KIVI", "memory_footprint", "What measured GPU memory footprint does KIVI report?"),
    ("DOM-02", "CXL-PNM", "memory_footprint", "How does CXL-PNM store the KV cache beyond GPU memory?"),
    ("DOM-03", "KIVI", "bandwidth_transfer", "How does KIVI affect KV cache memory transfer bandwidth?"),
    ("DOM-04", "CXL-PNM", "bandwidth_transfer", "How does CXL-PNM eliminate costly KV-cache recall overhead?"),
    ("DOM-05", "KIVI", "throughput_latency", "What throughput or latency measurements does KIVI report?"),
    ("DOM-06", "CXL-PNM", "throughput_latency", "What throughput improvement do PNM-KV and PnG-KV report relative to the baseline?"),
    ("DOM-07", "KIVI", "accuracy", "What accuracy degradation or limitations does KIVI acknowledge?"),
    ("DOM-08", "CXL-PNM", "accuracy", "What model accuracy degradation or retrieval-quality limitations does CXL-PNM report for its own design?"),
    ("DOM-09", "KIVI", "infrastructure", "What is KIVI's key and value quantization mechanism and its GPU kernel requirements?"),
    ("DOM-10", "CXL-PNM", "infrastructure", "What is the CXL-PNM KV cache management mechanism and its required hardware?"),
    ("DOM-11", "KIVI", "operational_complexity", "Which residual length and group size settings are used in KIVI evaluations?"),
    ("DOM-12", "CXL-PNM", "operational_complexity", "What GPU-PNM data is exchanged during decoding and how does it scale with context length?"),
    ("MAT-R01", "KIVI", "research", "What experimental conditions are used to evaluate KIVI, including model, context, and hardware?"),
    ("MAT-R02", "CXL-PNM", "research", "What experimental conditions (Llama models, context lengths, and GPU hardware) are used in CXL-PNM evaluation?"),
)
AXIS_BY_ID = {row[0]: row for row in AXES}
_AXIS_TERMS = {
    "memory_footprint": r"\b(?:footprint|capacity|storage|stor(?:e|ed|ing)|memory usage|memory demand|size)\b",
    "bandwidth_transfer": r"\b(?:bandwidth|transfers?|traffic|recalls?|offload(?:ing)?|data movement)\b",
    "throughput_latency": r"\b(?:throughput|latency|speed|tokens? per second)\b",
    "accuracy": r"\b(?:accuracy|quality|degradation|errors?|precision)\b",
    "infrastructure": r"\b(?:infrastructure|hardware|architecture|mechanism|devices?|controllers?|kernels?)\b",
    "operational_complexity": r"\b(?:coordination|configuration|settings?|scheduling|synchroni[sz]ation|communication|exchang(?:e|ed))\b",
    "research": r"\b(?:experimental|evaluation|simulation|models?|context|hardware)\b",
}
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


def _preserves_axis(original: str, rewritten: str, axis: str | None) -> bool:
    if not axis:
        return rewritten == original
    if not re.search(_AXIS_TERMS[axis], rewritten, re.I):
        return False
    return all(other == axis or not re.search(pattern, rewritten, re.I)
               or re.search(pattern, original, re.I)
               for other, pattern in _AXIS_TERMS.items())


def _grounded_quote(query: str, tech: str, db, llm) -> tuple[str, Document | None]:
    question = query
    axis = next((row[2] for row in AXES if row[1] == tech and row[3] == question), None)
    for attempt in range(3):
        try:
            docs = db.similarity_search(query, k=5, filter={"tech": tech})
        except Exception as exc:
            print(f"⚠️ [경고/Fallback] Paper retrieval failed: {exc}")
            docs = []
        for doc in docs:
            if doc.metadata.get("tech") != tech:
                continue
            metric_rule = (" Throughput is not evidence of memory transfer bandwidth."
                           if "bandwidth" in question.lower() else "")
            gate = _ask(llm, "Answer YES or NO only. Does this passage explicitly answer "
                        f"the question?{metric_rule}\nQuestion: {question}"
                        f"\nPassage: {doc.page_content}")
            if gate.upper() != "YES":
                continue
            quote = _ask(llm, "Copy an exact, contiguous passage of at most three sentences that "
                         "answers the question. Do not invent numbers, compare technologies, "
                         "or recommend anything. For measured numbers, include their stated "
                         "measurement context. If the passage does not answer, say INSUFFICIENT.\n"
                         f"Question: {question}\nPassage: {doc.page_content}")
            if quote and quote != "INSUFFICIENT" and quote not in doc.page_content:
                sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", doc.page_content)
                numbered = "\n".join(f"{i}: {sentence}" for i, sentence in enumerate(sentences, 1))
                choice = _ask(llm, "Select one to three CONSECUTIVE numbered sentences that "
                              "directly answer the question. Return only N or N-M; return "
                              "INSUFFICIENT if none do. Do not join separated sentences.\n"
                              f"Question: {question}\nSentences:\n{numbered}")
                match = re.match(r"^(\d+)(?:-(\d+))?(?:\D|$)", choice)
                if match:
                    start = int(match[1]) - 1
                    end = int(match[2] or match[1])
                    if 0 <= start < end <= len(sentences) and end - start <= 3:
                        first = doc.page_content.find(sentences[start])
                        last = doc.page_content.find(sentences[end - 1], first)
                        if first >= 0 and last >= first:
                            quote = doc.page_content[first:last + len(sentences[end - 1])]
            if ("bandwidth" in question.lower() and "throughput" in quote.lower()
                    and not re.search(r"bandwidth|transfer|bytes|data movement|traffic|loading",
                                      quote, re.I)):
                continue
            if question == AXIS_BY_ID["DOM-11"][3] and not re.search(
                    r"residual length|group size", quote, re.I):
                continue
            if re.search(r"\bFigure\s+\d+:", quote) and not quote.lstrip().startswith("Figure"):
                continue
            if quote and quote != "INSUFFICIENT" and quote in doc.page_content:
                if "experimental conditions" in question.lower():
                    if not re.search(r"context|tokens?", quote, re.I):
                        continue
                    verified = _ask(llm, "Answer YES or NO only. Does this excerpt itself "
                                    "include model, context length, and hardware?\n"
                                    f"Question: {question}\nExcerpt: {quote}")
                    if verified.upper() != "YES":
                        continue
                return quote, doc
        if attempt < 2:
            rewritten = _ask(llm, "Rewrite this English paper search query using technical "
                             "synonyms only. Return one English query, no answer or new facts.\n"
                             "Preserve the original evaluation axis and metric; do not switch "
                             "between memory, bandwidth, throughput/latency, accuracy, "
                             "infrastructure, or operational complexity.\n"
                             f"Query: {query}")
            if rewritten and _preserves_axis(question, rewritten, axis):
                query = rewritten
    return "", None


def _mat_r02_evidence(db, llm) -> tuple[str, list[Document]]:
    queries = (
        "What cycle-level simulator and GPU/CXL-PNM hardware setup is used for evaluation?",
        "What CXL-PNM evaluation workloads span 128K to 1M tokens, and which Llama models are used?",
    )
    docs = []
    for query in queries:
        try:
            results = db.similarity_search(query, k=5, filter={"tech": "CXL-PNM"})
        except Exception as exc:
            print(f"⚠️ [경고/Fallback] Paper retrieval failed: {exc}")
            return "", []
        for doc in results:
            if (doc.metadata.get("tech") == "CXL-PNM"
                    and doc.metadata.get("section") == "4.1 Evaluation Settings"
                    and all(doc.page_content != old.page_content for old in docs)):
                docs.append(doc)

    patterns = (
        r"\bWe use Llama models\b",
        r"\b(?:Workloads span|context length)\b.*\btokens?\b",
        r"\bNVIDIA DGX\b.*\bA100(?:-80GB)? GPUs\b",
        r"\bcycle-level simulator\b",
    )
    found = []
    for pattern in patterns:
        match = next(((sentence, doc) for doc in docs
                      for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", doc.page_content)
                      if re.search(pattern, sentence, re.I)), None)
        if not match:
            return "", []
        found.append(match)
    quote = "\n".join(sentence for sentence, _ in found)
    gate = _ask(llm, "Answer YES or NO only. Do these verbatim paper excerpts collectively "
                "state the evaluated model, context length, hardware, and simulation setup? "
                f"Do not infer missing conditions.\nExcerpts:\n{quote}")
    if gate.upper() != "YES":
        return "", []
    used_docs = []
    for _, doc in found:
        if all(doc.page_content != old.page_content for old in used_docs):
            used_docs.append(doc)
    return quote, used_docs


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
        mat_docs = []
        if claim_id == "MAT-R02" and db and llm:
            quote, mat_docs = _mat_r02_evidence(db, llm)
            doc = mat_docs[0] if mat_docs else None
        else:
            quote, doc = _grounded_quote(query, tech, db, llm) if db and llm else ("", None)
        claim = _claim(axis, quote)
        if mat_docs:
            claim["evidence_ids"] = [f"EV-{claim_id}-{i}" for i in range(1, len(mat_docs) + 1)]
        if actions.get(claim_id) == "re_extract" and not quote:
            claim["status"] = "rejected"
        claims.append(claim)
        if doc:
            source = SOURCES[tech]
            sources[tech] = source
            evidence.extend({"evidence_id": evidence_id,
                             "source_id": source["source_id"],
                             "snippet": evidence_doc.page_content}
                            for evidence_id, evidence_doc in zip(
                                claim["evidence_ids"], mat_docs or [doc]))
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
