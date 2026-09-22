"""tests/test_audit.py - Unit tests for Role D Fast-Fail Audit Module (R1~R5, auditor)"""
from unittest.mock import patch, MagicMock
from tests.mock_data import MOCK_STATE
from src.audit import (
    run_static_rules,
    JudgeDecision,
    judge_claim_consistency,
    run_llm_judge,
    evidence_audit_node,
)


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


def test_judge_decision_schema():
    decision = JudgeDecision(is_grounded=True, reason="Directly supported by snippet.")
    assert decision.is_grounded is True
    assert "supported" in decision.reason


def test_judge_claim_consistency_fallback():
    # When no API key or empty inputs, graceful degradation returns True
    assert judge_claim_consistency("", "some snippet") is True
    assert judge_claim_consistency("statement", "") is True


def test_run_llm_judge_fallback_no_api_key():
    claims = [{"id": "C1", "statement": "test", "evidence_ids": ["E1"], "perspective": "domain"}]
    evidence = [{"evidence_id": "E1", "snippet": "test snippet"}]
    with patch("src.audit.judge.OPENAI_API_KEY", ""):
        issues = run_llm_judge(claims, evidence)
        assert issues == []


def test_run_llm_judge_with_mocked_llm():
    claims = [
        {
            "id": "DOM-01",
            "perspective": "domain",
            "tech": "KIVI",
            "statement": "KIVI achieves 10x reduction",
            "kind": "fact",
            "evidence_ids": ["EV-01"],
            "counter_evidence_ids": [],
            "counter_searched": False,
            "status": "ok",
        },
        {
            "id": "MKT-01",
            "perspective": "market",
            "tech": "CXL-PNM",
            "statement": "Samsung released CXL 2.0",
            "kind": "fact",
            "evidence_ids": ["EV-02"],
            "counter_evidence_ids": [],
            "counter_searched": True,
            "status": "ok",
        },
    ]
    evidence = [
        {"evidence_id": "EV-01", "snippet": "KIVI achieves 2.6x reduction"},
        {"evidence_id": "EV-02", "snippet": "Samsung released CXL 2.0 in 2024"},
    ]
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [
        JudgeDecision(is_grounded=False, reason="Snippet says 2.6x, not 10x"),
        JudgeDecision(is_grounded=True, reason="Direct match"),
    ]
    with patch("src.audit.judge.OPENAI_API_KEY", "mock-key"), patch(
        "src.audit.judge.ChatOpenAI"
    ) as mock_chat:
        mock_chat.return_value.with_structured_output.return_value = mock_llm
        issues = run_llm_judge(claims, evidence)

    assert len(issues) == 1
    assert issues[0]["claim_id"] == "DOM-01"
    assert issues[0]["rule"] == "R5"
    assert "Snippet says 2.6x, not 10x" in issues[0]["issue"]
    assert issues[0]["target_agent"] == "paper"
    assert issues[0]["action"] == "re_extract"


def test_evidence_audit_node_clean_state():
    with patch("src.audit.judge.run_llm_judge", return_value=[]):
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
    with patch("src.audit.judge.run_llm_judge") as mock_judge:
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
    with patch("src.audit.judge.run_llm_judge", return_value=[{
        "claim_id": "DOM-R5-ERR",
        "rule": "R5",
        "issue": "스니펫과 사실 불일치: 100x reduction is unsupported",
        "target_agent": "paper",
        "action": "re_extract",
    }]):
        result = evidence_audit_node(state)

    assert len(result["audit"]["issues"]) == 1
    issue = result["audit"]["issues"][0]
    assert issue["rule"] == "R5"
    assert issue["action"] == "re_extract"
    assert issue["target_agent"] == "paper"
    assert result["retry_count"]["paper"] == 1
    assert "claims" in result
    assert result["claims"][0]["status"] == "flagged"


def test_evidence_audit_node_r5_stakeholder_routing():
    state = {
        **MOCK_STATE,
        "claims": [
            {
                "id": "STK-R5-ERR",
                "perspective": "stakeholder",
                "tech": "KIVI",
                "statement": "Stakeholder unsupported claim",
                "kind": "fact",
                "evidence_ids": ["EV-STK-01"],
                "counter_evidence_ids": [],
                "counter_searched": True,
                "status": "ok",
            }
        ],
        "evidence": [
            {"evidence_id": "EV-STK-01", "source_id": "SRC-01", "snippet": "Unrelated snippet text."}
        ],
        "retry_count": {"paper": 0, "market": 0, "stakeholder": 0},
    }
    with patch("src.audit.judge.run_llm_judge", return_value=[{
        "claim_id": "STK-R5-ERR",
        "rule": "R5",
        "issue": "스니펫과 사실 불일치: Unrelated snippet",
        "target_agent": "stakeholder",
        "action": "re_extract",
    }]):
        result = evidence_audit_node(state)

    assert len(result["audit"]["issues"]) == 1
    issue = result["audit"]["issues"][0]
    assert issue["rule"] == "R5"
    assert issue["target_agent"] == "stakeholder"
    assert result["retry_count"]["stakeholder"] == 1


def test_evidence_audit_node_unique_retry_count_increment():
    # Multiple issues targeting the same agent should only increment retry_count once
    state = {
        **MOCK_STATE,
        "claims": [
            {
                "id": "DOM-ERR-1",
                "perspective": "domain",
                "tech": "KIVI",
                "statement": "No evidence 1",
                "kind": "fact",
                "evidence_ids": [],
                "counter_evidence_ids": [],
                "counter_searched": False,
                "status": "ok",
            },
            {
                "id": "DOM-ERR-2",
                "perspective": "domain",
                "tech": "KIVI",
                "statement": "No evidence 2",
                "kind": "fact",
                "evidence_ids": [],
                "counter_evidence_ids": [],
                "counter_searched": False,
                "status": "ok",
            },
        ],
        "retry_count": {"paper": 0, "market": 0, "stakeholder": 0},
    }
    result = evidence_audit_node(state)
    assert len(result["audit"]["issues"]) == 2
    assert all(i["target_agent"] == "paper" for i in result["audit"]["issues"])
    # Crucial: paper retry count incremented by 1, NOT 2
    assert result["retry_count"]["paper"] == 1

