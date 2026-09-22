# 📋 [담당 C] 외부 웹 조사 엔진 구현 가이드

> **담당자**: 담당 C  
> **핵심 임무**: Tavily Search 클라이언트 구축, 지지 쿼리 및 반대 쿼리 의무 병행(R3 준수), 출처 Tier(T1~T4) 자동 분류, `market_research` 및 `stakeholder_research` 노드 구현  
> ⚠️ **필독 공통 개발 룰**: 코딩 시작 전 [`tasks/common.md`](common.md)의 LangGraph 안티패턴(1.2.12) 및 TDD 가이드를 반드시 숙지하세요!  
> ✅ **설계서 대조 체크리스트**: 이 문서 [§7](#7-설계서-checklist-이-파일에서만-체크) (공통 항목 포함). 인덱스는 [`design_checklist.md`](design_checklist.md)

---

## 🎯 1. 개발 목표 및 마일스톤 (10:00 ~ 14:00)
- **10:00 ~ 10:30 (Phase 1)**: Tavily API 연동 확인 및 `tests/test_research.py` 실행
- **10:30 ~ 11:30 (Phase 2-A)**: `client.py` 지지/반대 쿼리 쌍(R3) 및 Tier 분류기 고도화
- **11:30 ~ 12:30 (Phase 2-B)**: `market.py` 및 `stakeholder.py` 노드 구현 완료 & `tests/test_research.py` 통과
- **12:30 ~ 14:00 (Phase 3~5)**: 메인 그래프 결합 및 시장성 ➔ 이해관계자 체이닝(Cascade Chaining) 연동 검수

---

## 📁 2. 전담 파일 목록
- `src/research/client.py`: Tavily API 래퍼, 지지/반대 쌍 쿼리 실행기, Tier 분류기
- `src/research/market.py`: `market_research_node` (시장성 4대 축 조사 및 MAT 채택 Claim 생성)
- `src/research/stakeholder.py`: `stakeholder_research_node` (4대 Actor 조사)
- `tests/test_research.py`: 독립 단위 테스트

---

## 🌐 3. Tavily 검색 & Tier 분류 클라이언트 (`src/research/client.py`)

- **출처 Tier 분류 기준**:
  - `T1`: 학회/저널 논문, IEEE, 표준화 기구 (CXL Consortium)
  - `T2`: 기업 공식 블로그 (Samsung, SK Hynix, vLLM GitHub)
  - `T3`: IT 전문 매체 기사, 애널리스트 리포트
  - `T4`: 개인 블로그, Reddit, 커뮤니티 (단독 근거 불가)

```python
"""src/research/client.py"""
from tavily import TavilyClient
import os

tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY", "your-api-key"))

def classify_tier(url: str) -> str:
    """URL 기반 신뢰도 등급 자동 분류"""
    url_lower = url.lower()
    if any(d in url_lower for d in ["arxiv.org", "ieee.org", "acm.org", "computeexpresslink.org"]):
        return "T1"
    if any(d in url_lower for d in ["github.com", "samsung.com", "skhynix.com", "nvidia.com", "intel.com"]):
        return "T2"
    if any(d in url_lower for d in ["reddit.com", "medium.com", "tistory.com", "velog.io"]):
        return "T4"
    return "T3"

def search_pair(support_query: str, counter_query: str) -> tuple[dict, dict | None]:
    """지지 쿼리와 반대 쿼리를 1회 이상 병행 실행 (R3 규칙 강제)"""
    support_res = tavily.search(query=support_query, max_results=3)
    
    # 반대 쿼리 (한계점, 단점, 채택 지연 등)
    try:
        counter_res = tavily.search(query=counter_query, max_results=2)
    except Exception:
        counter_res = None
        
    return support_res, counter_res
```

---

## 📈 4. 시장성 조사 노드 (`src/research/market.py`)

기술 계열 단위(KV 양자화 vs CXL 메모리 확장)로 산업계 채택 및 배포 현황을 수집합니다.

```python
"""src/research/market.py"""
from src.state import OverallState, Claim, Evidence, Source
from src.research.client import search_pair, classify_tier
from langchain_openai import ChatOpenAI

def market_research_node(state: OverallState) -> dict:
    """시장성 조사 노드"""
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    
    new_claims: list[Claim] = []
    new_evidence: list[Evidence] = []
    new_sources: list[Source] = []
    
    # KIVI 계열 (KV 양자화) & CXL-PNM 계열 (CXL 메모리)
    queries = [
        {
            "id": "MKT-01", "tech": "KV Quantization",
            "support": "vLLM TensorRT-LLM 2-bit KV cache quantization adoption",
            "counter": "KV cache 2-bit quantization accuracy loss limitation"
        },
        {
            "id": "MKT-02", "tech": "CXL Memory Expansion",
            "support": "Samsung SK Hynix CXL 2.0 commercial memory deployment 2024",
            "counter": "CXL deployment barriers latency cost cloud servers"
        }
    ]
    
    for q in queries:
        supp, count = search_pair(q["support"], q["counter"])
        if supp and supp.get("results"):
            top = supp["results"][0]
            ev_id = f"EV-{q['id']}"
            src_id = f"SRC-{q['id']}"
            tier = classify_tier(top["url"])
            
            stmt = llm.invoke(f"Summarize in one sentence the adoption fact from: {top['content']}").content.strip()
            
            new_claims.append({
                "id": q["id"], "perspective": "market", "tech": q["tech"],
                "statement": stmt, "kind": "fact",
                "evidence_ids": [ev_id],
                "counter_evidence_ids": [],
                "counter_searched": True,  # R3 충족
                "status": "ok"
            })
            new_evidence.append({
                "evidence_id": ev_id, "source_id": src_id, "snippet": top["content"][:300]
            })
            new_sources.append({
                "source_id": src_id, "title": top["title"], "publisher": "Web",
                "date": "2024", "url": top["url"], "source_type": "web", "source_tier": tier
            })
            
    return {
        "market": {
            "key_vendors": ["Samsung", "SK Hynix", "vLLM community"],
            "summary": "CXL 2.0 hardware deployed, 2bit quantization under active community testing"
        },
        "claims": new_claims,
        "evidence": new_evidence,
        "sources": new_sources
    }
```

---

## 👥 5. 이해관계자 조사 노드 (`src/research/stakeholder.py`)

시장성 조사 노드가 전달한 `market` 컨텍스트를 입력으로 받아, 4대 주체의 반응을 조사합니다.

```python
"""src/research/stakeholder.py"""
from src.state import OverallState, Claim, Evidence, Source
from src.research.client import search_pair, classify_tier

def stakeholder_research_node(state: OverallState) -> dict:
    """이해관계자 조사 노드 (시장성 컨텍스트 이어받기)"""
    market_context = state.get("market", {})
    key_vendors = market_context.get("key_vendors", ["Cloud CSPs", "Hardware Vendors"])
    
    new_claims: list[Claim] = []
    new_evidence: list[Evidence] = []
    new_sources: list[Source] = []
    
    # 4대 주체: 서빙 운영자, 프레임워크 개발자, 엔드유저, 벤더
    actors = [
        {"id": "STK-01", "actor": "Cloud Provider", "query": f"{key_vendors[0]} cloud inference serving cost reduction benefit KV cache"},
        {"id": "STK-02", "actor": "Developer", "query": "serving framework developers concern KV cache custom CUDA kernel"}
    ]
    
    for act in actors:
        supp, count = search_pair(act["query"], f"{act['actor']} challenges adoption barrier")
        if supp and supp.get("results"):
            top = supp["results"][0]
            ev_id = f"EV-{act['id']}"
            src_id = f"SRC-{act['id']}"
            tier = classify_tier(top["url"])
            
            new_claims.append({
                "id": act["id"], "perspective": "stakeholder", "tech": "General",
                "statement": f"{act['actor']} views this as critical for cost efficiency.",
                "kind": "fact", "evidence_ids": [ev_id], "counter_evidence_ids": [],
                "counter_searched": True, "status": "ok"
            })
            new_evidence.append({
                "evidence_id": ev_id, "source_id": src_id, "snippet": top["content"][:300]
            })
            new_sources.append({
                "source_id": src_id, "title": top["title"], "publisher": "Web",
                "date": "2024", "url": top["url"], "source_type": "web", "source_tier": tier
            })

    return {
        "stakeholder": {"actors_surveyed": ["Cloud Ops", "Developers"]},
        "claims": new_claims,
        "evidence": new_evidence,
        "sources": new_sources
    }
```

---

## 🧪 6. 독립 단위 테스트 (`tests/test_research.py`)

```python
"""tests/test_research.py"""
from tests.mock_data import MOCK_STATE
from src.research.market import market_research_node
from src.research.stakeholder import stakeholder_research_node

def test_research_nodes():
    # 1. Market Node Test
    m_res = market_research_node(MOCK_STATE)
    assert "market" in m_res
    assert len(m_res["claims"]) > 0
    
    # 2. Stakeholder Node Test (Chaining 연결 테스트)
    state_after_market = {**MOCK_STATE, **m_res}
    s_res = stakeholder_research_node(state_after_market)
    assert "stakeholder" in s_res
    assert len(s_res["claims"]) > 0
    print("✅ Web Research Nodes Unit Test Passed!")

if __name__ == "__main__":
    test_research_nodes()
```

---

## 7. 설계서 Checklist (이 파일에서만 체크)

Phase 2에 [`design_checklist.md`](design_checklist.md) / [`common.md`](common.md) / `src/state.py` / `src/graph.py` / `src/rag/`를 수정하지 마세요.

### 충돌 방지 — 담당 C만 수정
- `src/research/**`, `tests/test_research.py` 만
- 반환 키: `market`(market 노드), `stakeholder`(stakeholder 노드), `claims`, `evidence`, `sources`. `tech_sw`/`domain`/`audit`/`retry_count`/`trl`/`report` 금지
- Claim ID: `MKT-01`~`MKT-08`, `STK-01`~`STK-04`, `MAT-A01`~`MAT-A02` 만. `DOM-*`/`MAT-R*` 생성 금지
- Source: `SRC-MKT-*`, `SRC-STK-*`. `SRC-PAPER-*` 금지
- `tech` 필드는 `"KIVI"` 또는 `"CXL-PNM"`. 계열명은 `market` 딕셔너리와 `selected.families`만. `"General"` 금지
- `retry_count`를 반환하지 않음 (D 전용)
- 재실행 시 자기 `target_agent`(market 또는 stakeholder) 이슈의 Claim만 패치. 상대 노드 Claim을 통째로 재생성하지 않음
- stakeholder는 `state["market"]`을 읽기만 하고 `market` 키를 덮어쓰지 않음

### 공통 (설계 1.4 · 3.7 · 3.8) — C 적용 범위: 검색 쿼리·Claim·statement
- [ ] 조사 statement/프롬프트에 우열 판정·승자·추천을 넣지 않았다
- [ ] 시장 규모·미래 예측·근거 없는 추측을 생성하지 않는다 (3.4)
- [ ] Claim `kind`/`status`가 설계 3.7 값만 사용한다
- [ ] 벤더 홍보 수치는 `vendor_claim`. 논문 시뮬레이션 수치를 웹에서 가져와 `fact`로 바꾸지 않는다
- [ ] 출처 없는 항목은 `insufficient`. 추측으로 채우지 않는다
- [ ] `OverallState`에 없는 키를 반환하지 않는다
- [ ] 수치 인용 시 실측/시뮬레이션·출처 맥락을 병기한다
- [ ] 온디바이스를 평가 도메인으로 쓰지 않는다

### 검색 규칙 (4.5 · 3.8)
- [ ] Tavily. URL·날짜를 Source에 저장
- [ ] 페르소나/가상 이해관계자 생성 금지. 공개 자료만
- [ ] 항목마다 지지 쿼리 + 반대 쿼리. 없으면 `counter-evidence not found`, 상태는 `ok`
- [ ] `counter_searched=True` = 쿼리 실행함 (결과 유무 무관)
- [ ] Tier T1~T4. T4 단독 근거 금지
- [ ] 인접 시장(HBM 등) 인용 시 인접 시장임을 명시

### 시장성 (3.4 · 3.2)
- [ ] 평가 단위 = 기술 계열 (KV 양자화 / CXL 메모리 확장)
- [ ] 4지표: adoption / deployment / ecosystem / barriers
- [ ] `market`에 stakeholder가 읽을 `key_vendors`(또는 동등 키워드) 포함
- [ ] MAT 채택 `MAT-A*`(TRL 5-9). 연구 MAT(`MAT-R*`) 만들지 않음

### 이해관계자 (3.5)
- [ ] `state["market"]`으로 쿼리 구체화
- [ ] Actor 4명: 서빙 운영자 / 개발자 / End User / 공급자
- [ ] Actor마다 Benefit / Concern / Adoption Barrier / Evidence
- [ ] End User는 지연·품질 간접 근거. 없으면 `insufficient`
