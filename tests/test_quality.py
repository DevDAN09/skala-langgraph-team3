"""tests/test_quality.py - 보고서 품질 평가: 1단계 규칙, 2단계 Judge, quality_eval 노드"""
import pytest

from src.quality import criteria, judge as judge_mod, node as node_mod, rules as rules_mod
from src.quality.judge import JudgeItem, JudgeVerdict, run_quality_judge
from src.quality.node import quality_eval_node, pick_target
from src.quality.rules import run_quality_rules

GOOD_MD = """# KV Cache 최적화 기술 다관점 평가 보고서

## SUMMARY
KIVI와 CXL-PNM의 관점별 근거를 대조하며 우열은 판정하지 않는다.

## 1. 분석 배경
KV Cache가 메모리 병목이 된다.

## 2. 기술 선정
두 기술을 각 진영의 대표로 선정했다.

## 3. 기술 개요

### 3.1 KIVI (SW 알고리즘)
- **[DOM-01]** KIVI는 피크 메모리를 2.6배 줄인다 (fact) [1]

### 3.2 CXL-PNM (HW 가속)
- **[DOM-02]** CXL-PNM은 처리량을 3.1배 높인다 (simulation) [2]

## 4. 관점별 평가

### 4.1 기술 성숙도 (TRL 이원화)
| KIVI | 5-6 | 7-8 |

### 4.2 시장성 및 생태계
- **시장 수용도**: MKT-01, MKT-02 근거 [3][4]

### 4.3 이해관계자 영향
- **서빙 운영자**: 비용 절감 (STK-01)
- **프레임워크 개발자**: 커널 통합 부담
- **End User**: 지연 개선
- **공급자**: CXL 모듈 수요 (STK-02)

### 4.4 도메인 6대 축 적합성
| 메모리 점유량 | 대역폭·전송 | 처리량·응답 지연 | 정확도 | 인프라 변경 | 운영 복잡도 |

## 5. 시사점

### 5.5 종합 의견
워크로드 조건에 따라 장점과 제약이 달라진다.

## 6. 한계점 및 Evidence Gap
- 미확인 Claim이 없다.

## REFERENCE
[1] Liu(2024). KIVI.
[2] Kim(2024). CXL-PNM.
[3] vLLM docs.
[4] Samsung news.
"""


def _claim(cid, perspective, tech, evidence_ids, status="ok"):
    return {"id": cid, "perspective": perspective, "tech": tech, "statement": f"{cid} statement", "kind": "fact",
            "evidence_ids": evidence_ids, "counter_evidence_ids": [], "counter_searched": True, "status": status}


def good_state():
    claims = [
        _claim("DOM-01", "domain", "KIVI", ["EV-1"]), _claim("DOM-02", "domain", "CXL-PNM", ["EV-2"]),
        _claim("MAT-R01", "maturity", "KIVI", ["EV-1"]), _claim("MAT-R02", "maturity", "CXL-PNM", ["EV-2"]),
        _claim("MKT-01", "market", "KIVI", ["EV-3", "EV-4"]), _claim("MKT-02", "market", "CXL-PNM", ["EV-5", "EV-6"]),
        _claim("STK-01", "stakeholder", "KIVI", ["EV-7", "EV-8"]), _claim("STK-02", "stakeholder", "CXL-PNM", ["EV-9", "EV-10"]),
    ]
    src_of = {"EV-1": "S1", "EV-2": "S2", "EV-3": "S3", "EV-4": "S4", "EV-5": "S5", "EV-6": "S6",
              "EV-7": "S3", "EV-8": "S7", "EV-9": "S5", "EV-10": "S8"}
    evidence = [{"evidence_id": e, "source_id": s, "snippet": f"snippet {e}"} for e, s in src_of.items()]
    sources = [{"source_id": f"S{i}", "title": f"t{i}", "publisher": "p", "date": "2024", "url": f"https://x/{i}",
                "source_type": "web", "source_tier": "T2"} for i in range(1, 9)]
    return {"claims": claims, "evidence": evidence, "sources": sources, "retry_count": {}, "report": GOOD_MD}


@pytest.fixture(autouse=True)
def fixed_pdf_pages(monkeypatch):
    monkeypatch.setattr(rules_mod, "_pdf_pages", lambda md: 3)


def failures(report=GOOD_MD, skeleton=None, state=None):
    items, agents = run_quality_rules(report, skeleton or report, state or good_state())
    return [f for item in items.values() for f in item["failures"]], agents


# ── 1단계 규칙 ──────────────────────────────────────────

def test_good_report_passes_all_rules():
    assert failures() == ([], [])


@pytest.mark.parametrize("old,new,code", [
    ("2.6배 줄인다 (fact) [1]", "2.6배 줄인다 (fact)", "G1"),
    ("[4] Samsung news.", "[4] Samsung news.\n[5] unused.", "G2"),
    ("우열은 판정하지 않는다.", "우열은 판정하지 않는다. DOM-99 참고.", "G3"),
    ("워크로드 조건에 따라", "KIVI를 추천한다. 워크로드 조건에 따라", "N1"),
    ("워크로드 조건에 따라", "KIVI가 CXL-PNM보다 유리하다. 워크로드 조건에 따라", "N2"),
    ("- **End User**: 지연 개선\n", "", "C3"),
    ("| 정확도 ", "| ", "C4"),
    ("## 2. 기술 선정\n두 기술을 각 진영의 대표로 선정했다.\n", "", "C1"),
    ("- **시장 수용도**: MKT-01, MKT-02 근거 [3][4]", "- **시장 수용도**: 검증된 시장 정보가 없다.", "C2"),
    ("## 5. 시사점", "### Why Your LLM Inference Is Slow\n\n## 5. 시사점", "F1"),
    ("| KIVI | 5-6 | 7-8 |", "| {'KIVI': 'x'} |", "F2"),
])
def test_rule_violation_is_detected(old, new, code):
    assert old in GOOD_MD
    fails, _ = failures(GOOD_MD.replace(old, new))
    assert any(f.startswith(code) for f in fails), fails


def test_negated_banned_term_is_allowed():
    md = GOOD_MD.replace("워크로드 조건에 따라", "특정 기술을 추천하지 않는다. 워크로드 조건에 따라")
    assert failures(md) == ([], [])


def test_g4_detects_number_changed_by_polishing():
    fails, _ = failures(GOOD_MD.replace("2.6배", "5배"), skeleton=GOOD_MD)
    assert any(f.startswith("G4") for f in fails)


def test_code_fence_wrapped_report_fails_format():
    fails, _ = failures("```markdown\n" + GOOD_MD + "```")
    assert any("코드 블록" in f for f in fails)


def test_f3_page_limit(monkeypatch):
    monkeypatch.setattr(rules_mod, "_pdf_pages", lambda md: criteria.MAX_PDF_PAGES + 1)
    fails, _ = failures()
    assert any(f.startswith("F3") for f in fails)


def test_bias_rules():
    state = good_state()
    for e in state["evidence"]:
        e["source_id"] = "S3"  # 모든 근거가 한 출처
    fails, agents = failures(state=state)
    assert any(f.startswith("B1") for f in fails)
    assert any(f.startswith("B2") for f in fails) and set(agents) == {"market", "stakeholder"}

    state = good_state()
    for s in state["sources"]:
        s["source_tier"] = "T4"
    state["claims"][4]["counter_searched"] = False
    fails, _ = failures(state=state)
    assert any(f.startswith("B3") for f in fails) and any(f.startswith("B4") for f in fails)


def test_b5_length_ratio_and_switch(monkeypatch):
    md = GOOD_MD.replace("2.6배 줄인다 (fact) [1]", "2.6배 줄인다 (fact) [1]" + " 설명" * 200)
    assert any(f.startswith("B5") for f in failures(md)[0])
    monkeypatch.setattr(criteria, "LENGTH_RATIO_RANGE", None)
    assert not any(f.startswith("B5") for f in failures(md)[0])


def test_c5_missing_cell_routes_to_collector_unless_gap_disclosed():
    state = good_state()
    state["claims"] = [c for c in state["claims"] if c["id"] != "STK-02"]
    md = GOOD_MD.replace(" (STK-02)", "")
    fails, agents = failures(md, state=state)
    assert any(f.startswith("C5") for f in fails) and "stakeholder" in agents

    state["claims"].append(_claim("STK-02", "stakeholder", "CXL-PNM", [], status="insufficient"))
    md = md.replace("- 미확인 Claim이 없다.", "- **[STK-02]** 근거 부족 (상태: `insufficient`)")
    fails, agents = failures(md, state=state)
    assert not any(f.startswith("C5") for f in fails)


# ── 2단계 Judge ─────────────────────────────────────────

class FakeLLM:
    def __init__(self, verdicts):
        self.verdicts, self.calls = list(verdicts), 0

    def __call__(self, **kwargs):
        return self

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages):
        self.calls += 1
        return self.verdicts.pop(0)


def verdict(**scores):
    def item(name):
        score, quotes = scores.get(name, (5, []))
        return JudgeItem(score=score, reason=f"{name} reason", quotes=quotes)
    return JudgeVerdict(**{n: item(n) for n in ("groundedness", "neutrality", "bias", "coverage")})


def _judge(monkeypatch, *verdicts):
    fake = FakeLLM(verdicts)
    monkeypatch.setattr(judge_mod, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(judge_mod, "ChatOpenAI", fake)
    return run_quality_judge(GOOD_MD, good_state()), fake


def test_judge_all_pass(monkeypatch):
    items, _ = _judge(monkeypatch, verdict())
    assert all(i["passed"] for i in items.values())


def test_judge_low_score_with_real_quote_fails(monkeypatch):
    quote = "워크로드 조건에 따라 장점과 제약이 달라진다."
    items, fake = _judge(monkeypatch, verdict(neutrality=(3, [quote])))
    assert not items["neutrality"]["passed"] and items["neutrality"]["quotes"] == [quote]
    assert fake.calls == 1


def test_judge_fabricated_quote_is_retried_then_voided(monkeypatch):
    bad = verdict(bias=(2, ["보고서에 없는 문장"]))
    items, fake = _judge(monkeypatch, bad, bad)
    assert fake.calls == 2
    assert items["bias"]["passed"] and "무효" in items["bias"]["failures"][0]


def test_judge_skipped_without_key_or_on_error(monkeypatch):
    monkeypatch.setattr(judge_mod, "OPENAI_API_KEY", "")
    assert run_quality_judge(GOOD_MD, good_state()) is None

    class Boom(FakeLLM):
        def invoke(self, messages):
            raise RuntimeError("api down")
    monkeypatch.setattr(judge_mod, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(judge_mod, "ChatOpenAI", Boom([]))
    assert run_quality_judge(GOOD_MD, good_state()) is None


# ── quality_eval 노드 ───────────────────────────────────

@pytest.fixture
def node_env(monkeypatch):
    calls = {"judge": 0}

    def fake_judge(report, state):
        calls["judge"] += 1
        return calls.get("judge_result")
    monkeypatch.setattr(node_mod, "render_skeleton", lambda state: state["report"])
    monkeypatch.setattr(node_mod, "run_quality_judge", fake_judge)
    return calls


def test_node_rule_failure_skips_judge_fast_fail(node_env):
    state = {**good_state(), "report": GOOD_MD.replace("워크로드", "KIVI를 추천한다. 워크로드")}
    ev = quality_eval_node(state)["report_eval"]
    assert node_env["judge"] == 0
    assert ev["stage"] == "rules" and not ev["passed"]
    assert ev["target"] == "report_generation" and "N1" in ev["feedback"]


def test_node_passes_with_judge(node_env):
    node_env["judge_result"] = {n: {"passed": True, "score": 5, "failures": [], "quotes": []}
                                for n in ("groundedness", "neutrality", "bias", "coverage")}
    ev = quality_eval_node(good_state())["report_eval"]
    assert ev["passed"] and ev["stage"] == "judge" and ev["target"] is None and ev["feedback"] == ""


def test_node_coverage_gap_targets_collector(node_env):
    state = good_state()
    state["claims"] = [c for c in state["claims"] if c["id"] != "MKT-02"]
    state["report"] = GOOD_MD.replace("MKT-01, MKT-02", "MKT-01")
    assert quality_eval_node(state)["report_eval"]["target"] == "market_research"


def test_node_limit_exhausted_appends_failures_section(node_env):
    state = {**good_state(), "report": GOOD_MD.replace("워크로드", "KIVI를 추천한다. 워크로드"),
             "retry_count": {"report": criteria.REPORT_REVISION_LIMIT}}
    out = quality_eval_node(state)
    assert out["report_eval"]["target"] is None
    assert "### 6.3 품질 평가 미통과 항목" in out["report"]
    assert out["report"].index("### 6.3") < out["report"].index("## REFERENCE")


def test_pick_target_priority():
    assert pick_target({"retry_count": {}}, ["market"]) == "market_research"
    assert pick_target({"retry_count": {"market": 2}}, ["market"]) == "report_generation"
    assert pick_target({"retry_count": {"market": 2, "report": criteria.REPORT_REVISION_LIMIT}}, ["market"]) is None


def test_conftest_mock_judge_returns_passing_verdict(monkeypatch):
    """conftest의 전역 OpenAI mock이 품질 Judge에도 적용되어 실제 API를 부르지 않는다."""
    monkeypatch.setattr(judge_mod, "OPENAI_API_KEY", "test-key")
    items = run_quality_judge(GOOD_MD, good_state())
    assert items is not None and all(i["passed"] and i["score"] == 5 for i in items.values())
