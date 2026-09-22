"""Build a page and section traceable FAISS index from the two supplied papers."""
import re
from collections import Counter
from pathlib import Path

from langchain_core.documents import Document

from src.config import DATA_DIR, EMBEDDING_MODEL, PAPERS_DIR

PAPERS = {"KIVI": "kivi.pdf", "CXL-PNM": "cxl_pnm.pdf"}
FAISS_INDEX_DIR = str(DATA_DIR / "faiss_index")
HEADER = re.compile(
    r"^(?:[1-9](?:\.\d+){0,2}\.?\s+[A-Z][^.!?\n]{2,80}"
    r"|[A-D]\.\s+[A-Z][^.!?\n]{2,80}|Abstract|References)$")


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
    """Chunk continuous sections across PDF pages without mixing their sources."""
    first_lines = Counter((p.metadata["tech"], p.page_content.splitlines()[0].strip())
                          for p in pages if p.page_content.splitlines())
    sections = []
    table_captions = {}
    for page in pages:
        tech = page.metadata["tech"]
        lines = page.page_content.splitlines()
        page_no = page.metadata["page"] + 1
        skip_affiliation = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if tech == "KIVI" and page_no == 1 and stripped.startswith("*Equal contribution"):
                skip_affiliation = True
            if skip_affiliation:
                if not HEADER.fullmatch(stripped):
                    continue
                skip_affiliation = False
            if (i == 0 and page.metadata["page"] > 0
                    and first_lines[tech, stripped] > 1):
                continue
            if i >= len(lines) - 2 and (stripped == str(page_no)
                                         or stripped.startswith("arXiv:")):
                continue
            if not stripped:
                continue
            if re.match(r"^Table \d+:", stripped):
                caption = stripped
                if not stripped.endswith((".", "!", "?")) and i + 1 < len(lines):
                    caption += " " + lines[i + 1].strip()
                table_captions[tech, page_no] = caption
            if HEADER.fullmatch(stripped) and not stripped.endswith("-"):
                if sections and sections[-1]["tech"] == tech and (
                        stripped == "Abstract" and sections[-1]["section"] == "Abstract"):
                    pass
                elif sections and sections[-1]["tech"] == tech and (
                        sections[-1]["words"] == sections[-1]["section"].split()):
                    sections[-1]["section"] = stripped
                else:
                    sections.append({"tech": tech, "section": stripped, "words": [], "pages": []})
            if not sections or sections[-1]["tech"] != tech:
                sections.append({"tech": tech, "section": "Abstract", "words": [], "pages": []})
            section = sections[-1]
            line_words = stripped.split()
            if (section["words"] and section["pages"][-1] != page_no
                    and section["words"][-1].endswith("-")
                    and line_words and line_words[0][0].islower()):
                section["words"][-1] = section["words"][-1][:-1] + line_words.pop(0)
            section["words"].extend(line_words)
            section["pages"].extend([page_no] * len(line_words))

    chunks = []
    for section in sections:
        words, word_pages = section["words"], section["pages"]
        if not words:
            continue

        def count(start, end):
            return token_count(" ".join(words[start:end]))

        spans = []
        start = 0
        while start < len(words):
            low, high, end = start + 1, len(words), start + 1
            while low <= high:
                mid = (low + high) // 2
                if count(start, mid) <= 480:
                    end, low = mid, mid + 1
                else:
                    high = mid - 1
            if end < len(words):
                sentence_ends = [i for i in range(start + 1, end + 1)
                                 if words[i - 1].endswith((".", "?", "!"))
                                 and count(start, i) >= 400]
                if sentence_ends:
                    end = sentence_ends[-1]
            spans.append((start, end))
            if end == len(words):
                break
            overlap_start = end - 1
            while overlap_start > start and count(overlap_start, end) < 72:
                overlap_start -= 1
            start = max(start + 1, overlap_start)
        if len(spans) > 1 and count(*spans[-1]) < 400 \
                and count(spans[-2][0], spans[-1][1]) <= 500:
            spans[-2:] = [(spans[-2][0], spans[-1][1])]
        for start, end in spans:
            content = " ".join(words[start:end])
            caption = table_captions.get((section["tech"], word_pages[start]))
            if (section["tech"] == "KIVI" and word_pages[start] == 15
                    and count(start, end) < 400 and caption
                    and "Table 10:" not in content
                    and token_count(caption + " " + content) <= 500):
                content = caption + " " + content
            chunks.append(Document(page_content=content,
                                   metadata={"tech": section["tech"],
                                             "section": section["section"],
                                             "page": word_pages[start]}))
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
                                           encode_kwargs={"normalize_embeddings": True,
                                                          "prompt": "passage: "})
        db = FAISS.from_documents(chunks, embeddings)
        db.save_local(output_dir)
        print(f"✅ [성공/통과] {len(chunks)} paper chunks indexed at {output_dir}")
        return True
    except Exception as exc:
        print(f"⚠️ [경고/Fallback] Index build failed: {exc}")
        return False


if __name__ == "__main__":
    raise SystemExit(0 if build_faiss_index() else 1)
