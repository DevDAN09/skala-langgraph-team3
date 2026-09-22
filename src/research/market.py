"""src/research/market.py - Market research node: SW vs HW adoption/ecosystem/barrier evidence via Tavily."""
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

# 기술 계열 단위(KIVI=KV 양자화, CXL-PNM=CXL 메모리 확장) x 시장 지표(adoption/ecosystem/deployment)
# 쿼리 플랜. 각 항목은 지지 쿼리 + 반대 쿼리를 병행 실행해 R3(반대 쿼리 의무)를 만족시킨다.
#
# 쿼리는 키워드 나열이 아니라 자연어 질문 형태로 작성한다. Tavily는 "basic" 키워드 검색이
# 아니라(client.py의 search_depth="advanced"와 함께) 구체적인 자연어 질문을 줄 때 의도를
# 더 정확히 이해하고 관련성 높은 결과를 반환한다. 세 지표의 의미를 서로 겹치지 않게 나눔:
#   - adoption   : 평가/파일럿 단계 신호 ("검토/시범 도입하고 있나?")
#   - deployment : 실제 상용 가동 신호 ("지금 실제로 운영 중인가? 누가/어떤 제품으로?")
#   - ecosystem  : 주변 생태계 지지 신호 (프레임워크/표준화 기구/복수 벤더 지원)
MARKET_QUERY_PLAN = [
    {
        "claim_id": "MKT-01", "tech": "KIVI", "axis": "adoption",
        "support": (
            "Which AI inference platforms or companies are evaluating or piloting "
            "2-bit KV cache quantization such as KIVI for production LLM serving "
            "in 2025 or 2026?"
        ),
        "counter": (
            "What accuracy or reliability problems have been reported when evaluating "
            "2-bit KV cache quantization for production LLM serving?"
        ),
    },
    {
        "claim_id": "MKT-02", "tech": "KIVI", "axis": "ecosystem",
        "support": (
            "Which open-source LLM serving frameworks, such as vLLM or TensorRT-LLM, "
            "currently support KV cache quantization, and what is the status of that "
            "support?"
        ),
        "counter": (
            "What engineering or integration challenges make it difficult to add "
            "KV cache quantization kernels to LLM serving frameworks?"
        ),
    },
    {
        "claim_id": "MKT-03", "tech": "CXL-PNM", "axis": "adoption",
        "support": (
            "Which cloud providers or hardware vendors are evaluating or piloting "
            "CXL memory expansion for AI or LLM inference workloads?"
        ),
        "counter": (
            "What adoption barriers are slowing CXL memory expansion for AI inference "
            "workloads?"
        ),
    },
    {
        "claim_id": "MKT-04", "tech": "CXL-PNM", "axis": "ecosystem",
        "support": (
            "Which companies or standards bodies, such as the CXL Consortium, support "
            "the CXL memory expansion ecosystem across CPU, memory, and server vendors?"
        ),
        "counter": "How mature is software and driver support for CXL memory pooling today?",
    },
    {
        "claim_id": "MKT-05", "tech": "KIVI", "axis": "deployment",
        "support": (
            "Is low-bit KV cache quantization already running in production LLM "
            "inference systems today, and which company or product ships it?"
        ),
        "counter": (
            "Why have companies decided not to deploy KV cache quantization in "
            "production LLM serving?"
        ),
    },
    {
        "claim_id": "MKT-06", "tech": "CXL-PNM", "axis": "deployment",
        "support": (
            "Are CXL 2.0 or CXL 3.0 memory expansion modules already shipping or "
            "deployed in production datacenters today, and which vendor sells them?"
        ),
        "counter": (
            "What latency or cost problems have been reported in production "
            "deployments of CXL memory expansion?"
        ),
    },
]
MARKET_PLAN_BY_ID = {q["claim_id"]: q for q in MARKET_QUERY_PLAN}
AXIS_BY_CLAIM_ID = {q["claim_id"]: q["axis"] for q in MARKET_QUERY_PLAN}

# 축(axis)별로 summarize_snippet에 넘기는 focus를 구체화한다. "{tech} adoption in the
# commercial market"처럼 뭉뚱그린 표현 대신, 그 축이 실제로 찾으려는 신호를 명시한다.
AXIS_FOCUS = {
    "adoption": (
        "whether {tech} is being evaluated, piloted, or considered for adoption in "
        "commercial LLM serving"
    ),
    "deployment": (
        "whether {tech} is already deployed or shipping in production LLM serving "
        "systems today, including which company or product"
    ),
    "ecosystem": "which frameworks, vendors, or standards bodies support the {tech} ecosystem",
}

# MAT-A*(상용 채택 성숙도, TRL 5-9 대역)는 같은 기술의 adoption+ecosystem+deployment MKT
# 근거를 결합해 산출한다. 별도 웹 검색을 추가하지 않고, 이미 수집한 근거만 재사용한다.
MAT_A_PLAN = [
    {"claim_id": "MAT-A01", "tech": "KIVI", "from": ["MKT-01", "MKT-02", "MKT-05"]},
    {"claim_id": "MAT-A02", "tech": "CXL-PNM", "from": ["MKT-03", "MKT-04", "MKT-06"]},
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


def _market_search_pair(support_query: str, counter_query: str) -> tuple[dict, dict | None]:
    """market 쿼리 전용 search_pair 래퍼. 채택/배포 현황처럼 시의성이 중요한 축이라
    최근 1년(time_range="year") 콘텐츠로 좁혀 오래된 정보를 걸러낸다."""
    return search_pair(support_query, counter_query, time_range="year")


def _select_evidence(results: list[dict], focus: str, exclude_urls: frozenset[str] = frozenset()):
    """Tier 순으로 후보를 돌며 쓸 만한 statement가 나오는 첫 결과를 고른다.

    예전에는 results[0] 한 건만 썼다. Tavily 1위가 검색 리스팅·광고 페이지면 본문이 없어
    statement 자리에 저자 목록이나 로그인 메뉴가 들어갔다. summarize_snippet이 빈 문자열을
    주면(=그 텍스트에 관련 내용 없음) 다음 후보로 넘어간다.

    전부 실패해도 Tier가 가장 높은 후보를 근거로는 남긴다(statement는 빈 문자열). 근거 없이
    insufficient로만 두면 D의 R1이 "근거 없음"으로만 보고, 어떤 출처를 확인했는지가 사라진다.
    """
    ranked = rank_results(results, exclude_urls)
    if not ranked:
        return None, "", ""
    for candidate in ranked:
        snippet_text = (candidate.get("content") or "")[:2000]
        statement = summarize_snippet(snippet_text, focus) if snippet_text else ""
        if statement:
            return candidate, snippet_text, statement
    return ranked[0], (ranked[0].get("content") or "")[:2000], ""


def _run_market_query(
    item: dict,
    sources_pool: list[Source],
    exclude_urls: frozenset[str] = frozenset(),
    queries: tuple[str, str] | None = None,
) -> tuple[Claim, list[Evidence], list[Source], str]:
    """지지/반대 쿼리를 1회 병행 실행해 Claim + Evidence(+반대 근거) + Source를 만든다.

    queries를 주면 plan의 기본 질의 대신 그것을 쓴다 (재검색용 재작성 질의).
    반환값 마지막 항목은 반대 근거를 한 문장으로 요약한 barrier_statement다
    (없으면 빈 문자열). market dict의 barriers 텍스트 조립에 쓴다.
    """
    claim_id, tech, axis = item["claim_id"], item["tech"], item["axis"]
    ev_id, src_id = f"EV-{claim_id}", f"SRC-{claim_id}"
    focus = AXIS_FOCUS[axis].format(tech=tech)
    support_query, counter_query = queries or (item["support"], item["counter"])

    support, counter = _market_search_pair(support_query, counter_query)
    support_results = (support or {}).get("results") or []

    if not support_results:
        # 수치 창작 금지: 못 찾으면 statement="" + status="insufficient"
        claim: Claim = {
            "id": claim_id, "perspective": "market", "tech": tech,
            "statement": "", "kind": "fact", "evidence_ids": [], "counter_evidence_ids": [],
            "counter_searched": True, "status": "insufficient",
        }
        return claim, [], [], ""

    new_sources: list[Source] = []
    # R5(LLM Judge)는 Evidence.snippet만 보고 statement 정합성을 판정한다.
    # statement를 만드는 입력과 snippet에 저장하는 텍스트를 반드시 동일하게 맞춰야
    # snippet 밖의 내용에서 나온 문장이 "근거 불일치"로 오판되지 않는다.
    top, snippet_text, statement = _select_evidence(support_results, focus, exclude_urls)
    url = top.get("url", "")
    tier = classify_tier(url)
    resolved_src_id, new_src = _build_source(url, top.get("title", ""), top.get("published_date", ""), tier, src_id, sources_pool)
    if new_src:
        new_sources.append(new_src)

    new_evidence: list[Evidence] = [{
        "evidence_id": ev_id, "source_id": resolved_src_id, "snippet": snippet_text,
    }]

    counter_evidence_ids: list[str] = []
    barrier_statement = ""
    counter_results = (counter or {}).get("results") or [] if counter else []
    if counter_results:
        # market dict의 barriers 문장은 스니펫을 그냥 잘라 붙이지 않고, 같은 summarize_snippet으로
        # 반대 근거를 한 문장으로 정리한다. 쓸 만한 문장이 안 나오면 barriers에 넣지 않는다.
        c_top, c_snippet_text, barrier_statement = _select_evidence(
            counter_results, f"barriers, risks, or limitations affecting {tech} {axis}", exclude_urls
        )
        c_url = c_top.get("url", "")
        c_tier = classify_tier(c_url)
        c_ev_id, c_src_id = f"{ev_id}-C", f"{src_id}-C"
        resolved_c_src_id, new_c_src = _build_source(
            c_url, c_top.get("title", ""), c_top.get("published_date", ""), c_tier, c_src_id, sources_pool + new_sources
        )
        if new_c_src:
            new_sources.append(new_c_src)
        new_evidence.append({"evidence_id": c_ev_id, "source_id": resolved_c_src_id, "snippet": c_snippet_text})
        counter_evidence_ids = [c_ev_id]
    else:
        # 반대 쿼리 결과 없음: counter_searched는 True 유지, claim은 ok 유지 (팀 룰)
        print(f"⚠️ [경고/Fallback] {claim_id}: counter-evidence not found")

    claim: Claim = {
        "id": claim_id, "perspective": "market", "tech": tech,
        "statement": statement, "kind": infer_kind(url, snippet_text),
        "evidence_ids": [ev_id], "counter_evidence_ids": counter_evidence_ids,
        "counter_searched": True, "status": "ok" if statement else "insufficient",
    }
    return claim, new_evidence, new_sources, barrier_statement


def _build_mat_a_claim(item: dict, claims: list[Claim], evidence: list[Evidence]) -> tuple[Claim, list[Evidence]]:
    """방금 수집한 MKT adoption+ecosystem+deployment 근거를 결합해 MAT-A(상용 채택 성숙도) Claim을 만든다."""
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
    # 원본 스니펫(각각 최대 1500자)을 그대로 이어붙이면 3개를 다 담을 수 없어 앞쪽 1개만
    # 남고 나머지가 통째로 잘린다. 이미 summarize_snippet을 거쳐 깨끗해진 각 축의 statement
    # (수백 자 수준)를 축 이름과 함께 합치면, 세 축 신호를 전부 보존하면서도 짧고 근거가
    # 분명하다 (각 statement 자체가 이미 그 축의 스니펫에서 근거를 확인한 문장).
    combined_snippet = " / ".join(
        f"[{AXIS_BY_CLAIM_ID.get(c['id'], '')}] {c['statement']}" for c in contributing
    )[:1500]
    base_evidence = evidence_by_id.get(f"EV-{contributing[0]['id']}")
    base_source_id = base_evidence["source_id"] if base_evidence else f"SRC-{contributing[0]['id']}"

    mat_ev_id = f"EV-{claim_id}"
    statement = summarize_snippet(
        combined_snippet,
        f"overall commercial adoption maturity signals for {tech}, combining evaluation/pilot, "
        "ecosystem support, and production deployment evidence "
        "(do not assign a numeric TRL value; that is computed downstream)",
    )
    claim: Claim = {
        "id": claim_id, "perspective": "maturity", "tech": tech,
        "statement": statement, "kind": "estimate",
        "evidence_ids": [mat_ev_id] if statement else [], "counter_evidence_ids": [],
        "counter_searched": True, "status": "ok" if statement else "insufficient",
    }
    new_evidence = [{"evidence_id": mat_ev_id, "source_id": base_source_id, "snippet": combined_snippet}] if statement else []
    return claim, new_evidence


def _previous_urls(existing_claim: Claim | None, evidence_by_id: dict, sources_by_id: dict) -> frozenset[str]:
    """이 Claim이 직전에 근거로 쓴 URL. 재검색에서 같은 출처를 다시 채택하지 않도록 제외한다."""
    claim = existing_claim or {}
    ev_ids = [*(claim.get("evidence_ids") or []), *(claim.get("counter_evidence_ids") or [])]
    urls = set()
    for ev_id in ev_ids:
        ev = evidence_by_id.get(ev_id)
        src = sources_by_id.get(ev["source_id"]) if ev else None
        if src and (src.get("url") or "").strip():
            urls.add(src["url"].strip())
    return frozenset(urls)


def _handle_retry(claim_id: str, action: str | None, state: OverallState, sources_pool: list[Source]):
    """재실행: 자기 target_agent 이슈의 claim_id만, action이 지시한 만큼만 고친다."""
    claims_by_id = {c["id"]: c for c in state.get("claims", []) if c.get("id") == claim_id}
    evidence_by_id = {e["evidence_id"]: e for e in state.get("evidence", [])}
    sources_by_id = {s["source_id"]: s for s in state.get("sources", [])}
    existing_claim = claims_by_id.get(claim_id)
    plan_item = MARKET_PLAN_BY_ID.get(claim_id)
    exclude_urls = _previous_urls(existing_claim, evidence_by_id, sources_by_id)

    if action == "search_counter_evidence" and existing_claim and plan_item:
        tech, axis = plan_item["tech"], plan_item["axis"]
        counter_query = rewrite_query(
            plan_item["counter"], "the previous counter-evidence search returned nothing usable"
        )
        _, counter = _market_search_pair(plan_item["support"], counter_query)
        counter_results = (counter or {}).get("results") or [] if counter else []
        if not counter_results:
            print(f"⚠️ [경고/Fallback] {claim_id}: 재실행에도 counter-evidence not found")
            return {**existing_claim, "counter_searched": True}, [], []
        c_top, c_snippet, _c_statement = _select_evidence(
            counter_results, f"barriers, risks, or limitations affecting {tech} {axis}", exclude_urls
        )
        c_url = c_top.get("url", "")
        c_ev_id, c_src_id = f"EV-{claim_id}-C", f"SRC-{claim_id}-C"
        resolved_c_src_id, new_c_src = _build_source(
            c_url, c_top.get("title", ""), c_top.get("published_date", ""), classify_tier(c_url), c_src_id, sources_pool
        )
        new_sources = [new_c_src] if new_c_src else []
        new_evidence = [{"evidence_id": c_ev_id, "source_id": resolved_c_src_id, "snippet": c_snippet}]
        updated = {**existing_claim, "counter_evidence_ids": [c_ev_id], "counter_searched": True, "status": "ok"}
        return updated, new_evidence, new_sources

    if action == "relabel" and existing_claim:
        ev = evidence_by_id.get((existing_claim.get("evidence_ids") or [None])[0])
        src = sources_by_id.get(ev["source_id"]) if ev else None
        new_kind = infer_kind(src["url"], ev.get("snippet", "")) if src and ev else existing_claim.get("kind", "fact")
        return {**existing_claim, "kind": new_kind, "status": "ok"}, [], []

    if action == "re_extract" and existing_claim:
        ev = evidence_by_id.get((existing_claim.get("evidence_ids") or [None])[0])
        if ev and ev.get("snippet"):
            statement = summarize_snippet(ev["snippet"], f"{existing_claim.get('tech')} market evidence, strictly grounded in the quoted snippet")
            status = "ok" if statement else "rejected"
        else:
            statement, status = "", "insufficient"
        return {**existing_claim, "statement": statement, "status": status}, [], []

    # search_evidence (기본) 또는 알 수 없는 action: 지지+반대 쿼리를 전부 다시 실행.
    # 같은 질의를 그대로 다시 던지면 같은 결과가 와서 재시도가 한도만 소진한다.
    # 질의를 다시 쓰고 직전 근거 URL을 제외해야 다른 출처에 닿는다.
    if plan_item:
        reason = "the previous search returned a page with no usable evidence for this claim"
        queries = (rewrite_query(plan_item["support"], reason), rewrite_query(plan_item["counter"], reason))
        claim, new_ev, new_src, _barrier = _run_market_query(plan_item, sources_pool, exclude_urls, queries)
        return claim, new_ev, new_src

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

    # 최초 실행: MKT-01~06(3지표 x 2기술) 전량 조사 후, 그 근거로 MAT-A01~02를 파생시킨다.
    claims = []
    evidence = []
    sources: list[Source] = []
    barrier_by_claim_id: dict[str, str] = {}
    for item in MARKET_QUERY_PLAN:
        claim, new_ev, new_src, barrier_statement = _run_market_query(item, existing_sources + sources)
        claims.append(claim)
        evidence.extend(new_ev)
        sources.extend(new_src)
        if barrier_statement:
            barrier_by_claim_id[claim["id"]] = barrier_statement

    for mat_item in MAT_A_PLAN:
        mat_claim, mat_ev = _build_mat_a_claim(mat_item, claims, evidence)
        claims.append(mat_claim)
        evidence.extend(mat_ev)

    # 3지표(adoption/deployment/ecosystem)를 서로 다른 버킷으로 모은다. barriers는 이제
    # 반대 근거 스니펫을 그냥 자르지 않고, _run_market_query가 미리 한 문장으로 정리해 둔
    # barrier_statement를 쓴다 (읽기 좋은 완결 문장).
    adoption_parts, deployment_parts, ecosystem_parts, barrier_parts, vendors = [], [], [], [], set()
    axis_buckets = {"adoption": adoption_parts, "deployment": deployment_parts, "ecosystem": ecosystem_parts}
    for c in claims:
        axis = AXIS_BY_CLAIM_ID.get(c["id"])
        if axis and c.get("status") == "ok" and c.get("statement"):
            axis_buckets[axis].append(f"{c['tech']}: {c['statement']}")
        barrier_statement = barrier_by_claim_id.get(c["id"])
        if barrier_statement:
            barrier_parts.append(f"{c['tech']}: {barrier_statement}")
    for s in existing_sources + sources:
        label = vendor_label(s.get("url", ""))
        if label:
            vendors.add(label)

    market = {
        # stakeholder 노드가 쿼리 특화를 위해 읽는 키
        "key_vendors": sorted(vendors) or ["Cloud CSPs", "Hardware Vendors"],
        # 4지표: adoption(평가/파일럿) / deployment(실제 상용 가동) / ecosystem(생태계 지지) / barriers
        "adoption": " | ".join(adoption_parts) if adoption_parts else "인용 가능한 공개 채택 근거 미확인",
        "deployment": " | ".join(deployment_parts) if deployment_parts else "인용 가능한 공개 배포 근거 미확인",
        "ecosystem": " | ".join(ecosystem_parts) if ecosystem_parts else "인용 가능한 생태계 근거 미확인",
        "barriers": " | ".join(barrier_parts) if barrier_parts else "counter-evidence not found",
    }

    return {
        "market": market,
        "claims": claims,
        "evidence": evidence,
        "sources": sources,
    }
