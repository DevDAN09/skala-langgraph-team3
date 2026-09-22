"""src/research/stakeholder.py - Stakeholder research node, chained from market context."""
from src.state import OverallState, Claim, Evidence, Source
from src.research.client import (
    search_pair,
    classify_tier,
    infer_kind,
    rank_results,
    resolve_source_id,
    rewrite_query,
    summarize_snippet,
    vendor_label,
)

# 4대 Actor(서빙 운영자 / 프레임워크 개발자 / End User / 공급자) × 기술 계열 2개 (설계 3.2·3.5, #8).
# STK-01~04는 기존 의미를 유지하고, 05~08이 각 Actor의 반대 계열을 채운다. slot은 stakeholder 요약 dict 키.
# {vendor}는 state["market"]["key_vendors"] (market_research가 남긴 컨텍스트)로 채워 쿼리를 구체화한다.
STAKEHOLDER_QUERY_PLAN = [
    {
        "claim_id": "STK-01", "actor": "Cloud Serving Operator", "slot": "cloud_serving_operator", "tech": "KIVI",
        "support": "cloud LLM serving operator cost savings KV cache quantization deployment {vendor}",
        "counter": "KV cache quantization production serving operational risk concern",
    },
    {
        "claim_id": "STK-02", "actor": "Framework Developer", "slot": "framework_developer", "tech": "KIVI",
        "support": "vLLM TensorRT-LLM LLM serving developer KV cache quantization kernel integration effort",
        "counter": "LLM serving KV cache quantization kernel developer integration difficulty complaint",
    },
    {
        "claim_id": "STK-03", "actor": "End User", "slot": "end_user", "tech": "CXL-PNM",
        "support": "CXL memory expansion LLM serving inference latency long context end user experience",
        "counter": "CXL memory expansion LLM serving inference latency degradation user complaint",
    },
    {
        "claim_id": "STK-04", "actor": "HW/Memory Supplier", "slot": "memory_vendor", "tech": "CXL-PNM",
        "support": "{vendor} CXL memory module enterprise AI server roadmap strategy",
        "counter": "CXL memory vendor data center adoption challenge cost competitiveness",
    },
    {
        "claim_id": "STK-05", "actor": "Cloud Serving Operator", "slot": "cloud_serving_operator", "tech": "CXL-PNM",
        "support": "cloud data center CXL memory expansion LLM inference server deployment {vendor}",
        "counter": "CXL memory expansion data center deployment cost operational concern",
    },
    {
        "claim_id": "STK-06", "actor": "Framework Developer", "slot": "framework_developer", "tech": "CXL-PNM",
        "support": "LLM serving framework CXL memory tiering KV cache offload support",
        "counter": "CXL memory tiering LLM serving software support complexity developer challenge",
    },
    {
        "claim_id": "STK-07", "actor": "End User", "slot": "end_user", "tech": "KIVI",
        "support": "cloud LLM serving KV cache quantization response quality latency long context user impact",
        "counter": "LLM serving KV cache 2-bit quantization accuracy degradation long context output quality",
    },
    {
        "claim_id": "STK-08", "actor": "HW/Memory Supplier", "slot": "memory_vendor", "tech": "KIVI",
        "support": "{vendor} data center GPU inference SDK KV cache quantization support",
        "counter": "KV cache quantization hardware support limitation data center GPU serving",
    },
]
TECH_ORDER = ("KIVI", "CXL-PNM")
END_USER_GAP = "인용 가능한 지연/품질 간접 근거 미확인"
COUNTER_NOT_FOUND = "counter-evidence not found"
# market.key_vendors는 알파벳순이라 첫 항목이 기술과 무관할 수 있다. 계열별로 쿼리에 넣을 벤더 후보를 정한다.
VENDOR_PREFERENCE = {"CXL-PNM": ("Samsung", "SK Hynix", "Intel", "CXL Consortium"), "KIVI": ("NVIDIA",)}
STAKEHOLDER_PLAN_BY_ID = {q["claim_id"]: q for q in STAKEHOLDER_QUERY_PLAN}
SNIPPET_LIMIT = 500


def _select_evidence(results: list[dict], focus: str, exclude_urls: set[str] = frozenset()):
    """T1~T3 결과를 먼저 고르고(R2: T4 단독 근거 금지), 쓸 만한 statement가 나오는 첫 후보를 쓴다.

    summarize_snippet이 빈 문자열을 주면 다음 후보로 넘어간다. 전부 실패하면 Tier가 가장 높은
    후보를 근거로만 남기고 statement는 비운다. 재검색 때는 직전 근거 URL을 뺀다.
    (요약이 "관련 내용 없음"을 빈 문자열로 알리는 부분은 이슈 #18 담당이다.)
    """
    ranked = rank_results(results, exclude_urls)
    if not ranked:
        return None, "", ""
    for candidate in ranked:
        snippet_text = (candidate.get("content") or "")[:SNIPPET_LIMIT]
        statement = summarize_snippet(snippet_text, focus) if snippet_text else ""
        if statement:
            return candidate, snippet_text, statement
    return ranked[0], (ranked[0].get("content") or "")[:SNIPPET_LIMIT], ""


def _family_ref(tech: str, labels: dict[str, str]) -> str:
    """웹 근거는 계열 단위라서 LLM 초점을 개별 기술이 아니라 계열로 준다 (설계 3.2)."""
    return f"the {labels[tech]} technology family (e.g., {tech})"


def _benefit_focus(item: dict, labels: dict[str, str]) -> str:
    return f"benefits or adoption status for the {item['actor']} regarding {_family_ref(item['tech'], labels)}"


def _counter_focus(what: str, item: dict, labels: dict[str, str]) -> str:
    # 반대 근거가 그 Actor의 발언이라는 보장이 없다. 주어를 지어내지 않게 한다 (설계 4.5 페르소나 금지).
    actor = item["actor"]
    return (f"{what} {_family_ref(item['tech'], labels)} that are relevant to the {actor}. "
            f"Do not attribute statements to the {actor} unless the text itself does")


def _fill_vendor(template: str, key_vendors: list[str], tech: str) -> str:
    """market이 찾은 벤더 중 이 기술 계열에 맞는 벤더로 쿼리를 구체화한다. 없으면 벤더 없이 검색한다."""
    vendor = next((v for v in VENDOR_PREFERENCE[tech] if v in key_vendors), "")
    return " ".join(template.format(vendor=vendor).split())


def _build_source(url: str, title: str, date: str, tier: str, proposed_id: str, sources_pool: list[Source]):
    """URL 중복이면 기존 source_id를 재사용(신규 Source 미생성), 아니면 새 Source를 만든다."""
    resolved_id = resolve_source_id(url, sources_pool, proposed_id)
    if resolved_id != proposed_id:
        return resolved_id, None
    new_source: Source = {
        "source_id": proposed_id,
        "title": title or "Untitled",
        "publisher": vendor_label(url) or "Web",
        "date": date or "n.d.",
        "url": url,
        "source_type": "web",
        "source_tier": tier,
    }
    return proposed_id, new_source


def _run_stakeholder_query(
    item: dict, key_vendors: list[str], sources_pool: list[Source], labels: dict[str, str],
    exclude_urls: set[str] = frozenset(), queries: tuple[str, str] | None = None,
) -> tuple[Claim, list[Evidence], list[Source]]:
    """Actor별 지지/반대 쿼리를 1회 병행 실행해 Claim + Evidence(+반대 근거) + Source를 만든다.

    queries를 주면 plan의 기본 질의 대신 그것을 쓴다 (재검색용 재작성 질의).
    """
    claim_id, tech = item["claim_id"], item["tech"]
    ev_id, src_id = f"EV-{claim_id}", f"SRC-{claim_id}"

    support_query, counter_query = queries or (
        _fill_vendor(item["support"], key_vendors, tech),
        _fill_vendor(item["counter"], key_vendors, tech),
    )
    support, counter = search_pair(support_query, counter_query)
    support_results = (support or {}).get("results") or []

    if not support_results:
        claim: Claim = {
            "id": claim_id, "perspective": "stakeholder", "tech": tech,
            "statement": "", "kind": "fact", "evidence_ids": [], "counter_evidence_ids": [],
            "counter_searched": True, "status": "insufficient",
        }
        return claim, [], []

    new_sources: list[Source] = []
    # R5(LLM Judge)는 Evidence.snippet만 보고 statement 정합성을 판정하므로,
    # statement 생성 입력과 저장되는 snippet을 동일한 텍스트로 맞춘다.
    top, snippet_text, statement = _select_evidence(support_results, _benefit_focus(item, labels), exclude_urls)
    url = top.get("url", "")
    tier = classify_tier(url)
    resolved_src_id, new_src = _build_source(url, top.get("title", ""), top.get("published_date", ""), tier, src_id, sources_pool)
    if new_src:
        new_sources.append(new_src)

    new_evidence: list[Evidence] = [{
        "evidence_id": ev_id, "source_id": resolved_src_id, "snippet": snippet_text,
    }]

    counter_evidence_ids: list[str] = []
    counter_results = (counter or {}).get("results") or [] if counter else []
    if counter_results:
        c_top = counter_results[0]
        c_url = c_top.get("url", "")
        c_ev_id, c_src_id = f"{ev_id}-C", f"{src_id}-C"
        resolved_c_src_id, new_c_src = _build_source(
            c_url, c_top.get("title", ""), c_top.get("published_date", ""), classify_tier(c_url), c_src_id, sources_pool + new_sources
        )
        if new_c_src:
            new_sources.append(new_c_src)
        new_evidence.append({"evidence_id": c_ev_id, "source_id": resolved_c_src_id, "snippet": (c_top.get("content") or "")[:500]})
        counter_evidence_ids = [c_ev_id]
    else:
        print(f"⚠️ [경고/Fallback] {claim_id}: counter-evidence not found")

    claim: Claim = {
        "id": claim_id, "perspective": "stakeholder", "tech": tech,
        "statement": statement, "kind": infer_kind(url),
        "evidence_ids": [ev_id], "counter_evidence_ids": counter_evidence_ids,
        "counter_searched": True, "status": "ok" if statement else "insufficient",
    }
    return claim, new_evidence, new_sources


def _handle_retry(claim_id: str, action: str | None, state: OverallState, key_vendors: list[str],
                  sources_pool: list[Source], labels: dict[str, str]):
    """재실행: 자기 target_agent(stakeholder) 이슈의 claim_id만, action이 지시한 만큼만 고친다."""
    existing_claim = next((c for c in state.get("claims", []) if c.get("id") == claim_id), None)
    evidence_by_id = {e["evidence_id"]: e for e in state.get("evidence", [])}
    sources_by_id = {s["source_id"]: s for s in state.get("sources", [])}
    plan_item = STAKEHOLDER_PLAN_BY_ID.get(claim_id)

    if action == "search_counter_evidence" and existing_claim and plan_item:
        tech = plan_item["tech"]
        counter_query = rewrite_query(
            _fill_vendor(plan_item["counter"], key_vendors, tech),
            "the previous counter-evidence search returned nothing usable",
        )
        _, counter = search_pair(_fill_vendor(plan_item["support"], key_vendors, tech), counter_query)
        counter_results = (counter or {}).get("results") or [] if counter else []
        if not counter_results:
            # 반대 쿼리를 실행했으면 결과가 없어도 R3 충족. counter-evidence not found는 상태에 영향 없음 (설계 표 11)
            print(f"⚠️ [경고/Fallback] {claim_id}: 재실행에도 counter-evidence not found")
            return {**existing_claim, "counter_searched": True, "status": "ok"}, [], []
        c_top = counter_results[0]
        c_url = c_top.get("url", "")
        c_ev_id, c_src_id = f"EV-{claim_id}-C", f"SRC-{claim_id}-C"
        resolved_c_src_id, new_c_src = _build_source(
            c_url, c_top.get("title", ""), c_top.get("published_date", ""), classify_tier(c_url), c_src_id, sources_pool
        )
        new_sources = [new_c_src] if new_c_src else []
        new_evidence = [{"evidence_id": c_ev_id, "source_id": resolved_c_src_id, "snippet": (c_top.get("content") or "")[:500]}]
        updated = {**existing_claim, "counter_evidence_ids": [c_ev_id], "counter_searched": True, "status": "ok"}
        return updated, new_evidence, new_sources

    if action == "relabel" and existing_claim:
        # R4는 벤더 수치를 fact로 둔 경우다. 도메인으로 다시 추론하면 제3자 매체 인용은 또 fact가 되어 재위반한다.
        kind = existing_claim.get("kind")
        return {**existing_claim, "kind": "vendor_claim" if kind == "fact" else kind, "status": "ok"}, [], []

    if action == "re_extract" and existing_claim:
        ev = evidence_by_id.get((existing_claim.get("evidence_ids") or [None])[0])
        if ev and ev.get("snippet") and plan_item:
            # R5 불일치 재추출: 처음과 같은 초점으로, snippet에 있는 내용만 다시 서술한다.
            statement = summarize_snippet(ev["snippet"], f"{_benefit_focus(plan_item, labels)}. Restate only what the text says")
            status = "ok" if statement else "rejected"
        else:
            statement, status = "", "insufficient"
        return {**existing_claim, "statement": statement, "status": status}, [], []

    # search_evidence (기본) 또는 알 수 없는 action: 지지+반대 쿼리를 전부 다시 실행.
    # 같은 쿼리는 같은 결과를 돌려주므로 직전 근거 URL은 제외하고, 질의 자체도 다시 써서
    # 다른 출처에 닿게 한다 (URL만 빼면 같은 결과 목록 안에서만 맴돈다).
    if plan_item:
        prev_ev = evidence_by_id.get(((existing_claim or {}).get("evidence_ids") or [None])[0])
        prev_src = sources_by_id.get(prev_ev["source_id"]) if prev_ev else None
        exclude = {prev_src["url"]} if prev_src and prev_src.get("url") else set()
        tech = plan_item["tech"]
        reason = "the previous search returned a page with no usable evidence for this claim"
        queries = (
            rewrite_query(_fill_vendor(plan_item["support"], key_vendors, tech), reason),
            rewrite_query(_fill_vendor(plan_item["counter"], key_vendors, tech), reason),
        )
        return _run_stakeholder_query(plan_item, key_vendors, sources_pool, labels, exclude, queries)
    if existing_claim:
        return {**existing_claim, "status": "insufficient"}, [], []
    return None, [], []


def _family_labels(state: OverallState) -> dict[str, str]:
    families = (state.get("selected") or {}).get("families") or {}
    return {"KIVI": families.get("sw", "KV Quantization"), "CXL-PNM": families.get("hw", "CXL Memory Expansion")}


def _detail(item: dict, claim: Claim, snippets: dict[str, str], labels: dict[str, str]) -> dict | None:
    """Actor 한 칸의 Benefit / Concern / Adoption Barrier / Evidence (설계 3.5).
    Benefit은 지지 근거 Claim statement, Concern·Barrier는 반대 근거 snippet에서만 뽑는다. 근거 없는 Claim은 None."""
    if not claim or claim.get("status") != "ok":
        return None
    counter = next((snippets[e] for e in claim.get("counter_evidence_ids", []) if snippets.get(e)), "")
    # ponytail: 같은 반대 snippet을 초점만 바꿔 두 번 요약한다. Concern·Barrier가 겹치면 Barrier 전용 쿼리 추가 검토.
    return {
        "benefit": claim["statement"],
        "concern": summarize_snippet(counter, _counter_focus("concerns or risks about", item, labels)) if counter else COUNTER_NOT_FOUND,
        "barrier": summarize_snippet(counter, _counter_focus("adoption barriers of", item, labels)) if counter else COUNTER_NOT_FOUND,
        "evidence_ids": [claim["id"], *claim.get("evidence_ids", []), *claim.get("counter_evidence_ids", [])],
    }


def _slot_text(slot: str, claims_by_id: dict[str, Claim], snippets: dict[str, str], family_labels: dict[str, str]) -> str:
    """Actor 슬롯 하나를 문자열로 만든다. stakeholder dict 계약(Actor별 문자열)은 그대로 두고,
    계열별로 [계열명] Benefit | Concern | Barrier (근거 ID)를 이어 붙인다 (설계 3.2·3.5·3.8)."""
    items = sorted((q for q in STAKEHOLDER_QUERY_PLAN if q["slot"] == slot), key=lambda q: TECH_ORDER.index(q["tech"]))
    parts = []
    for q in items:
        label = f"[{family_labels[q['tech']]} 계열]"
        d = _detail(q, claims_by_id.get(q["claim_id"]), snippets, family_labels)
        if d is None:
            # End User는 지연/품질 간접 근거가 없으면 미확인을 명시한다 (추정 금지).
            parts.append(f"{label} {END_USER_GAP if slot == 'end_user' else '근거 미확인'}")
        else:
            parts.append(
                f"{label} Benefit: {d['benefit']} | Concern: {d['concern']} | Barrier: {d['barrier']}"
                f" (근거: {', '.join(d['evidence_ids'])})"
            )
    return " / ".join(parts)


SLOTS = tuple(dict.fromkeys(q["slot"] for q in STAKEHOLDER_QUERY_PLAN))


def _summarize(claims_by_id: dict[str, Claim], snippets: dict[str, str], family_labels: dict[str, str],
               prev: dict | None = None, slots: tuple[str, ...] = SLOTS) -> dict:
    """stakeholder 요약 dict. 재실행에서는 prev를 두고 지정한 슬롯만 다시 쓴다."""
    out = dict(prev or {})
    for slot in slots:
        out[slot] = _slot_text(slot, claims_by_id, snippets, family_labels)
    actors = list(dict.fromkeys(q["actor"] for q in STAKEHOLDER_QUERY_PLAN))
    ok_ids = {cid for cid, c in claims_by_id.items() if c.get("status") == "ok"}
    out["actors_surveyed"] = [a for a in actors if any(
        q["actor"] == a and q["claim_id"] in ok_ids for q in STAKEHOLDER_QUERY_PLAN
    )] or actors
    # report.md.j2(E 소유)가 읽는 기존 키 이름과의 하위 호환 별칭.
    out["cloud_ops"] = out.get("cloud_serving_operator", "")
    out["hw_vendors"] = out.get("memory_vendor", "")
    return out


def stakeholder_research_node(state: OverallState) -> dict:
    """이해관계자 조사 노드: state["market"] 컨텍스트를 읽어 4대 Actor 반응을 조사 (market은 쓰지 않음)."""
    print("👥 [이해관계자] 4대 핵심 Actor(서빙 운영자/개발자/End User/공급자) 반응 조사 실행")

    market_context = state.get("market") or {}
    key_vendors = market_context.get("key_vendors") or []

    audit_issues = (state.get("audit") or {}).get("issues") or []
    my_issues = {i["claim_id"]: i for i in audit_issues if i.get("target_agent") == "stakeholder"}
    existing_sources = list(state.get("sources", []))
    labels = _family_labels(state)

    if my_issues:
        print(f"🔁 [이해관계자] 재실행 대상 Claim: {sorted(my_issues.keys())}")
        claims: list[Claim] = []
        evidence: list[Evidence] = []
        sources: list[Source] = []
        for claim_id, issue in my_issues.items():
            claim, new_ev, new_src = _handle_retry(claim_id, issue.get("action"), state, key_vendors, existing_sources + sources, labels)
            if claim is None:
                continue
            claims.append(claim)
            evidence.extend(new_ev)
            sources.extend(new_src)
        # 재실행: 자기 claim만 upsert. 요약 dict는 Overwrite 키라 기존 값을 펼친 뒤 재실행한 Claim이 속한 Actor 슬롯만 다시 쓴다.
        claims_by_id = {c["id"]: c for c in state.get("claims", []) if c.get("id", "").startswith("STK-")}
        claims_by_id.update({c["id"]: c for c in claims})
        snippets = {e["evidence_id"]: e["snippet"] for e in list(state.get("evidence", [])) + evidence}
        touched = tuple(dict.fromkeys(STAKEHOLDER_PLAN_BY_ID[c["id"]]["slot"] for c in claims if c["id"] in STAKEHOLDER_PLAN_BY_ID))
        stakeholder = _summarize(claims_by_id, snippets, labels, prev=state.get("stakeholder"), slots=touched)
        return {"stakeholder": stakeholder, "claims": claims, "evidence": evidence, "sources": sources}

    # 최초 실행: STK-01~08 (4대 Actor × 기술 계열 2개) 전량 조사
    claims = []
    evidence = []
    sources: list[Source] = []
    for item in STAKEHOLDER_QUERY_PLAN:
        claim, new_ev, new_src = _run_stakeholder_query(item, key_vendors, existing_sources + sources, labels)
        claims.append(claim)
        evidence.extend(new_ev)
        sources.extend(new_src)

    snippets = {e["evidence_id"]: e["snippet"] for e in evidence}
    return {
        "stakeholder": _summarize({c["id"]: c for c in claims}, snippets, labels),
        "claims": claims,
        "evidence": evidence,
        "sources": sources,
    }
