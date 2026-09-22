"""Measure Hit@5 and MRR on passages cut from the supplied papers."""
import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from src.config import DATA_DIR

SMALL_MODELS = ("BAAI/bge-small-en-v1.5", "intfloat/e5-small-v2")
LARGE_MODEL = "BAAI/bge-m3"


def evaluate_embedding(model_name: str, eval_queries: list[dict]) -> dict[str, float]:
    if not eval_queries:
        raise ValueError("A measured benchmark requires evaluation queries")
    model = SentenceTransformer(model_name)
    hits = []
    reciprocal_ranks = []
    corpus_vectors = {}
    for row in eval_queries:
        corpus = row["corpus"]
        targets = row.get("target_indices", [row.get("target_index")])
        if not corpus or not targets or any(t is None or not 0 <= t < len(corpus) for t in targets):
            raise ValueError(f"Invalid corpus/target in {row.get('id', 'query')}")
        e5 = model_name.startswith("intfloat/e5-")
        query = f"query: {row['query']}" if e5 else row["query"]
        passages = [f"passage: {text}" for text in corpus] if e5 else corpus
        query_vector = np.asarray(model.encode(query, normalize_embeddings=True))
        corpus_key = tuple(passages)
        if corpus_key not in corpus_vectors:
            corpus_vectors[corpus_key] = np.asarray(
                model.encode(passages, normalize_embeddings=True))
        vectors = corpus_vectors[corpus_key]
        ranking = np.argsort(vectors @ query_vector)[::-1]
        rank = min(int(np.where(ranking == target)[0][0]) + 1 for target in targets)
        hits.append(rank <= 5)
        reciprocal_ranks.append(1 / rank)
    return {"hit_at_5": float(np.mean(hits)), "mrr": float(np.mean(reciprocal_ranks))}


def prepare_queries(model_name: str, query_path: Path = DATA_DIR / "eval_queries.json") -> list[dict]:
    """Ground each target in an actual indexed PDF chunk, rather than canned text."""
    from transformers import AutoTokenizer
    from src.rag.indexer import chunk_pages, load_papers

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    chunks = chunk_pages(load_papers(), lambda text: len(tokenizer.encode(text)))
    rows = json.loads(query_path.read_text())
    if len(rows) != 20:
        raise ValueError("Exactly 20 PDF grounded evaluation queries are required")
    dataset = []
    for row in rows:
        corpus = [chunk.page_content for chunk in chunks if chunk.metadata["tech"] == row["tech"]]
        targets = [i for i, text in enumerate(corpus)
                   if row["target_phrase"].casefold() in " ".join(text.split()).casefold()]
        if not targets:
            raise ValueError(f"No source chunk for {row['id']}: {row['target_phrase']}")
        dataset.append({"id": row["id"], "query": row["query"],
                        "corpus": corpus, "target_indices": targets})
    return dataset


def main() -> None:
    results = {}
    for name in SMALL_MODELS:
        results[name] = evaluate_embedding(name, prepare_queries(name))
        print(f"{name}: Hit@5={results[name]['hit_at_5']:.3f}, MRR={results[name]['mrr']:.3f}")
    eligible = [name for name in SMALL_MODELS if results[name]["hit_at_5"] >= 0.8]
    if not eligible:
        results[LARGE_MODEL] = evaluate_embedding(LARGE_MODEL, prepare_queries(LARGE_MODEL))
        print(f"{LARGE_MODEL}: Hit@5={results[LARGE_MODEL]['hit_at_5']:.3f}, "
              f"MRR={results[LARGE_MODEL]['mrr']:.3f}")
        eligible = [LARGE_MODEL] if results[LARGE_MODEL]["hit_at_5"] >= 0.8 else []
    selected = max(eligible, key=lambda name: results[name]["mrr"]) if eligible else None
    output = {"results": results, "selected": selected, "queries": 20}
    (Path(__file__).parent / "benchmark_results.json").write_text(json.dumps(output, indent=2))
    print(f"Selected: {selected or 'none: no model met Hit@5 >= 0.8'}")


if __name__ == "__main__":
    main()
