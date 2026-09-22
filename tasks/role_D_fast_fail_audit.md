# 📋 [담당 D] 2단계 Fast-Fail 검증 엔진 구현 가이드

> **담당자**: 담당 D  
> **핵심 임무**: 1단계 정적 규칙 검사기(Rule Fast-Fail: R1~R4, 0ms), 2단계 R5 LLM-as-a-Judge(문장 일치성 정밀 심사), `evidence_audit` 노드 및 `AuditIssue` 구조화 피드백 생성  
> ⚠️ **필독 공통 개발 룰**: 코딩 시작 전 [`tasks/common.md`](common.md)의 LangGraph 안티패턴(1.2.12) 및 TDD 가이드를 반드시 숙지하세요!  
> ✅ **설계서 대조 체크리스트**: 이 문서 [§7](#7-설계서-checklist-이-파일에서만-체크) (공통 항목 포함). 인덱스는 [`design_checklist.md`](design_checklist.md)

---

## 🎯 1. 개발 목표 및 마일스톤 (10:00 ~ 14:00)
- **10:00 ~ 10:30 (Phase 1)**: 환경 셋업, `tests/test_audit.py` 실행 및 1단계 4대 규칙(R1~R4) 점검
- **10:30 ~ 11:30 (Phase 2-A)**: `rules.py` 1단계 정적 검사기(R1 출처, R2 T4단독, R3 반대쿼리, R4 시뮬레이션) 완성
- **11:30 ~ 12:30 (Phase 2-B)**: `judge.py` 2단계 R5 LLM Judge 프롬프트 및 `auditor.py` 연동 완료 & `tests/test_audit.py` 통과
- **12:30 ~ 14:00 (Phase 3~5)**: 메인 그래프 결합 및 재실행 루프(Cascade Chaining) 표적 피드백 검증

---

## 📁 2. 전담 파일 목록
- `src/audit/rules.py`: 1단계 정적 룰 검사 (R1: 무출처, R2: T4 단독, R3: 반대쿼리 누락, R4: 수치 왜곡)
- `src/audit/judge.py`: 2단계 R5 LLM Judge (Claim statement와 Evidence snippet 일치 판정)
- `src/audit/auditor.py`: `evidence_audit_node` (이슈 취합, 상태 업데이트, `retry_count` 증가)
- `tests/test_audit.py`: 고의 위반 데이터를 통한 단위 테스트

---

## ⚡ 3. 1단계: 정적 규칙 Fast-Fail (`src/audit/rules.py`)

LLM을 부르지 않고 0ms 안에 파이썬 로직만으로 형식적 결함을 즉시 걸러냅니다.

```python
"""src/audit/rules.py"""
from src.state import Claim, Source, AuditIssue

def run_static_rules(claims: list[Claim], sources: list[Source]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    source_tier_map = {s["source_id"]: s.get("source_tier", "T4") for s in sources}
    
    for c in claims:
        # R1: fact인데 출처(evidence_ids)가 비어있는 경우
        if c["kind"] == "fact" and not c.get("evidence_ids"):
            issues.append({
                "claim_id": c["id"], "rule": "R1", "issue": "Fact에 근거 출처 없음",
                "target_agent": "market" if c["perspective"] == "market" else "paper",
                "action": "search_evidence"
            })
            continue

        # R2: 출처가 T4(개인 블로그/커뮤니티)만 단독으로 존재하는 경우
        tiers = [source_tier_map.get(eid) for eid in c.get("evidence_ids", [])]
        if tiers and all(t == "T4" for t in tiers):
            issues.append({
                "claim_id": c["id"], "rule": "R2", "issue": "T4 블로그 단독 인용 금지 위반",
                "target_agent": "stakeholder" if c["perspective"] == "stakeholder" else "market",
                "action": "search_evidence"
            })
            continue

        # R3: 외부 조사인데 반대 쿼리를 수행하지 않은 경우
        if c["perspective"] in ["market", "stakeholder"] and not c.get("counter_searched"):
            issues.append({
                "claim_id": c["id"], "rule": "R3", "issue": "반대 쿼리 미수행 (확증편향 방지 위반)",
                "target_agent": c["perspective"],
                "action": "search_counter_evidence"
            })
            continue

        # R4: CXL-PNM 시뮬레이션 수치인데 kind를 fact로 기재한 경우
        if c["tech"] == "CXL-PNM" and c["kind"] == "fact" and "simulation" not in c["statement"].lower():
            issues.append({
                "claim_id": c["id"], "rule": "R4", "issue": "시뮬레이션 수치 왜곡 표기",
                "target_agent": "paper",
                "action": "relabel"
            })
            
    return issues
```

---

## ⚖️ 4. 2단계: R5 LLM-as-a-Judge (`src/audit/judge.py`)

1단계를 무사히 통과한 Claim에 한해서만 LLM을 호출하여 스니펫과 문장의 사실 일치성을 판정합니다.

```python
"""src/audit/judge.py"""
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from src.state import Claim, Evidence, AuditIssue

class JudgeDecision(BaseModel):
    is_grounded: bool = Field(description="주장 문장이 근거 스니펫에 정확히 기반하고 있는가")
    reason: str = Field(description="판정 이유")

judge_prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a strict academic fact-checker. Determine whether the statement is completely supported by the evidence snippet."),
    ("human", "Statement: {statement}\nEvidence Snippet: {snippet}\nVerify factual grounding:")
])

def run_llm_judge(claims: list[Claim], evidence_list: list[Evidence]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    ev_map = {e["evidence_id"]: e["snippet"] for e in evidence_list}
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(JudgeDecision)
    
    for c in claims:
        # 이미 1단계에서 걸러졌거나 슬롯이 빈 경우 스킵
        if not c.get("statement") or not c.get("evidence_ids"):
            continue
            
        snippet = ev_map.get(c["evidence_ids"][0], "")
        if not snippet:
            continue
            
        # LLM 판정 수행
        result: JudgeDecision = llm.invoke(judge_prompt.format(statement=c["statement"], snippet=snippet))
        if not result.is_grounded:
            issues.append({
                "claim_id": c["id"], "rule": "R5",
                "issue": f"스니펫과 사실 불일치: {result.reason}",
                "target_agent": "paper" if c["perspective"] == "domain" else "market",
                "action": "re_extract"
            })
            
    return issues
```

---

## 🛡️ 5. 검증 노드 조립 (`src/audit/auditor.py`)

```python
"""src/audit/auditor.py"""
from src.state import OverallState, Audit
from src.audit.rules import run_static_rules
from src.audit.judge import run_llm_judge

def evidence_audit_node(state: OverallState) -> dict:
    claims = state.get("claims", [])
    evidence = state.get("evidence", [])
    sources = state.get("sources", [])
    retry_count = dict(state.get("retry_count", {"paper": 0, "market": 0, "stakeholder": 0}))
    
    # 1단계: 0ms 정적 룰 검사
    stage1_issues = run_static_rules(claims, sources)
    
    # 1단계에서 위반이 감지되면 LLM 호출 없이 즉시 Fast-Fail!
    if stage1_issues:
        for issue in stage1_issues:
            agent = issue["target_agent"]
            retry_count[agent] = retry_count.get(agent, 0) + 1
        return {
            "audit": {"issues": stage1_issues},
            "retry_count": retry_count
        }
        
    # 2단계: 1단계 통과 Claim 대상 심층 LLM Judge
    stage2_issues = run_llm_judge(claims, evidence)
    for issue in stage2_issues:
        agent = issue["target_agent"]
        retry_count[agent] = retry_count.get(agent, 0) + 1
        
    return {
        "audit": {"issues": stage2_issues},
        "retry_count": retry_count
    }
```

---

## 🧪 6. 독립 단위 테스트 (`tests/test_audit.py`)

```python
"""tests/test_audit.py"""
from tests.mock_data import MOCK_STATE
from src.audit.auditor import evidence_audit_node

def test_fast_fail_detection():
    # 고의로 R1 위반 데이터 주입 (출처 없는 fact)
    bad_state = dict(MOCK_STATE)
    bad_state["claims"] = [{
        "id": "BAD-01", "perspective": "market", "tech": "KIVI",
        "statement": "False fact without source", "kind": "fact",
        "evidence_ids": [], "counter_searched": True, "status": "ok"
    }]
    
    result = evidence_audit_node(bad_state)
    assert len(result["audit"]["issues"]) > 0
    assert result["audit"]["issues"][0]["rule"] == "R1"
    print("✅ Fast-Fail Rule R1 Detection Passed!")

if __name__ == "__main__":
    test_fast_fail_detection()
```

---

## 7. 설계서 Checklist (이 파일에서만 체크)

Phase 2에 [`design_checklist.md`](design_checklist.md) / [`common.md`](common.md) / `src/state.py` / `src/graph.py` / 조사 모듈을 수정하지 마세요.

### 충돌 방지 — 담당 D만 수정
- `src/audit/**`, `tests/test_audit.py` 만
- 반환 키: `audit`, `retry_count`, 그리고 **기존 Claim의 `status` 패치용 `claims`만**. `tech_sw`/`market`/`trl`/`report` 금지
- **신규 Claim / Evidence / Source ID를 만들지 않음.** 덮어쓰면 B/C 데이터가 사라진다
- status 패치 시 원래 `id`를 유지하고 statement/evidence_ids를 지우지 않음 (`flagged`/`insufficient`/`rejected`만)
- `retry_count`는 `dict(...)`로 복사 후 증가해서 반환. in-place 뮤테이션 금지
- 라우터(graph.py)를 D가 수정하지 않음. 한도 2회·Cascade는 A 담당
- R1 paper 재검색 안 함 = **이슈만 만들고 paper 노드를 호출하지 않음**. 웹 검색 코드를 audit에 넣지 않음

### 공통 (설계 1.4 · 3.7 · 3.8) — D 적용 범위: 규칙·Judge·status
- [ ] Judge 프롬프트에 우열 판정·승자 언어를 넣지 않았다
- [ ] 검증 노드가 추측 statement를 생성하지 않는다
- [ ] `kind`/`status` 허용값만 사용해 패치한다 (3.7)
- [ ] R4: CXL-PNM·벤더 수치를 `fact`로 둔 Claim을 `relabel` 대상으로 잡는다
- [ ] 공란 `insufficient` Claim을 R1 위반으로 처리하지 않는다 (구 R5 공백 검사 폐지)
- [ ] `OverallState`에 없는 키를 반환하지 않는다
- [ ] Judge가 수치를 고치거나 실험 조건을 새로 쓰지 않는다
- [ ] 온디바이스를 규칙 축으로 넣지 않는다

### 1단계 (5.3)
- [ ] R1: `kind=fact` & 빈 `evidence_ids` → `search_evidence`. paper는 웹 재검색 없음 → 한도 후 `insufficient`
- [ ] R2: T4 단독 → T1~T3 보강
- [ ] R3: market/stakeholder/MAT채택 & `counter_searched` 아님 → `search_counter_evidence`
- [ ] R4: 시뮬레이션·벤더 수치를 `fact`로 표기 → `relabel`
- [ ] 1단계 위반 시 R5 LLM 호출 없음

### 2단계 R5
- [ ] 1단계 통과 Claim만 statement vs snippet
- [ ] Pydantic Structured Output
- [ ] 불일치 → `re_extract`, 한도 후 `rejected`

### 노드 조립 (5.3 / 5.4)
- [ ] `issues[]` = `{claim_id, rule, issue, target_agent, action}`
- [ ] `target_agent` ∈ {paper, market, stakeholder}
- [ ] `action` ∈ {search_evidence, search_counter_evidence, re_extract, relabel}
- [ ] 위반 시 해당 agent `retry_count` +1
- [ ] 위반 Claim `status=flagged`. 한도 소진 확정은 `insufficient`/`rejected`
- [ ] 통과 시 `issues=[]`
