"""tests/conftest.py - Global test fixtures and mocking for external services."""
import pytest


class MockTavilyClient:
    """Mock TavilyClient that avoids real external network/API calls during tests."""

    def __init__(self, api_key=None, **kwargs):
        self.api_key = api_key

    def search(
        self,
        query: str,
        max_results: int = 3,
        search_depth: str = "advanced",
        time_range: str | None = None,
        **kwargs,
    ):
        q = (query or "").lower()
        if "cxl" in q:
            url = "https://semiconductor.samsung.com/news-events/news/cxl-dram"
            title = "Samsung CXL Memory Solutions for Data Centers"
            content = f"Evaluation and deployment data for {query}. High scalability and lower TCO observed."
        else:
            url = "https://github.com/vllm-project/vllm"
            title = "vLLM KV Cache Quantization Support"
            content = f"Framework integration and serving pilot for {query}. Efficient 2-bit quantization tested."

        return {
            "results": [
                {
                    "url": url,
                    "title": title,
                    "content": content,
                    "published_date": "2024-06-01",
                }
            ]
        }


@pytest.fixture(autouse=True)
def mock_tavily(monkeypatch):
    """Automatically mock TavilyClient in all tests to eliminate direct Tavily API calls."""
    import tavily
    import src.research.client as client_mod

    if not client_mod.TAVILY_API_KEY:
        monkeypatch.setattr(client_mod, "TAVILY_API_KEY", "mock-tavily-key")

    monkeypatch.setattr(tavily, "TavilyClient", MockTavilyClient)
