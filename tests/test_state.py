from src.state import (
    upsert_claims,
    upsert_evidence,
    union_sources,
    OverallState,
    Claim,
    Evidence,
    Source,
    AuditIssue,
    Audit,
    TRL,
)
import src.config as config
from pathlib import Path


def test_upsert_claims_idempotent():
    existing = [
        {
            "id": "DOM-01",
            "perspective": "domain",
            "tech": "KIVI",
            "statement": "v1",
            "kind": "fact",
            "evidence_ids": [],
            "counter_evidence_ids": [],
            "counter_searched": False,
            "status": "ok",
        }
    ]
    updates = [
        {
            "id": "DOM-01",
            "perspective": "domain",
            "tech": "KIVI",
            "statement": "v2",
            "kind": "fact",
            "evidence_ids": ["EV-01"],
            "counter_evidence_ids": [],
            "counter_searched": False,
            "status": "ok",
        },
        {
            "id": "DOM-02",
            "perspective": "domain",
            "tech": "CXL-PNM",
            "statement": "new",
            "kind": "simulation",
            "evidence_ids": [],
            "counter_evidence_ids": [],
            "counter_searched": False,
            "status": "ok",
        },
    ]
    merged = upsert_claims(existing, updates)
    assert len(merged) == 2
    merged_map = {c["id"]: c for c in merged}
    assert merged_map["DOM-01"]["statement"] == "v2"
    assert merged_map["DOM-01"]["evidence_ids"] == ["EV-01"]
    assert merged_map["DOM-02"]["statement"] == "new"


def test_upsert_evidence_idempotent():
    existing = [
        {
            "evidence_id": "EV-01",
            "source_id": "SRC-01",
            "snippet": "Snippet 1",
        }
    ]
    updates = [
        {
            "evidence_id": "EV-01",
            "source_id": "SRC-01",
            "snippet": "Snippet 1 updated",
        },
        {
            "evidence_id": "EV-02",
            "source_id": "SRC-02",
            "snippet": "Snippet 2",
        },
    ]
    merged = upsert_evidence(existing, updates)
    assert len(merged) == 2
    merged_map = {e["evidence_id"]: e for e in merged}
    assert merged_map["EV-01"]["snippet"] == "Snippet 1 updated"
    assert merged_map["EV-02"]["snippet"] == "Snippet 2"


def test_union_sources_url_dedup():
    existing = [
        {
            "source_id": "SRC-01",
            "title": "Paper 1",
            "publisher": "ACM",
            "date": "2024",
            "url": "https://arxiv.org/1",
            "source_type": "paper",
            "source_tier": "T1",
        }
    ]
    updates = [
        {
            "source_id": "SRC-02",
            "title": "Same Paper URL",
            "publisher": "arXiv",
            "date": "2024",
            "url": "https://arxiv.org/1",
            "source_type": "paper",
            "source_tier": "T1",
        }
    ]
    merged = union_sources(existing, updates)
    assert len(merged) == 1
    assert merged[0]["source_id"] == "SRC-01"


def test_union_sources_new_url_and_empty_url():
    existing = [
        {
            "source_id": "SRC-01",
            "title": "Paper 1",
            "publisher": "ACM",
            "date": "2024",
            "url": "https://arxiv.org/1",
            "source_type": "paper",
            "source_tier": "T1",
        }
    ]
    updates = [
        {
            "source_id": "SRC-02",
            "title": "Paper 2",
            "publisher": "IEEE",
            "date": "2024",
            "url": "https://arxiv.org/2",
            "source_type": "paper",
            "source_tier": "T1",
        },
        {
            "source_id": "SRC-03",
            "title": "Unpublished Internal",
            "publisher": "Internal",
            "date": "2024",
            "url": "",
            "source_type": "paper",
            "source_tier": "T3",
        },
    ]
    merged = union_sources(existing, updates)
    assert len(merged) == 3
    ids = {s["source_id"] for s in merged}
    assert ids == {"SRC-01", "SRC-02", "SRC-03"}


def test_overall_state_schema_keys():
    expected_keys = {
        "selected",
        "tech_sw",
        "tech_hw",
        "domain",
        "market",
        "stakeholder",
        "claims",
        "evidence",
        "sources",
        "audit",
        "retry_count",
        "trl",
        "synthesis",
        "report",
    }
    assert set(OverallState.__annotations__.keys()) == expected_keys
    assert len(expected_keys) == 14


def test_config_exports():
    assert hasattr(config, "PROJECT_ROOT")
    assert hasattr(config, "DATA_DIR")
    assert hasattr(config, "PAPERS_DIR")
    assert hasattr(config, "FAISS_INDEX_DIR")
    assert Path(config.FAISS_INDEX_DIR) == config.PROJECT_ROOT / "data" / "faiss_index"
    assert hasattr(config, "REPORT_OUTPUT_PATH")
    assert config.DEFAULT_LLM_MODEL == "gpt-4o-mini"
    assert config.JUDGE_LLM_MODEL == "gpt-4o"
    assert config.POLISHING_LLM_MODEL == "gpt-4o"
    assert config.EMBEDDING_MODEL in ("BAAI/bge-small-en-v1.5", "intfloat/e5-small-v2")
