"""Build a page and section traceable FAISS index from the two supplied papers."""
import re
from pathlib import Path

from langchain_core.documents import Document

from src.config import EMBEDDING_MODEL, FAISS_INDEX_DIR, PAPERS_DIR

PAPERS = {"KIVI": "kivi.pdf", "CXL-PNM": "cxl_pnm.pdf"}
HEADER = re.compile(r"^(?:\d+(?:\.\d+)*\s+[A-Z][^\n]{2,85}|Abstract|References)$")


def load_papers(papers_dir: Path = PAPERS_DIR) -> list[Document]:
    from langchain_community.document_loaders import PyPDFLoader

    pages = []
    for tech, filename in PAPERS.items():
        path = Path(papers_dir) / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        for page in PyPDFLoader(str(path)).load():
            page.metadata = {"tech": tech, "page": page.metadata["page"]}
            pages.append(page)
    return pages


def chunk_pages(pages: list[Document], token_count) -> list[Document]:
    """Cut pages near 450 model tokens, preferring a nearby section boundary."""
    chunks = []
    current_section = {}
    for page in pages:
        tech = page.metadata["tech"]
        section = current_section.get(tech, "Abstract")
        words = []
        sections = []
        headers = set()
        for line in page.page_content.splitlines():
            stripped = line.strip()
            if HEADER.fullmatch(stripped):
                section = stripped
                headers.add(len(words))
            line_words = line.split()
            words.extend(line_words)
            sections.extend([section] * len(line_words))
        current_section[tech] = section
        if not words:
            continue

        def count(start, end):
            return token_count(" ".join(words[start:end]))

        start = 0
        while start < len(words):
            low, high = start + 1, len(words)
            end = low
            while low <= high:
                mid = (low + high) // 2
                if count(start, mid) <= 450:
                    end = mid
                    low = mid + 1
                else:
                    high = mid - 1
            if end == len(words):
                chunks.append(Document(
                    page_content=" ".join(words[start:end]),
                    metadata={"tech": tech, "section": sections[start],
                              "page": page.metadata["page"] + 1}))
                break
            # Align to a heading only when the resulting chunk remains 400-500 tokens.
            section_ends = [h for h in headers if start < h <= end
                            and 400 <= count(start, h) <= 500]
            if section_ends:
                end = max(section_ends)
            chunks.append(Document(
                page_content=" ".join(words[start:end]),
                metadata={"tech": tech, "section": sections[start],
                          "page": page.metadata["page"] + 1}))
            overlap_start = end - 1
            while overlap_start > start and count(overlap_start, end) < 68:
                overlap_start -= 1
            start = max(start + 1, overlap_start)
    return chunks


def build_faiss_index(papers_dir: Path = PAPERS_DIR, output_dir: str = FAISS_INDEX_DIR,
                      embedding_model_name: str = EMBEDDING_MODEL) -> bool:
    """Return False on missing PDFs or unavailable embedding dependencies/models."""
    try:
        pages = load_papers(papers_dir)
        from transformers import AutoTokenizer
        from langchain_community.vectorstores import FAISS
        from langchain_huggingface import HuggingFaceEmbeddings

        tokenizer = AutoTokenizer.from_pretrained(embedding_model_name)
        chunks = chunk_pages(pages, lambda text: len(tokenizer.encode(text)))
        embeddings = HuggingFaceEmbeddings(model_name=embedding_model_name,
                                           encode_kwargs={"normalize_embeddings": True})
        db = FAISS.from_documents(chunks, embeddings)
        db.save_local(output_dir)
        print(f"✅ [성공/통과] {len(chunks)} paper chunks indexed at {output_dir}")
        return True
    except Exception as exc:
        print(f"⚠️ [경고/Fallback] Index build failed: {exc}")
        return False


if __name__ == "__main__":
    raise SystemExit(0 if build_faiss_index() else 1)
