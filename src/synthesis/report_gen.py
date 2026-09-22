"""src/synthesis/report_gen.py - Jinja2 Template rendering & Strict Grounding report node"""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from src.state import OverallState

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
        claims=state.get("claims", [])
    )

    return {"report": rendered}
