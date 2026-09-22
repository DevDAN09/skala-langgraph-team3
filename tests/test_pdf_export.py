"""tests/test_pdf_export.py - Unit tests for Markdown to PDF conversion"""
from pathlib import Path
from src.synthesis.pdf_export import convert_markdown_to_pdf, find_korean_font


def test_find_korean_font():
    font_path = find_korean_font()
    assert font_path is not None
    assert font_path.exists()
    assert font_path.suffix.lower() in (".ttf", ".ttc")


def test_convert_markdown_to_pdf(tmp_path):
    sample_md = """# KV Cache 최적화 평가 보고서
    
## 1. 개요
본 문서는 **KIVI** 및 **CXL-PNM** 기술을 다관점에서 평가합니다.

| 기술 | 성숙도 | 비고 |
| :--- | :---: | :--- |
| KIVI | TRL 4 | 2-bit 양자화 |
| CXL-PNM | TRL 3-4 | 7nm 시뮬레이션 |

> 주의: 우열 판정 및 단정적 승자 선언은 배제합니다.
"""
    pdf_out = tmp_path / "test_report.pdf"
    success = convert_markdown_to_pdf(sample_md, pdf_out)

    assert success is True
    assert pdf_out.exists()
    assert pdf_out.stat().st_size > 1000  # Valid PDF size
