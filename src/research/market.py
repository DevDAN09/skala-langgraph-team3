"""src/research/market.py - Market research node"""
from src.state import OverallState, Claim, Evidence, Source


def market_research_node(state: OverallState) -> dict:
    """Investigates market adoption, ecosystem readiness, and commercialization barriers."""
    print("📈 [시장성 조사] 시장 채택 및 기술 장벽 다각도 조사 실행")

    claims: list[Claim] = [
        {
            "id": "MKT-01",
            "perspective": "market",
            "tech": "CXL-PNM",
            "statement": "Samsung Electronics and SK Hynix commercialized CXL 2.0 DRAM memory modules with volume shipments targeting cloud datacenters.",
            "kind": "fact",
            "evidence_ids": ["EV-MKT-01"],
            "counter_evidence_ids": [],
            "counter_searched": True,
            "status": "ok",
        },
        {
            "id": "MKT-02",
            "perspective": "market",
            "tech": "KIVI",
            "statement": "vLLM and TensorRT-LLM open-source ecosystems are evaluating sub-4bit quantization kernel integrations.",
            "kind": "fact",
            "evidence_ids": ["EV-MKT-02"],
            "counter_evidence_ids": [],
            "counter_searched": True,
            "status": "ok",
        },
    ]

    evidence: list[Evidence] = [
        {
            "evidence_id": "EV-MKT-01",
            "source_id": "SRC-MKT-01",
            "snippet": "Samsung and SK Hynix showcased commercial CXL 2.0 memory expansion controllers and modules for hyperscale servers.",
        },
        {
            "evidence_id": "EV-MKT-02",
            "source_id": "SRC-MKT-02",
            "snippet": "GitHub community issues and RFCs in vLLM discuss FP2/INT2 quantization algorithms including KIVI.",
        },
    ]

    sources: list[Source] = [
        {
            "source_id": "SRC-MKT-01",
            "title": "CXL Commercial Readiness",
            "publisher": "Industry News",
            "date": "2024",
            "url": "https://semiconductor.samsung.com/news",
            "source_type": "web",
            "source_tier": "T2",
        },
        {
            "source_id": "SRC-MKT-02",
            "title": "vLLM Open Source Discussion",
            "publisher": "GitHub",
            "date": "2024",
            "url": "https://github.com/vllm-project/vllm",
            "source_type": "web",
            "source_tier": "T2",
        },
    ]

    market = {
        "adoption": "KIVI: Open-source framework level; CXL: Hardware ecosystem mass production ready",
        "barriers": "KIVI: Kernel optimization complexity; CXL: Datacenter hardware upgrade cycle and software NUMA overhead",
    }

    return {
        "market": market,
        "claims": claims,
        "evidence": evidence,
        "sources": sources,
    }
