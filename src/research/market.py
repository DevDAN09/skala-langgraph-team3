"""src/research/market.py - Market research node: SW vs HW adoption/ecosystem/barrier evidence via Tavily."""
from src.state import OverallState, Claim, Evidence, Source
from src.research.client import (
    search_pair,
    classify_tier,
    infer_kind,
    resolve_source_id,
    summarize_snippet,
    vendor_label,
)

# 기술 계열 단위(KIVI=KV 양자화, CXL-PNM=CXL 메모리 확장) x 시장 지표(adoption/ecosystem) 쿼리 플랜.
# 각 항목은 지지 쿼리 + 반대 쿼리를 병행 실행해 R3(반대 쿼리 의무)를 만족시킨다.
MARKET_QUERY_PLAN = [
    {
        "claim_id": "MKT-01", "tech": "KIVI", "axis": "adoption",
        "support": "vLLM TensorRT-LLM production KV cache quantization deployment 2025",
        "counter": "KV cache quantization accuracy loss adoption barrier",
    },
    {
        "claim_id": "MKT-02", "tech": "KIVI", "axis": "ecosystem",
        "support": "KV cache quantization open source serving framework integration support",
        "counter": "KV cache quantization kernel integration complexity limitation",
    },
    {
        "claim_id": "MKT-03", "tech": "CXL-PNM", "axis": "adoption",
        "support": "Samsung SK Hynix CXL memory expansion commercial deployment datacenter",
        "counter": "CXL memory expansion latency cost deployment barrier",
    },
    {
        "claim_id": "MKT-04", "tech": "CXL-PNM", "axis": "ecosystem",
        "support": "CXL Consortium CXL 2.0 CXL 3.0 ecosystem server vendor standard adoption",
        "counter": "CXL ecosystem software driver support maturity gap",
    },
]
MARKET_PLAN_BY_ID = {q["claim_id"]: q for q in MARKET_QUERY_PLAN}
AXIS_BY_CLAIM_ID = {q["claim_id"]: q["axis"] for q in MARKET_QUERY_PLAN}

# MAT-A*(상용 채택 성숙도, TRL 5-9 대역)는 같은 기술의 adoption+ecosystem MKT 근거를 결합해 산출한다.
# 별도 웹 검색을 추가하지 않고, 이미 수집한 근거만 재사용한다 (신규 API 호출 최소화).
MAT_A_PLAN = [
    {"claim_id": "MAT-A01", "tech": "KIVI", "from": ["MKT-01", "MKT-02"]},
    {"claim_id": "MAT-A02", "tech": "CXL-PNM", "from": ["MKT-03", "MKT-04"]},
]


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


def _run_market_query(item: dict, sources_pool: list[Source]) -> tuple[Claim, list[Evidence], list[Source]]:
    """지지/반대 쿼리를 1회 병행 실행해 Claim + Evidence(+반대 근거) + Source를 만든다."""
    claim_id, tech, axis = item["claim_id"], item["tech"], item["axis"]
    ev_id, src_id = f"EV-{claim_id}", f"SRC-{claim_id}"

    support, counter = search_pair(item["support"], item["counter"])
    support_results = (support or {}).get("results") or []

    if not support_results:
        # 수치 창작 금지: 못 찾으면 statement="" + status="insufficient"
        claim: Claim = {
            "id": claim_id, "perspective": "market", "tech": tech,
            "statement": "", "kind": "fact", "evidence_ids": [], "counter_evidence_ids": [],
            "counter_searched": True, "status": "insufficient",
        }
        return claim, [], []

    new_sources: list[Source] = []
    top = support_results[0]
    url = top.get("url", "")
    tier = classify_tier(url)
    resolved_src_id, new_src = _build_source(url, top.get("title", ""), top.get("published_date", ""), tier, src_id, sources_pool)
    if new_src:
        new_sources.append(new_src)

    # R5(LLM Judge)는 Evidence.snippet만 보고 statement 정합성을 판정한다.
    # statement를 만드는 입력과 snippet에 저장하는 텍스트를 반드시 동일하게 맞춰야
    # snippet 밖의 내용에서 나온 문장이 "근거 불일치"로 오판되지 않는다.
    snippet_text = (top.get("content") or "")[:500]
    statement = summarize_snippet(snippet_text, f"{tech} {axis} in the commercial market")
    new_evidence: list[Evidence] = [{
        "evidence_id": ev_id, "source_id": resolved_src_id, "snippet": snippet_text,
    }]

    counter_evidence_ids: list[str] = []
    counter_results = (counter or {}).get("results") or [] if counter else []
    if counter_results:
        c_top = counter_results[0]
        c_url = c_top.get("url", "")
        c_tier = classify_tier(c_url)
        c_ev_id, c_src_id = f"{ev_id}-C", f"{src_id}-C"
        resolved_c_src_id, new_c_src = _build_source(
            c_url, c_top.get("title", ""), c_top.get("published_date", ""), c_tier, c_src_id, sources_pool + new_sources
        )
        if new_c_src:
            new_sources.append(new_c_src)
        new_evidence.append({"evidence_id": c_ev_id, "source_id": resolved_c_src_id, "snippet": (c_top.get("content") or "")[:500]})
        counter_evidence_ids = [c_ev_id]
    else:
        # 반대 쿼리 결과 없음: counter_searched는 True 유지, claim은 ok 유지 (팀 룰)
        print(f"⚠️ [경고/Fallback] {claim_id}: counter-evidence not found")

    claim: Claim = {
        "id": claim_id, "perspective": "market", "tech": tech,
        "statement": statement, "kind": infer_kind(url),
        "evidence_ids": [ev_id], "counter_evidence_ids": counter_evidence_ids,
        "counter_searched": True, "status": "ok" if statement else "insufficient",
    }
    return claim, new_evidence, new_sources


def _build_mat_a_claim(item: dict, claims: list[Claim], evidence: list[Evidence]) -> tuple[Claim, list[Evidence]]:
    """방금 수집한 MKT adoption+ecosystem 근거를 결합해 MAT-A(상용 채택 성숙도) Claim을 만든다."""
    claim_id, tech = item["claim_id"], item["tech"]
    claims_by_id = {c["id"]: c for c in claims}
    contributing = [claims_by_id[cid] for cid in item["from"] if claims_by_id.get(cid, {}).get("status") == "ok"]

    if not contributing:
        return {
            "id": claim_id, "perspective": "maturity", "tech": tech,
            "statement": "", "kind": "estimate", "evidence_ids": [], "counter_evidence_ids": [],
            "counter_searched": True, "status": "insufficient",
        }, []

    evidence_by_id = {e["evidence_id"]: e for e in evidence}
    snippets = [evidence_by_id[f"EV-{c['id']}"]["snippet"] for c in contributing if f"EV-{c['id']}" in evidence_by_id]
    combined_snippet = " / ".join(snippets)[:400]
    base_evidence = evidence_by_id.get(f"EV-{contributing[0]['id']}")
    base_source_id = base_evidence["source_id"] if base_evidence else f"SRC-{contributing[0]['id']}"

    mat_ev_id = f"EV-{claim_id}"
    statement = summarize_snippet(
        combined_snippet,
        f"overall commercial adoption maturity signals for {tech}, combining deployment and ecosystem "
        "evidence (do not assign a numeric TRL value; that is computed downstream)",
    )
    claim: Claim = {
        "id": claim_id, "perspective": "maturity", "tech": tech,
        "statement": statement, "kind": "estimate",
        "evidence_ids": [mat_ev_id] if statement else [], "counter_evidence_ids": [],
        "counter_searched": True, "status": "ok" if statement else "insufficient",
    }
    new_evidence = [{"evidence_id": mat_ev_id, "source_id": base_source_id, "snippet": combined_snippet}] if statement else []
    return claim, new_evidence


def _handle_retry(claim_id: str, action: str | None, state: OverallState, sources_pool: list[Source]):
    """재실행: 자기 target_agent 이슈의 claim_id만, action이 지시한 만큼만 고친다."""
    claims_by_id = {c["id"]: c for c in state.get("claims", []) if c.get("id") == claim_id}
    evidence_by_id = {e["evidence_id"]: e for e in state.get("evidence", [])}
    sources_by_id = {s["source_id"]: s for s in state.get("sources", [])}
    existing_claim = claims_by_id.get(claim_id)
    plan_item = MARKET_PLAN_BY_ID.get(claim_id)

    if action == "search_counter_evidence" and existing_claim and plan_item:
        _, counter = search_pair(plan_item["support"], plan_item["counter"])
        counter_results = (counter or {}).get("results") or [] if counter else []
        if not counter_results:
            print(f"⚠️ [경고/Fallback] {claim_id}: 재실행에도 counter-evidence not found")
            return {**existing_claim, "counter_searched": True}, [], []
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
        ev = evidence_by_id.get((existing_claim.get("evidence_ids") or [None])[0])
        src = sources_by_id.get(ev["source_id"]) if ev else None
        new_kind = infer_kind(src["url"]) if src else existing_claim.get("kind", "fact")
        return {**existing_claim, "kind": new_kind, "status": "ok"}, [], []

    if action == "re_extract" and existing_claim:
        ev = evidence_by_id.get((existing_claim.get("evidence_ids") or [None])[0])
        if ev and ev.get("snippet"):
            statement = summarize_snippet(ev["snippet"], f"{existing_claim.get('tech')} market evidence, strictly grounded in the quoted snippet")
            status = "ok" if statement else "rejected"
        else:
            statement, status = "", "insufficient"
        return {**existing_claim, "statement": statement, "status": status}, [], []

    # search_evidence (기본) 또는 알 수 없는 action: 지지+반대 쿼리를 전부 다시 실행
    if plan_item:
        return _run_market_query(plan_item, sources_pool)

    # MAT-A처럼 전담 쿼리 플랜이 없는 claim: 새 검색을 만들 수 없으므로 insufficient로 확정
    if existing_claim:
        return {**existing_claim, "status": "insufficient"}, [], []
    return None, [], []


def market_research_node(state: OverallState) -> dict:
    """시장성 조사 노드: KIVI(SW) vs CXL-PNM(HW) 채택/생태계/장벽을 지지+반대 쿼리로 조사."""
    print("📈 [시장성 조사] 시장 채택 및 기술 장벽 다각도 조사 실행")

    audit_issues = (state.get("audit") or {}).get("issues") or []
    my_issues = {i["claim_id"]: i for i in audit_issues if i.get("target_agent") == "market"}
    existing_sources = list(state.get("sources", []))

    if my_issues:
        print(f"🔁 [시장성 조사] 재실행 대상 Claim: {sorted(my_issues.keys())}")
        claims: list[Claim] = []
        evidence: list[Evidence] = []
        sources: list[Source] = []
        for claim_id, issue in my_issues.items():
            claim, new_ev, new_src = _handle_retry(claim_id, issue.get("action"), state, existing_sources + sources)
            if claim is None:
                continue
            claims.append(claim)
            evidence.extend(new_ev)
            sources.extend(new_src)
        # 재실행에서는 자기 target_agent claim만 patch. market 요약 dict는 건드리지 않는다 (Overwrite 리듀서 보호).
        return {"claims": claims, "evidence": evidence, "sources": sources}

    # 최초 실행: MKT-01~04 전량 조사 후, 그 근거로 MAT-A01~02를 파생시킨다.
    claims = []
    evidence = []
    sources: list[Source] = []
    for item in MARKET_QUERY_PLAN:
        claim, new_ev, new_src = _run_market_query(item, existing_sources + sources)
        claims.append(claim)
        evidence.extend(new_ev)
        sources.extend(new_src)

    for mat_item in MAT_A_PLAN:
        mat_claim, mat_ev = _build_mat_a_claim(mat_item, claims, evidence)
        claims.append(mat_claim)
        evidence.extend(mat_ev)

    adoption_parts, ecosystem_parts, barrier_parts, vendors = [], [], [], set()
    for c in claims:
        axis = AXIS_BY_CLAIM_ID.get(c["id"])
        if axis and c.get("status") == "ok" and c.get("statement"):
            label = f"{c['tech']}: {c['statement']}"
            (adoption_parts if axis == "adoption" else ecosystem_parts).append(label)
        for cev_id in c.get("counter_evidence_ids", []):
            snippet = next((e["snippet"] for e in evidence if e["evidence_id"] == cev_id), "")
            if snippet:
                barrier_parts.append(f"{c['tech']}: {snippet[:160]}")
    for s in existing_sources + sources:
        label = vendor_label(s.get("url", ""))
        if label:
            vendors.add(label)

    market = {
        # stakeholder 노드가 쿼리 특화를 위해 읽는 키
        "key_vendors": sorted(vendors) or ["Cloud CSPs", "Hardware Vendors"],
        # 4지표: adoption / deployment / ecosystem / barriers.
        # 이 과제 범위(클라우드 서빙 상용화)에서 상용 배포 여부가 곧 채택 신호이므로 동일 근거를 공유한다.
        "adoption": " | ".join(adoption_parts) if adoption_parts else "인용 가능한 공개 채택 근거 미확인",
        "deployment": " | ".join(adoption_parts) if adoption_parts else "인용 가능한 공개 배포 근거 미확인",
        "ecosystem": " | ".join(ecosystem_parts) if ecosystem_parts else "인용 가능한 생태계 근거 미확인",
        "barriers": " | ".join(barrier_parts) if barrier_parts else "counter-evidence not found",
    }

    return {
        "market": market,
        "claims": claims,
        "evidence": evidence,
        "sources": sources,
    }
