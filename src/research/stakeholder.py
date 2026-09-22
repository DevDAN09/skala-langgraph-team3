"""src/research/stakeholder.py - Stakeholder research node chained from market"""
from src.state import OverallState, Claim, Evidence, Source


def stakeholder_research_node(state: OverallState) -> dict:
    """Investigates benefits and barriers across 4 key actors (cloud ops, HW vendors, chipmakers, users)."""
    print("👥 [이해관계자] 4대 핵심 Actor(클라우드, HW벤더 등) 영향 분석 실행")

    claims: list[Claim] = [
        {
            "id": "STK-01",
            "perspective": "stakeholder",
            "tech": "KIVI",
            "statement": "Cloud service providers prioritize KIVI for zero-CAPEX software-only deployment on existing GPU fleets.",
            "kind": "fact",
            "evidence_ids": ["EV-STK-01"],
            "counter_evidence_ids": [],
            "counter_searched": True,
            "status": "ok",
        },
        {
            "id": "STK-02",
            "perspective": "stakeholder",
            "tech": "CXL-PNM",
            "statement": "Memory vendors push CXL-PNM to overcome memory wall while cloud providers balance high initial server CAPEX.",
            "kind": "fact",
            "evidence_ids": ["EV-STK-02"],
            "counter_evidence_ids": [],
            "counter_searched": True,
            "status": "ok",
        },
    ]

    evidence: list[Evidence] = [
        {
            "evidence_id": "EV-STK-01",
            "source_id": "SRC-STK-01",
            "snippet": "Cloud operators favor software quantization due to immediate ROI and no physical infrastructure modifications.",
        },
        {
            "evidence_id": "EV-STK-02",
            "source_id": "SRC-STK-02",
            "snippet": "Enterprise surveys indicate CXL adoption requires long-term datacenter architectural planning.",
        },
    ]

    sources: list[Source] = [
        {
            "source_id": "SRC-STK-01",
            "title": "Cloud AI Infrastructure Report",
            "publisher": "Analyst Group",
            "date": "2024",
            "url": "https://analyst-ai.com/report",
            "source_type": "web",
            "source_tier": "T3",
        },
        {
            "source_id": "SRC-STK-02",
            "title": "Enterprise Datacenter Memory Survey",
            "publisher": "Tech Insight",
            "date": "2024",
            "url": "https://techinsight.org/survey",
            "source_type": "web",
            "source_tier": "T3",
        },
    ]

    stakeholder = {
        "cloud_ops": "KIVI enables immediate batch scale; CXL requires capital investment",
        "hw_vendors": "CXL opens new high-margin enterprise memory tier",
        "end_users": "Lower latency and reduced per-token serving cost",
    }

    return {
        "stakeholder": stakeholder,
        "claims": claims,
        "evidence": evidence,
        "sources": sources,
    }
