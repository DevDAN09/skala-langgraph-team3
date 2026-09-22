"""src/rag/indexer.py - PDF Chunking and FAISS Vector Index Builder"""
import os
from pathlib import Path
from src.config import FAISS_INDEX_DIR, PAPERS_DIR, EMBEDDING_MODEL

def build_faiss_index(papers_dir: Path = PAPERS_DIR, output_dir: str = FAISS_INDEX_DIR) -> bool:
    """Builds local FAISS index from papers in PAPERS_DIR if PDFs exist."""
    if not papers_dir.exists() or not list(papers_dir.glob("*.pdf")):
        return False
    try:
        from langchain_community.document_loaders import PyPDFLoader
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        from langchain_community.vectorstores import FAISS
        from langchain_huggingface import HuggingFaceEmbeddings

        docs = []
        for pdf_path in papers_dir.glob("*.pdf"):
            loader = PyPDFLoader(str(pdf_path))
            loaded = loader.load()
            tech = "KIVI" if "kivi" in pdf_path.name.lower() else "CXL-PNM"
            for d in loaded:
                d.metadata["tech"] = tech
            docs.extend(loaded)

        splitter = RecursiveCharacterTextSplitter(chunk_size=450, chunk_overlap=70)
        chunks = splitter.split_documents(docs)
        embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        db = FAISS.from_documents(chunks, embeddings)
        os.makedirs(output_dir, exist_ok=True)
        db.save_local(output_dir)
        return True
    except Exception as e:
        print(f"⚠️ [Fallback] Index build skipped: {e}")
        return False
