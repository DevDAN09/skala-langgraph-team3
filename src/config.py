"""src/config.py - Centralized configuration, model names, and file paths"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

# Project Root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# LLM & Embedding Models
DEFAULT_LLM_MODEL = "gpt-4o-mini"
JUDGE_LLM_MODEL = "gpt-4o"
POLISHING_LLM_MODEL = "gpt-4o"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

# Directory & File Paths
DATA_DIR = PROJECT_ROOT / "data"
PAPERS_DIR = DATA_DIR / "papers"
FAISS_INDEX_DIR = str(DATA_DIR / "faiss_index")
REPORT_OUTPUT_PATH = PROJECT_ROOT / "final_evaluation_report.md"
