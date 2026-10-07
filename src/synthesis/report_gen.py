"""src/synthesis/report_gen.py - Jinja2 Template rendering & Strict Grounding report node"""
from pathlib import Path
from datetime import date
from functools import lru_cache
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from jinja2 import Environment, FileSystemLoader
from langchain_openai import ChatOpenAI
from src.state import OverallState
from src.config import OPENAI_API_KEY, POLISHING_LLM_MODEL
from src.rag.agentic_rag import AXIS_BY_ID
from src.research.market import AXIS_BY_CLAIM_ID as MARKET_AXIS_BY_ID
from src.research.stakeholder import COUNTER_NOT_FOUND, END_USER_GAP, STAKEHOLDER_QUERY_PLAN, UNVERIFIED

_PLACEHOLDER_VALUES = {"", "web", "unknown", "n.d.", "na", "n/a"}
_DOMAIN_FIELD_ALIASES = {
    "memory_footprint": ("memory_footprint",), "bandwidth_transfer": ("bandwidth_transfer",),
    "throughput_latency": ("throughput_latency", "latency_impact"), "accuracy": ("accuracy",),
    "infrastructure": ("infrastructure", "infrastructure_change", "infra_change"),
    "operational_complexity": ("operational_complexity",),
}


def _is_placeholder(value: object) -> bool:
    return str(value or "").strip().lower() in _PLACEHOLDER_VALUES


class _SourceMetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.metadata: dict[str, list[str]] = {}
        self.json_ld: list[object] = []
        self._json_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): (value or "").strip() for key, value in attrs}
        if tag == "script" and values.get("type", "").lower() == "application/ld+json":
            self._json_parts = []
        elif tag == "meta":
            key = (values.get("name") or values.get("property") or "").lower()
            aliases = {"citation_author": "author", "author": "author", "article:author": "author", "parsely-author": "author", "dc.creator": "author", "og:site_name": "site_name", "article:published_time": "date", "date": "date", "datepublished": "date", "publishdate": "date", "dc.date": "date"}
            if key in aliases and values.get("content"):
                self.metadata.setdefault(aliases[key], []).append(values["content"])

    def handle_data(self, data: str) -> None:
        if self._json_parts is not None:
            self._json_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._json_parts is not None:
            try:
                self.json_ld.append(json.loads("".join(self._json_parts)))
            except json.JSONDecodeError:
                pass
            self._json_parts = None


def _json_ld_values(payload: object) -> dict[str, list[str]]:
    values = {"author": [], "site_name": [], "date": []}
    def name(value: object) -> str:
        return str(value.get("name") or "") if isinstance(value, dict) else str(value or "")
    def visit(node: object) -> None:
        if isinstance(node, list):
            for item in node: visit(item)
        elif isinstance(node, dict):
            author = node.get("author")
            for item in (author if isinstance(author, list) else [author]):
                if name(item): values["author"].append(name(item))
            for key in ("publisher", "isPartOf"):
                if name(node.get(key)): values["site_name"].append(name(node[key]))
            for key in ("datePublished", "dateCreated"):
                if name(node.get(key)): values["date"].append(name(node[key]))
            visit(node.get("@graph", []))
    visit(payload)
    return {key: list(dict.fromkeys(items)) for key, items in values.items()}


@lru_cache(maxsize=32)
def fetch_source_metadata(url: str) -> dict[str, str]:
    try:
        with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=4) as response:
            parser = _SourceMetadataParser()
            parser.feed(response.read(512_000).decode("utf-8", errors="ignore"))
        json_ld = _json_ld_values(parser.json_ld)
        authors = parser.metadata.get("author") or json_ld["author"]
        dates = parser.metadata.get("date") or json_ld["date"]
        sites = parser.metadata.get("site_name") or json_ld["site_name"]
        return {"authors": "; ".join(authors), "date": (dates or [""])[0][:10], "site_name": (sites or [""])[0]}
    except Exception:
        return {}


def enrich_source(source: dict) -> dict:
    result = dict(source)
    metadata = fetch_source_metadata(str(result.get("url", "")))
    for key in ("authors", "date", "site_name"):
        if _is_placeholder(result.get(key)) and metadata.get(key): result[key] = metadata[key]
    return result


def citation_date(value: object, precision: str) -> str:
    pattern = {"year": r"^\d{4}$", "month": r"^\d{4}-\d{2}$", "day": r"^\d{4}-\d{2}-\d{2}$"}[precision]
    return str(value) if re.fullmatch(pattern, str(value or "")) else "발행일 미상"


def citation_site_name(source: dict) -> str:
    if not _is_placeholder(source.get("site_name")): return str(source["site_name"])
    if not _is_placeholder(source.get("publisher")): return str(source["publisher"])
    return urlparse(str(source.get("url", ""))).netloc.removeprefix("www.") or "사이트명 미상"


def citation_author(source: dict, allow_publisher: bool = True) -> str:
    authors = source.get("authors")
    if not _is_placeholder(authors):
        names = authors if isinstance(authors, list) else str(authors).split(";")
        names = [re.sub(r",?\s*https?://\S+", "", str(item)).strip(" ,") for item in names]
        names = [name for name in names if name]
        return f"{names[0]} et al." if len(names) >= 3 else ", ".join(names)
    if allow_publisher and not _is_placeholder(source.get("publisher")): return str(source["publisher"])
    return citation_site_name(source) if source.get("source_type") == "web" else "기관 또는 작성자 미상"


def domain_axis_value(domain: dict, field: str) -> str:
    value = next((domain.get(key) for key in _DOMAIN_FIELD_ALIASES[field] if domain.get(key) is not None), None)
    if not isinstance(value, dict): return str(value or "공개 근거 미확인").replace("corpus 내 근거 미확인", "공개 근거 미확인")
    return "<br>".join(f"**{tech}**: {str(value.get(tech) or '공개 근거 미확인').replace('corpus 내 근거 미확인', '공개 근거 미확인')}" for tech in ("KIVI", "CXL-PNM"))


def claim_reference_numbers(claim: dict, evidence: list[dict], numbers: dict[str, int]) -> str:
    """Render each source number once even when a Claim has duplicate evidence."""
    evidence_by_id = {item.get("evidence_id"): item for item in evidence}
    seen, refs = set(), []
    for evidence_id in claim.get("evidence_ids", []):
        source_id = evidence_by_id.get(evidence_id, {}).get("source_id")
        if source_id in numbers and source_id not in seen:
            seen.add(source_id)
            refs.append(f"[{numbers[source_id]}]")
    return " " + " ".join(refs) if refs else ""


# --- Presentation layer: the report shows a compressed, cited view; State is never trimmed. ---

_TECHS = ("KIVI", "CXL-PNM")
# 3장 대표 Claim 우선순위: 메커니즘(infrastructure 축 = tech.mechanism) > 메모리 효과 > 성능 > 정확도 > 나머지.
_OVERVIEW_PRIORITY = ("infrastructure", "memory_footprint", "throughput_latency", "accuracy", "bandwidth_transfer", "operational_complexity")
_OVERVIEW_LIMIT = 4
_AXIS_LABELS = {
    "infrastructure": "메커니즘·인프라 요구", "memory_footprint": "메모리 효과", "throughput_latency": "성능·지연",
    "accuracy": "정확도·한계", "bandwidth_transfer": "대역폭·전송", "operational_complexity": "운영 복잡도",
}
_DOMAIN_ROWS = (
    ("memory_footprint", "메모리 점유량"), ("bandwidth_transfer", "대역폭·전송"), ("throughput_latency", "처리량·응답 지연"),
    ("accuracy", "정확도"), ("infrastructure", "인프라 변경"), ("operational_complexity", "운영 복잡도"),
)
_KIND_LABELS = {"vendor_claim": "벤더 주장", "simulation": "시뮬레이션", "estimate": "추정"}
_MARKET_GROUPS = (("채택·실증", ("adoption", "deployment")), ("생태계·지원", ("ecosystem",)))
_ACTOR_LABELS = {
    "cloud_serving_operator": "클라우드/서빙 운영자", "framework_developer": "프레임워크 개발자",
    "end_user": "End User", "memory_vendor": "HW·메모리 공급자",
}
_PERSPECTIVE_LABELS = {"maturity": "기술 성숙도", "market": "시장성", "stakeholder": "이해관계자", "domain": "도메인"}
_GAP_LABELS = {
    "insufficient": "근거 부족(insufficient): 공개 자료에서 충분한 근거를 확보하지 못함",
    "rejected": "불채택(rejected): 확보된 Evidence와 Claim이 일치하지 않아 채택하지 않음",
}
_NO_COUNTER = "반대 근거 미확인"
_STK_SEGMENT = re.compile(
    r"^\[(?P<family>.+?) 계열\] Benefit: (?P<benefit>.*?) \| Concern: (?P<concern>.*?)"
    r" \| Barrier: (?P<barrier>.*?) \(근거: (?P<ids>[^()]*)\)$"
)


def _one_line(text: object) -> str:
    return " ".join(str(text or "").split())


def _display(text: object) -> str:
    """One-line statement whose in-paper numeric citations cannot be confused with REFERENCE numbers."""
    return re.sub(r"\[(\d+(?:\s*[,–-]\s*\d+)*)\]", r"(원문 인용 \1)", _one_line(text))


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(r"```[A-Za-z]*\n(.*)\n```", stripped, re.S)
    return match.group(1).strip() if match else stripped


_EXCERPT_LIMIT = 160


def _excerpt(text: str) -> str:
    """Keep table cells short: a long quote is cut at its first sentence and marked as an excerpt."""
    if len(text) <= _EXCERPT_LIMIT:
        return text
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return f"{first} …(발췌)" if len(first) < len(text) else text


def summary_sentence(text: str) -> str:
    """SUMMARY shows only the first sentence of a representative Claim; the full quote stays in 3장."""
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return f"{first} …" if len(first) < len(text) else text


_TRANSLATE_KEYS = {"statement", "benefit", "concern", "barrier", "text"}
_TRANSLATE_BATCH = 15
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _needs_translation(text: str) -> bool:
    letters = re.findall(r"[A-Za-z가-힣]", text)
    return bool(letters) and sum("가" <= ch <= "힣" for ch in letters) < len(letters) * 0.3


def _walk_texts(node: object, apply=None) -> list[str]:
    """Collect (or replace via `apply`) every free-text field the report displays."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _TRANSLATE_KEYS and isinstance(value, str):
                found.append(value)
                if apply: node[key] = apply(value)
            elif key == "barriers" and isinstance(value, list):
                found.extend(value)
                if apply: node[key] = [apply(item) for item in value]
            else:
                found.extend(_walk_texts(value, apply))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk_texts(item, apply))
    return found


def translate_texts(texts: list[str]) -> dict[str, str]:
    """Translate evidence-derived sentences to Korean; a translation that changes any number is discarded."""
    pending = [text for text in dict.fromkeys(texts) if _needs_translation(text)]
    if not pending or not OPENAI_API_KEY:
        return {}
    llm = ChatOpenAI(model=POLISHING_LLM_MODEL, temperature=0)
    translated: dict[str, str] = {}
    for start in range(0, len(pending), _TRANSLATE_BATCH):
        batch = pending[start:start + _TRANSLATE_BATCH]
        prompt = f"""다음 JSON 배열의 각 문장을 한국어 보고서 문체(`-다.` 체)로 번역하라.
- 배열 길이와 순서를 그대로 유지하고, JSON 문자열 배열만 반환하라.
- 수치·단위·연도·괄호 안 표기·고유명사·제품명·기술 용어(KIVI, CXL, KV cache 등)는 바꾸지 마라.
- 논문 원문의 1인칭(we/our)은 '저자들은'·'해당 연구는'처럼 옮겨라.
- 내용을 추가·삭제·요약하지 마라.

{json.dumps(batch, ensure_ascii=False)}"""
        try:
            result = json.loads(_strip_fence(llm.invoke(prompt).content))
        except Exception as error:
            print(f"⚠️ [경고/Fallback] Claim 번역 실패, 원문 유지: {error}")
            continue
        if not isinstance(result, list) or len(result) != len(batch):
            print("⚠️ [경고/Fallback] Claim 번역 결과 형식 불일치, 원문 유지")
            continue
        for source, target in zip(batch, result):
            if isinstance(target, str) and target.strip() and sorted(_NUMBER.findall(source)) == sorted(_NUMBER.findall(target)):
                translated[source] = target.strip()
    return translated


def _verified(claims: list[dict]) -> list[dict]:
    return [claim for claim in claims if claim.get("status") == "ok" and claim.get("statement")]


class _Citations:
    """Collects the evidence actually cited in the body; REFERENCE lists only those sources."""

    def __init__(self, evidence: list[dict], sources: list[dict]) -> None:
        self._source_by_evidence = {item.get("evidence_id"): item.get("source_id") for item in evidence}
        self._sources = {source.get("source_id"): source for source in sources}
        self._order = list(dict.fromkeys(source.get("source_id") for source in sources))
        self._used: set[str] = set()

    def use(self, evidence_ids: list[str]) -> list[str]:
        for evidence_id in evidence_ids:
            if self._source_by_evidence.get(evidence_id) in self._sources:
                self._used.add(self._source_by_evidence[evidence_id])
        return list(evidence_ids)

    def numbers(self) -> dict[str, int]:
        return {source_id: index for index, source_id in enumerate((sid for sid in self._order if sid in self._used), 1)}

    def cited_sources(self) -> list[dict]:
        return [self._sources[source_id] for source_id in self.numbers()]

    def marker(self, evidence_ids: list[str]) -> str:
        numbers, refs = self.numbers(), []
        for evidence_id in evidence_ids:
            number = numbers.get(self._source_by_evidence.get(evidence_id))
            if number and f"[{number}]" not in refs:
                refs.append(f"[{number}]")
        return " " + " ".join(refs) if refs else ""


def _claim_axis(claim: dict) -> str | None:
    return (AXIS_BY_ID.get(claim.get("id")) or (None, None, None))[2]


def select_overview_claims(claims: list[dict], tech: str, limit: int = _OVERVIEW_LIMIT) -> list[dict]:
    """Pick representative verified domain Claims by axis priority, skipping duplicate statements."""
    candidates = [claim for claim in _verified(claims) if claim.get("tech") == tech and claim.get("perspective") == "domain"]
    def rank(claim: dict) -> int:
        axis = _claim_axis(claim)
        return _OVERVIEW_PRIORITY.index(axis) if axis in _OVERVIEW_PRIORITY else len(_OVERVIEW_PRIORITY)
    picked, seen = [], set()
    for claim in sorted(candidates, key=rank):
        key = _one_line(claim["statement"]).lower()
        if key in seen:
            continue
        seen.add(key)
        picked.append(claim)
        if len(picked) == limit:
            break
    return picked


def _claim_item(claim: dict, citations: _Citations) -> dict:
    return {
        "id": claim["id"], "tech": claim.get("tech"), "statement": _display(claim["statement"]),
        "kind": _KIND_LABELS.get(claim.get("kind"), ""), "axis": _AXIS_LABELS.get(_claim_axis(claim) or "", ""),
        "ev": citations.use(claim.get("evidence_ids", [])),
    }


def _domain_rows(domain: dict, verified: list[dict], shown_ids: set[str], citations: _Citations) -> list[dict]:
    """Domain table cells cite a Claim only when the cell text is exactly that Claim's statement."""
    rows = []
    for field, label in _DOMAIN_ROWS:
        value = next((domain.get(key) for key in _DOMAIN_FIELD_ALIASES[field] if domain.get(key) is not None), None)
        if not isinstance(value, dict):
            rows.append({"label": label, "cells": [{"tech": None, "text": domain_axis_value(domain, field), "id": None, "ev": [], "shown": False}]})
            continue
        cells = []
        for tech in _TECHS:
            text = _one_line(value.get(tech)).replace("corpus 내 근거 미확인", "공개 근거 미확인") or "공개 근거 미확인"
            backing = next((c for c in verified if c.get("tech") == tech and _one_line(c["statement"]) == text), None)
            shown = bool(backing and backing["id"] in shown_ids)
            cells.append({
                "tech": tech, "text": _excerpt(_display(text)), "id": backing["id"] if backing else None,
                "ev": citations.use(backing.get("evidence_ids", [])) if backing else [],
                "shown": shown,
            })
        rows.append({"label": label, "cells": cells})
    return rows


def _market_view(market: dict, verified: list[dict], citations: _Citations) -> dict:
    groups = [
        {"label": label, "items": [_claim_item(c, citations) for c in verified if MARKET_AXIS_BY_ID.get(c.get("id")) in axes]}
        for label, axes in _MARKET_GROUPS
    ]
    maturity = [_claim_item(c, citations) for c in verified if str(c.get("id", "")).startswith("MAT-A")]
    raw_barriers = _one_line(market.get("barriers"))
    barriers = [] if raw_barriers in {"", COUNTER_NOT_FOUND} else [part.strip() for part in raw_barriers.split(" | ") if part.strip()]
    return {"groups": groups, "maturity": maturity, "barriers": barriers}


def _counter_text(text: str) -> str:
    return _NO_COUNTER if text == COUNTER_NOT_FOUND else _one_line(text)


def _stakeholder_view(stakeholder: dict, claims: list[dict], families: dict[str, str], citations: _Citations) -> list[dict]:
    """4 Actor x 2 technology rows from the canonical slots; Concern/Barrier cite the counter evidence they came from."""
    claims_by_id = {claim.get("id"): claim for claim in claims}
    tech_by_family = {family: tech for tech, family in families.items()}
    actors = []
    for slot in dict.fromkeys(item["slot"] for item in STAKEHOLDER_QUERY_PLAN):
        segments = {}
        for segment in re.split(r" / (?=\[[^\[\]]+ 계열\] )", str(stakeholder.get(slot) or "")):
            match = _STK_SEGMENT.match(segment.strip())
            if match and match["family"] in tech_by_family:
                segments[tech_by_family[match["family"]]] = match.groupdict()
        plan = {item["tech"]: item for item in STAKEHOLDER_QUERY_PLAN if item["slot"] == slot}
        rows = []
        for tech in _TECHS:
            claim_id = plan[tech]["claim_id"]
            claim = claims_by_id.get(claim_id) or {}
            row = {"tech": tech, "family": families[tech], "id": claim_id}
            if claim.get("status") != "ok" or not claim.get("statement"):
                rows.append({**row, "gap": END_USER_GAP if slot == "end_user" else UNVERIFIED})
                continue
            benefit = _one_line(claim["statement"])
            concern = barrier = UNVERIFIED
            concern_ev, barrier_ev = [], []
            segment = segments.get(tech)
            # 요약 슬롯이 현재 Claim과 같은 시점에 만들어진 경우에만 Concern/Barrier를 가져온다.
            if segment and _one_line(segment["benefit"]) == benefit:
                concern, barrier = _counter_text(segment["concern"]), _counter_text(segment["barrier"])
                listed = {item.strip() for item in segment["ids"].split(",")}
                counter_id = next((eid for eid in claim.get("counter_evidence_ids", []) if eid in listed), None)
                if counter_id and concern not in {UNVERIFIED, _NO_COUNTER}:
                    concern_ev = citations.use([counter_id])
                if counter_id and barrier not in {UNVERIFIED, _NO_COUNTER}:
                    barrier_ev = citations.use([f"{counter_id}2" if f"{counter_id}2" in listed else counter_id])
            rows.append({**row, "gap": None, "benefit": _display(benefit), "kind": _KIND_LABELS.get(claim.get("kind"), ""),
                         "benefit_ev": citations.use(claim.get("evidence_ids", [])),
                         "concern": concern, "concern_ev": concern_ev, "barrier": barrier, "barrier_ev": barrier_ev})
        actors.append({"label": _ACTOR_LABELS.get(slot, slot), "rows": rows})
    return actors


def _evidence_gaps(gaps: list[dict]) -> list[dict]:
    grouped = []
    for status, label in _GAP_LABELS.items():
        items = [
            f"{gap.get('id', 'Unknown')}({_PERSPECTIVE_LABELS.get(gap.get('perspective'), '관점 미상')}·{gap.get('tech') or '기술 미상'})"
            for gap in gaps if gap.get("status") == status
        ]
        if items:
            grouped.append({"label": label, "items": items})
    return grouped


def build_report_view(state: OverallState) -> dict:
    """Precompute every cited section so reference numbers cover exactly what the body cites."""
    claims = state.get("claims", [])
    verified = _verified(claims)
    citations = _Citations(state.get("evidence", []), state.get("sources", []))
    families_raw = (state.get("selected") or {}).get("families") or {}
    families = {"KIVI": families_raw.get("sw", "KV Quantization"), "CXL-PNM": families_raw.get("hw", "CXL Memory Expansion")}

    overview = {tech: [_claim_item(c, citations) for c in select_overview_claims(claims, tech)] for tech in _TECHS}
    shown_ids = {item["id"] for items in overview.values() for item in items}
    trl = state.get("trl") or {}
    return {
        "overview": overview,
        "domain_rows": _domain_rows(state.get("domain") or {}, verified, shown_ids, citations),
        "market_view": _market_view(state.get("market") or {}, verified, citations),
        "actors": _stakeholder_view(state.get("stakeholder") or {}, claims, families, citations),
        "tradeoff_basis": [c["id"] for c in verified if c.get("perspective") == "domain" and _claim_axis(c) == "infrastructure"],
        "trl_basis": {tech: {key: ", ".join((trl.get(tech) or {}).get(key, [])) or "-" for key in ("research_evidence", "adoption_evidence")} for tech in _TECHS},
        "has_simulation": any(c.get("kind") == "simulation" for c in verified),
        "gap_groups": _evidence_gaps((state.get("synthesis") or {}).get("evidence_gaps", [])),
        "cite": citations.marker,
        "cited_sources": [enrich_source(source) for source in citations.cited_sources()],
    }


def report_generation_node(state: OverallState) -> dict:
    """Renders the final report for the orchestration layer to persist."""
    print("📝 [보고서 생성] 8대 필수 목차 Jinja2 렌더링 실행")
    templates_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)), trim_blocks=True, lstrip_blocks=True)
    env.filters["citation_date"] = citation_date
    env.filters["citation_author"] = citation_author
    env.filters["citation_site_name"] = citation_site_name
    env.filters["summary_sentence"] = summary_sentence
    template = env.get_template("report.md.j2")

    # 문서 전체를 LLM에 넘기면 긴 문서 후반부가 번역되지 않거나 인용·표기가 바뀐다.
    # 근거 문장 필드만 번역하고, 인용 번호·Claim ID·해석 표기는 템플릿이 결정적으로 렌더링한다.
    view = build_report_view(state)
    translations = translate_texts(_walk_texts(view))
    if translations:
        _walk_texts(view, lambda text: translations.get(text, text))

    rendered = template.render(
        selected=state.get("selected", {}),
        trl=state.get("trl", {}),
        synthesis=state.get("synthesis", {}),
        issued_on=date.today().isoformat(),
        **view,
    )
    return {"report": rendered}
