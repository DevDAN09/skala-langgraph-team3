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


def test_market_retry_only_patches_flagged_claim_and_keeps_market_key_frozen(monkeypatch):
    import src.research.market as mkt
    monkeypatch.setattr(mkt, "rewrite_query", lambda q, reason="": q)
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


def test_stakeholder_retry_only_patches_flagged_claim(monkeypatch):
    import src.research.stakeholder as stk
    monkeypatch.setattr(stk, "rewrite_query", lambda q, reason="": q)
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
    """재실행한 Claim이 속한 Actor 슬롯만 다시 쓰고 나머지 슬롯·키는 그대로 둔다 (설계 5.4)."""
    import src.research.stakeholder as stk
    monkeypatch.setattr(stk, "summarize_snippet", lambda text, focus: "STK-01 new statement.")
    state = _retry_state(
        [_stk_claim("STK-01", status="flagged"), _stk_claim("STK-04", tech="CXL-PNM", statement="STK-04 kept.")],
        {"claim_id": "STK-01", "rule": "R5", "action": "re_extract"},
        evidence=[{"evidence_id": "EV-STK-01", "source_id": "SRC-STK-01", "snippet": "operator snippet."}],
        stakeholder={"memory_vendor": "memory vendor text kept", "hw_vendors": "memory vendor text kept", "extra": "keep me"},
    )
    summary = stakeholder_research_node(state)["stakeholder"]
    assert "Benefit: STK-01 new statement." in summary["cloud_serving_operator"]
    assert summary["cloud_ops"] == summary["cloud_serving_operator"]
    assert summary["memory_vendor"] == "memory vendor text kept"
    assert summary["hw_vendors"] == "memory vendor text kept"
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


def test_stakeholder_dict_keeps_original_contract(monkeypatch):
    """stakeholder dict 구조는 바꾸지 않는다: 키 7개, actors_surveyed만 list이고 나머지는 문자열."""
    import src.research.stakeholder as stk
    monkeypatch.setattr(stk, "search_pair", _fake_search())
    summary = stakeholder_research_node(INITIAL_INPUT_STATE)["stakeholder"]
    assert set(summary) == {"actors_surveyed", "cloud_serving_operator", "framework_developer",
                            "end_user", "memory_vendor", "cloud_ops", "hw_vendors"}
    assert isinstance(summary["actors_surveyed"], list)
    assert all(isinstance(v, str) for k, v in summary.items() if k != "actors_surveyed")
    assert summary["cloud_ops"] == summary["cloud_serving_operator"]
    assert summary["hw_vendors"] == summary["memory_vendor"]


def test_stakeholder_slot_has_benefit_concern_barrier_evidence(monkeypatch):
    """Actor마다 Benefit / Concern / Adoption Barrier / Evidence를 문자열 안에 계열별로 남긴다 (설계 3.5, 3.2).
    Benefit은 지지 근거 Claim, Concern·Barrier는 반대 근거에서만 뽑는다."""
    import src.research.stakeholder as stk
    monkeypatch.setattr(stk, "search_pair", _fake_search())
    monkeypatch.setattr(stk, "summarize_snippet", lambda text, focus: f"{focus.split()[0]}|{text}")
    res = stakeholder_research_node(INITIAL_INPUT_STATE)
    text = res["stakeholder"]["cloud_serving_operator"]
    claim = next(c for c in res["claims"] if c["id"] == "STK-01")
    kivi_part, cxl_part = text.split(" / [")
    assert kivi_part.startswith("[KV Quantization 계열]")
    assert cxl_part.startswith("CXL Memory Expansion 계열]")
    assert f"Benefit: {claim['statement']}" in kivi_part
    assert "Concern: concerns|Counter:" in kivi_part
    assert "Barrier: adoption|Counter:" in kivi_part
    assert "(근거: STK-01, EV-STK-01, EV-STK-01-C)" in kivi_part


def _fake_search_two_counters(first="Counter one about risks.", second="Counter two about adoption barriers."):
    def fake(support_query, counter_query):
        sup = {"results": [{"url": f"https://www.theregister.com/{abs(hash(support_query))}", "title": "s",
                            "content": f"Support: {support_query}."}]}
        h = abs(hash(counter_query))
        cnt = {"results": [
            {"url": f"https://www.zdnet.com/{h}", "title": "c1", "content": first},
            {"url": f"https://www.infoworld.com/{h}", "title": "c2", "content": second},
        ]}
        return sup, cnt
    return fake


def test_stakeholder_barrier_uses_second_counter_result(monkeypatch):
    """Concern과 Barrier가 같은 원문 하나에서 나와 겹치지 않도록, Barrier는 두 번째 반대 검색 결과에서 요약한다.
    Claim 스키마는 그대로: counter_evidence_ids는 첫 번째 반대 근거만 가리킨다."""
    import src.research.stakeholder as stk
    monkeypatch.setattr(stk, "search_pair", _fake_search_two_counters())
    monkeypatch.setattr(stk, "summarize_snippet", lambda text, focus: f"Summary of {text}")
    res = stakeholder_research_node(INITIAL_INPUT_STATE)
    kivi_part = res["stakeholder"]["cloud_serving_operator"].split(" / [")[0]
    assert "Concern: Summary of Counter one about risks." in kivi_part
    assert "Barrier: Summary of Counter two about adoption barriers." in kivi_part
    assert "(근거: STK-01, EV-STK-01, EV-STK-01-C, EV-STK-01-C2)" in kivi_part
    claim = next(c for c in res["claims"] if c["id"] == "STK-01")
    assert claim["counter_evidence_ids"] == ["EV-STK-01-C"]
    ev_ids = {e["evidence_id"] for e in res["evidence"]}
    assert {"EV-STK-01-C", "EV-STK-01-C2"} <= ev_ids
    src_ids = {s["source_id"] for s in res["sources"]}
    assert all(e["source_id"] in src_ids for e in res["evidence"])


def test_stakeholder_barrier_same_as_concern_is_marked_unverified(monkeypatch):
    """반대 근거가 1건뿐이라 요약이 같게 나오면 같은 문장을 반복하지 않고 Barrier를 근거 미확인으로 둔다."""
    import src.research.stakeholder as stk
    monkeypatch.setattr(stk, "search_pair", _fake_search())
    monkeypatch.setattr(stk, "summarize_snippet", lambda text, focus: "Same sentence.")
    text = stakeholder_research_node(INITIAL_INPUT_STATE)["stakeholder"]["cloud_serving_operator"]
    assert "Concern: Same sentence. | Barrier: 근거 미확인" in text


def test_stakeholder_counter_snippet_keeps_more_text_than_support(monkeypatch):
    """반대 근거 snippet은 요약 입력 한도(2000자)까지 보존한다. 지지 근거 snippet은 D의 R5 입력이라 500자 그대로 둔다."""
    import src.research.stakeholder as stk
    long_text = "x" * 3000
    monkeypatch.setattr(stk, "search_pair", _fake_search_two_counters(first=long_text, second=long_text))
    res = stakeholder_research_node(INITIAL_INPUT_STATE)
    ev = {e["evidence_id"]: e for e in res["evidence"]}
    assert len(ev["EV-STK-01-C"]["snippet"]) == 2000
    assert len(ev["EV-STK-01-C2"]["snippet"]) == 2000
    assert len(ev["EV-STK-01"]["snippet"]) <= 500


def test_stakeholder_counter_retry_also_collects_second_counter(monkeypatch):
    """R3 재실행(search_counter_evidence)도 첫 실행과 같은 방식으로 반대 근거 2건을 남긴다."""
    import src.research.stakeholder as stk
    monkeypatch.setattr(stk, "search_pair", _fake_search_two_counters())
    state = _retry_state(
        [_stk_claim("STK-01", status="flagged", counter_searched=False)],
        {"claim_id": "STK-01", "rule": "R3", "action": "search_counter_evidence"},
    )
    res = stakeholder_research_node(state)
    assert {e["evidence_id"] for e in res["evidence"]} == {"EV-STK-01-C", "EV-STK-01-C2"}
    assert res["claims"][0]["counter_evidence_ids"] == ["EV-STK-01-C"]


def test_stakeholder_raw_snippet_fallback_is_not_used_as_concern_or_barrier(monkeypatch):
    """summarize_snippet은 LLM이 NONE을 반환하거나 실패하면 원문 앞부분을 그대로 돌려준다(#18).
    요약이 아니라 페이지 제목·메뉴 같은 잡문이므로 Concern·Barrier로 쓰지 않고 근거 미확인으로 둔다."""
    import src.research.stakeholder as stk
    from src.research.client import _clip_to_sentence
    monkeypatch.setattr(stk, "search_pair", _fake_search_two_counters(
        first="Skip to primary navigation\n Skip to footer\n Investor Relations",
        second="Table of Contents\n\n## Introduction\nLong-context LLM serving is memory-bound.",
    ))
    monkeypatch.setattr(stk, "summarize_snippet", lambda text, focus: _clip_to_sentence(text.strip()))
    text = stakeholder_research_node(INITIAL_INPUT_STATE)["stakeholder"]["cloud_serving_operator"]
    assert "Concern: 근거 미확인 | Barrier: 근거 미확인" in text
    assert "Skip to primary navigation" not in text and "Table of Contents" not in text


def test_stakeholder_slot_text_is_single_line(monkeypatch):
    """요약 문장에 줄바꿈·마크다운 제목이 섞여도 Actor 문자열은 한 줄이다. 보고서 4.3절 목록 구조가 깨지지 않게 한다."""
    import src.research.stakeholder as stk
    monkeypatch.setattr(stk, "search_pair", _fake_search_two_counters())
    monkeypatch.setattr(stk, "summarize_snippet", lambda text, focus: f"{focus.split()[0]} line one.\n\n## Heading\n  line two.")
    summary = stakeholder_research_node(INITIAL_INPUT_STATE)["stakeholder"]
    for key in ("cloud_serving_operator", "framework_developer", "end_user", "memory_vendor", "cloud_ops", "hw_vendors"):
        assert "\n" not in summary[key], key
        assert "## " not in summary[key], key


def test_stakeholder_records_counter_evidence_not_found(monkeypatch):
    """반대 쿼리 결과가 없으면 Concern·Barrier에 counter-evidence not found를 기록한다 (설계 표 11)."""
    import src.research.stakeholder as stk
    monkeypatch.setattr(stk, "search_pair", _fake_search(counter=False))
    text = stakeholder_research_node(INITIAL_INPUT_STATE)["stakeholder"]["framework_developer"]
    assert "Concern: counter-evidence not found | Barrier: counter-evidence not found" in text


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
    assert "[KV Quantization 계열]" in summary["end_user"] and "[CXL Memory Expansion 계열]" in summary["end_user"]


def test_stakeholder_end_user_gap_is_marked_per_tech(monkeypatch):
    """End User 근거가 없으면 기술별로 미확인을 남기고 추정하지 않는다 (설계 3.5)."""
    import src.research.client as client
    monkeypatch.setattr(client, "TAVILY_API_KEY", "")
    summary = stakeholder_research_node(INITIAL_INPUT_STATE)["stakeholder"]
    assert summary["end_user"] == (
        "[KV Quantization 계열] 인용 가능한 지연/품질 간접 근거 미확인"
        " / [CXL Memory Expansion 계열] 인용 가능한 지연/품질 간접 근거 미확인"
    )


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
    monkeypatch.setattr(stk, "rewrite_query", lambda q, reason="": q)
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


def _record_focus(monkeypatch):
    import src.research.stakeholder as stk
    focuses = []
    monkeypatch.setattr(stk, "summarize_snippet", lambda text, focus: (focuses.append(focus), "Summarized.")[1])
    return focuses


def test_stakeholder_focus_describes_family_not_single_tech(monkeypatch):
    """웹 근거는 계열 단위다. focus가 개별 기술만 가리키면 일반론을 KIVI 주장으로 옮겨 쓴다 (설계 3.2)."""
    import src.research.stakeholder as stk
    monkeypatch.setattr(stk, "search_pair", _fake_search())
    focuses = _record_focus(monkeypatch)
    stakeholder_research_node(INITIAL_INPUT_STATE)
    benefit, concern, barrier = focuses[0], focuses[8], focuses[9]  # STK-01: 지지 요약 → (8개 Claim 후) Concern·Barrier
    for f in (benefit, concern, barrier):
        assert "KV Quantization technology family" in f
        assert "(e.g., KIVI)" in f


def test_stakeholder_concern_barrier_do_not_attribute_to_actor(monkeypatch):
    """반대 근거가 그 Actor의 발언이라는 보장이 없다. 주어를 지어내지 않게 한다 (설계 4.5 페르소나 금지)."""
    import src.research.stakeholder as stk
    monkeypatch.setattr(stk, "search_pair", _fake_search())
    focuses = _record_focus(monkeypatch)
    stakeholder_research_node(INITIAL_INPUT_STATE)
    for f in focuses[8:]:
        assert "raised by" not in f and "faced by" not in f
        assert "relevant to the" in f
        assert "Do not attribute" in f


def test_stakeholder_re_extract_reuses_initial_benefit_focus(monkeypatch):
    """R5 재추출은 처음 생성할 때와 같은 초점으로, snippet 내용만 다시 서술한다."""
    import src.research.stakeholder as stk
    monkeypatch.setattr(stk, "search_pair", _fake_search())
    focuses = _record_focus(monkeypatch)
    stakeholder_research_node(INITIAL_INPUT_STATE)
    initial = focuses[0]
    focuses.clear()
    state = _retry_state(
        [_stk_claim("STK-01", status="flagged")],
        {"claim_id": "STK-01", "rule": "R5", "action": "re_extract"},
        evidence=[{"evidence_id": "EV-STK-01", "source_id": "SRC-STK-01", "snippet": "operator snippet."}],
    )
    stakeholder_research_node(state)
    assert focuses[0].startswith(initial)
    assert "Restate only what the text says" in focuses[0]


def test_stakeholder_queries_are_scoped_to_cloud_serving():
    """평가 도메인은 클라우드 LLM 서빙 (설계 3.1). 온디바이스 양자화 글이 잡히지 않게 모든 쿼리에 서빙 범위를 둔다."""
    scope = ("cloud", "data center", "serving", "server")
    for q in STAKEHOLDER_QUERY_PLAN:
        for key in ("support", "counter"):
            assert any(s in q[key].lower() for s in scope), (q["claim_id"], key, q[key])



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


def test_rewrite_query_returns_original_without_llm(monkeypatch):
    """키가 없으면 재작성을 포기하고 원본 질의를 그대로 쓴다 (Graceful Degradation)."""
    import src.research.client as client

    monkeypatch.setattr(client, "OPENAI_API_KEY", "")
    assert client.rewrite_query("who ships CXL memory?") == "who ships CXL memory?"


def test_market_skips_result_without_usable_statement(monkeypatch):
    """검색 1위가 본문 없는 리스팅 페이지면 다음 후보로 넘어간다 (예전에는 results[0]만 썼다)."""
    import src.research.market as mkt

    results = [
        {"url": "https://www.theregister.com/listing", "title": "listing", "content": "Sign up Log in"},
        {"url": "https://www.zdnet.com/article", "title": "article", "content": "vLLM ships KV cache quantization."},
    ]
    monkeypatch.setattr(mkt, "search_pair", lambda s, c, **kw: ({"results": results}, None))
    monkeypatch.setattr(mkt, "summarize_snippet",
                        lambda text, focus: "" if "Sign up" in text else "Usable statement.")
    res = market_research_node(INITIAL_INPUT_STATE)

    claim = next(c for c in res["claims"] if c["id"] == "MKT-01")
    ev = next(e for e in res["evidence"] if e["evidence_id"] == "EV-MKT-01")
    src = {s["source_id"]: s for s in res["sources"]}[ev["source_id"]]
    assert claim["statement"] == "Usable statement."
    assert claim["status"] == "ok"
    assert src["url"] == "https://www.zdnet.com/article"


def test_market_leaves_claim_insufficient_instead_of_quoting_boilerplate(monkeypatch):
    """후보가 전부 쓸 수 없으면 statement를 비우고 insufficient로 남긴다. 요약 dict에도 원문이 새지 않는다."""
    import src.research.market as mkt

    results = [{"url": "https://www.theregister.com/listing", "title": "l", "content": "Sign up Log in"}]
    monkeypatch.setattr(mkt, "search_pair", lambda s, c, **kw: ({"results": results}, None))
    monkeypatch.setattr(mkt, "summarize_snippet", lambda text, focus: "")
    res = market_research_node(INITIAL_INPUT_STATE)

    claim = next(c for c in res["claims"] if c["id"] == "MKT-01")
    assert claim["statement"] == ""
    assert claim["status"] == "insufficient"
    assert all("Sign up" not in res["market"][axis]
               for axis in ("adoption", "deployment", "ecosystem", "barriers"))


def test_market_search_evidence_retry_rewrites_query_and_skips_previous_url(monkeypatch):
    """재검색은 질의를 다시 쓰고 직전 근거 URL을 제외한다.

    같은 질의를 그대로 다시 던지면 같은 결과가 돌아와 재시도 한도(2회)만 소진한다.
    """
    import src.research.market as mkt

    recorded = []
    results = [
        {"url": "https://www.theregister.com/a", "title": "a", "content": "First article."},
        {"url": "https://www.zdnet.com/b", "title": "b", "content": "Second article."},
    ]

    def fake_search(support_query, counter_query, **kwargs):
        recorded.extend([support_query, counter_query])
        return {"results": results}, None

    monkeypatch.setattr(mkt, "search_pair", fake_search)
    monkeypatch.setattr(mkt, "summarize_snippet", lambda text, focus: "Restated from the new source.")
    monkeypatch.setattr(mkt, "rewrite_query", lambda q, reason="": f"rewritten: {q}")

    old_src = {"source_id": "SRC-MKT-01", "title": "a", "publisher": "Web", "date": "n.d.",
               "url": "https://www.theregister.com/a", "source_type": "web", "source_tier": "T3"}
    state = {
        **INITIAL_INPUT_STATE,
        "claims": [{"id": "MKT-01", "perspective": "market", "tech": "KIVI", "statement": "old statement",
                    "kind": "fact", "evidence_ids": ["EV-MKT-01"], "counter_evidence_ids": [],
                    "counter_searched": True, "status": "flagged"}],
        "evidence": [{"evidence_id": "EV-MKT-01", "source_id": "SRC-MKT-01", "snippet": "First article."}],
        "sources": [old_src],
        "audit": {"issues": [{"claim_id": "MKT-01", "rule": "R2", "issue": "T4 only",
                              "target_agent": "market", "action": "search_evidence"}]},
    }
    res = market_research_node(state)

    assert recorded and all(q.startswith("rewritten: ") for q in recorded)
    ev = next(e for e in res["evidence"] if e["evidence_id"] == "EV-MKT-01")
    src = {s["source_id"]: s for s in union_sources([old_src], res["sources"])}[ev["source_id"]]
    assert src["url"] == "https://www.zdnet.com/b"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
