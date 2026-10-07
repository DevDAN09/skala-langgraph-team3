# 코드 정리 리뷰 프롬프트 (Supervisor 전환 완료 후 실행)

> 용도: 검증 노드를 Supervisor로 승격한 버전이 완성된 뒤, 동작은 그대로 두고 불필요한 코드만 줄이기 위한 리뷰 프롬프트.
> 사용법: 아래 `---` 사이 전체를 AI 코딩 도구에 그대로 붙여 넣는다.

---

# 역할
너는 enterprise 코드 리뷰어다. AI로 생성된 이 Python/LangGraph 코드베이스에서
"동작은 그대로 두고, 불필요한 코드를 줄이는" 리뷰를 수행한다.

# 시스템 전제 (리뷰 전에 반드시 이해할 것)
- 패턴: Supervisor. 기존 evidence_audit(R1~R5 검증)를 Supervisor 판단 로직으로 승격했다.
- 흐름: START → supervisor → (paper / market / stakeholder) → supervisor → ... →
  evaluation_synthesis → report_generation → quality_evaluation → (END | report_generation | supervisor)
- 하위 에이전트는 Supervisor로만 복귀한다. 에이전트 간 직접 엣지는 없다.
- Supervisor 판단은 규칙 우선이다: R1~R4 정적 규칙(LLM 미호출, Fast-Fail) → 통과한 Claim만 R5 LLM Judge.
- 종료 보장: 에이전트별 retry_count 한도 2, quality_retry 한도, recursion_limit.

# 판단 기준 (출처)
- Google Engineering Practices: over-engineering = 필요 이상으로 범용적이거나 현재 불필요한 기능
- Fowler, Refactoring 2nd ed. Ch.3 / Refactoring.Guru Dispensables: Dead Code, Duplicated Code,
  Speculative Generality, Lazy Class, Comments, Long Function
- Fowler, Yagni: 투기적 코드의 유지 비용(cost of carry)
- Sonar way for AI Code: 신규 코드 중복 ≤ 3%
- Google Python Style Guide: bare except 금지, 가변 기본 인자 금지
- Sculley et al., Hidden Technical Debt in ML Systems: 접착 코드, 죽은 실험 코드 경로
- Anthropic, Claude prompting best practices (Overeagerness): 요청·필요한 변경만, 일회성 작업용 헬퍼/추상화 금지,
  가상의 미래 요구사항을 위한 설계 금지
- CodeScene, Refactoring vs Refuctoring: LLM 리팩토링은 검증 없이 37%만 동작 보존 → 검증 게이트 필수
- Meta TestGen-LLM / Google AI code migrations: LLM 결과는 자동 검증(테스트·정적 분석)을 통과한 것만 채택

# 점검 항목
1. 죽은 코드: 미호출 함수/클래스/변수, 같은 이름 재정의, 도달 불가 분기, 미사용 import
2. 중복: 모듈 간 복사된 헬퍼, 같은 상수/매핑의 다중 정의
3. 투기적 일반화: 구현이 하나뿐인 추상화, 아무도 넘기지 않는 파라미터, 미사용 설정값
4. 과잉 방어: 예외가 날 수 없는 try/except, 이미 보장된 값의 재검사, 불필요한 .get() 연쇄
5. 불필요한 주석: 코드를 그대로 다시 쓴 주석, 정보 없는 docstring
6. 긴 함수/높은 복잡도: 한 함수가 2개 이상 책임을 가지는 경우
7. 접착 코드: LangGraph/LangChain/표준 라이브러리 기능을 다시 구현한 래퍼

# Supervisor 전환 후 특히 확인할 잔재
- 승격 전 구조의 흔적: 삭제된 라우터(route_after_paper 등), market→stakeholder 직접 연결용 코드,
  START 고정 fan-out 전제를 가진 헬퍼/주석/테스트
- 검증 로직 중복: 기존 src/audit/ 와 Supervisor 모듈에 같은 규칙·target_agent 매핑·재시도 한도 상수가
  두 군데 정의되어 있는지 (RETRY_LIMIT, TERMINAL_CLAIM_STATUSES, resolve_target_agent 등은 한 곳에서만 정의)
- 평가 기준 중복: Supervisor(Claim 단위 근거 충분성)와 quality_evaluation(보고서 단위 품질)이
  같은 검사를 두 번 하고 있는지. 역할이 겹치면 한 쪽으로 모은다.
- 라우팅 결정이 print와 routing_log에 이중 기록되는지 (관측은 routing_log 기준)

# 절대 바꾸면 안 되는 것
- 의도된 fallback은 삭제 금지: API 키 부재, 근거 부족(insufficient), PDF 변환 실패,
  LLM 호출 실패 시의 graceful degradation은 설계상 정상 출력이다.
- src/state.py의 State 키, TypedDict 필드, 리듀서 시그니처 변경 금지
  (routing_log, retry_count, quality_retry 등 제어 필드 포함)
- 노드 이름, add_conditional_edges 분기 대상, 재시도/품질 루프 한도, 종료 조건 변경 금지
- Supervisor의 규칙 우선 순서(R1~R4 → R5) 변경 금지. R1~R4 위반 Claim이 LLM을 호출하게 만드는 수정 금지
- Supervisor는 신규 Claim/Evidence/Source ID를 만들지 않는다는 계약 유지
- 보고서 템플릿의 필수 목차(SUMMARY, REFERENCE) 변경 금지
- 테스트에서 사용하는 공개 함수는 삭제 전 반드시 tests/ 사용처 확인

# 리팩토링 원칙 (검증 게이트)
- 이번 작업의 범위는 "불필요한 코드 제거"뿐이다. 기능 추가, 이름 일괄 변경, 스타일 재작성, 새 추상화 도입은 하지 않는다.
- 결정적으로 판정 가능한 항목(미사용 import, 재정의, bare except 등)은 도구 결과를 근거로 삼고,
  판단이 필요한 항목(중복·투기적 일반화·과잉 방어)만 직접 판정한다.
- 각 수정은 테스트를 통과해야만 채택한다. 통과하지 못하면 되돌리고 표에 "보류"로 기록한다.

# 수행 방식
1. 기준선 기록:
   uv run pytest -q
   uvx radon cc src/ -s -a
   uvx radon raw src/ -s
2. 후보 수집:
   uvx ruff check src/ --select F401,F811,F841,E722,B006
   uvx vulture src/ --min-confidence 80
   uvx radon cc src/ -s -n C
3. 도구 결과는 후보일 뿐이다. LangGraph 노드처럼 문자열이나 동적으로 호출되는 코드는
   grep으로 실제 사용처(src/, tests/, main.py, app.py)를 확인한 뒤에만 판정한다.
4. 수정은 파일 단위로 작게 나누고, 각 단계 후 uv run pytest -q 가 기준선과 같은 결과여야 한다.
5. 마지막에 radon을 다시 실행해 수정 전후를 비교한다.

# 출력 형식
| # | 파일:라인 | 항목(1~7 / 잔재) | 근거(출처) | 문제 | 조치(삭제/병합/단순화/유지) | 삭제 라인 수 |

마지막 요약:
- 총 삭제 라인 수 (radon raw SLOC 전후)
- 평균 순환 복잡도 전후
- 테스트 통과 여부 (기준선 대비)
- "유지" 판정 항목은 왜 남기는지 한 줄 이유 (예: 의도된 fallback)

---

## Reference
- Google Engineering Practices, What to look for in a code review — https://google.github.io/eng-practices/review/reviewer/looking-for.html
- Martin Fowler, *Refactoring: Improving the Design of Existing Code* 2nd ed. (2018), Ch.3 Bad Smells in Code
- Refactoring.Guru, Dispensables — https://refactoring.guru/refactoring/smells/dispensables
- Martin Fowler, bliki: Yagni — https://www.martinfowler.com/bliki/Yagni.html
- Thoughtworks Technology Radar Vol.32, Complacency with AI-generated code — https://www.thoughtworks.com/en-us/radar/techniques/complacency-with-ai-generated-code
- SonarSource, Quality gates for AI code — https://docs.sonarsource.com/sonarqube-server/2026.3/quality-standards-administration/ai-code-assurance/quality-gates-for-ai-code
- Google Python Style Guide — https://google.github.io/styleguide/pyguide.html
- Sculley et al., Hidden Technical Debt in Machine Learning Systems (NeurIPS 2015) — https://proceedings.neurips.cc/paper/2015/file/86df7dcfd896fcaf2674f757a2463eba-Paper.pdf
- Anthropic, Prompting best practices (Claude 4) — Overeagerness — https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/claude-4-best-practices
- Anthropic Engineering, Claude Code: Best practices for agentic coding — https://www.anthropic.com/engineering/claude-code-best-practices
- OpenAI Cookbook, GPT-5-Codex Prompting Guide — https://cookbook.openai.com/examples/gpt-5-codex_prompting_guide
- OpenAI, Codex code review (AGENTS.md Review guidelines) — https://developers.openai.com/codex/integrations/github
- Google, How is Google using AI for internal code migrations? (ICSE-SEIP 2025) — https://arxiv.org/abs/2501.06972
- Google Research, Resolving code review comments with ML — https://research.google/blog/resolving-code-review-comments-with-ml/
- Meta, Automated Unit Test Improvement using LLMs at Meta (FSE 2024) — https://arxiv.org/abs/2402.09171
- CodeScene, Refactoring vs Refuctoring (2024) — https://codescene.com/hubfs/whitepapers/Refactoring-vs-Refuctoring-Advancing-the-state-of-AI-automated-code-improvements.pdf
- From Human to Machine Refactoring: GPT-4's Impact on Python Class Quality (arXiv 2601.13139) — https://arxiv.org/abs/2601.13139
- GitClear, AI Copilot Code Quality (2025) — 중복 코드 블록 8배 증가 (배경 근거)
