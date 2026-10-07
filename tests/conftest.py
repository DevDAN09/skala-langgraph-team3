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


@pytest.fixture(autouse=True)
def mock_fetch_source_metadata(monkeypatch):
    """Automatically mock fetch_source_metadata in report_gen to prevent real urlopen calls."""
    import src.synthesis.report_gen as report_gen_mod
    monkeypatch.setattr(report_gen_mod, "fetch_source_metadata", lambda url: {})


class MockAIMessage:
    def __init__(self, content=""):
        self.content = content

    def __str__(self):
        return self.content


class MockChatOpenAI:
    """Mock ChatOpenAI to eliminate unmocked OpenAI API calls during unit tests."""

    def __init__(self, *args, **kwargs):
        self.model = kwargs.get("model", "mock-model")

    def invoke(self, prompt, *args, **kwargs):
        prompt_str = str(prompt)
        if "says about" in prompt_str or "ARTICLE CONTENT" in prompt_str or "Source text:" in prompt_str:
            return MockAIMessage(content="Framework developers report stable integration and positive evaluation results.")
        if "Rewrite the web search question" in prompt_str:
            return MockAIMessage(content="rewritten web search query for evaluation")
        if "초안이다" in prompt_str or "보고서" in prompt_str:
            return MockAIMessage(content=prompt_str)
        return MockAIMessage(content="Mocked LLM completion response for tests.")

    def with_structured_output(self, schema, *args, **kwargs):
        from unittest.mock import MagicMock
        mock_structured = MagicMock()
        try:
            from src.audit.judge import JudgeDecision
            if schema == JudgeDecision:
                mock_structured.invoke.return_value = JudgeDecision(is_grounded=True, reason="Mocked grounded decision")
                return mock_structured
        except Exception:
            pass
        mock_structured.invoke.return_value = MagicMock()
        return mock_structured


@pytest.fixture(autouse=True)
def mock_openai(monkeypatch):
    """Automatically mock ChatOpenAI in all tests to eliminate direct OpenAI API calls."""
    import langchain_openai
    import src.research.client as client_mod

    if not client_mod.OPENAI_API_KEY:
        monkeypatch.setattr(client_mod, "OPENAI_API_KEY", "mock-openai-key")

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", MockChatOpenAI)

    for mod_name in ("src.research.client", "src.synthesis.report_gen", "src.audit.judge", "src.rag.agentic_rag"):
        try:
            import sys
            mod = sys.modules.get(mod_name)
            if mod and hasattr(mod, "ChatOpenAI"):
                monkeypatch.setattr(mod, "ChatOpenAI", MockChatOpenAI)
        except Exception:
            pass

