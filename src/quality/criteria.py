"""src/quality/criteria.py - 보고서 품질 평가 기준값 (설계 문서 9절: 팀 결정 항목)

이 파일의 값만 바꾸면 규칙·Judge·루프 동작이 따라 바뀐다. 값을 정한 근거(측정 결과)는
docs/plans/2026-10-07-report-quality-eval-design.md 11절 결정 기록표에 남긴다.
"""
from src.config import JUDGE_LLM_MODEL

# ── [팀 결정] 9절 항목 ───────────────────────────────────────────
JUDGE_PASS_SCORE = 4                 # Judge 항목별 통과 하한 (1–5). 항목별 최저점 기준
JUDGE_MODEL = JUDGE_LLM_MODEL        # Polishing(gpt-4o)과 같으면 자기 평가 편향 위험 → 교체 여부 결정
SINGLE_SOURCE_MAX_RATIO = 0.4        # B1: 외부 근거 중 단일 출처 최대 비율
LENGTH_RATIO_RANGE: tuple[float, float] | None = (0.5, 2.0)  # B5: 3.1/3.2 분량 비율. None이면 B5 끔
REPORT_REVISION_LIMIT = 2            # 품질 미달로 report_generation을 다시 돌리는 최대 횟수

# ── 설계 고정값 (바꿀 일 거의 없음) ─────────────────────────────
MIN_EXTERNAL_SOURCES = 2             # B2: 기술별 시장성/이해관계자 고유 출처 수 하한
MIN_CITATIONS_FOR_RATIO = 4          # B1: 표본이 이보다 적으면 비율 검사 생략
MAX_PDF_PAGES = 10                   # F3: 과제 조건 (보고서 최대 10장)
FEEDBACK_MAX_CHARS = 1500
JUDGE_SEED = 42

BANNED_TERMS = ("우수", "승자", "추천", "권장", "도입해야", "더 낫", "압도", "최선",
                "superior", "outperform", "winner", "recommend")
NEGATION_MARKERS = ("않", "없", "아니", "금지", "배제", "not ", "no ", "n't")
