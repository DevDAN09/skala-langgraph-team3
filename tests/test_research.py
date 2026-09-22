from unittest.mock import patch

from tests.mock_data import INITIAL_INPUT_STATE
from src.state import union_sources
from src.research.client import classify_tier, search_pair, infer_kind, resolve_source_id, vendor_label
from src.research.market import market_research_node, MARKET_QUERY_PLAN, MAT_A_PLAN
from src.research.stakeholder import stakeholder_research_node, STAKEHOLDER_QUERY_PLAN


def test_classify_tier():
    assert classify_tier("https://arxiv.org/abs/2402.02750") == "T1"
    assert classify_tier("https://semiconductor.samsung.com/news") == "T2"
    assert classify_tier("https://www.anandtech.com/show/1234") == "T3"
    assert classify_tier("https://medium.com/@user/post") == "T4"


def test_infer_kind_vendor_domain_is_vendor_claim():
    # 벤더 자체 도메인 발표는 독립 검증된 fact가 아니라 vendor_claim (R4 대응)
    assert infer_kind("https://semiconductor.samsung.com/news") == "vendor_claim"
    assert infer_kind("https://www.nvidia.com/blog") == "vendor_claim"
    # 제3자 보도/커뮤니티는 fact
    assert infer_kind("https://github.com/vllm-project/vllm") == "fact"
    assert infer_kind("https://www.anandtech.com/show/1234") == "fact"


def test_infer_kind_forecast_content_is_estimate():
    # 시장 리포트의 CAGR/미래 예측 수치는 실측 fact가 아니라 estimate로 분류한다
    forecast_content = "The market is projected to reach $11.8 billion by 2034 at a CAGR of 28.7%."
    assert infer_kind("https://marketintelo.com/report/cxl-memory", forecast_content) == "estimate"
    # 예측 문구가 없으면 기존처럼 fact
    assert infer_kind("https://marketintelo.com/report/cxl-memory", "vLLM added support for this feature.") == "fact"
    # 벤더 도메인이 우선한다 (벤더가 자기 예측을 말해도 vendor_claim)
    assert infer_kind("https://www.nvidia.com/blog", forecast_content) == "vendor_claim"


def test_vendor_label_maps_known_domains():
    assert vendor_label("https://semiconductor.samsung.com/news") == "Samsung"
    assert vendor_label("https://github.com/vllm-project/vllm") == "GitHub OSS community"
    assert vendor_label("https://www.anandtech.com/show/1234") is None


def test_resolve_source_id_reuses_existing_url():
    # Task A 발신: URL이 같은데 source_id가 다르면 뒤에 들어온 Source가 버려지는 문제의 회귀 테스트.
    existing = [{"source_id": "SRC-MKT-01", "url": "https://semiconductor.samsung.com", "title": "x",
                 "publisher": "Samsung", "date": "2024", "source_type": "web", "source_tier": "T2"}]
    reused = resolve_source_id("https://semiconductor.samsung.com", existing, "SRC-STK-01")
    assert reused == "SRC-MKT-01"

    fresh = resolve_source_id("https://a-totally-different-domain.com", existing, "SRC-STK-02")
    assert fresh == "SRC-STK-02"

    # URL 없는 경우 항상 proposed_id를 그대로 쓴다
    assert resolve_source_id("", existing, "SRC-STK-03") == "SRC-STK-03"


def test_market_node_counter_searched_rule():
    res = market_research_node(INITIAL_INPUT_STATE)
    assert "market" in res
    assert "claims" in res
    assert "evidence" in res
    assert "sources" in res
    for c in res["claims"]:
        assert c["counter_searched"] is True
        assert c["status"] in ("ok", "insufficient")


def test_market_node_claim_ids_and_fields_are_in_contract_range():
    res = market_research_node(INITIAL_INPUT_STATE)
    mkt_ids = {q["claim_id"] for q in MARKET_QUERY_PLAN}
    mat_a_ids = {q["claim_id"] for q in MAT_A_PLAN}
    assert mkt_ids <= {f"MKT-{i:02d}" for i in range(1, 9)}
    assert mat_a_ids <= {"MAT-A01", "MAT-A02"}

    returned_ids = {c["id"] for c in res["claims"]}
    assert returned_ids == mkt_ids | mat_a_ids

    for c in res["claims"]:
        assert c["tech"] in ("KIVI", "CXL-PNM")  # "General" 금지
        assert c["perspective"] in ("market", "maturity")
    assert all(c["id"].startswith("MAT-A") for c in res["claims"] if c["perspective"] == "maturity")

    assert "key_vendors" in res["market"]
    assert all(axis in res["market"] for axis in ("adoption", "deployment", "ecosystem", "barriers"))


def test_stakeholder_node_counter_searched_rule():
    res = stakeholder_research_node(INITIAL_INPUT_STATE)
    assert "stakeholder" in res
    assert "claims" in res
    assert "evidence" in res
    assert "sources" in res
    for c in res["claims"]:
        assert c["counter_searched"] is True
        assert c["status"] in ("ok", "insufficient")


def test_stakeholder_node_reads_market_context_and_covers_four_actors():
    market_ctx = {"market": {"key_vendors": ["Samsung", "SK Hynix"], "adoption": "x", "ecosystem": "y"}}
    state = {**INITIAL_INPUT_STATE, **market_ctx}
    res = stakeholder_research_node(state)

    assert len(STAKEHOLDER_QUERY_PLAN) == 4
    assert {c["id"] for c in res["claims"]} == {"STK-01", "STK-02", "STK-03", "STK-04"}
    for c in res["claims"]:
        assert c["tech"] in ("KIVI", "CXL-PNM")
        assert c["perspective"] == "stakeholder"
    # stakeholder는 market 딕셔너리를 절대 반환하지 않는다 (쓰기 권한은 market 노드 전용)
    assert "market" not in res


def test_stakeholder_node_does_not_overwrite_market_when_market_missing():
    # market 노드가 아직 실행되지 않았어도(빈 dict) 기본 vendor로 안전하게 동작해야 함
    res = stakeholder_research_node(INITIAL_INPUT_STATE)
    assert "market" not in res
    assert res["stakeholder"]["actors_surveyed"]


def test_market_to_stakeholder_url_dedup_chain_keeps_evidence_linked():
    """Issue #3 재현: market과 stakeholder가 같은 URL(예: vLLM GitHub)을 인용해도
    union_sources 리듀서를 거친 뒤 모든 evidence.source_id가 실존 source를 가리켜야 한다.

    client.search_pair()는 이제 키가 없으면 빈 결과({"results": []})를 반환하므로
    (Issue #3: 가짜 URL로 Source를 만들지 않음) 실제 URL 충돌 상황을 오프라인에서
    결정론적으로 재현하려면 search_pair 자체를 모킹해야 한다.
    """
    shared_url = "https://github.com/vllm-project/vllm"

    def fake_search_pair(support_query, counter_query, **kwargs):
        return (
            {"results": [{
                "url": shared_url, "title": "vLLM", "published_date": "2024",
                "content": f"Result for: {support_query}",
            }]},
            {"results": [{
                "url": "https://example.com/counter", "title": "Counter", "published_date": "2024",
                "content": "counter content",
            }]},
        )

    with patch("src.research.market.search_pair", side_effect=fake_search_pair), \
         patch("src.research.stakeholder.search_pair", side_effect=fake_search_pair):
        m = market_research_node(INITIAL_INPUT_STATE)
        sources_after_market = union_sources(INITIAL_INPUT_STATE["sources"], m["sources"])
        state_after_market = {**INITIAL_INPUT_STATE, **m, "sources": sources_after_market}

        s = stakeholder_research_node(state_after_market)

    final_sources = union_sources(sources_after_market, s["sources"])
    final_source_ids = {src["source_id"] for src in final_sources}

    all_evidence = m["evidence"] + s["evidence"]
    assert all_evidence, "모킹이 제대로 되지 않아 evidence가 하나도 만들어지지 않았다"
    for ev in all_evidence:
        assert ev["source_id"] in final_source_ids, (
            f"{ev['evidence_id']} points to {ev['source_id']} which was dropped by union_sources"
        )

    # dedup이 실제로 일어났는지: 같은 URL은 최종적으로 Source 1개로만 수렴해야 한다
    shared_url_sources = [src for src in final_sources if src["url"] == shared_url]
    assert len(shared_url_sources) == 1, "같은 URL이 union_sources 이후에도 여러 Source로 남아있다"


def test_market_retry_only_patches_flagged_claim_and_keeps_market_key_frozen():
    state = {
        **INITIAL_INPUT_STATE,
        "audit": {"issues": [{
            "claim_id": "MKT-02", "rule": "R1", "issue": "missing evidence",
            "target_agent": "market", "action": "search_evidence",
        }]},
    }
    res = market_research_node(state)
    assert [c["id"] for c in res["claims"]] == ["MKT-02"]
    assert "market" not in res  # Overwrite 리듀서 보호: 재실행에서 market 요약을 지우면 안 됨


def test_stakeholder_retry_only_patches_flagged_claim():
    state = {
        **INITIAL_INPUT_STATE,
        "audit": {"issues": [{
            "claim_id": "STK-03", "rule": "R3", "issue": "missing counter search",
            "target_agent": "stakeholder", "action": "search_counter_evidence",
        }]},
    }
    res = stakeholder_research_node(state)
    assert [c["id"] for c in res["claims"]] == ["STK-03"]
    assert "stakeholder" not in res


def test_search_pair():
    sup, cnt = search_pair("support query", "counter query")
    assert isinstance(sup, dict)
    assert "results" in sup


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
