"""tests/test_audit.py - Unit tests for Role D Fast-Fail Audit Module (R1~R5, auditor)"""
from unittest.mock import patch, MagicMock
from tests.mock_data import MOCK_STATE
from src.state import upsert_claims
from src.audit import (
    run_static_rules,
    JudgeDecision,
    judge_claim_consistency,
    run_llm_judge,
    evidence_audit_node,
    judge_prompt,
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
    # T1-tier sources so these claims pass R2 and exercise R3 in isolation.
    sources = [
        {
            "source_id": "EV-01",
            "title": "Market Report",
            "publisher": "Analyst Firm",
            "date": "2024",
            "url": "https://analyst.example/report",
            "source_type": "web",
            "source_tier": "T1",
        },
        {
            "source_id": "EV-02",
            "title": "Stakeholder Report",
            "publisher": "Analyst Firm",
            "date": "2024",
            "url": "https://analyst.example/stakeholder",
            "source_type": "web",
            "source_tier": "T1",
        },
    ]
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
    issues = run_static_rules(claims, sources)
    assert len(issues) == 2
    assert issues[0]["rule"] == "R3"
    assert issues[0]["target_agent"] == "market"
    assert issues[0]["action"] == "search_counter_evidence"
    assert issues[1]["rule"] == "R3"
    assert issues[1]["target_agent"] == "stakeholder"
    assert issues[1]["action"] == "search_counter_evidence"


def test_static_rule_r4_simulation_mislabeled():
    # T1-tier source (paper) so this exercises the R4a simulation-mislabel path, not R2.
    sources = [
        {
            "source_id": "EV-01",
            "title": "CXL-PNM Paper",
            "publisher": "PACT",
            "date": "2024",
            "url": "https://doi.org/10.1109/PACT",
            "source_type": "paper",
            "source_tier": "T1",
        }
    ]
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
    issues = run_static_rules(claims, sources)
    assert any(i["rule"] == "R4" and i["action"] == "relabel" for i in issues)
    assert issues[0]["target_agent"] == "paper"


def test_static_rule_r4_vendor_figure_mislabeled():
    """R4b (issue #4 §4): a market/stakeholder claim citing a T2 (vendor-official)
    source but tagged kind='fact' must be flagged for relabel to 'vendor_claim'."""
    sources = [
        {
            "source_id": "SRC-VENDOR-01",
            "title": "Samsung Press Release",
            "publisher": "Samsung",
            "date": "2024",
            "url": "https://samsung.com/press",
            "source_type": "web",
            "source_tier": "T2",
        }
    ]
    claims = [
        {
            "id": "MKT-VEND-ERR",
            "perspective": "market",
            "tech": "CXL-PNM",
            "statement": "Samsung claims 3x throughput improvement",
            "kind": "fact",
            "evidence_ids": ["SRC-VENDOR-01"],
            "counter_evidence_ids": [],
            "counter_searched": True,
            "status": "ok",
        }
    ]
    issues = run_static_rules(claims, sources)
    assert len(issues) == 1
    assert issues[0]["rule"] == "R4"
    assert issues[0]["action"] == "relabel"
    assert issues[0]["target_agent"] == "market"


def test_static_rule_r1_skips_terminal_status_claims():
    """issue #4 §2: a blank/unconfirmed slot (or any claim already finalized to
    insufficient/rejected) must never be re-flagged as an R1 violation."""
    claims = [
        {
            "id": "DOM-BLANK",
            "perspective": "domain",
            "tech": "KIVI",
            "statement": "",
            "kind": "fact",
            "evidence_ids": [],
            "counter_evidence_ids": [],
            "counter_searched": False,
            "status": "insufficient",
        },
        {
            "id": "MKT-REJ",
            "perspective": "market",
            "tech": "KIVI",
            "statement": "Rejected claim",
            "kind": "fact",
            "evidence_ids": [],
            "counter_evidence_ids": [],
            "counter_searched": False,
            "status": "rejected",
        },
    ]
    issues = run_static_rules(claims, [])
    assert issues == []


def test_resolve_target_agent_id_prefix_routing():
    """issue #4 §3: target_agent must be resolved from the Claim ID prefix, since
    perspective='maturity' is shared by both B's MAT-R* and C's MAT-A* claims."""
    from src.audit.rules import resolve_target_agent

    assert resolve_target_agent("DOM-05", "domain") == "paper"
    assert resolve_target_agent("MAT-R01", "maturity") == "paper"
    assert resolve_target_agent("MAT-A01", "maturity") == "market"
    assert resolve_target_agent("MKT-03", "market") == "market"
    assert resolve_target_agent("STK-02", "stakeholder") == "stakeholder"


def test_static_rule_r3_covers_mat_adoption_claims():
    """issue #4 §4 R3: MAT-A* (C's maturity-adoption claims) must also require a
    counter-search, not just perspective in {market, stakeholder}."""
    claims = [
        {
            "id": "MAT-A01",
            "perspective": "maturity",
            "tech": "CXL-PNM",
            "statement": "CXL-PNM adoption is accelerating",
            "kind": "vendor_claim",
            "evidence_ids": [],
            "counter_evidence_ids": [],
            "counter_searched": False,
            "status": "ok",
        }
    ]
    issues = run_static_rules(claims, [])
    assert len(issues) == 1
    assert issues[0]["rule"] == "R3"
    assert issues[0]["target_agent"] == "market"


def test_static_rule_r4_covers_mat_research_simulation_claims():
    """issue #4 §4 R4: MAT-R* (B's maturity-research claims) must also be checked for
    CXL-PNM simulation numbers mislabeled as fact, not just perspective='domain'."""
    sources = [
        {
            "source_id": "EV-MAT-R-01",
            "title": "CXL-PNM Maturity Study",
            "publisher": "PACT",
            "date": "2024",
            "url": "https://doi.org/10.1109/PACT-mat",
            "source_type": "paper",
            "source_tier": "T1",
        }
    ]
    claims = [
        {
            "id": "MAT-R01",
            "perspective": "maturity",
            "tech": "CXL-PNM",
            "statement": "CXL-PNM TRL is 6",
            "kind": "fact",
            "evidence_ids": ["EV-MAT-R-01"],
            "counter_evidence_ids": [],
            "counter_searched": False,
            "status": "ok",
        }
    ]
    issues = run_static_rules(claims, sources)
    assert len(issues) == 1
    assert issues[0]["rule"] == "R4"
    assert issues[0]["target_agent"] == "paper"


def test_static_rule_r2_treats_dangling_source_reference_as_untrusted():
    """issue #4 §4 R2: if an evidence's source_id can't be resolved in `sources`
    (e.g. dropped by union_sources URL dedup, see issue #3), it must be treated as
    unverified (T4-equivalent) rather than silently passing R2."""
    claims = [
        {
            "id": "STK-DANGLING",
            "perspective": "stakeholder",
            "tech": "KIVI",
            "statement": "Claim citing a dropped source",
            "kind": "vendor_claim",
            "evidence_ids": ["EV-DANGLING"],
            "counter_evidence_ids": [],
            "counter_searched": True,
            "status": "ok",
        }
    ]
    # `sources` intentionally does not contain the source EV-DANGLING points to.
    issues = run_static_rules(claims, [])
    assert len(issues) == 1
    assert issues[0]["rule"] == "R2"
    assert issues[0]["target_agent"] == "stakeholder"


def test_judge_decision_schema():
    decision = JudgeDecision(is_grounded=True, reason="Directly supported by snippet.")
    assert decision.is_grounded is True
    assert "supported" in decision.reason


def test_judge_prompt_tolerates_lexical_variation_but_rejects_factual_mismatch():
    """R5 threshold tuning: the Judge prompt must explicitly instruct the LLM not to
    reject a Claim for mere wording/paraphrase differences, while still requiring a
    reject on genuine factual mismatches (different numbers/entities/unsupported
    claims). Guards against re-tightening the prompt back to word-for-word matching.
    """
    system_message = judge_prompt.messages[0].prompt.template

    # Must explicitly tolerate surface-level (non-factual) differences
    for leniency_cue in ("paraphrasing", "synonyms", "word order"):
        assert leniency_cue in system_message

    # Must still require a reject for substantive factual mismatches
    for strictness_cue in ("materially different", "contradicted"):
        assert strictness_cue in system_message

    # No comparative/winner language leaked into the Judge prompt (checklist item)
    for banned in ("better", "winner", "recommend"):
        assert banned not in system_message.lower()


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
        # SRC-01 must be a resolvable, non-T4 source so this claim passes R1~R4 and
        # actually reaches R5 (an unresolvable source_id would now be treated as
        # T4-equivalent by R2's dangling-reference defense, see issue #4 §4 R2).
        "sources": [
            {
                "source_id": "SRC-01",
                "title": "Stakeholder Analyst Report",
                "publisher": "Analyst Firm",
                "date": "2024",
                "url": "https://analyst.example/stakeholder-report",
                "source_type": "web",
                "source_tier": "T1",
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


def test_evidence_audit_node_no_new_claim_id_created():
    """Audit must never mint a new Claim ID — only patch `status` on existing claims.

    Guards design_checklist.md 충돌 방지 rule: 'D는 신규 ID 없음. 기존 Claim `status`만'.
    A regression here means upsert_claims() would silently inject a phantom claim into
    OverallState and corrupt B/C's data.
    """
    state = {
        **MOCK_STATE,
        "claims": [
            {
                "id": "DOM-ERR-NEW",
                "perspective": "domain",
                "tech": "KIVI",
                "statement": "No evidence claim",
                "kind": "fact",
                "evidence_ids": [],
                "counter_evidence_ids": [],
                "counter_searched": False,
                "status": "ok",
            },
        ],
        "retry_count": {"paper": 0, "market": 0, "stakeholder": 0},
    }
    original_ids = {c["id"] for c in state["claims"]}
    original_by_id = {c["id"]: c for c in state["claims"]}

    result = evidence_audit_node(state)
    patched_claims = result.get("claims", [])
    assert patched_claims, "expected the R1 violation to produce a status patch"

    # No id outside the original claim set may appear in the returned patch
    returned_ids = {c["id"] for c in patched_claims}
    assert returned_ids.issubset(original_ids)

    # Every field except `status` must be preserved unchanged (no re-derived content)
    for patched in patched_claims:
        original = original_by_id[patched["id"]]
        for key in original:
            if key == "status":
                continue
            assert patched[key] == original[key]

    # Merging through the real reducer must not grow the claim count in OverallState
    merged = upsert_claims(state["claims"], patched_claims)
    assert len(merged) == len(state["claims"])
    assert {c["id"] for c in merged} == original_ids


def test_evidence_audit_node_retry_count_accumulates_across_retry_loop():
    """retry_count must accumulate across sequential audit passes (Cascade retry loop),
    not reset each call, and must never mutate the caller's retry_count dict in place.

    Guards common.md §7①.4: '에이전트당 재시도 2회. retry_count 증가는 auditor만 수행합니다.'
    """
    state_round1 = {
        **MOCK_STATE,
        "claims": [
            {
                "id": "MKT-ERR",
                "perspective": "market",
                "tech": "KIVI",
                "statement": "Unsupported market claim",
                "kind": "fact",
                "evidence_ids": [],
                "counter_evidence_ids": [],
                "counter_searched": False,
                "status": "ok",
            },
        ],
        "retry_count": {"paper": 0, "market": 0, "stakeholder": 0},
    }
    original_retry_count = dict(state_round1["retry_count"])

    result1 = evidence_audit_node(state_round1)
    assert result1["retry_count"]["market"] == 1
    # The input dict must not have been mutated in place
    assert state_round1["retry_count"] == original_retry_count

    # Router re-enters evidence_audit after market's retry attempt, carrying the
    # updated retry_count forward; the claim is still unresolved (still no evidence).
    state_round2 = {
        **state_round1,
        "retry_count": result1["retry_count"],
        "claims": [{**state_round1["claims"][0], "evidence_ids": []}],
    }
    result2 = evidence_audit_node(state_round2)
    assert result2["retry_count"]["market"] == 2
    # Untouched agents must stay untouched
    assert result2["retry_count"]["paper"] == 0
    assert result2["retry_count"]["stakeholder"] == 0


def test_evidence_audit_node_claim_level_fast_fail():
    """Claim-level Fast-Fail: when an R1~R4 static defect exists on one claim,
    that defective claim skips R5 LLM review, but other clean claims in the same batch
    proceed to R5 LLM review without being blocked.
    """
    state = {
        **MOCK_STATE,
        "claims": [
            # Clean claim that proceeds to R5 LLM review
            {
                "id": "DOM-OK",
                "perspective": "domain",
                "tech": "KIVI",
                "statement": "KIVI reduces KV cache memory footprint by up to 2.6x.",
                "kind": "fact",
                "evidence_ids": ["EV-DOM-01"],
                "counter_evidence_ids": [],
                "counter_searched": False,
                "status": "ok",
            },
            # R4 violation on another claim in the same batch
            {
                "id": "DOM-R4-ERR",
                "perspective": "domain",
                "tech": "CXL-PNM",
                "statement": "CXL-PNM achieves 3.1x energy efficiency.",
                "kind": "fact",
                "evidence_ids": ["EV-DOM-02"],
                "counter_evidence_ids": [],
                "counter_searched": False,
                "status": "ok",
            },
        ],
        "retry_count": {"paper": 0, "market": 0, "stakeholder": 0},
    }
    with patch(
        "src.audit.judge.run_llm_judge", return_value=[]
    ) as mock_run_llm_judge:
        result = evidence_audit_node(state)
        # R5 LLM judge is called ONLY for the clean claim (DOM-OK), NOT for DOM-R4-ERR
        mock_run_llm_judge.assert_called_once()
        reviewed_claims = mock_run_llm_judge.call_args[0][0]
        assert [c["id"] for c in reviewed_claims] == ["DOM-OK"]

    # Only DOM-R4-ERR is flagged with R4; DOM-OK passed both R1~R4 and R5
    assert len(result["audit"]["issues"]) == 1
    assert result["audit"]["issues"][0]["rule"] == "R4"
    assert result["audit"]["issues"][0]["claim_id"] == "DOM-R4-ERR"


def test_evidence_audit_node_finalizes_status_when_retry_limit_reached():
    """issue #4 §1: once the target agent's retry_count reaches the limit (2) in this
    pass, the violated claim must be finalized (R1 -> insufficient) instead of staying
    `flagged` forever — a `flagged` claim never surfaces in evaluator.py's Evidence Gap
    section (design 5.2), so it would silently vanish from the report.
    """
    state = {
        **MOCK_STATE,
        "claims": [
            {
                "id": "MKT-LIMIT",
                "perspective": "market",
                "tech": "KIVI",
                "statement": "Still unsupported after one retry",
                "kind": "fact",
                "evidence_ids": [],
                "counter_evidence_ids": [],
                "counter_searched": False,
                "status": "flagged",
            }
        ],
        # market already retried once (count=1); this pass pushes it to 2 -> limit
        "retry_count": {"paper": 0, "market": 1, "stakeholder": 0},
    }
    result = evidence_audit_node(state)
    assert result["retry_count"]["market"] == 2
    assert result["audit"]["issues"][0]["rule"] == "R1"
    assert result["claims"][0]["status"] == "insufficient"


def test_evidence_audit_node_finalizes_r5_as_rejected_at_retry_limit():
    """issue #4 §1: R5 violations finalize to `rejected` (사실 불일치), not
    `insufficient`, once the limit is reached."""
    state = {
        **MOCK_STATE,
        "claims": [
            {
                "id": "DOM-R5-LIMIT",
                "perspective": "domain",
                "tech": "KIVI",
                "statement": "KIVI achieves 100x reduction",
                "kind": "fact",
                "evidence_ids": ["EV-DOM-01"],
                "counter_evidence_ids": [],
                "counter_searched": False,
                "status": "flagged",
            }
        ],
        "retry_count": {"paper": 1, "market": 0, "stakeholder": 0},
    }
    with patch("src.audit.judge.run_llm_judge", return_value=[{
        "claim_id": "DOM-R5-LIMIT",
        "rule": "R5",
        "issue": "스니펫과 사실 불일치: unsupported",
        "target_agent": "paper",
        "action": "re_extract",
    }]):
        result = evidence_audit_node(state)

    assert result["retry_count"]["paper"] == 2
    assert result["claims"][0]["status"] == "rejected"


def test_evidence_audit_node_does_not_reflag_finalized_claims():
    """issue #4 §2 end-to-end: once a claim is finalized (insufficient/rejected), it
    must stay out of every future audit pass through the full node, not just
    run_static_rules in isolation."""
    state = {
        **MOCK_STATE,
        "claims": [
            {
                "id": "DOM-BLANK",
                "perspective": "domain",
                "tech": "KIVI",
                "statement": "",
                "kind": "fact",
                "evidence_ids": [],
                "counter_evidence_ids": [],
                "counter_searched": False,
                "status": "insufficient",
            }
        ],
        "retry_count": {"paper": 2, "market": 0, "stakeholder": 0},
    }
    with patch("src.audit.judge.run_llm_judge", return_value=[]):
        result = evidence_audit_node(state)

    assert result["audit"]["issues"] == []
    assert result["retry_count"] == {"paper": 2, "market": 0, "stakeholder": 0}
    assert "claims" not in result


def test_evidence_audit_node_target_agent_mapping_bug_repro():
    """Reproduces issue #4 §3 exactly: an R1 violation on a stakeholder claim (STK-*)
    and on a B-owned maturity-research claim (MAT-R*) must route to `stakeholder` and
    `paper` respectively — previously both were misrouted to `market`."""
    state = {
        **MOCK_STATE,
        "claims": [
            {
                "id": "STK-01",
                "perspective": "stakeholder",
                "tech": "KIVI",
                "statement": "Stakeholder claim missing evidence",
                "kind": "fact",
                "evidence_ids": [],
                "counter_evidence_ids": [],
                "counter_searched": True,
                "status": "ok",
            },
            {
                "id": "MAT-R01",
                "perspective": "maturity",
                "tech": "KIVI",
                "statement": "Maturity research claim missing evidence",
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
    by_claim = {i["claim_id"]: i for i in result["audit"]["issues"]}
    assert by_claim["STK-01"]["target_agent"] == "stakeholder"
    assert by_claim["MAT-R01"]["target_agent"] == "paper"
    assert result["retry_count"] == {"paper": 1, "market": 0, "stakeholder": 1}

