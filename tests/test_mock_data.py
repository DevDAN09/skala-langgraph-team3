from tests.mock_data import MOCK_STATE, INITIAL_INPUT_STATE


def test_mock_state_keys():
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
    assert set(MOCK_STATE.keys()) == expected_keys
    assert set(INITIAL_INPUT_STATE.keys()) == expected_keys


def test_mock_state_constraints():
    for claim in MOCK_STATE["claims"]:
        assert claim["tech"] in ["KIVI", "CXL-PNM"]
        if claim["tech"] == "CXL-PNM" and claim["perspective"] == "domain":
            assert claim["kind"] == "simulation"

        # Domain constraint: no winner/superiority claims
        statement_lower = claim["statement"].lower()
        for forbidden in ["is superior to", "wins over", "is clearly better", "outperforms overall"]:
            assert forbidden not in statement_lower

    # Source tier constraint: valid source tiers T1/T2
    for source in MOCK_STATE["sources"]:
        assert source["source_tier"] in ["T1", "T2"]


def test_mock_state_referential_integrity():
    source_ids = {s["source_id"] for s in MOCK_STATE["sources"]}
    evidence_ids = {e["evidence_id"] for e in MOCK_STATE["evidence"]}

    for ev in MOCK_STATE["evidence"]:
        assert ev["source_id"] in source_ids

    for claim in MOCK_STATE["claims"]:
        for ev_id in claim["evidence_ids"]:
            assert ev_id in evidence_ids


def test_initial_input_state_defaults():
    assert INITIAL_INPUT_STATE["selected"]["sw"] == "KIVI"
    assert INITIAL_INPUT_STATE["selected"]["hw"] == "CXL-PNM"
    assert INITIAL_INPUT_STATE["claims"] == []
    assert INITIAL_INPUT_STATE["evidence"] == []
    assert INITIAL_INPUT_STATE["sources"] == []
    assert INITIAL_INPUT_STATE["audit"] == {"issues": []}
    assert INITIAL_INPUT_STATE["retry_count"] == {"paper": 0, "market": 0, "stakeholder": 0}
    assert INITIAL_INPUT_STATE["report"] == ""


def test_mock_sources_match_design_references():
    """설계서 표 5의 원문 서지 정보와 같아야 한다. 가짜 URL은 REFERENCE로 새어 나간다."""
    src = {s["source_id"]: s for s in MOCK_STATE["sources"]}
    assert src["SRC-PAPER-KIVI"]["url"] == "https://arxiv.org/abs/2402.02750"
    assert src["SRC-PAPER-CXL-PNM"]["url"] == "https://arxiv.org/abs/2511.00321"
    assert src["SRC-PAPER-CXL-PNM"]["date"] == "2025"
    for trl in MOCK_STATE["trl"].values():
        assert not any("PACT 2024" in e for e in trl["research_evidence"])


def test_mock_has_no_unsupported_claims():
    """근거 없는 비용 단정·수치는 mock에도 넣지 않는다 (role_A §7 공통)."""
    import json
    text = json.dumps(MOCK_STATE, ensure_ascii=False).lower()
    for banned in ["zero capex", "zero-capex", "3.1x", "fp2"]:
        assert banned not in text, banned


def test_mock_vendor_press_is_vendor_claim():
    claims = {c["id"]: c for c in MOCK_STATE["claims"]}
    assert claims["MKT-01"]["kind"] == "vendor_claim"


def test_mock_market_exposes_key_vendors_for_stakeholder_chaining():
    assert MOCK_STATE["market"]["key_vendors"]


def test_mock_cxl_paper_title_matches_actual_paper():
    """data/papers/cxl_pnm.pdf 실제 제목과 같아야 한다 (REFERENCE에 그대로 인용됨)."""
    src = {s["source_id"]: s for s in MOCK_STATE["sources"]}
    assert src["SRC-PAPER-CXL-PNM"]["title"] == (
        "Scalable Processing-Near-Memory for 1M-Token LLM Inference: "
        "CXL-Enabled KV-Cache Management Beyond GPU Limits"
    )


def test_mock_has_kivi_adoption_claim_for_dual_trl():
    """E의 TRL 이원화 테스트가 쓰는 KIVI 채택 근거 MKT-02 (#5). 저자 자체 공개라 vendor_claim."""
    claims = {c["id"]: c for c in MOCK_STATE["claims"]}
    mkt02 = claims["MKT-02"]
    assert (mkt02["tech"], mkt02["perspective"], mkt02["kind"], mkt02["status"]) == ("KIVI", "market", "vendor_claim", "ok")
    assert mkt02["counter_searched"] is True
