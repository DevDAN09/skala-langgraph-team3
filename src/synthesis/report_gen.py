"""src/synthesis/report_gen.py - Jinja2 Template rendering & Strict Grounding report node"""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from src.state import OverallState
from src.config import REPORT_OUTPUT_PATH, OPENAI_API_KEY

def report_generation_node(state: OverallState) -> dict:
    """Generates final report using Jinja2 template and writes to final_evaluation_report.md."""
    print("📝 [보고서 생성] 8대 필수 목차 Jinja2 렌더링 및 최종 보고서 작성 실행")
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
        claims=state.get("claims", [])
    )

    with open(REPORT_OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(rendered)

    return {"report": rendered}
