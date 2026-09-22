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
| **강건호** | 담당 D | • 규칙 기반 4대 룰과 LLM 판정의 2단계 파이프라인으로 검증 속도와 정밀도를 동시에 달성함. | • LLM 심사 프롬프트의 미세한 문맥 차이로 정상 Claim이 오탐되는 케이스가 있어 정밀 튜닝이 필요했음. | 엄격한 근거 검증 루프가 멀티 에이전트 시스템 전체의 출력 신뢰도를 지탱하는 핵심 안전장치임을 체감함. |
| **김효민** | 담당 C | • 4대 액터별 Benefit, Concern, Barrier, Evidence를 일관된 계약 구조로 성공적으로 정형화함. | • 웹 검색 API의 응답 속도 및 비정형 텍스트 파싱 과정의 예외 처리를 더욱 강화할 필요가 있음. | 다양한 이해관계자의 상충되는 요구사항을 정량적 근거(Claim-Evidence)와 연결하여 다각도로 분석하는 방법론을 습득함. |
| **윤영민** | 담당 A | • State 스키마 엄격 분리 및 병렬 브랜치/피드백 루프 설계를 통해 팀원 간 병렬 개발 충돌을 최소화함. | • 실시간 웹 검색 및 RAG 간 레이턴시 차이로 인한 비동기 동기화 처리 최적화 여지 존재. | LangGraph의 유연한 State 분기와 조건부 라우팅을 통해 복잡한 오케스트레이션을 견고하게 제어할 수 있음을 배움. |
| **전경호** | 담당 C | • 자연어 질문형 질의 생성 및 카테고리별 분리 수집으로 시장성 조사 결과의 품질을 높임. | • Tavily API Rate Limit 및 키 누락 상황에 대응하는 모의 데이터와 실제 데이터 간 편차 최소화 필요. | 외부 검색 도구를 에이전트 파이프라인에 결합할 때, 견고한 Fallback과 구조화된 쿼리 전략이 필수적임을 깨달음. |
| **정은희** | 담당 E | • Jinja2 기반 템플릿과 TRL 이원화 매핑을 결합하여 가독성 높고 학술적 깊이가 있는 보고서를 도출함. | • 다양한 노드에서 취합된 비정형 텍스트의 톤앤매너를 완전히 균일하게 맞추는 데 추가 튜닝이 필요했음. | 다관점 평가 체계에서 이원화된 TRL 및 근거 연결(Citation)이 보고서의 설득력을 결정짓는다는 점을 깊이 이해함. |
| **최지윤** | 담당 B | • 임베딩 벤치마크를 통해 최적 모델(`intfloat/e5-small-v2`)을 선정하고 고품질 청킹/검색 파이프라인을 구축함. | • 논문 내 표/수식 등 비텍스트 데이터 추출 및 정밀도 향상을 위한 멀티모달 파서 도입 고려. | RAG 시스템에서 도메인에 특화된 청킹 및 임베딩 모델 선정이 다운스트림 에이전트의 근거 품질에 미치는 막대한 영향을 확인함. |
