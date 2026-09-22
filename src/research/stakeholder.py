"""src/research/stakeholder.py - Stakeholder research node, chained from market context."""
from src.state import OverallState, Claim, Evidence, Source
from src.research.client import (
    search_pair,
    classify_tier,
    infer_kind,
    resolve_source_id,
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
        "support": "vLLM TensorRT-LLM developer KV cache quantization kernel integration effort",
        "counter": "KV cache quantization kernel developer integration difficulty complaint",
    },
    {
        "claim_id": "STK-03", "actor": "End User", "slot": "end_user", "tech": "CXL-PNM",
        "support": "CXL memory expansion LLM inference latency long context end user experience",
        "counter": "CXL memory expansion inference latency degradation user complaint",
    },
    {
        "claim_id": "STK-04", "actor": "HW/Memory Supplier", "slot": "memory_vendor", "tech": "CXL-PNM",
        "support": "{vendor} CXL memory module enterprise AI server roadmap strategy",
        "counter": "CXL memory vendor adoption challenge cost competitiveness",
    },
    {
        "claim_id": "STK-05", "actor": "Cloud Serving Operator", "slot": "cloud_serving_operator", "tech": "CXL-PNM",
        "support": "cloud data center CXL memory expansion LLM inference server deployment {vendor}",
        "counter": "CXL memory expansion data center deployment cost operational concern",
    },
    {
        "claim_id": "STK-06", "actor": "Framework Developer", "slot": "framework_developer", "tech": "CXL-PNM",
        "support": "LLM serving framework CXL memory tiering KV cache offload support",
        "counter": "CXL memory tiering software support complexity developer challenge",
    },
    {
        "claim_id": "STK-07", "actor": "End User", "slot": "end_user", "tech": "KIVI",
        "support": "KV cache quantization LLM response quality latency long context user impact",
        "counter": "KV cache 2-bit quantization accuracy degradation long context output quality",
    },
    {
        "claim_id": "STK-08", "actor": "HW/Memory Supplier", "slot": "memory_vendor", "tech": "KIVI",
        "support": "{vendor} GPU inference SDK KV cache quantization support",
        "counter": "KV cache quantization hardware support limitation GPU",
    },
]
TECH_ORDER = ("KIVI", "CXL-PNM")
END_USER_GAP = "인용 가능한 지연/품질 간접 근거 미확인"
COUNTER_NOT_FOUND = "counter-evidence not found"
# market.key_vendors는 알파벳순이라 첫 항목이 기술과 무관할 수 있다. 계열별로 쿼리에 넣을 벤더 후보를 정한다.
VENDOR_PREFERENCE = {"CXL-PNM": ("Samsung", "SK Hynix", "Intel", "CXL Consortium"), "KIVI": ("NVIDIA",)}
STAKEHOLDER_PLAN_BY_ID = {q["claim_id"]: q for q in STAKEHOLDER_QUERY_PLAN}
TIER_RANK = {"T1": 0, "T2": 1, "T3": 2, "T4": 3}


def _pick_result(results: list[dict], exclude_urls: set[str] = frozenset()) -> dict:
    """T1~T3 결과를 먼저 고른다 (R2: T4 단독 근거 금지). 재검색 때는 직전 근거 URL을 뺀다.
    제외하고 남는 결과가 없으면 원래 목록에서 고른다."""
    candidates = [r for r in results if (r.get("url") or "") not in exclude_urls] or results
    return min(candidates, key=lambda r: TIER_RANK[classify_tier(r.get("url", ""))])


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
    item: dict, key_vendors: list[str], sources_pool: list[Source], exclude_urls: set[str] = frozenset()
) -> tuple[Claim, list[Evidence], list[Source]]:
    """Actor별 지지/반대 쿼리를 1회 병행 실행해 Claim + Evidence(+반대 근거) + Source를 만든다."""
    claim_id, tech, actor = item["claim_id"], item["tech"], item["actor"]
    ev_id, src_id = f"EV-{claim_id}", f"SRC-{claim_id}"

    support_query = _fill_vendor(item["support"], key_vendors, tech)
    counter_query = _fill_vendor(item["counter"], key_vendors, tech)
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
    top = _pick_result(support_results, exclude_urls)
    url = top.get("url", "")
    tier = classify_tier(url)
    resolved_src_id, new_src = _build_source(url, top.get("title", ""), top.get("published_date", ""), tier, src_id, sources_pool)
    if new_src:
        new_sources.append(new_src)

    # R5(LLM Judge)는 Evidence.snippet만 보고 statement 정합성을 판정하므로,
    # statement 생성 입력과 저장되는 snippet을 동일한 텍스트로 맞춘다.
    snippet_text = (top.get("content") or "")[:500]
    statement = summarize_snippet(snippet_text, f"the {actor}'s benefit or adoption status regarding {tech}")
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


def _handle_retry(claim_id: str, action: str | None, state: OverallState, key_vendors: list[str], sources_pool: list[Source]):
    """재실행: 자기 target_agent(stakeholder) 이슈의 claim_id만, action이 지시한 만큼만 고친다."""
    existing_claim = next((c for c in state.get("claims", []) if c.get("id") == claim_id), None)
    evidence_by_id = {e["evidence_id"]: e for e in state.get("evidence", [])}
    sources_by_id = {s["source_id"]: s for s in state.get("sources", [])}
    plan_item = STAKEHOLDER_PLAN_BY_ID.get(claim_id)

    if action == "search_counter_evidence" and existing_claim and plan_item:
        tech = plan_item["tech"]
        counter_query = _fill_vendor(plan_item["counter"], key_vendors, tech)
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
        if ev and ev.get("snippet"):
            statement = summarize_snippet(ev["snippet"], f"{existing_claim.get('tech')} stakeholder evidence, strictly grounded in the quoted snippet")
            status = "ok" if statement else "rejected"
        else:
            statement, status = "", "insufficient"
        return {**existing_claim, "statement": statement, "status": status}, [], []

    # search_evidence (기본) 또는 알 수 없는 action: 지지+반대 쿼리를 전부 다시 실행.
    # 같은 쿼리는 같은 결과를 돌려주므로 직전 근거 URL은 제외해야 R1/R2 재위반을 피할 수 있다.
    if plan_item:
        prev_ev = evidence_by_id.get(((existing_claim or {}).get("evidence_ids") or [None])[0])
        prev_src = sources_by_id.get(prev_ev["source_id"]) if prev_ev else None
        exclude = {prev_src["url"]} if prev_src and prev_src.get("url") else set()
        return _run_stakeholder_query(plan_item, key_vendors, sources_pool, exclude)
    if existing_claim:
        return {**existing_claim, "status": "insufficient"}, [], []
    return None, [], []


def _family_labels(state: OverallState) -> dict[str, str]:
    families = (state.get("selected") or {}).get("families") or {}
    return {"KIVI": families.get("sw", "KV Quantization"), "CXL-PNM": families.get("hw", "CXL Memory Expansion")}


def _detail(item: dict, claim: Claim, snippets: dict[str, str]) -> dict:
    """Actor 한 칸의 Benefit / Concern / Adoption Barrier / Evidence (설계 3.5).
    Benefit은 지지 근거 Claim statement, Concern·Barrier는 반대 근거 snippet에서만 뽑는다."""
    if claim.get("status") != "ok":
        return {"claim_id": claim["id"], "benefit": "", "concern": "", "barrier": "", "evidence_ids": []}
    counter = next((snippets[e] for e in claim.get("counter_evidence_ids", []) if snippets.get(e)), "")
    subject = f"the {item['actor']} regarding {claim['tech']}"
    # ponytail: 같은 반대 snippet을 초점만 바꿔 두 번 요약한다. Concern·Barrier가 겹치면 Barrier 전용 쿼리 추가 검토.
    return {
        "claim_id": claim["id"],
        "benefit": claim["statement"],
        "concern": summarize_snippet(counter, f"concerns or risks raised by {subject}") if counter else COUNTER_NOT_FOUND,
        "barrier": summarize_snippet(counter, f"adoption barriers faced by {subject}") if counter else COUNTER_NOT_FOUND,
        "evidence_ids": list(claim.get("evidence_ids", [])) + list(claim.get("counter_evidence_ids", [])),
    }


def _summarize(details: dict[str, dict], family_labels: dict[str, str]) -> dict:
    """claim_id별 detail로 Actor 요약 dict를 만든다. 슬롯은 {tech: detail}.
    시장성·이해관계자 근거는 계열 단위라서 E 템플릿용 문자열 별칭에는 계열명을 붙인다 (설계 3.2)."""
    slots: dict[str, dict[str, dict]] = {}
    for q in STAKEHOLDER_QUERY_PLAN:
        d = {"claim_id": q["claim_id"], "benefit": "", "concern": "", "barrier": "", "evidence_ids": [],
             **details.get(q["claim_id"], {})}
        # End User는 지연/품질 간접 근거가 없으면 기술별로 미확인을 남긴다 (추정 금지).
        if q["slot"] == "end_user" and not d["benefit"]:
            d["benefit"] = END_USER_GAP
        slots.setdefault(q["slot"], {})[q["tech"]] = d

    def by_family(slot: str) -> str:
        return " / ".join(
            f"[{family_labels[tech]} 계열] {slots[slot][tech]['benefit'] or '근거 미확인'}" for tech in TECH_ORDER
        )

    actors = list(dict.fromkeys(q["actor"] for q in STAKEHOLDER_QUERY_PLAN))
    surveyed = [a for a in actors if any(
        q["actor"] == a and details.get(q["claim_id"], {}).get("benefit") for q in STAKEHOLDER_QUERY_PLAN
    )]
    return {
        "actors_surveyed": surveyed or actors,
        **slots,
        # report.md.j2(E 소유)가 읽는 기존 키 이름과의 하위 호환 문자열 별칭.
        "cloud_ops": by_family("cloud_serving_operator"),
        "hw_vendors": by_family("memory_vendor"),
    }


def stakeholder_research_node(state: OverallState) -> dict:
    """이해관계자 조사 노드: state["market"] 컨텍스트를 읽어 4대 Actor 반응을 조사 (market은 쓰지 않음)."""
    print("👥 [이해관계자] 4대 핵심 Actor(서빙 운영자/개발자/End User/공급자) 반응 조사 실행")

    market_context = state.get("market") or {}
    key_vendors = market_context.get("key_vendors") or []

    audit_issues = (state.get("audit") or {}).get("issues") or []
    my_issues = {i["claim_id"]: i for i in audit_issues if i.get("target_agent") == "stakeholder"}
    existing_sources = list(state.get("sources", []))

    if my_issues:
        print(f"🔁 [이해관계자] 재실행 대상 Claim: {sorted(my_issues.keys())}")
        claims: list[Claim] = []
        evidence: list[Evidence] = []
        sources: list[Source] = []
        for claim_id, issue in my_issues.items():
            claim, new_ev, new_src = _handle_retry(claim_id, issue.get("action"), state, key_vendors, existing_sources + sources)
            if claim is None:
                continue
            claims.append(claim)
            evidence.extend(new_ev)
            sources.extend(new_src)
        # 재실행: 자기 claim만 upsert. 요약 dict는 Overwrite 키라 기존 슬롯을 그대로 두고 재실행한 Claim 칸만 다시 계산한다.
        prev = state.get("stakeholder") or {}
        details = {
            q["claim_id"]: prev[q["slot"]][q["tech"]]
            for q in STAKEHOLDER_QUERY_PLAN
            if isinstance((prev.get(q["slot"]) or {}).get(q["tech"]), dict)
        }
        snippets = {e["evidence_id"]: e["snippet"] for e in list(state.get("evidence", [])) + evidence}
        for claim in claims:
            if claim["id"] in STAKEHOLDER_PLAN_BY_ID:
                details[claim["id"]] = _detail(STAKEHOLDER_PLAN_BY_ID[claim["id"]], claim, snippets)
        stakeholder = {**prev, **_summarize(details, _family_labels(state))}
        return {"stakeholder": stakeholder, "claims": claims, "evidence": evidence, "sources": sources}

    # 최초 실행: STK-01~08 (4대 Actor × 기술 계열 2개) 전량 조사
    claims = []
    evidence = []
    sources: list[Source] = []
    for item in STAKEHOLDER_QUERY_PLAN:
        claim, new_ev, new_src = _run_stakeholder_query(item, key_vendors, existing_sources + sources)
        claims.append(claim)
        evidence.extend(new_ev)
        sources.extend(new_src)

    snippets = {e["evidence_id"]: e["snippet"] for e in evidence}
    details = {c["id"]: _detail(STAKEHOLDER_PLAN_BY_ID[c["id"]], c, snippets) for c in claims}
    return {
        "stakeholder": _summarize(details, _family_labels(state)),
        "claims": claims,
        "evidence": evidence,
        "sources": sources,
    }
