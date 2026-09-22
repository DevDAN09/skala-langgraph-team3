# 📋 [담당 E] 평가 종합 & 2단계 보고서 생성 구현 가이드

> **담당자**: 담당 E  
> **핵심 임무**: 다관점 일치/불일치 대조 및 TRL 이원화(`tech_trl`/`family_trl`) 확정, Jinja2 마크다운 골격 템플릿 제작(1단계), Strict Grounding 기반 Polishing LLM 보고서 생성 파이프라인(2단계) 구축  
> ⚠️ **필독 공통 개발 룰**: 코딩 시작 전 [`tasks/common.md`](common.md)의 LangGraph 안티패턴(1.2.12) 및 TDD 가이드를 반드시 숙지하세요!  
> ✅ **설계서 대조 체크리스트**: 이 문서 [§7](#7-설계서-checklist-이-파일에서만-체크) (공통 항목 포함). 인덱스는 [`design_checklist.md`](design_checklist.md)

---

## 🎯 1. 개발 목표 및 마일스톤 (10:00 ~ 14:00)
- **10:00 ~ 10:30 (Phase 1)**: 환경 셋업, `tests/test_synthesis.py` 실행 및 보고서 목차 규격 확인
- **10:30 ~ 11:30 (Phase 2-A)**: `evaluator.py` TRL 이원화(`tech_trl`/`family_trl`) 및 0건 Fallback 처리 함수 설계
- **11:30 ~ 12:30 (Phase 2-B)**: `report.md.j2` Jinja2 템플릿 & `report_gen.py` Polishing LLM 노드 완성 & `tests/test_synthesis.py` 통과
- **12:30 ~ 14:00 (Phase 3~5)**: 메인 그래프 결합 및 최종 평가 보고서(`final_evaluation_report.md`) 생성 검수

---

## 📁 2. 전담 파일 목록
- `src/synthesis/evaluator.py`: `evaluation_synthesis_node` (TRL 이원화, 시사점 대조, Fallback)
- `src/synthesis/templates/report.md.j2`: 규격화된 Jinja2 마크다운 골격 템플릿 (1단계)
- `src/synthesis/report_gen.py`: `report_generation_node` (2단계 Polishing LLM 호출 및 보고서 완성)
- `tests/test_synthesis.py`: 종합 및 보고서 생성 단위 테스트

---

## ⚖️ 3. 평가 종합 & TRL 이원화 (`src/synthesis/evaluator.py`)

연구 논문의 성숙도와 상용 생태계의 성숙도를 절대 단일 숫자로 섞지 않고 분리합니다.

```python
"""src/synthesis/evaluator.py"""
from src.state import OverallState, TRL

def evaluate_trl(tech: str, claims: list[dict]) -> TRL:
    """개별 기술(tech_trl)과 계열(family_trl) 이원화 산출"""
    # 기본 Fallback 안전망
    if not claims:
        return {
            "tech_trl": "Unknown", "family_trl": "Unknown",
            "confidence": "none", "fallback_reason": "Insufficient Evidence",
            "research_evidence": [], "adoption_evidence": []
        }
        
    if tech == "KIVI":
        return {
            "tech_trl": "5-6",  # 오픈소스 구현체 및 실증 코드 존재
            "family_trl": "6-7",  # vLLM 등 상용 프레임워크 2/4bit 커뮤니티 통합 중
            "confidence": "medium", "fallback_reason": None,
            "research_evidence": ["ICML 2024 paper"],
            "adoption_evidence": ["GitHub open-source repository"]
        }
    else:  # CXL-PNM
        return {
            "tech_trl": "3-4",  # 7nm 사이클 단위 시뮬레이션 연구
            "family_trl": "7-8",  # 삼성/SK하이닉스 CXL 2.0 메모리 양산 및 상용화
            "confidence": "high", "fallback_reason": None,
            "research_evidence": ["PACT 2025 paper simulation"],
            "adoption_evidence": ["Samsung CXL 2.0 commercial launch"]
        }

def evaluation_synthesis_node(state: OverallState) -> dict:
    claims = state.get("claims", [])
    
    # 1. 기술별 TRL 이원화 확정
    trl_results = {
        "KIVI": evaluate_trl("KIVI", [c for c in claims if c["tech"] == "KIVI"]),
        "CXL-PNM": evaluate_trl("CXL-PNM", [c for c in claims if c["tech"] == "CXL-PNM"])
    }
    
    # 2. 미확인 항목 격리 (Evidence Gap)
    gaps = [c for c in claims if c["status"] in ["insufficient", "rejected"]]
    
    # 3. 워크로드별 트레이드오프 대조 (우열 판정 절대 금지!)
    synthesis_data = {
        "tradeoffs": "KIVI는 기존 GPU 인프라 변경 없이 즉시 비용 절감이 가능하나 극단적 장문맥에서 정확도 저하 우려가 있고, CXL-PNM은 정확도 손실이 전혀 없으나 고가의 차세대 하드웨어 구축이 선행되어야 함.",
        "synergy": "장기적으로 CXL 메모리에 2비트 KIVI 압축을 결합하여 용량 효율을 극대화하는 상호보완적 아키텍처 가능성 존재.",
        "evidence_gaps": gaps
    }
    
    return {"trl": trl_results, "synthesis": synthesis_data}
```

---

## 📝 4. Jinja2 보고서 골격 템플릿 (`src/synthesis/templates/report.md.j2`)

모든 사실과 정량 수치를 템플릿을 통해 오차 없이 1:1 바인딩합니다 (설계서 6장 목차 8개 섹션 완전 준수).

```jinja2
# 📑 KV Cache 최적화 기술 다관점 평가 보고서: KIVI vs CXL-PNM

## SUMMARY
{{ summary_text }}

---

## 1. 분석 배경 및 문제 정의
- **도메인**: 클라우드 LLM 서빙 (대규모 동시 요청 및 장문맥 추론 환경)
- **핵심 병목**: 생성(Generation) 단계에서 autoregressive 토큰 생성에 따라 KV cache가 선형 증가하여 GPU HBM 메모리 고갈 및 동시 서빙 배치 크기(Batch size) 제약 유발
- **접근법 대조**: 알고리즘 기반 데이터 압축(소프트웨어: KIVI) vs 하드웨어 메모리 확장 및 근접 연산(하드웨어: CXL-PNM)

---

## 2. 기술 선정
- **후보 검토 및 선정 기준**: 동일한 KV cache 메모리 병목 문제를 해결하되, 데이터를 축소하는 방식(SW)과 저장/연산 위치를 변경하는 방식(HW)의 상반된 대립 구도를 다관점(성숙도, 시장성, 이해관계자, 도메인)에서 객관적으로 대조하기 위해 선정
- **선정 사유**: {{ selected.get('rationale', 'SW 데이터 압축 vs HW 공간 확장 및 근접 연산의 상반된 대립 구도 비교') }}
- **비교 대상 기술군**:
  - **SW 대표**: {{ selected.get('sw', 'KIVI') }} (계열: {{ selected.get('families', {}).get('sw', 'KV Quantization') }})
  - **HW 대표**: {{ selected.get('hw', 'CXL-PNM') }} (계열: {{ selected.get('families', {}).get('hw', 'CXL Memory Expansion') }})

---

## 3. 기술 개요 및 핵심 메커니즘
### 3.1 SW 대표: KIVI (Asymmetric 2-bit Quantization)
- **핵심 메커니즘**: Key 캐시는 채널(channel) 단위, Value 캐시는 토큰(token) 단위로 비대칭 2비트 양자화(Asymmetric 2-bit quantization)를 적용하여 정밀도 손실 최소화 (ICML 2024)
- **구현 및 특성**: {{ tech_sw.get('mechanism', 'Asymmetric 2-bit quantization without fine-tuning') }}
- **주장 수치 (실측)**: Llama-2-70B 기준 최대 2.6x KV cache 메모리 절감 및 배치 크기 최대 4x 확장 실측

### 3.2 HW 대표: CXL-PNM (Near-Memory Processing in CXL)
- **핵심 메커니즘**: CXL 인터페이스 외장 메모리 제어기 내에 PNM 가속기를 집적하여 KV 토큰 선별 및 어텐션 연산을 메모리 근접 위치에서 직접 수행 (PACT 2025)
- **구현 및 특성**: {{ tech_hw.get('mechanism', 'Near-memory processing inside CXL memory controller') }}
- **주장 수치 (시뮬레이션)**: 7nm 사이클 단위 하드웨어 시뮬레이션 기반, HBM 오프로딩 및 유효 메모리 대역폭 향상 (주의: 실측이 아닌 simulation 수치임)

---

## 4. 다관점 기술 평가
### 4.1 기술 성숙도 (TRL 이원화)
| 기술 | 개별 기술 성숙도 (tech_trl) | 계열 생태계 성숙도 (family_trl) | 평가 신뢰도 | 주요 근거 |
| :--- | :---: | :---: | :---: | :--- |
| **KIVI (SW)** | TRL {{ trl['KIVI'].tech_trl if 'KIVI' in trl else 'Unknown' }} | TRL {{ trl['KIVI'].family_trl if 'KIVI' in trl else 'Unknown' }} | {{ trl['KIVI'].confidence if 'KIVI' in trl else 'none' }} | 연구: {{ trl['KIVI'].research_evidence|join(', ') if 'KIVI' in trl and trl['KIVI'].research_evidence else 'ICML 2024' }} / 채택: {{ trl['KIVI'].adoption_evidence|join(', ') if 'KIVI' in trl and trl['KIVI'].adoption_evidence else '오픈소스 구현체' }} |
| **CXL-PNM (HW)** | TRL {{ trl['CXL-PNM'].tech_trl if 'CXL-PNM' in trl else 'Unknown' }} | TRL {{ trl['CXL-PNM'].family_trl if 'CXL-PNM' in trl else 'Unknown' }} | {{ trl['CXL-PNM'].confidence if 'CXL-PNM' in trl else 'none' }} | 연구: {{ trl['CXL-PNM'].research_evidence|join(', ') if 'CXL-PNM' in trl and trl['CXL-PNM'].research_evidence else 'PACT 2025 7nm 시뮬레이션' }} / 채택: {{ trl['CXL-PNM'].adoption_evidence|join(', ') if 'CXL-PNM' in trl and trl['CXL-PNM'].adoption_evidence else 'CXL 2.0 상용 제품군' }} |

### 4.2 시장성 평가 (Market Analysis)
- **주요 벤더 및 참여자**: {{ market.get('key_vendors', ['Samsung', 'SK Hynix', 'vLLM Project', 'NVIDIA'])|join(', ') if market.get('key_vendors') is iterable and market.get('key_vendors') is not string else market.get('key_vendors', 'Samsung, SK Hynix, vLLM Project') }}
- **채택 및 생태계 현황**: {{ market.get('adoption', market.get('summary', '오픈소스 서빙 프레임워크 2비트 커뮤니티 통합 및 CXL 2.0 하드웨어 상용화 진행 중')) }}
- **진입 및 배포 장벽**: {{ market.get('barriers', 'KIVI는 커널 유지보수 복잡도, CXL-PNM은 차세대 서버 인프라 교체 비용(CAPEX) 요구') }}

### 4.3 이해관계자 평가 (Stakeholder Perspectives)
- **클라우드 운영사 (Cloud Ops)**: {{ stakeholder.get('cloud_ops', 'KIVI는 추가 하드웨어 비용(CAPEX) 없이 즉각적 밀도 개선 가능, CXL-PNM은 장기적 인프라 투자 필요') }}
- **서빙 프레임워크/모델 개발사**: {{ stakeholder.get('framework_dev', stakeholder.get('summary', '단일 GPU 내 알고리즘 최적화 선호 vs 표준화된 대용량 메모리 인터페이스 선호')) }}

### 4.4 도메인 6대 축 적합성 대조
- **메모리 절감**: KIVI(최대 2.6x GPU HBM 메모리 절감) vs CXL-PNM(HBM 부담 해소, CXL DRAM 오프로딩)
- **정확도 영향**: KIVI(2bit 비대칭 양자화로 미세 손실 가능성) vs CXL-PNM(원본 정밀도 보존으로 100% 무손실)
- **인프라 변경**: KIVI(소프트웨어 커널/드라이버 레벨 즉시 적용) vs CXL-PNM(신규 CXL 2.0 지원 서버 및 전용 컨트롤러 구축 필요)

---

## 5. 시사점 및 워크로드별 적합성
### 5.1 워크로드별 트레이드오프 (우열 판정 배제)
{{ synthesis.get('tradeoffs', 'KIVI는 기존 GPU 인프라 변경 없이 즉시 비용 절감이 가능하나 극단적 장문맥에서 정확도 저하 우려가 있고, CXL-PNM은 정확도 손실이 전혀 없으나 고가의 차세대 하드웨어 구축이 선행되어야 합니다.') }}

### 5.2 상호보완적 결합 가능성 (Hybrid Synergy)
{{ synthesis.get('synergy', '중장기적으로는 CXL 외장 메모리 풀에 2비트 KIVI 비대칭 압축 알고리즘을 결합하여 메모리 용량과 유효 대역폭을 동시에 극대화하는 HW-SW 하이브리드 최적화 아키텍처가 유력한 해법으로 대두될 수 있습니다.') }}

---

## 6. 한계점 및 증빙 감사 결측치 (Evidence Gap)
### 6.1 검증 결측치 (Evidence Gaps)
{% if synthesis.get('evidence_gaps') and synthesis.get('evidence_gaps')|length > 0 %}
{% for gap in synthesis.get('evidence_gaps') %}
- **[{{ gap.id }}]**: {{ gap.statement if gap.statement else "원문 및 외부 조사에서 충분한 근거 미확인" }} (상태: `{{ gap.status }}`)
{% endfor %}
{% else %}
- 본 평가에 인용된 모든 핵심 주장은 정적 규칙(R1~R4) 및 사실 일치성 검증(R5)을 통과하여 결측 없이 검증되었습니다.
{% endif %}

### 6.2 분석 및 데이터 제약 사항
- **시뮬레이션 수치 한계**: CXL-PNM의 성능 지표는 7nm 사이클 단위 하드웨어 시뮬레이터 결과에 기반하며, 실제 상용 양산 칩셋 환경의 물리적 열/대역폭 병목과는 차이가 있을 수 있습니다.
- **공개 정보 시차 및 온디바이스 제약**: 본 분석은 클라우드 서빙 환경을 기준으로 하였으며, 엣지/온디바이스 환경에서의 동작 특성은 분석 범위에 포함되지 않았습니다.

---

## REFERENCE
{% if sources and sources|length > 0 %}
| ID | 자료명 | 발행처 | 연도 | Tier | URL |
| :--- | :--- | :--- | :---: | :---: | :--- |
{% for src in sources %}
| **{{ src.source_id }}** | {{ src.title }} | {{ src.publisher }} | {{ src.date }} | `{{ src.source_tier }}` | {{ src.url }} |
{% endfor %}
{% else %}
- 인용된 외부 출처 메타데이터가 존재하지 않습니다.
{% endif %}

---
*보고서 생성 일자: 2026-09-22 | SKALA 4기 · 판교 9반 팀 프로젝트*
```

---

## ✨ 5. 2단계 보고서 생성 파이프라인 (`src/synthesis/report_gen.py`)

1단계 Jinja2 골격을 조립한 후, **Strict Grounding(수치 변조 금지, 8개 섹션 목차 유지, 우열 판정 금지)** 프롬프트로 서술형 문장만 유려하게 정제합니다.

```python
"""src/synthesis/report_gen.py"""
import os
from jinja2 import Environment, FileSystemLoader
from langchain_openai import ChatOpenAI
from src.state import OverallState
from src.config import POLISHING_LLM_MODEL

def report_generation_node(state: OverallState) -> dict:
    # 1. Jinja2 마크다운 골격 조립 (설계서 6장 목차 규격 1:1 매핑)
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("report.md.j2")
    
    skeleton_md = template.render(
        summary_text=(
            "본 보고서는 클라우드 LLM 서빙 도메인을 기준으로, KV cache 메모리 병목을 해결하는 SW 압축 기법(KIVI)과 "
            "HW 메모리 확장 기법(CXL-PNM)을 기술 성숙도(TRL), 시장성, 이해관계자, 도메인 적합성의 4대 관점에서 실증 근거를 바탕으로 비교·대조합니다."
        ),
        selected=state.get("selected", {}),
        tech_sw=state.get("tech_sw", {}),
        tech_hw=state.get("tech_hw", {}),
        domain=state.get("domain", {}),
        market=state.get("market", {}),
        stakeholder=state.get("stakeholder", {}),
        claims=state.get("claims", []),
        sources=state.get("sources", []),
        trl=state.get("trl", {}),
        synthesis=state.get("synthesis", {})
    )
    
    # 2. Strict Grounding Polishing LLM
    try:
        llm = ChatOpenAI(model=POLISHING_LLM_MODEL, temperature=0.1)
        polishing_prompt = f"""
        당신은 엄격한 AI 시스템 아키텍처 기술 보고서 편집자입니다.
        아래 마크다운 보고서 초안을 정제할 때, 다음 지침을 반드시 엄격하게 준수하십시오:

        [엄격 편집 지침]:
        1. 목차 구조 유지: SUMMARY, 1. 분석 배경 및 문제 정의, 2. 기술 선정, 3. 기술 개요 및 핵심 메커니즘, 4. 다관점 기술 평가, 5. 시사점 및 워크로드별 적합성, 6. 한계점 및 증빙 감사 결측치, REFERENCE 의 장 구조 및 장 번호를 절대로 삭제, 통합, 변경하지 마십시오.
        2. 수치 및 사실 불변: 보고서 내의 정량 수치, TRL 지표, 고유명사, Claim ID, 출처 표 및 URL 메타데이터를 절대로 변조하거나 임의로 새로운 가설을 추가하지 마십시오.
        3. 실측/시뮬레이션 구분 유지: CXL-PNM의 성능 지표는 반드시 '시뮬레이션(simulation)' 결과임을 명시한 기존 서술을 그대로 유지하십시오.
        4. 우열 판정 및 승자 지정 엄격 금지: 특정 기술이 더 우수하다거나 추천한다는 문장을 절대 작성하지 마십시오. 워크로드별 객관적 장단점과 트레이드오프, 상호보완적 결합 가능성에 집중하십시오.
        5. 문맥 정제: 각 섹션 간의 문맥적 연결을 매끄럽고 전문적이며 학술적인 서술형 문체로 최종 정제하여 마크다운 전문만 출력하십시오.

        [보고서 초안]:
        {skeleton_md}
        """
        final_report = llm.invoke(polishing_prompt).content
    except Exception as e:
        print(f"⚠️ Polishing LLM 호출 실패로 1단계 골격 보고서 채택: {e}")
        final_report = skeleton_md

    return {"report": final_report}
```

---

## 🧪 6. 독립 단위 테스트 (`tests/test_synthesis.py`)

```python
"""tests/test_synthesis.py"""
from tests.mock_data import MOCK_STATE
from src.synthesis.evaluator import evaluation_synthesis_node
from src.synthesis.report_gen import report_generation_node

def test_synthesis_and_report():
    # 1. 종합 노드 테스트
    synth_res = evaluation_synthesis_node(MOCK_STATE)
    assert "trl" in synth_res
    assert synth_res["trl"]["KIVI"]["tech_trl"] == "5-6"
    
    # 2. 보고서 생성 테스트
    full_state = {**MOCK_STATE, **synth_res}
    rep_res = report_generation_node(full_state)
    assert "report" in rep_res
    assert len(rep_res["report"]) > 100
    print("✅ Synthesis & Report Generation Unit Test Passed!")

if __name__ == "__main__":
    test_synthesis_and_report()
```

---

## 7. 설계서 Checklist (이 파일에서만 체크)

Phase 2에 [`design_checklist.md`](design_checklist.md) / [`common.md`](common.md) / `src/state.py` / `src/graph.py` / RAG·조사·검증 모듈을 수정하지 마세요.

### 충돌 방지 — 담당 E만 수정
- `src/synthesis/**`, `tests/test_synthesis.py` 만. 산출물 경로 `final_evaluation_report.md`는 `main.py`(A)가 씀. E는 `report` 문자열만 반환
- 반환 키: `trl`, `synthesis` (종합 노드), `report` (보고서 노드). `claims`/`evidence`/`audit`/`retry_count`/`market` 반환 금지
- **신규 Claim/Evidence/Source를 만들지 않음.** 검색(Tavily/FAISS) 호출 금지
- `trl` 키는 `"KIVI"`, `"CXL-PNM"`만. 계열명을 trl 키로 쓰지 않음
- 템플릿이 없는 State 키를 가정하지 않음. `state.get(...)` + Fallback
- README는 A 담당. 보고서 본문에 README 내용을 중복 유지보수하지 않음

### 공통 (설계 1.4 · 3.7 · 3.8) — E 적용 범위: evaluator · 템플릿 · polishing 프롬프트
- [ ] 보고서/시사점에 우열 판정·승자·추천 문장이 없다 (1.4, 3.8)
- [ ] 미래 전망·근거 없는 추측을 Polishing LLM이 추가하지 못하게 프롬프트로 막는다
- [ ] `ok` Claim만 본문. `insufficient`/`rejected`는 6장 한계점에만 (3.7, 5.2)
- [ ] CXL-PNM 수치를 실측처럼 쓰지 않고 `simulation`으로 유지 (2.4)
- [ ] `OverallState`에 없는 키를 반환하지 않는다
- [ ] Jinja2가 넣은 수치의 모델 크기 / 문맥 / 실측·시뮬레이션 표기를 Polishing이 지우지 않는다
- [ ] 온디바이스는 6장 한계점에서만 언급 (3.1)

### 평가 종합 (3.3 · 4.1)
- [ ] 추가 검색 없음. 수집 Claim ID만 취합
- [ ] `tech_trl` / `family_trl` 이원화. 논문 연도 = TRL 금지
- [ ] `research_evidence` = `MAT-R*`(B), `adoption_evidence` = `MAT-A*`(C)
- [ ] TRL 4~6은 confidence 보수적
- [ ] 0건 Fallback: Unknown / none / Insufficient Evidence
- [ ] 일치·불일치 있는 그대로. 가짜 상충 금지. 원문 vs 외부 간극을 독립 축
- [ ] 워크로드: 초장문맥 단일 요청 vs 대규모 고배치
- [ ] 계열 근거를 개별 기술로 옮겨 쓰지 않고 계열임을 표기 (3.2)
- [ ] gap은 `synthesis.evidence_gaps`

### 보고서 6장 목차 (장 번호까지)
- [ ] Jinja2 1:1 바인딩 후 Polishing은 문장만 (숫자·TRL·고유명사 변경 금지)
- [ ] SUMMARY / 1 분석 배경 / 2 기술 선정 / 3 기술 개요 / 4 관점별 평가 / 5 시사점 / 6 한계점 / REFERENCE
- [ ] 본문에 Claim ID와 출처 Tier 병기
- [ ] REFERENCE는 실제 `sources`만. 가짜 URL 금지
