"""src/synthesis/pdf_export.py - Markdown to PDF conversion utility with Korean font support"""
import os
import sys
from pathlib import Path
from typing import Optional

CANDIDATE_FONT_PATHS = [
    Path(__file__).resolve().parent.parent.parent / "data" / "fonts" / "NanumGothic.ttf",
    Path(__file__).resolve().parent.parent.parent / "data" / "fonts" / "AppleGothic.ttf",
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"),
]


def find_korean_font() -> Optional[Path]:
    """Finds available Korean TrueType font file path."""
    for path in CANDIDATE_FONT_PATHS:
        if path.exists() and path.is_file():
            return path
    return None


def convert_markdown_to_pdf(markdown_text: str, output_pdf_path: Path | str) -> bool:
    """Converts a Markdown string to a styled PDF document.

    Args:
        markdown_text: Raw markdown report string.
        output_pdf_path: Target PDF file path.

    Returns:
        bool: True if PDF generation succeeded, False otherwise (Graceful fallback).
    """
    output_path = Path(output_pdf_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import markdown
        from xhtml2pdf import pisa
    except ImportError as e:
        print(f"⚠️ [PDF Export Notice] PDF library not available ({e}). Fallback to Markdown.")
        return False

    try:
        html_body = markdown.markdown(
            markdown_text,
            extensions=["tables", "fenced_code"],
        )

        font_path = find_korean_font()
        font_face_rule = ""
        font_family = "sans-serif"

        if font_path:
            try:
                rel_path = font_path.relative_to(Path.cwd())
                font_src = str(rel_path)
            except ValueError:
                font_src = font_path.as_uri()

            font_face_rule = f"""
            @font-face {{
                font-family: 'KoreanReportFont';
                src: url('{font_src}');
            }}
            * {{
                font-family: 'KoreanReportFont';
            }}
            """
            font_family = "'KoreanReportFont', sans-serif"

        html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
@page {{
    size: a4 portrait;
    margin: 1.5cm;
}}
{font_face_rule}
body {{
    font-family: {font_family};
    font-size: 9.5pt;
    line-height: 1.5;
    color: #2d3748;
}}
h1 {{
    font-size: 16pt;
    color: #1a365d;
    border-bottom: 2px solid #2b6cb0;
    padding-bottom: 4px;
    margin-bottom: 12px;
}}
h2 {{
    font-size: 12.5pt;
    color: #2b6cb0;
    margin-top: 14px;
    margin-bottom: 8px;
    border-bottom: 1px solid #e2e8f0;
    padding-bottom: 3px;
}}
h3 {{
    font-size: 10.5pt;
    color: #2d3748;
    margin-top: 10px;
    margin-bottom: 6px;
}}
p {{
    margin-top: 4px;
    margin-bottom: 6px;
}}
ul, ol {{
    margin-top: 4px;
    margin-bottom: 6px;
    padding-left: 20px;
}}
li {{
    margin-bottom: 3px;
}}
table {{
    width: 100%;
    margin: 10px 0;
}}
th, td {{
    border: 1px solid #cbd5e0;
    padding: 6px 8px;
    text-align: left;
    font-size: 8.5pt;
}}
th {{
    background-color: #edf2f7;
    font-weight: bold;
    color: #1a202c;
}}
blockquote {{
    background-color: #f7fafc;
    border-left: 3px solid #4299e1;
    margin: 8px 0;
    padding: 6px 10px;
    font-size: 8.5pt;
    color: #4a5568;
}}
code {{
    background-color: #edf2f7;
    padding: 2px 4px;
    font-size: 8pt;
}}
hr {{
    border: 0;
    border-top: 1px solid #e2e8f0;
    margin: 12px 0;
}}
</style>
</head>
<body>
{html_body}
</body>
</html>
"""
        with open(output_path, "wb") as f:
            pisa_status = pisa.CreatePDF(html_content, dest=f)

        if pisa_status.err == 0 and output_path.exists() and output_path.stat().st_size > 0:
            return True
        else:
            print(f"⚠️ [PDF Export Warning] pisa returned error code: {pisa_status.err}")
            return False
    except Exception as exc:
        print(f"⚠️ [PDF Export Error] Failed to generate PDF: {exc}")
        return False
