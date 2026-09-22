"""src/synthesis/report_gen.py - Jinja2 Template rendering & Strict Grounding report node"""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from langchain_openai import ChatOpenAI
from src.state import OverallState
from src.config import OPENAI_API_KEY, POLISHING_LLM_MODEL

def report_generation_node(state: OverallState) -> dict:
    """Renders the final report for the orchestration layer to persist."""
    print("📝 [보고서 생성] 8대 필수 목차 Jinja2 렌더링 실행")
    templates_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
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
        sources=state.get("sources", []),
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
- 마크다운 전문만 반환하십시오.

{rendered}"""
        polished = ChatOpenAI(model=POLISHING_LLM_MODEL, temperature=0.1).invoke(prompt).content
        return {"report": polished}
    except Exception as error:
        print(f"⚠️ [경고/Fallback] Polishing LLM 호출 실패: {error}")
        return {"report": rendered}
