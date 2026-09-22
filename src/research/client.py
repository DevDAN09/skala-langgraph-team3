"""src/research/client.py - Tavily Search wrapper, paired queries, Tier classifier, and shared research utilities"""
from src.config import TAVILY_API_KEY, DEFAULT_LLM_MODEL, OPENAI_API_KEY
from src.state import Source


def classify_tier(url: str) -> str:
    """Classify URL trustworthiness into T1~T4."""
    u = (url or "").lower()
    if any(domain in u for domain in ["arxiv.org", "ieee.org", "acm.org", "computeexpresslink.org"]):
        return "T1"
    if any(domain in u for domain in ["samsung.com", "skhynix.com", "nvidia.com", "intel.com", "github.com"]):
        return "T2"
    if any(domain in u for domain in ["medium.com", "reddit.com", "tistory.com", "velog.io", "substack.com"]):
        return "T4"
    return "T3"


def search_pair(
    support_query: str,
    counter_query: str,
    search_depth: str = "advanced",
    time_range: str | None = None,
) -> tuple[dict, dict | None]:
    """Execute paired support and counter queries for R3 bias mitigation.

    키가 없거나 호출이 실패하면 빈 결과({"results": []})를 반환한다 (Issue #3).
    예전에는 가짜 URL(semiconductor.samsung.com)을 진짜 검색 결과처럼 돌려줘서,
    market/stakeholder가 이를 실제 근거로 착각해 status="ok"인 가짜 Claim과
    가짜 Source를 만들었다. 빈 결과를 주면 호출부의 "결과 없음 -> insufficient"
    경로가 그대로 타져서, 크래시 없이도 근거를 지어내지 않는다 (Graceful Degradation).

    search_depth="advanced"(기본값): Tavily는 자연어 질문형처럼 구체적인 쿼리를
    "basic"보다 "advanced"에서 훨씬 잘 이해하고 관련성 높은 결과를 낸다. 쿼리
    문장 자체를 구체적으로 쓰는 것과 함께, Tavily 쪽 이해도를 높이는 파라미터.
    time_range: "day"/"week"/"month"/"year" 중 하나. 채택·배포 현황처럼 시의성이
    중요한 질의에서 호출부가 명시적으로 넘긴다 (기본 None = 기간 제한 없음).
    """
    if not TAVILY_API_KEY:
        return {"results": []}, None
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=TAVILY_API_KEY)
        sup = client.search(
            query=support_query, max_results=3, search_depth=search_depth, time_range=time_range
        )
        try:
            cnt = client.search(
                query=counter_query, max_results=2, search_depth=search_depth, time_range=time_range
            )
        except Exception:
            cnt = None
        return sup, cnt
    except Exception as e:
        print(f"⚠️ [경고/Fallback] Tavily 호출 실패, 결과 없음으로 처리: {e}")
        return {"results": []}, None


# 벤더 자체 도메인: 이 도메인에서 나온 statement는 독립 검증된 fact가 아니라 vendor_claim으로 분류한다.
VENDOR_DOMAINS = ["samsung.com", "skhynix.com", "nvidia.com", "intel.com"]

# URL -> 사람이 읽을 벤더/생태계 이름. market 노드가 key_vendors를, stakeholder 노드가 쿼리 특화를 위해 사용.
VENDOR_LABELS = {
    "samsung.com": "Samsung",
    "skhynix.com": "SK Hynix",
    "nvidia.com": "NVIDIA",
    "intel.com": "Intel",
    "github.com": "GitHub OSS community",
    "computeexpresslink.org": "CXL Consortium",
}


# 시장 리포트/애널리스트 자료에 흔한 미래 예측 표현. 이런 수치는 실측 fact가 아니라
# estimate로 분류한다 (수치 인용 시 실측/추정 맥락을 병기해야 한다는 팀 룰 대응).
FORECAST_MARKERS = [
    "cagr", "forecast", "projected to", "is expected to reach", "market size",
    "compound annual growth rate", "growth rate of", "by 2030", "by 2031", "by 2032",
    "by 2033", "by 2034", "by 2035",
]


def infer_kind(url: str, content: str = "") -> str:
    """URL·내용으로 Claim의 kind를 추정한다 (R4 대응).

    벤더 공식 도메인에서 가져온 내용은 vendor_claim. 시장 리포트류의 미래 예측/CAGR
    수치는 estimate (실측이 아닌 추정치이므로 fact로 두면 안 됨). 그 외 제3자 보도는 fact.
    content를 안 주면(기본값) 기존처럼 URL만으로 vendor_claim/fact를 판정한다.
    """
    u = (url or "").lower()
    if any(domain in u for domain in VENDOR_DOMAINS):
        return "vendor_claim"
    c = (content or "").lower()
    if any(marker in c for marker in FORECAST_MARKERS):
        return "estimate"
    return "fact"


def vendor_label(url: str) -> str | None:
    """URL 도메인을 사람이 읽을 벤더/생태계 이름으로 변환. 매칭 없으면 None."""
    u = (url or "").lower()
    for domain, label in VENDOR_LABELS.items():
        if domain in u:
            return label
    return None


def resolve_source_id(url: str, existing_sources: list[Source], proposed_id: str) -> str:
    """같은 URL을 가진 Source가 이미 있으면 그 source_id를 재사용한다.

    market/stakeholder가 각자 새 source_id를 발급하면, union_sources 리듀서가
    URL 충돌 시 나중에 들어온 Source를 조용히 버린다. 그러면 이미 발급된
    evidence.source_id가 존재하지 않는 source_id를 가리키게 되어, R2 Tier
    검사와 REFERENCE 출력에서 그 출처가 누락된다. 새 Source를 만들기 전에
    이 함수로 기존 source_id를 먼저 찾아 재사용해 연결이 끊기지 않게 한다.
    """
    norm = (url or "").strip()
    if not norm:
        return proposed_id
    for s in existing_sources or []:
        if (s.get("url") or "").strip() == norm:
            return s["source_id"]
    return proposed_id


def _clip_to_sentence(text: str, limit: int = 220) -> str:
    """limit 근처 문장 경계에서 자른다. 문장부호가 없으면 단순 하드 컷.

    단순 text[:limit]는 문장 중간에서 잘려 어색하거나(R5 Judge가 이상 문장으로
    오판할 수 있음) 읽기 나쁜 statement를 만든다. 마침표/느낌표/물음표 뒤에서
    잘라 완결된 문장을 우선한다.
    """
    clipped = text[:limit]
    best_cut = -1
    for sep in (". ", "! ", "? ", ".\n"):
        idx = clipped.rfind(sep)
        if idx > 40:
            best_cut = max(best_cut, idx + 1)
    return (clipped[:best_cut] if best_cut > 0 else clipped).strip()


def summarize_snippet(content: str, focus: str) -> str:
    """검색 스니펫에서 중립적인 factual 한 문장 statement를 만든다.

    승패 판정/비교 문구를 금지하는 프롬프트로 LLM을 시도하고, 키가 없거나
    호출이 실패하면 원문을 문장 경계에서 잘라 그대로 반환한다 (숫자 창작 금지, Graceful Degradation).
    """
    text = (content or "").strip()
    if not text:
        return ""
    try:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY not set")
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=DEFAULT_LLM_MODEL, temperature=0)
        prompt = (
            "The source text below is scraped from a live web page, so it may start with "
            "navigation menus, page titles, breadcrumbs, a '## References' or link list, ads, "
            "or other boilerplate before the actual article content begins. Read the WHOLE text "
            "and ignore that boilerplate. "
            "Write exactly ONE neutral, factual sentence reporting what the ARTICLE CONTENT "
            f"(not the boilerplate) says about {focus}. "
            "Do not use comparative or evaluative words (better, worse, superior, recommended, best). "
            "Do not invent numbers, dates, or claims that are not present in the text. "
            "Output ONLY the sentence itself, nothing else: no preamble, no meta-commentary about "
            "the text, no explanation of what is missing. "
            'Only reply with the single token NONE if, after reading the whole text, there is truly '
            'no relevant information about the focus anywhere in it.\n\n'
            f"Source text:\n{text[:2000]}"
        )
        resp = llm.invoke(prompt)
        summarized = (getattr(resp, "content", "") or "").strip()
        if not summarized or summarized.strip(' .').upper() == "NONE":
            return _clip_to_sentence(text)
        return summarized
    except Exception as e:
        print(f"⚠️ [경고/Fallback] statement 요약 LLM 호출 실패, 원문 인용으로 대체: {e}")
        return _clip_to_sentence(text)
