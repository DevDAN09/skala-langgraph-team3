"""src/synthesis/report_gen.py - Jinja2 Template rendering & Strict Grounding report node"""
from pathlib import Path
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
        names = [str(item).strip() for item in names if str(item).strip()]
        return f"{names[0]} et al." if len(names) >= 3 else ", ".join(names)
    if allow_publisher and not _is_placeholder(source.get("publisher")): return str(source["publisher"])
    return citation_site_name(source) if source.get("source_type") == "web" else "기관 또는 작성자 미상"


def domain_axis_value(domain: dict, field: str) -> str:
    value = next((domain.get(key) for key in _DOMAIN_FIELD_ALIASES[field] if domain.get(key) is not None), None)
    if not isinstance(value, dict): return str(value or "공개 근거 미확인").replace("corpus 내 근거 미확인", "공개 근거 미확인")
    return "<br>".join(f"**{tech}**: {str(value.get(tech) or '공개 근거 미확인').replace('corpus 내 근거 미확인', '공개 근거 미확인')}" for tech in ("KIVI", "CXL-PNM"))


_DOMAIN_FIELD_ALIASES = {
    "memory_footprint": ("memory_footprint",),
    "bandwidth_transfer": ("bandwidth_transfer",),
    "throughput_latency": ("throughput_latency", "latency_impact"),
    "accuracy": ("accuracy",),
    "infrastructure": ("infrastructure", "infrastructure_change", "infra_change"),
    "operational_complexity": ("operational_complexity",),
}


def domain_axis_value(domain: dict, field: str) -> str:
    """Format per-technology domain data for one Markdown table cell."""
    value = next((domain.get(key) for key in _DOMAIN_FIELD_ALIASES[field] if domain.get(key) is not None), None)
    if not isinstance(value, dict):
        return str(value or "공개 근거 미확인").replace("corpus 내 근거 미확인", "공개 근거 미확인")
    return "<br>".join(
        f"**{tech}**: {str(value.get(tech) or '공개 근거 미확인').replace('corpus 내 근거 미확인', '공개 근거 미확인')}"
        for tech in ("KIVI", "CXL-PNM")
    )

def report_generation_node(state: OverallState) -> dict:
    """Renders the final report for the orchestration layer to persist."""
    print("📝 [보고서 생성] 8대 필수 목차 Jinja2 렌더링 실행")
    templates_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    env.filters["citation_date"] = citation_date
    env.filters["citation_author"] = citation_author
    env.filters["citation_site_name"] = citation_site_name
    env.globals["domain_axis_value"] = domain_axis_value
    env.globals["domain_axis_value"] = domain_axis_value
    template = env.get_template("report.md.j2")

    rendered = template.render(
        selected=state.get("selected", {}),
        tech_sw=state.get("tech_sw", {}),
        tech_hw=state.get("tech_hw", {}),
        domain=state.get("domain", {}),
        market=state.get("market", {}),
        stakeholder=state.get("stakeholder", {}),
        trl=state.get("trl", {}),
        synthesis=state.get("synthesis", {}),
        sources=[enrich_source(source) for source in state.get("sources", [])],
        evidence=state.get("evidence", []),
        claims=state.get("claims", [])
    )

    if not OPENAI_API_KEY:
        return {"report": rendered}

    try:
        prompt = f"""정적 근거 기반 기술 보고서 편집자입니다.
다음 마크다운의 문장만 다듬으십시오.
- SUMMARY, 1~6, REFERENCE 제목과 순서를 변경하지 마십시오.
- 수치, TRL, Claim ID, URL, 출처 Tier, simulation 표기를 변경하거나 추가하지 마십시오.
- 기술 우열, 승자, 추천, 근거 없는 전망을 추가하지 마십시오.
- 영어 원문 자료를 바탕으로 하더라도 보고서의 서술 문장은 한국어로 작성하십시오.
- KIVI, CXL-PNM, LLM, KV Cache 같은 고유명사·기술 용어, 논문·특허·웹페이지 제목, 인용 번호는 원문 표기를 유지하십시오.
- 영어 Claim 문장은 원문 그대로 남기지 말고 한국어로 번역하십시오. 단, 수치·단위·연도·Claim ID·인용 번호·고유명사·기술 용어는 변경하지 마십시오.
- 보고서 본문 문체는 `-다.` 체로 통일하고, `-습니다.` 체를 사용하지 마십시오.
- 마크다운 전문만 반환하십시오.

{rendered}"""
        polished = ChatOpenAI(model=POLISHING_LLM_MODEL, temperature=0.1).invoke(prompt).content
        return {"report": polished}
    except Exception as error:
        print(f"⚠️ [경고/Fallback] Polishing LLM 호출 실패: {error}")
        return {"report": rendered}
