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
