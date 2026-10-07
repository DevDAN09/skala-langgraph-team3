---
type: workflow
title: Evidence Audit, Fast-Fail, and Targeted Retry
description: The evidence-audit node validates claims with four deterministic fast-fail rules and an optional structured R5 factuality judge. It resolves each issue to an owning research agent, limits retries per agent, and sends unresolved terminal gaps to synthesis.
tags: [evidence, audit, retry, claims, orchestration]
verified:
  - by: openwiki/0.7.1
    at: 2026-10-07T01:43:12.707Z
sources:
  - id: openwiki-source-ca2828fdac20263921377590
    resource: repo://src/audit/auditor.py
  - id: openwiki-source-845b2a70e0198c23a42ca661
    resource: repo://src/audit/judge.py
  - id: openwiki-source-f5e2b8ff0c7138c8f5516e2f
    resource: repo://src/audit/rules.py
  - id: openwiki-source-d502c275990c6476221bf080
    resource: repo://src/config.py
  - id: openwiki-source-91eeb4c49f698320d444439b
    resource: repo://src/graph.py
  - id: openwiki-source-feb2ec95acc8a6bc97be21c0
    resource: repo://src/rag/agentic_rag.py
  - id: openwiki-source-119ab4e4190a7eb6651a1858
    resource: repo://src/research/market.py
  - id: openwiki-source-f9ce4f6142dac4b0fee881d2
    resource: repo://src/research/stakeholder.py
  - id: openwiki-source-4250e292dceed417d15194c5
    resource: repo://src/synthesis/evaluator.py
  - id: openwiki-source-5711f725c9f4b8e27680b277
    resource: repo://tests/test_audit.py
  - id: openwiki-source-9f96f06bbd9cdd32677cab48
    resource: repo://tests/test_graph.py
generated: { by: "openwiki/0.7.1", at: "2026-10-07T01:43:12.707Z" }
---

# Evidence Audit, Fast-Fail, and Targeted Retry

The evidence audit is the quality gate between parallel research and evaluation synthesis. It checks the shared `claims`, `evidence`, and `sources` state, records structured `audit.issues`, and either routes only the responsible research agent back to a focused retry or allows synthesis to proceed. The workflow deliberately separates **insufficient evidence** from **rejected factual inconsistency**: the former means the claim could not be adequately supported or classified, while the latter means the statement conflicts with the evidence snippet.

See [orchestration](../architecture/orchestration.md) for the wider graph and [state and evidence contract](../concepts/state-and-evidence-contract.md) for the state model. The research-side retry behavior is described alongside [web research](../integrations/web-research.md).

## Audit lifecycle

<!-- openwiki: mermaid parse failed and this diagram was converted to a text fence so it does not break rendering. Fix the diagram source and restore the mermaid fence. Parser error: Heuristic: a semicolon inside a label breaks rendering; rephrase the label. -->
```text
flowchart TD
    A["Research nodes update claims evidence and sources"] --> B["evidence_audit_node"]
    B --> C["R1-R4 static rules"]
    C --> D{"Static issue on claim?"}
    D -- "yes" --> E["Flag claim and skip R5 for it"]
    D -- "no" --> F["R5 structured LLM judge when API key is configured"]
    F --> G{"R5 factual inconsistency?"}
    G -- "yes" --> H["Add R5 re_extract issue"]
    G -- "no" --> I["Claim passes this audit pass"]
    E --> J["Increment target agent retry count once"]
    H --> J
    J --> K{"Target agent retry count below 2?"}
    K -- "yes" --> L["status = flagged; targeted retry"]
    K -- "no" --> M{"Issue rule is R5?"}
    M -- "yes" --> N["status = rejected"]
    M -- "no" --> O["status = insufficient"]
    L --> P["Research agent applies issue action to issue claim IDs"]
    P --> B
    N --> Q["Isolate terminal issue"]
    O --> Q
    I --> R{"No remaining issues?"}
    Q --> R
    R -- "yes" --> S["evaluation_synthesis"]
    R -- "no" --> L
```

*The flow shows the audit pass, per-agent retry limit, and the distinct terminal outcomes for evidence gaps and rejected factual claims.*

`evidence_audit_node` runs in two stages. It first calls `run_static_rules` for every non-terminal claim. Claims already marked `insufficient` or `rejected` are skipped, so a finalized gap is not repeatedly reported. Claims with an R1–R4 issue are excluded from R5 in the same pass: this is claim-level fast-fail, not a batch-wide abort. Only active claims that pass the static stage reach `run_llm_judge`.

The audit result contains the complete issue list for that pass and an updated `retry_count`. If several claims target the same agent in one pass, that agent's count increases only once. This makes the limit an **agent-level** limit rather than a claim-level multiplier. `RETRY_LIMIT` is 2.

## R1–R4 deterministic checks

Static validation is local and does not require an LLM:

| Rule | Condition | Issue action | Meaning of failure |
| --- | --- | --- | --- |
| R1 | A `kind="fact"` claim has no `evidence_ids` | `search_evidence` | There is no supporting evidence reference. |
| R2 | Every cited evidence/source tier is T4, including an unresolvable reference treated as T4 | `search_evidence` | The claim has only unverified support. |
| R3 | A market, stakeholder, or `MAT-A*` adoption claim has not run a counter-evidence search | `search_counter_evidence` | The required opposing search is missing. |
| R4 | A paper-side CXL-PNM simulation is labeled `fact`, or a market/stakeholder/MAT-A claim with a T2 source is labeled `fact` | `relabel` | The evidence kind does not reflect its provenance. |

Rules stop at the first applicable defect for each claim (`continue` after each issue), so a claim receives one static issue per pass. R2 builds its tier map from both `sources` and `evidence`: an evidence item can inherit the tier of its source. Missing tier resolution is conservatively treated as T4. R4 distinguishes the paper-side `CXL-PNM` simulation case from vendor-originated T2 figures; the expected correction is respectively a simulation-oriented label or `vendor_claim`, performed by the owning agent.

## R5 structured factuality judging

R5 is the second stage and checks substance rather than wording. `judge.py` creates a `ChatOpenAI` client with `JUDGE_LLM_MODEL` (`gpt-4o`) and calls `with_structured_output(JudgeDecision)`. The output has `is_grounded: bool` and a textual `reason`. The prompt permits paraphrases, synonyms, unit/format changes, and minor rounding, but rejects materially different or absent numbers, entities, or assertions and does not allow extrapolation beyond the snippet.

For each active claim, the judge uses the first `evidence_ids` entry and looks up its `Evidence.snippet`. Claims without a statement, evidence IDs, or a non-empty snippet are skipped. A false `is_grounded` result creates an R5 issue with action `re_extract`. If the API key is absent, judge initialization fails, or an invocation raises an exception, the judge falls back by logging/skipping rather than inventing an issue; the static gate still operates. The model and key are configured centrally in `src/config.py`.

R5 is intentionally different from R1–R4. R1–R4 identify missing, weak, incomplete, or misclassified support; R5 identifies a factual mismatch between an existing statement and the cited snippet. Once the retry limit is exhausted, static-rule failures become `insufficient`, whereas R5 failures become `rejected`.

## Target resolution and focused actions

`resolve_target_agent` uses Claim ID prefixes as the source of truth because `perspective="maturity"` is shared by research maturity (`MAT-R*`) and adoption maturity (`MAT-A*`):

- `DOM-*` and `MAT-R*` → `paper`
- `MKT-*` and `MAT-A*` → `market`
- `STK-*` → `stakeholder`

Unknown or ad-hoc IDs fall back to perspective (`domain` → paper, `stakeholder` → stakeholder, otherwise market). Every issue carries `claim_id`, `rule`, `target_agent`, and an action from the state contract.

The graph router derives the set of targets whose retry count is still below 2. It returns `market_research` in preference to `stakeholder_research` when both market and stakeholder issues exist, because market research feeds stakeholder query context; the stakeholder node then runs through its normal edge into the next audit. Paper can be returned alongside market, enabling a targeted parallel retry. When only paper needs retry, `route_after_paper` sends it directly to audit; on the initial fan-out it avoids opening a duplicate audit because the stakeholder edge owns the fan-in.

Research nodes consume only their own issues. Market and stakeholder nodes map issue IDs to their query plans and apply the requested action:

- `search_evidence`: rewrite support and counter queries, exclude previously used URLs, and collect another source;
- `search_counter_evidence`: rewrite only the opposing query and attach counter evidence;
- `re_extract`: summarize the existing snippet again with a strict grounding focus;
- `relabel`: repair the claim kind without unnecessary searching.

A retry patches only targeted claims and associated evidence/sources. This preserves unrelated claims and summary dictionaries through the state upsert reducers. Paper retries similarly restrict axes to issue Claim IDs; its grounded extraction requires verbatim contiguous paper passages and returns no fabricated quote when retrieval fails.

## Terminal isolation and synthesis

After each audit pass, the router checks the current issue targets against `retry_count`. If no issue remains, it routes to `evaluation_synthesis`. If issues remain but every target agent has reached 2, it also routes to synthesis rather than looping forever. The unresolved claims remain visible in `synthesis.evidence_gaps`: the evaluator collects claims with status `insufficient` or `rejected` and does not treat them as verified evidence for TRL calculation. Verified claims alone contribute to research/adoption TRL and confidence.

A retry may itself produce a terminal state: for example, a failed re-extraction can set a claim to `rejected`, while an unavailable or unsupported search can leave it `insufficient`. Terminal statuses are never re-audited by the static rules or judge. This preserves the difference between “we could not establish it” and “the cited text does not support what was asserted,” while still allowing the rest of the report pipeline to complete.

## Operational and testing notes

The audit is deterministic through R4 and optionally network/model-dependent through R5. An operator can diagnose a pass from `audit.issues`, `retry_count`, each issue's `target_agent` and `action`, and the claim status. The judge's graceful fallback means missing OpenAI configuration does not block the graph, but it also means factual R5 coverage is unavailable until the key and model service are configured.

Focused coverage lives in [tests/test_audit.py](../../tests/test_audit.py) and [tests/test_graph.py](../../tests/test_graph.py). The audit tests exercise all five rules, terminal-status skipping, ID-prefix routing (including `MAT-R*` versus `MAT-A*`), per-agent deduplication, status finalization, and judge structured output/fallback behavior. The graph tests cover initial fan-out/fan-in, market-to-stakeholder cascade, paper-only and parallel retries, audit-once behavior, and routing to synthesis after the retry limit. Together they protect the invariants that prevent infinite feedback loops, cross-agent claim mutation, and accidental conflation of insufficient evidence with factual rejection.
