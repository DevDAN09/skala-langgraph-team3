"""src/quality/rules.py - 보고서 품질 평가 1단계: 결정적 규칙 검사 (LLM 호출 없음)

설계: docs/plans/2026-10-07-report-quality-eval-design.md 4절
G: Groundedness · N: 중립성 · B: 편향 통제 · C: 관점 커버리지 · F: 형식
T4 단독 근거(R2)와 반대 쿼리 수행(R3)은 Claim 단위로 evidence_audit가 보장한다. 보고서에는 status=ok
Claim만 들어가고 ok는 마지막 검증에서 R2·R3를 통과했다는 뜻이라 여기서 다시 검사하지 않는다.
"""
import contextlib
import os
import re
import tempfile
from collections import Counter
from pathlib import Path

from src.state import OverallState, QualityItem
from src.quality import criteria

ITEMS = ("groundedness", "neutrality", "bias", "coverage", "format")
REQUIRED_CHAPTERS = ("SUMMARY", "1", "2", "3", "4", "5", "6", "REFERENCE")
ALLOWED_HEADINGS = set(REQUIRED_CHAPTERS) | {
    "3.1", "3.2", "4.1", "4.2", "4.3", "4.4", "5.1", "5.2", "5.3", "5.4", "5.5", "6.1", "6.2", "6.3"}
TECHS = ("KIVI", "CXL-PNM")
PERSPECTIVE_AGENT = {"domain": "paper", "maturity": "paper", "market": "market", "stakeholder": "stakeholder"}
EXTERNAL_PREFIXES = ("MKT-", "STK-", "MAT-A")
ACTOR_ALIASES = {
    "서빙 운영자": ("서빙 운영자", "클라우드 운영자", "운영자"),
    "프레임워크 개발자": ("프레임워크 개발자", "개발자"),
    "End User": ("End User", "최종 사용자", "엔드 유저", "서비스 이용자"),
    "공급자": ("공급자", "벤더"),
}
DOMAIN_AXES = ("메모리", "대역폭", "처리량", "정확도", "인프라", "운영")

_HEADING = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.M)
_CLAIM_ID = re.compile(r"(?<![A-Z-])([A-Z]{3}-[A-Z]?\d{2})(?![\d-])")
_CITATION = re.compile(r"\[(\d+)\]")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_COMPARATIVE = re.compile(r"보다\s*(?:더\s*)?(?:우수|낫|뛰어|적합|유리)")
_RENDER_ERROR = re.compile(r"\{\{|\{%|\{'|\|\s*None\s*\|")
_FALLBACK_LINE = re.compile(r"^\s*-?\s*(\*\*[^*]+\*\*:\s*)?검증된 .*없다\.?\s*$")


def heading_key(title: str) -> str:
    """'3.1 KIVI (SW 알고리즘)' → '3.1', '1. 분석 배경' → '1', 'SUMMARY' → 'SUMMARY'."""
    m = re.match(r"(\d+(?:\.\d+)?)\.?\s", title + " ")
    return m.group(1) if m else title.strip()


def split_sections(md: str) -> list[tuple[str, str]]:
    """[(heading key, 본문)] 순서 보존. 본문은 다음 헤딩(##/###) 직전까지."""
    heads = list(_HEADING.finditer(md))
    return [(heading_key(h.group(2)), md[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(md)])
            for i, h in enumerate(heads)]


def _text(sections, *prefixes: str) -> str:
    """key가 prefix와 같거나 'prefix.'로 시작하는 섹션 본문을 이어 붙인다."""
    return "\n".join(body for key, body in sections
                     if any(key == p or key.startswith(p + ".") for p in prefixes))


def _numbers(text: str) -> set[str]:
    text = _CLAIM_ID.sub(" ", _CITATION.sub(" ", text))
    text = re.sub(r"\b(?:EV|SRC)-[\w-]+", " ", text)
    return set(_NUMBER.findall(text))


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?。])\s+|\n", text) if s.strip()]


def _pdf_pages(md: str) -> int | None:
    """보고서 PDF 페이지 수. 변환 실패 시 None (F3 미검사)."""
    from pypdf import PdfReader
    from src.synthesis.pdf_export import convert_markdown_to_pdf
    with tempfile.TemporaryDirectory() as tmp, open(os.devnull, "w") as null, \
            contextlib.redirect_stdout(null), contextlib.redirect_stderr(null):  # xhtml2pdf 경고 출력 억제
        path = Path(tmp) / "report.pdf"
        if not convert_markdown_to_pdf(md, path):
            return None
        return len(PdfReader(str(path)).pages)


# ── 항목별 검사 ────────────────────────────────────────────

def _groundedness(sections, skeleton_sections, ok_ids: set[str], all_ids: set[str]) -> list[str]:
    fails = []
    for line in _text(sections, "3").splitlines():  # G1
        m = _CLAIM_ID.search(line)
        if line.lstrip().startswith("-") and m and not _CITATION.search(line):
            fails.append(f"G1: 3장 Claim {m.group(1)}에 인용 번호가 없다")

    body = "\n".join(b for k, b in sections if k != "REFERENCE")  # G2
    cited = {int(n) for n in _CITATION.findall(body)}
    listed = {int(n) for n in re.findall(r"^\[(\d+)\]", _text(sections, "REFERENCE"), re.M)}
    if cited - listed:
        fails.append(f"G2: REFERENCE에 없는 인용 번호 {sorted(cited - listed)}")
    if listed - cited:
        fails.append(f"G2: 본문에서 인용되지 않은 참고문헌 {sorted(listed - cited)}")

    mentioned = set(_CLAIM_ID.findall(_text(sections, "SUMMARY", "3", "4", "5")))  # G3
    if mentioned - all_ids:
        fails.append(f"G3: State에 없는 Claim ID {sorted(mentioned - all_ids)}")
    if (mentioned & all_ids) - ok_ids:
        fails.append(f"G3: 검증 미통과 Claim이 6장 밖에 인용됨 {sorted((mentioned & all_ids) - ok_ids)}")

    before, after = _numbers(_text(skeleton_sections, "3", "4", "5")), _numbers(_text(sections, "3", "4", "5"))  # G4
    if after - before:
        fails.append(f"G4: polishing 중 추가된 수치 {sorted(after - before)}")
    if before - after:
        fails.append(f"G4: polishing 중 사라진 수치 {sorted(before - after)}")
    return fails


def _neutrality(sections) -> list[str]:
    fails = []
    for sent in _sentences(_text(sections, "SUMMARY", "5")):
        low = sent.lower()
        if any(neg in low for neg in criteria.NEGATION_MARKERS):
            continue
        hit = next((t for t in criteria.BANNED_TERMS if t in low), None)
        if hit:
            fails.append(f'N1: 우열·추천 표현 "{hit}": {sent[:80]}')
        elif _COMPARATIVE.search(sent):
            fails.append(f"N2: 비교 우위 구문: {sent[:80]}")
    return fails


def _bias(sections, state: OverallState, ok_claims: list[dict]) -> tuple[list[str], set[str]]:
    fails, agents = [], set()
    ev_source = {e["evidence_id"]: e["source_id"] for e in state.get("evidence", [])}
    external = [c for c in ok_claims if c["id"].startswith(EXTERNAL_PREFIXES)]

    ext_sources = [ev_source[e] for c in external for e in c.get("evidence_ids", []) if e in ev_source]  # B1
    if len(ext_sources) >= criteria.MIN_CITATIONS_FOR_RATIO:
        src, n = Counter(ext_sources).most_common(1)[0]
        if n / len(ext_sources) > criteria.SINGLE_SOURCE_MAX_RATIO:
            fails.append(f"B1: 외부 근거의 {n / len(ext_sources):.0%}가 단일 출처 {src} "
                         f"(기준 {criteria.SINGLE_SOURCE_MAX_RATIO:.0%})")

    for perspective in ("market", "stakeholder"):  # B2
        for tech in TECHS:
            srcs = {ev_source[e] for c in external if c.get("perspective") == perspective and c.get("tech") == tech
                    for e in c.get("evidence_ids", []) if e in ev_source}
            if len(srcs) < criteria.MIN_EXTERNAL_SOURCES:
                fails.append(f"B2: {tech} {perspective} 고유 출처 {len(srcs)}개 (기준 {criteria.MIN_EXTERNAL_SOURCES}개)")
                agents.add(PERSPECTIVE_AGENT[perspective])

    if criteria.LENGTH_RATIO_RANGE:  # B5
        lo, hi = criteria.LENGTH_RATIO_RANGE
        sw, hw = len(_text(sections, "3.1").strip()), len(_text(sections, "3.2").strip())
        ratio = sw / hw if hw else float("inf")
        if not lo <= ratio <= hi:
            fails.append(f"B5: KIVI/CXL-PNM 서술 분량 비율 {ratio:.2f} (기준 {lo}–{hi})")
    return fails, agents


def _coverage(sections, claims: list[dict]) -> tuple[list[str], set[str]]:
    fails, agents = [], set()
    order = list(dict.fromkeys(k for k, _ in sections if k in REQUIRED_CHAPTERS))  # C1
    if order != list(REQUIRED_CHAPTERS):
        fails.append(f"C1: 필수 목차 누락 또는 순서 오류 (발견: {order})")

    for key in ("3.1", "3.2", "4.1", "4.2", "4.3", "4.4"):  # C2
        body = [ln for ln in _text(sections, key).splitlines() if ln.strip() and not _FALLBACK_LINE.match(ln)]
        if not body:
            fails.append(f"C2: {key}절이 비어 있거나 기본 문구뿐이다")

    stakeholder = _text(sections, "4.3")  # C3
    missing = [actor for actor, aliases in ACTOR_ALIASES.items() if not any(a in stakeholder for a in aliases)]
    if missing:
        fails.append(f"C3: 4.3절에 이해관계자 누락 {missing}")

    domain = _text(sections, "4.4")  # C4
    missing = [axis for axis in DOMAIN_AXES if axis not in domain]
    if missing:
        fails.append(f"C4: 4.4절에 도메인 축 누락 {missing}")

    gap_text = _text(sections, "6")  # C5
    for perspective, agent in PERSPECTIVE_AGENT.items():
        for tech in TECHS:
            cell = [c for c in claims if c.get("perspective") == perspective and c.get("tech") == tech]
            if any(c.get("status") == "ok" for c in cell):
                continue
            if any(c["id"] in gap_text for c in cell):
                continue
            fails.append(f"C5: {tech} {perspective} 관점에 검증된 근거도, 6장 Gap 공개도 없다")
            agents.add(agent)
    return fails, agents


def _format(sections, report: str) -> list[str]:
    fails = []
    odd = [k for k, _ in sections if k not in ALLOWED_HEADINGS]  # F1
    if odd:
        fails.append(f"F1: 템플릿에 없는 헤딩 {odd[:5]}")
    errors = sorted(set(_RENDER_ERROR.findall(report)))  # F2
    if errors:
        fails.append(f"F2: 렌더링 오류 흔적 {errors}")
    if report.lstrip().startswith("```"):
        fails.append("F2: 보고서 전체가 코드 블록(```)으로 감싸져 있다 (PDF가 코드로 렌더링됨)")
    pages = _pdf_pages(report)  # F3
    if pages is None:
        print("⚠️ [품질 평가] PDF 변환 실패로 F3(페이지 수) 미검사")
    elif pages > criteria.MAX_PDF_PAGES:
        fails.append(f"F3: PDF {pages}장 (기준 {criteria.MAX_PDF_PAGES}장 이하)")
    return fails


def run_quality_rules(report: str, skeleton: str, state: OverallState) -> tuple[dict[str, QualityItem], list[str]]:
    """(항목별 결과, 재수집이 필요한 관점 목록 ['paper'|'market'|'stakeholder'])를 반환한다."""
    sections, skeleton_sections = split_sections(report), split_sections(skeleton)
    claims = state.get("claims", [])
    ok_claims = [c for c in claims if c.get("status") == "ok"]

    bias, bias_agents = _bias(sections, state, ok_claims)
    coverage, coverage_agents = _coverage(sections, claims)
    fails = {
        "groundedness": _groundedness(sections, skeleton_sections, {c["id"] for c in ok_claims}, {c["id"] for c in claims}),
        "neutrality": _neutrality(sections),
        "bias": bias,
        "coverage": coverage,
        "format": _format(sections, report),
    }
    items = {k: {"passed": not fails[k], "score": None, "failures": fails[k], "quotes": []} for k in ITEMS}
    agents = [a for a in ("paper", "market", "stakeholder") if a in bias_agents | coverage_agents]
    return items, agents
