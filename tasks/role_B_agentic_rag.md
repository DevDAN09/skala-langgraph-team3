# 📋 [담당 B] Agentic RAG & 임베딩 벤치마크 구현 가이드

> **담당자**: 담당 B  
> **핵심 임무**: 오픈소스 임베딩 3종 Hit@5/MRR 실측 벤치마크 수행, 논문 코퍼스 청킹(400~500토큰) 및 FAISS 인덱싱, `paper_analysis` 노드(Agentic RAG: 충분성 게이트 + Query Rewrite) 구현  
> ⚠️ **필독 공통 개발 룰**: 코딩 시작 전 [`tasks/common.md`](common.md)의 LangGraph 안티패턴(1.2.12) 및 TDD 가이드를 반드시 숙지하세요!  
> ✅ **설계서 대조 체크리스트**: 이 문서 [§7](#7-설계서-checklist-이-파일에서만-체크) (공통 항목 포함). 인덱스는 [`design_checklist.md`](design_checklist.md)

---

## 🎯 1. 개발 목표 및 마일스톤 (10:00 ~ 14:00)
- **10:00 ~ 10:30 (Phase 1)**: 환경 셋업, `tests/test_rag.py` 실행 및 `data/eval_queries.json` 20개 질의 셋 확인
- **10:30 ~ 11:30 (Phase 2-A)**: `benchmark.py` 실행으로 임베딩 모델(Hit@5 ≥ 0.8) 확정 & `indexer.py`로 FAISS 인덱스 사전 빌드
- **11:30 ~ 12:30 (Phase 2-B)**: `paper_analysis` 노드 구현(충분성 게이트, Query Rewrite) 및 `tests/test_rag.py` 통과 달성
- **12:30 ~ 14:00 (Phase 3~5)**: 메인 그래프 결합 및 최종 보고서 원문 인용 데이터 정합성 검수

---

## 📁 2. 전담 파일 목록
- `src/rag/benchmark.py`: BAAI/bge-small-en-v1.5 vs intfloat/e5-small-v2 실측 스크립트
- `src/rag/indexer.py`: PyPDF 청킹(헤더 기준, 400~500토큰, overlap 15%) 및 FAISS 인덱스 빌더
- `src/rag/agentic_rag.py`: `paper_analysis_node` (하위 질의 ➔ FAISS ➔ 충분성 게이트 ➔ Rewrite)
- `tests/test_rag.py`: RAG 파이프라인 단독 단위 테스트

---

## 🔬 3. 임베딩 모델 실측 벤치마크 (`src/rag/benchmark.py`)

리더보드 점수 대신, 도메인 특화 어휘(CXL, PNM, asymmetric quantization 등)가 포함된 20개 질의에 대해 실측 평가합니다.

```python
"""src/rag/benchmark.py"""
from sentence_transformers import SentenceTransformer
import numpy as np

MODELS = ["BAAI/bge-small-en-v1.5", "intfloat/e5-small-v2"]

def evaluate_embedding(model_name: str, test_dataset: list[dict]):
    """Hit@5 및 MRR 계산"""
    model = SentenceTransformer(model_name)
    hits_at_5 = []
    reciprocal_ranks = []
    
    # 질의 임베딩 및 코퍼스 유사도 측정
    for item in test_dataset:
        q_emb = model.encode(item["query"])
        doc_embs = model.encode(item["corpus"])
        scores = np.dot(doc_embs, q_emb)
        top5_indices = np.argsort(scores)[::-1][:5]
        
        target_idx = item["target_index"]
        # Hit@5
        hits_at_5.append(1 if target_idx in top5_indices else 0)
        # MRR
        ranks = np.where(np.argsort(scores)[::-1] == target_idx)[0]
        reciprocal_ranks.append(1.0 / (ranks[0] + 1) if len(ranks) > 0 else 0)
        
    print(f"[{model_name}] Hit@5: {np.mean(hits_at_5):.3f}, MRR: {np.mean(reciprocal_ranks):.3f}")
    return np.mean(hits_at_5)
```

---

## 📄 4. 청킹 및 FAISS 인덱싱 (`src/rag/indexer.py`)

- **청크 크기**: 400~500 토큰 (임베딩 한도 512에 맞춤)
- **중첩(Overlap)**: 약 15% (문맥 연속성)
- **메타데이터 보존**: `tech` (KIVI / CXL-PNM), `section`, `page`

```python
"""src/rag/indexer.py"""
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings

def build_faiss_index(pdf_paths: dict[str, str], embedding_model_name: str, save_dir: str):
    documents = []
    for tech, path in pdf_paths.items():
        loader = PyPDFLoader(path)
        pages = loader.load()
        for p in pages:
            p.metadata["tech"] = tech  # 기술 간 혼입 방지 필터용
        documents.extend(pages)
        
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1200,  # 글자 수 기준 약 400~500 토큰
        chunk_overlap=180,
        separators=["\n## ", "\n### ", "\n\n", "\n", " "]
    )
    chunks = splitter.split_documents(documents)
    
    embeddings = HuggingFaceEmbeddings(model_name=embedding_model_name)
    vector_db = FAISS.from_documents(chunks, embeddings)
    vector_db.save_local(save_dir)
    print(f"FAISS index saved to {save_dir} with {len(chunks)} chunks.")
    return vector_db
```

---

## 🤖 5. Agentic RAG 노드 구현 (`src/rag/agentic_rag.py`)

원문 분석 노드는 **충분성 게이트(Sufficiency Gate)**를 거쳐 부족 시 Query Rewrite(최대 2회)를 수행합니다.

```python
"""src/rag/agentic_rag.py"""
from src.state import OverallState, Claim, Evidence, Source
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI

def paper_analysis_node(state: OverallState) -> dict:
    """원문 분석 노드 함수"""
    audit_issues = state.get("audit", {}).get("issues", [])
    paper_issues = [i for i in audit_issues if i["target_agent"] == "paper"]
    
    embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")
    db = FAISS.load_local("data/faiss_index", embeddings, allow_dangerous_deserialization=True)
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    
    new_claims: list[Claim] = []
    new_evidence: list[Evidence] = []
    new_sources: list[Source] = []
    
    # 6대 축 질의 정의 (메모리, 대역폭, 처리량, 정확도, 인프라, 복잡도)
    eval_axes = [
        {"id": "DOM-01", "tech": "KIVI", "query": "What is the KV cache memory footprint reduction in KIVI?"},
        {"id": "DOM-02", "tech": "CXL-PNM", "query": "How does CXL-PNM solve KV cache capacity and recall overhead?"}
    ]
    
    for axis in eval_axes:
        query = axis["query"]
        retries = 0
        is_sufficient = False
        selected_chunk = None
        
        while retries < 2 and not is_sufficient:
            # 1. FAISS 검색 (tech 필터링 적용)
            results = db.similarity_search(query, k=5, filter={"tech": axis["tech"]})
            context = "\n".join([doc.page_content for doc in results])
            
            # 2. 충분성 게이트 검사 (LLM Judge)
            check_prompt = f"Does the following context answer the question: '{query}'?\nContext: {context}\nAnswer 'YES' or 'NO':"
            res = llm.invoke(check_prompt).content.strip()
            
            if "YES" in res:
                is_sufficient = True
                selected_chunk = results[0]
            else:
                retries += 1
                rewrite_prompt = f"Rewrite this search query with technical synonyms: '{query}'"
                query = llm.invoke(rewrite_prompt).content.strip()
        
        # 3. Claim 및 Evidence 객체 생성
        if is_sufficient and selected_chunk:
            ev_id = f"EV-{axis['id']}"
            src_id = f"SRC-{axis['tech']}"
            
            # 한 문장 statement 추출
            stmt = llm.invoke(f"Extract one concise factual statement answering '{axis['query']}' from:\n{selected_chunk.page_content}").content.strip()
            
            new_claims.append({
                "id": axis["id"], "perspective": "domain", "tech": axis["tech"],
                "statement": stmt, "kind": "simulation" if axis["tech"] == "CXL-PNM" else "fact",
                "evidence_ids": [ev_id], "counter_evidence_ids": [],
                "counter_searched": False, "status": "ok"
            })
            new_evidence.append({
                "evidence_id": ev_id, "source_id": src_id,
                "snippet": selected_chunk.page_content[:300]
            })
            new_sources.append({
                "source_id": src_id, "title": f"{axis['tech']} Paper",
                "publisher": "Academic Paper", "date": "2024",
                "url": "local_pdf", "source_type": "paper", "source_tier": "T1"
            })
        else:
            # 3회 시도 후에도 미발견 시 미확인 슬롯 격리
            new_claims.append({
                "id": axis["id"], "perspective": "domain", "tech": axis["tech"],
                "statement": "", "kind": "fact",
                "evidence_ids": [], "counter_evidence_ids": [],
                "counter_searched": False, "status": "insufficient"
            })

    return {
        "tech_sw": {"name": "KIVI"},
        "tech_hw": {"name": "CXL-PNM"},
        "domain": {"status": "extracted"},
        "claims": new_claims,
        "evidence": new_evidence,
        "sources": new_sources
    }
```

---

## 🧪 6. 독립 단위 테스트 (`tests/test_rag.py`)

다른 팀원의 모듈 없이 혼자 즉시 테스트할 수 있는 코드입니다.

```python
"""tests/test_rag.py"""
from tests.mock_data import MOCK_STATE
from src.rag.agentic_rag import paper_analysis_node

def test_paper_analysis_node():
    result = paper_analysis_node(MOCK_STATE)
    assert "claims" in result
    assert "evidence" in result
    assert len(result["claims"]) > 0
    print("✅ Paper Analysis Node Unit Test Passed!")

if __name__ == "__main__":
    test_paper_analysis_node()
```

---

## 7. 설계서 Checklist (이 파일에서만 체크)

Phase 2에 [`design_checklist.md`](design_checklist.md) / [`common.md`](common.md) / `README.md` / `src/state.py` / `src/graph.py`를 수정하지 마세요.

### 충돌 방지 — 담당 B만 수정
- `src/rag/**`, `tests/test_rag.py`, `data/papers/`, `data/faiss_index/`, `data/eval_queries.json`
- `src/config.py`의 **`EMBEDDING_MODEL` 한 줄만** (벤치 확정 후). LLM 모델명·API 키는 건드리지 않음
- 반환 키: `tech_sw`, `tech_hw`, `domain`, `claims`, `evidence`, `sources` 만. `market`/`audit`/`retry_count`/`trl`/`report` 금지
- Claim ID: `DOM-01`~`DOM-12`, `MAT-R01`~`MAT-R02` 만. `MKT-*`/`STK-*`/`MAT-A*` 생성 금지
- Source: `SRC-PAPER-KIVI`, `SRC-PAPER-CXL-PNM` (또는 `SRC-DOM-*`). `SRC-MKT-*` 금지
- README Retrieval은 쓰지 않음. 실측 숫자는 벤치 로그로 남기고 Phase 3에 A가 이관
- 재실행 시 `target_agent=paper` 이슈의 자기 Claim만 upsert. 다른 관점 Claim을 새 리스트로 갈아끼우지 않음

### 공통 (설계 1.4 · 3.7 · 3.8) — B 적용 범위: rag 노드·프롬프트·Claim
- [ ] paper 프롬프트/statement에 우열 판정·승자·추천을 넣지 않았다
- [ ] 원문에 없는 미래 전망·추측 수치를 생성하지 않는다
- [ ] Claim `kind`/`status`가 설계 3.7 값만 사용한다
- [ ] CXL-PNM 논문 수치는 `kind=simulation` (2.4)
- [ ] 검색 실패 Claim은 `statement=""`, `status=insufficient`. 이를 `ok`로 포장하지 않는다
- [ ] `OverallState`에 없는 키를 반환하지 않는다
- [ ] 인용 수치에 모델 크기 / 문맥 길이 / 실측·시뮬레이션을 병기한다 (3.6)
- [ ] 온디바이스를 도메인 평가 축으로 넣지 않는다

### 코퍼스 · 인덱스 (4.2)
- [ ] KIVI + CXL-PNM PDF만. 섹션 헤더 청킹 400~500토큰, overlap ~15%, 캡션 보존
- [ ] 메타데이터 `tech`/`section`/`page`. 검색 top-k 5 + `tech` 필터. 질의 영어
- [ ] FAISS 로컬 인덱스 + `indexer.py` 빌드 스크립트

### 임베딩 실측 (4.4 / 부록 C)
- [ ] bge-small / e5-small 실측 (미달 시만 bge-m3). 20질의, Hit@5·MRR
- [ ] Hit@5 ≥ 0.8 중 가장 가벼운 모델 채택 후 `EMBEDDING_MODEL`만 갱신

### Agentic RAG 루프 (4.3)
- [ ] 영어 질의 → top-5 tech 필터 → 충분성 게이트 → Rewrite ≤2 (총 3회)
- [ ] snippet = 검색된 원문 청크. fallback을 `status=ok`로 넣지 않음
- [ ] 실패: `corpus 내 근거 미확인`. 원문에 없다고 단정 금지. 한 축 실패해도 나머지 축 계속

### 원문 산출 (4.1 · 3.6)
- [ ] 메커니즘·수치·한계·실험 조건 + 도메인 6대 축
- [ ] MAT 연구 Claim만 (`MAT-R*`, TRL 3-4). 채택 MAT 금지
- [ ] `perspective=domain` (MAT 연구는 `maturity` 가능)
- [ ] R1: paper는 웹 재검색하지 않음. 없으면 `insufficient`
