"""src/research/client.py - Tavily Search wrapper, paired queries, and Tier classifier"""
from src.config import TAVILY_API_KEY


def classify_tier(url: str) -> str:
    """Classify URL trustworthiness into T1~T4."""
    u = (url or "").lower()
    if any(domain in u for domain in ["arxiv.org", "ieee.org", "acm.org", "computeexpresslink.org"]):
        return "T1"
    if any(domain in u for domain in ["samsung.com", "skhynix.com", "nvidia.com", "intel.com", "github.com"]):
        return "T2"
    if any(domain in u for domain in ["medium.com", "reddit.com", "tistory.com", "velog.io", "substack.com"]):
        return "T4"
    return "T3"


def search_pair(support_query: str, counter_query: str) -> tuple[dict, dict | None]:
    """Execute paired support and counter queries for R3 bias mitigation."""
    if not TAVILY_API_KEY:
        return {"results": [{"url": "https://semiconductor.samsung.com", "content": "Fallback support snippet"}]}, None
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=TAVILY_API_KEY)
        sup = client.search(query=support_query, max_results=3)
        try:
            cnt = client.search(query=counter_query, max_results=2)
        except Exception:
            cnt = None
        return sup, cnt
    except Exception:
        return {"results": [{"url": "https://semiconductor.samsung.com", "content": "Fallback support snippet"}]}, None
