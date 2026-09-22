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

    # 4대 Actor × 기술 계열 2개 (설계 3.2·3.5, #8). STK-01~04 의미는 유지하고 05~08로 반대 계열을 채운다.
    assert len(STAKEHOLDER_QUERY_PLAN) == 8
    assert {c["id"] for c in res["claims"]} == {f"STK-0{i}" for i in range(1, 9)}
    for c in res["claims"]:
        assert c["tech"] in ("KIVI", "CXL-PNM")
        assert c["perspective"] == "stakeholder"
    techs_by_actor = {}
    for q in STAKEHOLDER_QUERY_PLAN:
        techs_by_actor.setdefault(q["actor"], set()).add(q["tech"])
    assert len(techs_by_actor) == 4
    assert all(t == {"KIVI", "CXL-PNM"} for t in techs_by_actor.values())
    # stakeholder는 market 딕셔너리를 절대 반환하지 않는다 (쓰기 권한은 market 노드 전용)
    assert "market" not in res


def test_stakeholder_node_does_not_overwrite_market_when_market_missing():
    # market 노드가 아직 실행되지 않았어도(빈 dict) 기본 vendor로 안전하게 동작해야 함
    res = stakeholder_research_node(INITIAL_INPUT_STATE)
    assert "market" not in res
    assert res["stakeholder"]["actors_surveyed"]


def test_market_to_stakeholder_url_dedup_chain_keeps_evidence_linked():
    """Task A 발신 버그 재현: market과 stakeholder가 같은 URL을 인용해도
    union_sources 리듀서를 거친 뒤 모든 evidence.source_id가 실존 source를 가리켜야 한다."""
    m = market_research_node(INITIAL_INPUT_STATE)
    sources_after_market = union_sources(INITIAL_INPUT_STATE["sources"], m["sources"])
    state_after_market = {**INITIAL_INPUT_STATE, **m, "sources": sources_after_market}

    s = stakeholder_research_node(state_after_market)
    final_sources = union_sources(sources_after_market, s["sources"])
    final_source_ids = {src["source_id"] for src in final_sources}

    all_evidence = m["evidence"] + s["evidence"]
    for ev in all_evidence:
        assert ev["source_id"] in final_source_ids, (
            f"{ev['evidence_id']} points to {ev['source_id']} which was dropped by union_sources"
        )


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
    assert "market" not in res


def _stk_claim(claim_id, **kw):
    base = {
        "id": claim_id, "perspective": "stakeholder", "tech": "KIVI", "statement": f"{claim_id} old statement.",
        "kind": "fact", "evidence_ids": [f"EV-{claim_id}"], "counter_evidence_ids": [],
        "counter_searched": True, "status": "ok",
    }
    return {**base, **kw}


def _retry_state(claims, issue, evidence=None, sources=None, stakeholder=None):
    return {
        **INITIAL_INPUT_STATE,
        "claims": claims,
        "evidence": evidence or [],
        "sources": sources or [],
        "stakeholder": stakeholder or {},
        "audit": {"issues": [{"issue": "", "target_agent": "stakeholder", **issue}]},
    }


def test_stakeholder_counter_retry_without_result_restores_ok(monkeypatch):
    """반대 쿼리를 다시 실행했는데 결과가 없으면 counter-evidence not found로 두고 상태는 ok (common.md 5절 ②)."""
    import src.research.stakeholder as stk
    monkeypatch.setattr(stk, "search_pair", lambda s, c: ({"results": []}, None))
    state = _retry_state(
        [_stk_claim("STK-01", status="flagged", counter_searched=False)],
        {"claim_id": "STK-01", "rule": "R3", "action": "search_counter_evidence"},
    )
    claim = stakeholder_research_node(state)["claims"][0]
    assert claim["counter_searched"] is True
    assert claim["status"] == "ok"


def test_stakeholder_retry_patches_only_its_summary_slot(monkeypatch):
    """재실행한 Claim의 요약 슬롯만 갱신하고 나머지 Actor 슬롯은 그대로 둔다 (설계 5.4)."""
    import src.research.stakeholder as stk
    monkeypatch.setattr(stk, "summarize_snippet", lambda text, focus: "STK-01 new statement.")
    kept = {"claim_id": "STK-04", "benefit": "STK-04 kept.", "concern": "c", "barrier": "b", "evidence_ids": ["EV-STK-04"]}
    state = _retry_state(
        [_stk_claim("STK-01", status="flagged"), _stk_claim("STK-04", tech="CXL-PNM", statement="STK-04 kept.")],
        {"claim_id": "STK-01", "rule": "R5", "action": "re_extract"},
        evidence=[{"evidence_id": "EV-STK-01", "source_id": "SRC-STK-01", "snippet": "operator snippet."}],
        stakeholder={"memory_vendor": {"CXL-PNM": kept}, "extra": "keep me"},
    )
    summary = stakeholder_research_node(state)["stakeholder"]
    assert summary["cloud_serving_operator"]["KIVI"]["benefit"] == "STK-01 new statement."
    assert "STK-01 new statement." in summary["cloud_ops"]
    assert summary["memory_vendor"]["CXL-PNM"] == kept
    assert summary["extra"] == "keep me"


def _fake_search(recorded=None, counter=True):
    def fake(support_query, counter_query):
        if recorded is not None:
            recorded.extend([support_query, counter_query])
        sup = {"results": [{"url": f"https://www.theregister.com/{abs(hash(support_query))}", "title": "s",
                            "content": f"Support: {support_query}."}]}
        cnt = {"results": [{"url": f"https://www.zdnet.com/{abs(hash(counter_query))}", "title": "c",
                            "content": f"Counter: {counter_query}."}]} if counter else None
        return sup, cnt
    return fake


def test_stakeholder_slot_has_benefit_concern_barrier_evidence(monkeypatch):
    """Actor마다 Benefit / Concern / Adoption Barrier / Evidence를 남긴다 (설계 3.5).
    Benefit은 지지 근거 Claim, Concern·Barrier는 반대 근거에서만 뽑는다."""
    import src.research.stakeholder as stk
    monkeypatch.setattr(stk, "search_pair", _fake_search())
    monkeypatch.setattr(stk, "summarize_snippet", lambda text, focus: f"{focus.split()[0]}|{text}")
    res = stakeholder_research_node(INITIAL_INPUT_STATE)
    slot = res["stakeholder"]["cloud_serving_operator"]["KIVI"]
    claim = next(c for c in res["claims"] if c["id"] == "STK-01")
    assert slot["claim_id"] == "STK-01"
    assert slot["benefit"] == claim["statement"]
    assert slot["concern"].startswith("concerns|Counter:")
    assert slot["barrier"].startswith("adoption|Counter:")
    assert slot["evidence_ids"] == ["EV-STK-01", "EV-STK-01-C"]


def test_stakeholder_records_counter_evidence_not_found(monkeypatch):
    """반대 쿼리 결과가 없으면 Concern·Barrier에 counter-evidence not found를 기록한다 (설계 표 11)."""
    import src.research.stakeholder as stk
    monkeypatch.setattr(stk, "search_pair", _fake_search(counter=False))
    slot = stakeholder_research_node(INITIAL_INPUT_STATE)["stakeholder"]["framework_developer"]["CXL-PNM"]
    assert slot["concern"] == slot["barrier"] == "counter-evidence not found"
    assert slot["benefit"]


def test_stakeholder_queries_use_tech_relevant_vendor_from_market(monkeypatch):
    """market.key_vendors 중 기술 계열에 맞는 벤더로 쿼리를 구체화한다. 알파벳순 첫 항목을 쓰지 않는다."""
    import src.research.stakeholder as stk
    recorded = []
    monkeypatch.setattr(stk, "search_pair", _fake_search(recorded))
    state = {**INITIAL_INPUT_STATE, "market": {"key_vendors": ["GitHub OSS community", "NVIDIA", "SK Hynix", "Samsung"]}}
    stakeholder_research_node(state)
    by_id = dict(zip([q["claim_id"] for q in stk.STAKEHOLDER_QUERY_PLAN], recorded[::2]))
    assert "Samsung" in by_id["STK-04"] and "Samsung" in by_id["STK-05"]
    assert "NVIDIA" in by_id["STK-08"]
    assert not any("GitHub OSS community" in q for q in recorded)


def test_stakeholder_queries_without_market_context_have_no_placeholder_vendor(monkeypatch):
    import src.research.stakeholder as stk
    recorded = []
    monkeypatch.setattr(stk, "search_pair", _fake_search(recorded))
    stakeholder_research_node(INITIAL_INPUT_STATE)
    assert not any("Cloud CSPs" in q or "leading vendors" in q or "  " in q for q in recorded)


def test_stakeholder_summary_labels_family_evidence(monkeypatch):
    """시장성·이해관계자 근거는 계열 근거임을 표기한다 (설계 3.2). E 템플릿용 문자열 별칭에도 계열명이 붙는다."""
    import src.research.stakeholder as stk
    results = [{"url": "https://www.theregister.com/a", "title": "a", "content": "Operators report lower serving cost."}]
    monkeypatch.setattr(stk, "search_pair", lambda s, c: ({"results": results}, None))
    summary = stakeholder_research_node(INITIAL_INPUT_STATE)["stakeholder"]
    for alias in ("cloud_ops", "hw_vendors"):
        assert isinstance(summary[alias], str)
        assert "KV Quantization" in summary[alias]
        assert "CXL Memory Expansion" in summary[alias]
    assert set(summary["end_user"]) == {"KIVI", "CXL-PNM"}


def test_stakeholder_end_user_gap_is_marked_per_tech(monkeypatch):
    """End User 근거가 없으면 기술별로 미확인을 남기고 추정하지 않는다 (설계 3.5)."""
    import src.research.client as client
    monkeypatch.setattr(client, "TAVILY_API_KEY", "")
    summary = stakeholder_research_node(INITIAL_INPUT_STATE)["stakeholder"]
    assert {tech: v["benefit"] for tech, v in summary["end_user"].items()} == {
        "KIVI": "인용 가능한 지연/품질 간접 근거 미확인",
        "CXL-PNM": "인용 가능한 지연/품질 간접 근거 미확인",
    }


def test_stakeholder_prefers_non_t4_source(monkeypatch):
    """T4(블로그) 단독 근거를 피하려고 검색 결과 중 T1~T3를 먼저 채택한다 (R2)."""
    import src.research.stakeholder as stk
    results = [
        {"url": "https://medium.com/post", "title": "blog", "content": "Blog text about serving."},
        {"url": "https://www.theregister.com/news", "title": "news", "content": "News text about serving."},
    ]
    monkeypatch.setattr(stk, "search_pair", lambda s, c: ({"results": results}, None))
    res = stakeholder_research_node({**INITIAL_INPUT_STATE, "market": {"key_vendors": ["Samsung"]}})
    tiers = {s["source_id"]: s["source_tier"] for s in res["sources"]}
    ev = next(e for e in res["evidence"] if e["evidence_id"] == "EV-STK-01")
    assert tiers[ev["source_id"]] == "T3"


def test_stakeholder_search_evidence_retry_skips_previous_url(monkeypatch):
    """재검색은 같은 결과를 다시 채택하지 않고 직전 근거 URL을 제외한다 (재시도 낭비 방지)."""
    import src.research.stakeholder as stk
    results = [
        {"url": "https://www.theregister.com/a", "title": "a", "content": "First article."},
        {"url": "https://www.zdnet.com/b", "title": "b", "content": "Second article."},
    ]
    monkeypatch.setattr(stk, "search_pair", lambda s, c: ({"results": results}, None))
    old_src = {"source_id": "SRC-STK-01", "title": "a", "publisher": "Web", "date": "n.d.",
               "url": "https://www.theregister.com/a", "source_type": "web", "source_tier": "T3"}
    state = _retry_state(
        [_stk_claim("STK-01", status="flagged")],
        {"claim_id": "STK-01", "rule": "R2", "action": "search_evidence"},
        evidence=[{"evidence_id": "EV-STK-01", "source_id": "SRC-STK-01", "snippet": "First article."}],
        sources=[old_src],
    )
    res = stakeholder_research_node(state)
    ev = next(e for e in res["evidence"] if e["evidence_id"] == "EV-STK-01")
    src = {s["source_id"]: s for s in union_sources([old_src], res["sources"])}[ev["source_id"]]
    assert src["url"] == "https://www.zdnet.com/b"


def test_stakeholder_relabel_changes_fact_even_on_non_vendor_domain():
    """R4 relabel은 URL 도메인과 무관하게 fact를 vendor_claim으로 바꿔야 재위반 루프가 끝난다."""
    src = {"source_id": "SRC-STK-02", "title": "t", "publisher": "Web", "date": "n.d.",
           "url": "https://www.theregister.com/x", "source_type": "web", "source_tier": "T3"}
    state = _retry_state(
        [_stk_claim("STK-02", status="flagged")],
        {"claim_id": "STK-02", "rule": "R4", "action": "relabel"},
        evidence=[{"evidence_id": "EV-STK-02", "source_id": "SRC-STK-02", "snippet": "Vendor says 2x."}],
        sources=[src],
    )
    claim = stakeholder_research_node(state)["claims"][0]
    assert claim["kind"] == "vendor_claim"
    assert claim["status"] == "ok"


def test_search_pair():
    sup, cnt = search_pair("support query", "counter query")
    assert isinstance(sup, dict)
    assert "results" in sup


def test_search_pair_fallback_returns_no_fabricated_result(monkeypatch):
    """키가 없거나 Tavily 호출이 실패하면 가짜 URL·snippet 대신 빈 결과를 돌려준다 (common.md 7절 ②, 가짜 URL 금지)."""
    import src.research.client as client
    monkeypatch.setattr(client, "TAVILY_API_KEY", "")
    assert client.search_pair("support", "counter") == ({"results": []}, None)

    class BrokenTavily:
        def __init__(self, api_key):
            raise RuntimeError("network down")

    import tavily
    monkeypatch.setattr(client, "TAVILY_API_KEY", "dummy-key")
    monkeypatch.setattr(tavily, "TavilyClient", BrokenTavily)
    assert client.search_pair("support", "counter") == ({"results": []}, None)


def test_stakeholder_without_search_results_is_insufficient(monkeypatch):
    """검색 결과가 없으면 추측으로 채우지 않고 insufficient, Source도 만들지 않는다."""
    import src.research.client as client
    monkeypatch.setattr(client, "TAVILY_API_KEY", "")
    res = stakeholder_research_node(INITIAL_INPUT_STATE)
    assert {c["status"] for c in res["claims"]} == {"insufficient"}
    assert all(c["statement"] == "" for c in res["claims"])
    assert res["sources"] == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
