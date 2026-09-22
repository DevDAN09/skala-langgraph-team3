"""tests/test_audit.py - Unit tests for Role D Fast-Fail Audit Module (R1~R5, auditor)"""
from unittest.mock import patch
from tests.mock_data import MOCK_STATE
from src.audit.rules import run_static_rules
from src.audit.judge import judge_claim_consistency
from src.audit.auditor import evidence_audit_node


def test_static_rule_r1_missing_evidence():
    claims = [
        {
            "id": "ERR-01",
            "perspective": "domain",
            "tech": "KIVI",
            "statement": "No evidence claim",
            "kind": "fact",
            "evidence_ids": [],
            "counter_evidence_ids": [],
            "counter_searched": False,
            "status": "ok",
        },
        {
            "id": "ERR-01-MKT",
            "perspective": "market",
            "tech": "KIVI",
            "statement": "No evidence market claim",
            "kind": "fact",
            "evidence_ids": [],
            "counter_evidence_ids": [],
            "counter_searched": False,
            "status": "ok",
        },
    ]
    issues = run_static_rules(claims, [])
    assert len(issues) == 2
    assert issues[0]["rule"] == "R1"
    assert issues[0]["target_agent"] == "paper"
    assert issues[0]["action"] == "search_evidence"
    assert issues[1]["rule"] == "R1"
    assert issues[1]["target_agent"] == "market"
    assert issues[1]["action"] == "search_evidence"


def test_static_rule_r2_solo_t4():
    sources = [
        {
            "source_id": "SRC-T4-01",
            "title": "Blog Post",
            "publisher": "Medium",
            "date": "2024",
            "url": "https://medium.com/post",
            "source_type": "web",
            "source_tier": "T4",
        }
    ]
    claims = [
        {
            "id": "ERR-T4-STK",
            "perspective": "stakeholder",
            "tech": "CXL-PNM",
            "statement": "Rumor on blog",
            "kind": "vendor_claim",
            "evidence_ids": ["SRC-T4-01"],
            "counter_evidence_ids": [],
            "counter_searched": True,
            "status": "ok",
        },
        {
            "id": "ERR-T4-MKT",
            "perspective": "market",
            "tech": "KIVI",
            "statement": "Rumor on reddit",
            "kind": "vendor_claim",
            "evidence_ids": ["SRC-T4-01"],
            "counter_evidence_ids": [],
            "counter_searched": True,
            "status": "ok",
        },
    ]
    issues = run_static_rules(claims, sources)
    assert len(issues) == 2
    assert issues[0]["rule"] == "R2"
    assert issues[0]["target_agent"] == "stakeholder"
    assert issues[0]["action"] == "search_evidence"
    assert issues[1]["rule"] == "R2"
    assert issues[1]["target_agent"] == "market"
    assert issues[1]["action"] == "search_evidence"


def test_static_rule_r3_missing_counter_search():
    claims = [
        {
            "id": "ERR-R3-MKT",
            "perspective": "market",
            "tech": "KIVI",
            "statement": "Market claim without counter search",
            "kind": "vendor_claim",
            "evidence_ids": ["EV-01"],
            "counter_evidence_ids": [],
            "counter_searched": False,
            "status": "ok",
        },
        {
            "id": "ERR-R3-STK",
            "perspective": "stakeholder",
            "tech": "CXL-PNM",
            "statement": "Stakeholder claim without counter search",
            "kind": "vendor_claim",
            "evidence_ids": ["EV-02"],
            "counter_evidence_ids": [],
            "counter_searched": False,
            "status": "ok",
        },
    ]
    issues = run_static_rules(claims, [])
    assert len(issues) == 2
    assert issues[0]["rule"] == "R3"
    assert issues[0]["target_agent"] == "market"
    assert issues[0]["action"] == "search_counter_evidence"
    assert issues[1]["rule"] == "R3"
    assert issues[1]["target_agent"] == "stakeholder"
    assert issues[1]["action"] == "search_counter_evidence"


def test_static_rule_r4_simulation_mislabeled():
    claims = [
        {
            "id": "ERR-02",
            "perspective": "domain",
            "tech": "CXL-PNM",
            "statement": "CXL-PNM achieves 3x speedup",
            "kind": "fact",
            "evidence_ids": ["EV-01"],
            "counter_evidence_ids": [],
            "counter_searched": False,
            "status": "ok",
        }
    ]
    issues = run_static_rules(claims, [])
    assert any(i["rule"] == "R4" and i["action"] == "relabel" for i in issues)
    assert issues[0]["target_agent"] == "paper"


def test_judge_claim_consistency_fallback():
    # When no API key or empty inputs, graceful degradation returns True
    assert judge_claim_consistency("", "some snippet") is True
    assert judge_claim_consistency("statement", "") is True


def test_evidence_audit_node_clean_state():
    result = evidence_audit_node(MOCK_STATE)
    assert "audit" in result
    assert "retry_count" in result
    assert result["audit"]["issues"] == []
    assert result["retry_count"] == {"paper": 0, "market": 0, "stakeholder": 0}


def test_evidence_audit_node_fast_fail_static():
    state = {
        **MOCK_STATE,
        "claims": [
            {
                "id": "DOM-ERR",
                "perspective": "domain",
                "tech": "KIVI",
                "statement": "No evidence claim",
                "kind": "fact",
                "evidence_ids": [],
                "counter_evidence_ids": [],
                "counter_searched": False,
                "status": "ok",
            }
        ],
        "retry_count": {"paper": 0, "market": 0, "stakeholder": 0},
    }
    with patch("src.audit.judge.judge_claim_consistency") as mock_judge:
        result = evidence_audit_node(state)
        # Fast-fail: static rules failed, so R5 judge must NOT be called
        mock_judge.assert_not_called()

    assert len(result["audit"]["issues"]) == 1
    issue = result["audit"]["issues"][0]
    assert issue["rule"] == "R1"
    assert issue["target_agent"] == "paper"
    assert result["retry_count"]["paper"] == 1
    assert "claims" in result
    assert result["claims"][0]["status"] == "flagged"


def test_evidence_audit_node_r5_failure():
    state = {
        **MOCK_STATE,
        "claims": [
            {
                "id": "DOM-R5-ERR",
                "perspective": "domain",
                "tech": "KIVI",
                "statement": "KIVI achieves 100x reduction",
                "kind": "fact",
                "evidence_ids": ["EV-DOM-01"],
                "counter_evidence_ids": [],
                "counter_searched": False,
                "status": "ok",
            }
        ],
        "retry_count": {"paper": 0, "market": 0, "stakeholder": 0},
    }
    with patch("src.audit.judge.judge_claim_consistency", return_value=False):
        result = evidence_audit_node(state)

    assert len(result["audit"]["issues"]) == 1
    issue = result["audit"]["issues"][0]
    assert issue["rule"] == "R5"
    assert issue["action"] == "re_extract"
    assert issue["target_agent"] == "paper"
    assert result["retry_count"]["paper"] == 1
    assert "claims" in result
    assert result["claims"][0]["status"] == "flagged"
