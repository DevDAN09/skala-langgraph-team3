"""Report-template level checks: what the rendered report shows, not only what State contains."""
import re

import pytest

from src.synthesis import report_gen
from src.synthesis.evaluator import evaluation_synthesis_node
from src.synthesis.report_gen import report_generation_node, select_overview_claims


def _claim(cid, perspective, tech, statement, kind="fact", status="ok", counter=()):
    return {
        "id": cid, "perspective": perspective, "tech": tech, "statement": statement, "kind": kind,
        "evidence_ids": [f"EV-{cid}"] if status == "ok" else [], "counter_evidence_ids": list(counter),
        "counter_searched": perspective in {"market", "stakeholder"}, "status": status,
    }


def _source(sid, source_type="web"):
    return {"source_id": sid, "title": f"Title {sid}", "publisher": "Pub", "date": "2024",
            "url": f"https://example.com/{sid}", "source_type": source_type, "source_tier": "T2"}


KIVI_MECH = "KIVI quantizes Keys per-channel and Values per-token to 2 bits with a custom GPU kernel."
CXL_MECH = "CXL-PNM keeps the KV cache in CXL memory and runs attention in a near-memory accelerator."

CLAIMS = [
    _claim("DOM-09", "domain", "KIVI", KIVI_MECH),
    _claim("DOM-01", "domain", "KIVI", "KIVI reduces peak memory by 2.6x."),
    _claim("DOM-05", "domain", "KIVI", "KIVI improves throughput by 2.35x-3.47x."),
    _claim("DOM-07", "domain", "KIVI", "KIVI shows small accuracy loss on long-context tasks."),
    _claim("DOM-03", "domain", "KIVI", "KIVI reduces KV transfer volume."),
    _claim("DOM-10", "domain", "CXL-PNM", CXL_MECH, kind="simulation"),
    _claim("DOM-08", "domain", "CXL-PNM", "REJECTED_TEXT should never be shown", status="rejected"),
    _claim("MAT-R01", "maturity", "KIVI", "KIVI is evaluated on Llama-2 with an A100 GPU."),
    _claim("MKT-01", "market", "KIVI", "Vendor X pilots 2-bit KV cache quantization.", counter=["EV-MKT-01-C"]),
    _claim("MKT-02", "market", "KIVI", "vLLM supports FP8 KV cache quantization."),
    _claim("MKT-03", "market", "CXL-PNM", "Cloud Y evaluates CXL memory expansion.", kind="vendor_claim"),
    _claim("MKT-05", "market", "KIVI", "INSUFFICIENT_TEXT should never be shown", status="insufficient"),
    _claim("MAT-A01", "maturity", "KIVI", "KV quantization shows pilot-level adoption signals.", kind="estimate"),
    _claim("STK-01", "stakeholder", "KIVI", "Operators cut GPU memory cost with KV quantization.", counter=["EV-STK-01-C"]),
    _claim("STK-02", "stakeholder", "KIVI", "Framework developers added quantized KV kernels."),
    _claim("STK-04", "stakeholder", "CXL-PNM", "Memory vendors ship CXL modules for AI servers.", kind="vendor_claim"),
]

EVIDENCE = [{"evidence_id": f"EV-{c['id']}", "source_id": f"SRC-{c['id']}", "snippet": c["statement"]} for c in CLAIMS if c["status"] == "ok"]
EVIDENCE += [
    {"evidence_id": "EV-MKT-01-C", "source_id": "SRC-MKT-01-C", "snippet": "Accuracy risk."},
    {"evidence_id": "EV-STK-01-C", "source_id": "SRC-STK-01-C", "snippet": "Operators worry about accuracy."},
    {"evidence_id": "EV-STK-01-C2", "source_id": "SRC-STK-01-C2", "snippet": "Kernel support is limited."},
]
for item in EVIDENCE:
    if item["source_id"] in {"SRC-DOM-09", "SRC-DOM-01", "SRC-DOM-05", "SRC-DOM-07", "SRC-DOM-03", "SRC-MAT-R01"}:
        item["source_id"] = "SRC-PAPER-KIVI"
    if item["source_id"] == "SRC-DOM-10":
        item["source_id"] = "SRC-PAPER-CXL-PNM"
SOURCES = [_source("SRC-PAPER-KIVI", "paper"), _source("SRC-PAPER-CXL-PNM", "paper")]
SOURCES += [_source(sid) for sid in sorted({e["source_id"] for e in EVIDENCE} - {"SRC-PAPER-KIVI", "SRC-PAPER-CXL-PNM"})]

STATE = {
    "selected": {"sw": "KIVI", "hw": "CXL-PNM", "families": {"sw": "KV Quantization", "hw": "CXL Memory Expansion"}},
    "tech_sw": {"name": "KIVI", "mechanism": KIVI_MECH},
    "tech_hw": {"name": "CXL-PNM", "mechanism": CXL_MECH},
    "domain": {
        "infrastructure": {"KIVI": KIVI_MECH, "CXL-PNM": CXL_MECH},
        "bandwidth_transfer": {"KIVI": "KIVI reduces KV transfer volume.", "CXL-PNM": "corpus 내 근거 미확인"},
    },
    "market": {"key_vendors": ["Samsung"], "barriers": "KIVI: accuracy risk at 2-bit | CXL-PNM: new CXL servers required"},
    "stakeholder": {
        "cloud_serving_operator": (
            "[KV Quantization 계열] Benefit: Operators cut GPU memory cost with KV quantization. | Concern: accuracy worries"
            " | Barrier: kernel support limited (근거: STK-01, EV-STK-01, EV-STK-01-C, EV-STK-01-C2)"
            " / [CXL Memory Expansion 계열] 근거 미확인"
        ),
        "framework_developer": (
            "[KV Quantization 계열] Benefit: Framework developers added quantized KV kernels. | Concern: counter-evidence not found"
            " | Barrier: counter-evidence not found (근거: STK-02, EV-STK-02) / [CXL Memory Expansion 계열] 근거 미확인"
        ),
        "end_user": "[KV Quantization 계열] 인용 가능한 지연/품질 간접 근거 미확인 / [CXL Memory Expansion 계열] 인용 가능한 지연/품질 간접 근거 미확인",
        "memory_vendor": "[KV Quantization 계열] 근거 미확인 / [CXL Memory Expansion 계열] Benefit: Memory vendors ship CXL modules for AI servers. | Concern: counter-evidence not found | Barrier: counter-evidence not found (근거: STK-04, EV-STK-04)",
        "cloud_ops": "legacy alias", "hw_vendors": "legacy alias",
    },
    "claims": CLAIMS, "evidence": EVIDENCE, "sources": SOURCES,
}


@pytest.fixture
def report(monkeypatch):
    monkeypatch.setattr(report_gen, "OPENAI_API_KEY", "")
    monkeypatch.setattr(report_gen, "fetch_source_metadata", lambda url: {})
    state = {**STATE, **evaluation_synthesis_node(STATE)}
    return report_generation_node(state)["report"]


def _section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def _reference_numbers(text: str) -> set[str]:
    return set(re.findall(r"^\[(\d+)\] ", text.split("## REFERENCE", 1)[1], re.M))


def test_required_sections_and_numbering(report):
    for heading in ("## SUMMARY", "## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6.", "## REFERENCE",
                    "### 4.1", "### 4.2", "### 4.3", "### 4.4", "### 6.1", "### 6.2"):
        assert heading in report
    assert "습니다" not in report


def test_body_citations_resolve_to_reference_entries(report):
    body = report.split("## REFERENCE", 1)[0]
    cited = set(re.findall(r"\[(\d+)\]", body))
    assert cited and cited == _reference_numbers(report)
    assert re.search(r"\*\*\[DOM-09\]\*\* " + re.escape(KIVI_MECH) + r" \[\d+\]", report)


def test_non_ok_claims_only_appear_in_evidence_gap(report):
    assert "REJECTED_TEXT" not in report and "INSUFFICIENT_TEXT" not in report
    gap = _section(report, "### 6.1", "### 6.2")
    assert "DOM-08(도메인·CXL-PNM)" in gap and "불채택(rejected)" in gap
    assert "MKT-05(시장성·KIVI)" in gap and "근거 부족(insufficient)" in gap
    assert "MKT-05" not in report.split("## 6.", 1)[0]


def test_overview_is_compressed_by_axis_priority_but_state_is_untouched(report):
    assert [c["id"] for c in select_overview_claims(CLAIMS, "KIVI")] == ["DOM-09", "DOM-01", "DOM-05", "DOM-07"]
    overview = _section(report, "### 3.1", "### 3.2")
    assert "DOM-03" not in overview
    assert "4.4" in report and "KIVI reduces KV transfer volume. [DOM-03]" in report
    assert len(STATE["claims"]) == len(CLAIMS)


def test_summary_is_grounded_and_neutral(report):
    summary = _section(report, "## SUMMARY", "## 1.")
    assert "[DOM-09]" in summary and "[DOM-10]" in summary
    assert "우열 또는 추천을 판정하지 않" in summary
    assert "종합 해석" in summary
    for banned in ("더 우수", "추천한다", "승자"):
        assert banned not in report


def test_market_section_cites_real_references(report):
    market = _section(report, "### 4.2", "### 4.3")
    assert re.search(r"\[MKT-01\].*\[\d+\]", market)
    assert re.search(r"\[MKT-02\].*\[\d+\]", market)
    assert re.search(r"\[MAT-A01\].*\(추정\) \[\d+\]", market)
    assert "accuracy risk at 2-bit" in market


def test_all_four_stakeholder_actors_with_citations(report):
    section = _section(report, "### 4.3", "### 4.4")
    for actor in ("클라우드/서빙 운영자", "프레임워크 개발자", "End User", "HW·메모리 공급자"):
        assert actor in section
    assert re.search(r"\[STK-01\]: 이점: .*\[\d+\] / 우려: accuracy worries \[\d+\] / 장벽: kernel support limited \[\d+\]", section)
    assert "우려: 반대 근거 미확인" in section
    assert "인용 가능한 지연/품질 간접 근거 미확인" in section
    assert "legacy alias" not in section


def test_interpretation_is_labeled_and_uncited(report):
    implications = _section(report, "## 5.", "## 6.")
    assert "종합 해석:" in implications and "분석적 제안:" in implications
    assert "결합 구현 자체를 검증한 것은 아니다" in implications
    assert not re.search(r"\[\d+\]", implications)


def test_no_python_repr_in_report(report):
    assert not re.search(r"\['|\{'|'\]|'\}", report)
    assert "None" not in report


def test_in_paper_citation_numbers_are_not_confused_with_references():
    assert report_gen._display("built on modules [41] and [3, 5]") == "built on modules (원문 인용 41) and (원문 인용 3, 5)"


class _FakeLLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    def invoke(self, prompt):
        return type("Message", (), {"content": self.outputs.pop(0)})()


def _polish(monkeypatch, outputs):
    monkeypatch.setattr(report_gen, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(report_gen, "fetch_source_metadata", lambda url: {})
    fake = _FakeLLM(outputs)
    monkeypatch.setattr(report_gen, "ChatOpenAI", lambda **kwargs: fake)
    return report_generation_node({**STATE, **evaluation_synthesis_node(STATE)})["report"]


def test_polishing_that_drops_citations_or_labels_falls_back_to_rendered(monkeypatch):
    report = _polish(monkeypatch, ["## SUMMARY\n다듬은 문장", "```markdown\n## SUMMARY\n다시 다듬은 문장\n```"])
    assert "종합 해석" in report and re.search(r"\[DOM-09\]", report)


def test_polishing_that_keeps_markers_is_used_without_code_fence(monkeypatch):
    monkeypatch.setattr(report_gen, "OPENAI_API_KEY", "")
    monkeypatch.setattr(report_gen, "fetch_source_metadata", lambda url: {})
    rendered = report_generation_node({**STATE, **evaluation_synthesis_node(STATE)})["report"]
    report = _polish(monkeypatch, [f"```markdown\n{rendered}\n```"])
    assert report == rendered.strip()
