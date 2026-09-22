from tests.mock_data import INITIAL_INPUT_STATE
from src.research.client import classify_tier, search_pair
from src.research.market import market_research_node
from src.research.stakeholder import stakeholder_research_node


def test_classify_tier():
    assert classify_tier("https://arxiv.org/abs/2402.02750") == "T1"
    assert classify_tier("https://semiconductor.samsung.com/news") == "T2"
    assert classify_tier("https://www.anandtech.com/show/1234") == "T3"
    assert classify_tier("https://medium.com/@user/post") == "T4"


def test_market_node_counter_searched_rule():
    res = market_research_node(INITIAL_INPUT_STATE)
    assert "market" in res
    assert "claims" in res
    assert "evidence" in res
    assert "sources" in res
    for c in res["claims"]:
        assert c["counter_searched"] is True
        assert c["status"] == "ok"


def test_stakeholder_node_counter_searched_rule():
    res = stakeholder_research_node(INITIAL_INPUT_STATE)
    assert "stakeholder" in res
    assert "claims" in res
    assert "evidence" in res
    assert "sources" in res
    for c in res["claims"]:
        assert c["counter_searched"] is True
        assert c["status"] == "ok"


def test_search_pair():
    sup, cnt = search_pair("support query", "counter query")
    assert isinstance(sup, dict)
    assert "results" in sup
