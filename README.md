# KV Cache 최적화 기술 평가 LangGraph 멀티 에이전트 시스템 (팀 3)

> SKALA 4기 멀티 에이전트 프로젝트 (10:00 ~ 14:00)  
> 기술 비교: **KIVI** (SW 2-bit 양자화) vs **CXL-PNM** (HW CXL 근접 처리 가속)  
> 프레임워크: **Python 3.10+ / uv / LangGraph 1.2.12**

---

## 1. 프로젝트 아키텍처

```mermaid
flowchart TD
    START([START]) --> paper_analysis["paper_analysis (B)<br/>Agentic RAG"]
    START --> market_research["market_research (C)<br/>시장성 조사"]
    market_research --> stakeholder_research["stakeholder_research (C)<br/>이해관계자"]
    stakeholder_research --> evidence_audit["evidence_audit (D)<br/>Fast-Fail 검증"]
    paper_analysis -.->|재시도 시| evidence_audit
    paper_analysis -.->|첫 실행| END_BRANCH([END])
    evidence_audit -.->|조건부 피드백| market_research
    evidence_audit -.->|조건부 피드백| stakeholder_research
    evidence_audit -.->|조건부 피드백| paper_analysis
    evidence_audit -->|통과/한도초과| evaluation_synthesis["evaluation_synthesis (E)<br/>TRL 이원화"]
    evaluation_synthesis --> report_generation["report_generation (E)<br/>보고서 생성"]
    report_generation --> END([END])
```

### 1.1 데이터 흐름 상세 (End-to-End Data Flow)

파이프라인 실행 시 14개의 전역 State 필드가 각 노드를 거치며 점진적으로 축적·검증·종합되는 데이터 라이프사이클은 다음과 같습니다.

| 단계 | 실행 노드 (담당) | 입력 State | 처리 내용 | 출력/누적 State |
| :---: | :--- | :--- | :--- | :--- |
| **Step 1<br/>초기화 & 병렬 분기** | `START` (A) | `INITIAL_INPUT_STATE` | • 대상 기술(KIVI vs CXL-PNM) 및 기술 계열 선정 사유 주입<br/>• `paper_analysis` 및 `market_research`로 병렬 Fan-out | `selected`, `retry_count: 0` |
| **Step 2<br/>논문 RAG 분석** | `paper_analysis` (B) | `selected` | • KIVI/CXL-PNM 원문 PDF 청킹 및 E5 임베딩 벡터 검색<br/>• 정량 실험 수치(2.6배 압축, 3.1배 효율 등) 및 6대 축 적합성 추출 | `tech_sw`, `tech_hw`, `domain`,<br/>`claims(DOM-*, MAT-R*)`, `evidence`, `sources` |
| **Step 3<br/>시장성 및 이해관계자** | `market_research`<br/>→ `stakeholder_research` (C) | `selected`<br/>(+ `market` 컨텍스트) | • Tavily Web Search 기반 최신 시장 동향 및 배포 장벽 조사<br/>• 4대 핵심 액터(CSP, 운영자, HW 벤더, 개발사) 관점 영향도 분석<br/>• 컨텍스트 체이닝을 통해 시장 데이터를 반영한 정량/정성 Claim 생성 | `market`, `stakeholder`,<br/>`claims(MKT-*, STK-*)`, `evidence`, `sources` |
| **Step 4<br/>Fast-Fail 근거 검증** | `evidence_audit` (D) | `claims`, `evidence`, `sources` | • **1단계 규칙 검증**: 형식·출처(T1~T4)·수치 왜곡 4대 룰 체크<br/>• **2단계 LLM 심사**: `gpt-4o` 기반 Claim-Snippet 사실 일치 판정<br/>• 검증 미달 항목 피드백 발행 및 라우팅 (최대 2회 재시도) | `audit.issues`, `retry_count`,<br/>`claims[*].status` (ok/flagged/insufficient/rejected) |
| **Step 5<br/>TRL 이원화 & 종합** | `evaluation_synthesis` (E) | `claims`, `evidence`, `tech_*`, `market`, `stakeholder` | • 개별 기술 TRL(5-6 / Unknown) vs 계열 산업 TRL(7-8) 이원화 평가<br/>• 기술별 트레이드오프 및 상호 보완적 하이브리드 결합 가능성 도출 | `trl`, `synthesis` |
| **Step 6<br/>보고서 생성 & 산출** | `report_generation` (E)<br/>→ `main.py` / `app.py` (A) | 전체 누적 State | • Jinja2 템플릿 기반 마크다운 렌더링 및 인용 넘버링 연동<br/>• LLM(`gpt-4o`) 문체 정제 및 `final_evaluation_report.md` 생성<br/>• 한국어 폰트 임베딩 기반 PDF(`result.pdf`) 자동 변환 | `report` (Markdown 텍스트),<br/>`final_evaluation_report.md`, `result.pdf` |

#### 1.2 State 계약 및 충돌 방지 원칙 (Reducer)
- **전담 Writer 분리**: 각 노드는 자신이 전담하는 State 키만 수정하여 병렬 실행 시 경합(Race Condition)을 원천 방지합니다.
- **멱등적 Reducer 적용**:
  - `claims`: Claim ID 기준 멱등 업데이트 (`upsert_claims`)로 재시도 시 기존 Claim 정정
  - `evidence`: Evidence ID 기준 멱등 업데이트 (`upsert_evidence`)
  - `sources`: URL 기준 정규화 및 중복 제거 결합 (`union_sources`)

## 2. 빠른 실행 방법

### 환경 변수 설정 (`.env.example`)

`.env.example` 파일을 복사하여 `.env`를 생성하고 필요한 환경 변수를 입력합니다. (API 키가 없더라도 Fallback 및 Mock 로직이 내장되어 있어 테스트와 기본 파이프라인이 정상 동작합니다.)

```bash
cp .env.example .env
```

#### `.env.example` 코드
```dotenv
OPENAI_API_KEY=
LANGCHAIN_API_KEY=
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_PROJECT=RAG-PROJECT
HF_TOKEN=
TAVILY_API_KEY=
```

#### 환경 변수 상세 설명

| 환경 변수 | 필수 여부 | 기본/예시 값 | 설명 |
| :--- | :---: | :--- | :--- |
| `OPENAI_API_KEY` | 선택 (권장) | `sk-...` | **OpenAI API Key**: 2단계 Fast-Fail 검증 심사(`JudgeDecision` - `gpt-4o`), 최종 보고서 윤문(Polishing - `gpt-4o`), 리서치 쿼리 생성 등에 사용됩니다. (미설정 시 Rule-based Mock/Fallback 모드로 자동 전환) |
| `LANGCHAIN_API_KEY` | 선택 | `lsv2_pt_...` | **LangSmith API Key**: LangGraph 멀티 에이전트 실행 흐름, 노드 간 State 전이 및 LLM 호출 트레이싱 모니터링에 사용됩니다. |
| `LANGCHAIN_TRACING_V2` | 선택 | `true` | **LangSmith V2 트레이싱 활성화**: 실행 로그 및 그래프 트레이스를 LangSmith로 전송할지 여부 (`true` / `false`). |
| `LANGCHAIN_ENDPOINT` | 선택 | `https://api.smith.langchain.com` | **LangSmith 엔드포인트 URL**: 트레이싱 데이터를 수신하는 LangSmith 서버 주소. |
| `LANGCHAIN_PROJECT` | 선택 | `RAG-PROJECT` | **LangSmith 프로젝트명**: LangSmith 대시보드에서 트레이스를 그룹화하여 확인할 프로젝트 이름. |
| `HF_TOKEN` | 선택 | `hf_...` | **Hugging Face Token**: RAG 임베딩 모델(`intfloat/e5-small-v2`) 다운로드 속도 향상 및 Hugging Face API Rate Limit 완화용. |
| `TAVILY_API_KEY` | 선택 (권장) | `tvly-...` | **Tavily Search API Key**: 시장성 조사(`market_research`) 및 이해관계자 리서치(`stakeholder_research`) 노드의 실시간 웹 검색에 사용됩니다. (미설정 시 안전한 내장 Fallback 데이터로 동작) |

### 가상환경 설정 및 의존성 설치
```bash
# uv 가상환경 설정 및 활성화
uv venv
source .venv/bin/activate

# 의존성 설치
uv pip install -r requirements.txt
```

### 전체 테스트 실행 (TDD 검증)
```bash
pytest tests/ -v
```

### 파이프라인 실행 및 보고서 생성
```bash
python main.py
test -s final_evaluation_report.md
```

## 3. 팀 구성 및 역할 분담

| 이름 (가나다순) | 역할 | 담당 영역 | 주요 수행 내용 요약 (Summary) |
| :--- | :---: | :--- | :--- |
| **강건호** | 담당 D | 2단계 Fast-Fail 검증 엔진 (`src/audit/**`) | • **2단계 검증 파이프라인 구축**: 규칙 기반 4대 룰(형식·출처·신뢰도) + LLM 심사(`gpt-4o`)<br/>• **오류 피드백 및 라우팅**: 검증 미달 Claim 대상 피드백 생성 및 재시도(최대 2회) 라우팅 연계<br/>• **환각 차단**: 출처 누락 및 사실 왜곡을 필터링하여 보고서 신뢰도 확보 |
| **김효민** | 담당 C | 이해관계자 리서치 엔진 (`src/research/stakeholder.py`) | • **4대 액터 분석**: CSP, 클라우드 운영자, H/W 벤더, AI 개발사별 다각적 영향도 분석<br/>• **구조화 데이터 생성**: 기술 계열별 Benefit·Concern·Barrier·Evidence 정밀 구조화<br/>• **이해관계자 Claim 도출**: STK-01~08 정량/정성 Claim 및 출처 연계 |
| **윤영민** | 담당 A | 시스템 아키텍처 & LangGraph 오케스트레이션 (`src/state.py`, `src/graph.py`, `main.py`, `app.py`) | • **LangGraph 오케스트레이션**: 병렬 RAG/리서치 실행 및 조건부 Fast-Fail 피드백 루프 설계<br/>• **State 계약 관리**: 14개 State 필드 분리 및 에이전트 간 데이터 충돌 방지 구조 확립<br/>• **UI 및 산출물 파이프라인**: Streamlit 웹 대시보드(`app.py`) 및 PDF 보고서 자동 내보내기 구현 |
| **전경호** | 담당 C | 외부 웹 시장성 조사 엔진 (`src/research/market.py`, `src/research/client.py`) | • **실시간 시장성 조사**: Tavily Search 연동을 통한 최신 시장 동향 및 도입 장벽 데이터 수집<br/>• **자연어 쿼리 최적화**: 기술별 세부 카테고리 질의 생성 및 시장성 Claim(MKT-01~04) 정제<br/>• **안정성 보장**: API 실패 및 키 미제공 상황에 대응하는 견고한 Fallback 로직 구축 |
| **정은희** | 담당 E | 다관점 종합 & 보고서 생성 파이프라인 (`src/synthesis/**`) | • **TRL 이원화 종합 평가**: 개별 기술 TRL과 계열 산업 TRL을 분리 분석하는 프레임워크 구축<br/>• **보고서 템플릿 엔진**: Jinja2 기반 마크다운 템플릿 설계, 본문 Citation 번호와 References 자동 연동<br/>• **보고서 정제 및 윤문**: LLM(`gpt-4o`)을 활용한 논리적 흐름 정제 및 문체 통일 |
| **최지윤** | 담당 B | 논문 분석 Agentic RAG 및 임베딩 벤치마크 (`src/rag/**`) | • **Agentic RAG 구축**: KIVI 및 CXL-PNM 논문 원문 PDF 파싱, 청킹 및 FAISS 인덱싱<br/>• **임베딩 벤치마크**: 5종 임베딩 모델 정량 평가 수행 및 최적 모델(`intfloat/e5-small-v2`) 채택<br/>• **논문 근거 추출**: 2.6배 압축 및 3.1배 효율 등 정량 지표 Claim 및 원문 Evidence 추출 |

---

## 4. 평가 보고서의 핵심 포인트

| 이름 (가나다순) | 담당 | 평가 보고서 핵심 포인트 (Key Takeaway) | 비고 |
| :--- | :---: | :--- | :--- |
| **강건호** | 담당 D | • 엄격한 Fast-Fail 2단계 검증(Rule + LLM Judge)을 통해 환각(Hallucination) 및 출처 없는 주장을 사전 차단하여 보고서의 신뢰도와 객관성을 극대화함.<br/>• 수치 왜곡 방지 및 Claim-Evidence 일치성 검증으로 학술 논문/웹 출처에 기반한 사실 검증 체계 확립. | Fast-Fail 검증 |
| **김효민** | 담당 C | • CSP, 엔터프라이즈 운영자, H/W 벤더 등 다각적 이해관계자(Stakeholder) 관점의 분석 반영.<br/>• KIVI의 제로 CAPEX 즉시 도입 가치와 CXL-PNM의 인프라 전환 비용 및 생태계 종속성 이슈를 정밀 대조. | 이해관계자 리서치 |
| **윤영민** | 담당 A | • SW 양자화(KIVI)와 HW 메모리 확장(CXL-PNM)의 상호 배타적 경쟁이 아닌 '하이브리드 결합 가능성'을 도출.<br/>• Fast-Fail 피드백 루프와 TRL 이원화 체계를 결합한 안정적 엔드투엔드 파이프라인 완성. | 오케스트레이션 |
| **전경호** | 담당 C | • 글로벌 데이터센터 현장 관점에서의 최신 시장 동향 및 배포 장벽(Latency 오버헤드, CXL 상용화 성숙도) 발굴.<br/>• 단기적 실용성(SW 압축)과 장기적 메모리 풀링(HW 확장)의 시장 수용 주기 차이를 규명. | 웹 시장성 조사 |
| **정은희** | 담당 E | • 개별 기술 TRL과 계열 산업 TRL을 분리하는 TRL 이원화 평가를 통해 시뮬레이션 지표와 실증 기술의 성숙도 간극을 체계적으로 조명.<br/>• 학술·시장·검증 데이터를 통합한 고품질 기술 평가 보고서 템플릿 완성. | 다관점 종합 보고서 |
| **최지윤** | 담당 B | • E5 임베딩 기반 논문 Agentic RAG를 통해 Llama-2-70B 2.6배 절감(KIVI) 및 3.1배 에너지 효율(CXL-PNM) 등 핵심 정량 데이터를 논문 원문으로부터 오차 없이 추출·제공. | Agentic RAG |

---

## 5. Lessons Learned

| 이름 (가나다순) | 담당 | 잘된 점 (Keep) | 아쉬웠던 점 및 시도해볼 점 (Problem / Try) | 핵심 배운 점 (Lesson Learned) |
| :--- | :---: | :--- | :--- | :--- |
| **강건호** | 담당 D | • 규칙 기반 4대 룰과 LLM 판정의 2단계 파이프라인으로 검증 속도와 정밀도를 동시에 달성함.<br/>• 팀 합의로 설계한 "근거 감사관 + 표적 피드백(Auditor Loop)" 구조(규칙 + LLM Judge 검사 → 문제 있는 에이전트에만 표적 피드백 → 최대 2회 재시도)가 실제 구현에 거의 그대로 반영됨. | • LLM 심사 프롬프트의 미세한 문맥 차이로 정상 Claim이 오탐되는 케이스가 있어 정밀 튜닝이 필요했음.<br/>• 초반 설계 방향을 잡을 때 팀원 전원의 의견을 반영하느라 소통에 시간이 꽤 걸림. | 엄격한 근거 검증 루프가 멀티 에이전트 시스템 전체의 출력 신뢰도를 지탱하는 핵심 안전장치임을 체감함.<br/>• RAG를 직접 설계·구현하며 청킹, 임베딩, 검색 필터링, LLM Judge 프롬프트 튜닝 같은 디테일이 결과 품질을 좌우함을 체감함.<br/>• 여러 팀원이 같은 코드베이스를 병렬로 다루는 협업(브랜치 전략, merge conflict, 역할 경계)에서 설계 문서와 코드의 정합성을 계속 맞추는 습관을 기름. |
| **김효민** | 담당 C | • 4대 액터별 Benefit, Concern, Barrier, Evidence를 일관된 계약 구조로 성공적으로 정형화함.<br/>• (#3) State 리듀서 `union_sources`를 LangGraph 1.2.12에서 실제로 실행해 참조 끊김을 재현하고, 공통 계약(Interface Freeze)인 리듀서는 그대로 둔 채 조사 노드가 기존 `source_id`를 재사용하도록 해 해결함.<br/>• (#4) 라우터 기준(`retry_count < 2`)에 맞춰 검증 노드가 한도 도달 Claim의 최종 상태를 확정하도록 합의하고, 재실행 대상을 소유권이 분명한 Claim ID 접두어로 판단하게 함. | • 웹 검색 API의 응답 속도 및 비정형 텍스트 파싱 과정의 예외 처리를 더욱 강화할 필요가 있음.<br/>• (#3) URL은 같고 `source_id`가 다른 Source가 들어오면 Evidence가 존재하지 않는 Source를 가리켜, R2 검사를 경고 없이 통과하고 REFERENCE에서도 빠짐.<br/>• (#4) 재시도 한도를 소진한 Claim이 `flagged`로 남아 보고서 본문과 한계점 어디에도 나오지 않았고, 공란 슬롯의 R1 오탐으로 재시도가 낭비되며 관계없는 노드가 재실행됨. | 다양한 이해관계자의 상충되는 요구사항을 정량적 근거(Claim-Evidence)와 연결하여 다각도로 분석하는 방법론을 습득함.<br/>• 리듀서는 필드 단위로 병합할 뿐 엔티티 간 참조 무결성까지는 보장하지 않으므로, 공통 State 계약에는 "참조 무결성을 어느 쪽이 책임지는가"까지 정의해야 함.<br/>• 조건부 루프는 탈출 조건만으로는 수렴하지 않으며, 라우터는 State를 쓸 수 없으므로 종료 상태를 누가 기록하는지까지 노드 간 계약으로 정해야 결과가 보고서에 올바르게 반영됨. |
| **윤영민** | 담당 A | • State 스키마 엄격 분리 및 병렬 브랜치/피드백 루프 설계를 통해 팀원 간 병렬 개발 충돌을 최소화함. | • 실시간 웹 검색 및 RAG 간 레이턴시 차이로 인한 비동기 동기화 처리 최적화 여지 존재.<br/>• Agent 구성을 먼저 정한 뒤 보고서를 구성하는 탑다운 방식으로 진행했으나, 경험 부족과 기한 내 Volume 선정 근거가 부족했던 점이 아쉬움.<br/>• (Try) 산출물(보고서) 형식을 먼저 정하고 Agent와 LangGraph를 선정하는 바텀업 방식, 다른 LangGraph 패턴을 활용한 더 정교한 Agent 시스템 구축 | LangGraph의 유연한 State 분기와 조건부 라우팅을 통해 복잡한 오케스트레이션을 견고하게 제어할 수 있음을 배움.<br/>• 보고서 형식을 우선 정의하고 LangGraph를 설계하면 더 나은 결과와 효율적인 개발이 가능하다는 점을 깨달음. |
| **전경호** | 담당 C | • 자연어 질문형 질의 생성 및 카테고리별 분리 수집으로 시장성 조사 결과의 품질을 높임.<br/>• 키가 없을 때 가짜 URL을 돌려주던 fallback을 "빈 결과 + insufficient"로 바꿔 시스템의 신뢰성을 확보함.<br/>• 키워드 나열을 자연어 질문으로, 자르는 글자 수를 넉넉하게 바꾸는 것만으로 결과 품질이 확연히 개선됨. | • Tavily API Rate Limit 및 키 누락 상황에 대응하는 모의 데이터와 실제 데이터 간 편차 최소화 필요.<br/>• 각자의 유닛 테스트는 통과했지만 서로 다른 전제(같은 출처를 다르게 분류)로 코드를 엮자 좋은 데이터가 버려지는 통합 문제가 발생함.<br/>• 브랜치를 나눠도 공용 파일을 같은 이유로 동시에 고치면 충돌이 생기므로 사전 조율이 필요함. | 외부 검색 도구를 에이전트 파이프라인에 결합할 때, 견고한 Fallback과 구조화된 쿼리 전략이 필수적임을 깨달음.<br/>• 가짜보다 정직한 실패가 낫다.<br/>• State 충돌 버그(#3)는 직접 재현 코드를 짜봐야 완전히 이해된다.<br/>• LLM에 "보여준 것"과 "저장한 근거"는 항상 일치해야 하며, 이런 버그는 실제 API로 돌려봐야 드러난다.<br/>• 유닛 테스트 초록불 ≠ 통합 정합성. |
| **정은희** | 담당 E | • Jinja2 기반 템플릿과 TRL 이원화 매핑을 결합하여 가독성 높고 학술적 깊이가 있는 보고서를 도출함.<br/>• 출처를 논문·특허·기업 발표·웹페이지로 구분하고 신뢰도 Tier를 부여해 Claim의 근거 수준을 관리하는 구조를 적용함.<br/>• Claim·Evidence·Source를 분리하고, 근거가 부족한 항목은 억지로 채우지 않도록 상태와 fallback 규칙을 설계함.<br/>• 중간 데이터와 최종 보고서 표현을 분리해 딕셔너리·내부 상태값이 보고서에 노출되지 않도록 정규화하고, 출처 메타데이터 기반 인용, LLM 거절 응답 검증, 실패 상황을 포함한 테스트를 보완함. | • 다양한 노드에서 취합된 비정형 텍스트의 톤앤매너를 완전히 균일하게 맞추는 데 추가 튜닝이 필요했음. | 다관점 평가 체계에서 이원화된 TRL 및 근거 연결(Citation)이 보고서의 설득력을 결정짓는다는 점을 깊이 이해함.<br/>• 다중 에이전트 평가 시스템은 기능을 나누는 것보다 각 모듈이 어떤 근거를 받고 어떤 형식으로 반환하는지를 명확히 정하는 일이 더 중요함.<br/>• 검색 실패, 근거 부족, 메타데이터 누락을 예외가 아닌 정상 상태로 처리해야 최종 보고서의 품질을 지킬 수 있음. |
| **최지윤** | 담당 B | • 임베딩 벤치마크를 통해 최적 모델(`intfloat/e5-small-v2`)을 선정하고 고품질 청킹/검색 파이프라인을 구축함.<br/>• 평가 축이 바뀐 Query Rewrite는 거부하고 원문에 근거가 없으면 insufficient로 남기도록 보완했으며, 필요한 정보가 여러 청크에 나뉜 경우 원문이 확인된 여러 Evidence를 하나의 Claim에 연결함. | • 논문 내 표/수식 등 비텍스트 데이터 추출 및 정밀도 향상을 위한 멀티모달 파서 도입 고려.<br/>• 관련 청크가 Top-k에 포함되더라도 현재 평가 축에 직접 답하는지 검증하지 않으면, 대역폭 질문에 처리량 수치가 연결되는 것처럼 잘못된 Claim이 만들어짐.<br/>• 단위 테스트 통과만으로는 충분하지 않아, 실제 PDF·FAISS·LLM을 함께 실행하며 Retrieval → Gate → 인용 → Rewrite 순으로 실패 지점을 나눠 검증함. | RAG 시스템에서 도메인에 특화된 청킹 및 임베딩 모델 선정이 다운스트림 에이전트의 근거 품질에 미치는 막대한 영향을 확인함.<br/>• 검색된 문장과 실제로 사용할 수 있는 근거는 다르며, Agentic RAG는 검색 결과를 그대로 답으로 쓰는 것이 아니라 질문에 맞는 원문 근거인지 반복해서 확인하는 과정임.<br/>• Query Rewrite는 검색 성공률만 높이는 것이 아니라 원래 질문의 의미를 유지해야 함. |
