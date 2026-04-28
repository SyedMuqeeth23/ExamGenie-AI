import re
import textwrap
from pathlib import Path
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    HRFlowable, Image, Paragraph, Preformatted,
    SimpleDocTemplate, Spacer, Table, TableStyle, KeepTogether,
)


PAGE_TEXT = colors.HexColor("#37352F")
MUTED_TEXT = colors.HexColor("#787774")
RULE_COLOR = colors.HexColor("#E9E5E3")
SURFACE = colors.HexColor("#F7F6F3")

# ── Code block dark theme ─────────────────────────────────────────────────────
CODE_BG        = colors.HexColor("#0D1117")   # GitHub dark background
CODE_BORDER    = colors.HexColor("#00D4FF")   # Neon cyan border
CODE_TEXT      = colors.HexColor("#C9D1D9")   # Default code text (light grey)
CODE_HEADER_BG = colors.HexColor("#161B22")   # Header bar background
CODE_HEADER_FG = colors.HexColor("#58A6FF")   # Header label (blue)
CODE_GUTTER_BG = colors.HexColor("#0D1117")

# Syntax token approximate colors (applied via line-level heuristics)
COLOR_KEYWORD  = colors.HexColor("#FF7B72")   # Red-orange  — def, class, if, for…
COLOR_STRING   = colors.HexColor("#A5D6FF")   # Sky blue    — quoted strings
COLOR_COMMENT  = colors.HexColor("#8B949E")   # Grey        — # comments
COLOR_NUMBER   = colors.HexColor("#F2CC60")   # Gold        — numeric literals
COLOR_BUILTIN  = colors.HexColor("#D2A8FF")   # Lavender    — print, len, type…
COLOR_PUNCT    = colors.HexColor("#56D364")   # Green       — brackets, operators


def _build_styles():
    base_styles = getSampleStyleSheet()

    return {
        "title": ParagraphStyle(
            "NotionTitle",
            parent=base_styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=27,
            textColor=PAGE_TEXT,
            spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "NotionSubtitle",
            parent=base_styles["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=12,
            textColor=MUTED_TEXT,
            spaceAfter=0,
        ),
        "section_label": ParagraphStyle(
            "NotionSectionLabel",
            parent=base_styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=10,
            textColor=MUTED_TEXT,
            spaceAfter=0,
        ),
        "body": ParagraphStyle(
            "NotionBody",
            parent=base_styles["BodyText"],
            fontName="Helvetica",
            fontSize=11,
            leading=13,
            textColor=PAGE_TEXT,
            spaceAfter=0,
        ),
        "bullet": ParagraphStyle(
            "NotionBullet",
            parent=base_styles["BodyText"],
            fontName="Helvetica",
            fontSize=11,
            leading=13,
            textColor=PAGE_TEXT,
            leftIndent=14,
            firstLineIndent=-8,
            spaceAfter=2,
        ),
        "code": ParagraphStyle(
            "NotionCode",
            parent=base_styles["Code"],
            fontName="Courier",
            fontSize=8.5,
            leading=10.5,
            textColor=CODE_TEXT,
            backColor=CODE_BG,
            leftIndent=8,
            rightIndent=0,
            spaceAfter=0,
        ),
        "code_header": ParagraphStyle(
            "CodeHeader",
            parent=base_styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=9,
            textColor=CODE_HEADER_FG,
            backColor=CODE_HEADER_BG,
            leftIndent=8,
            spaceAfter=0,
        ),
    }


def _is_list_item(line):
    stripped = line.strip()
    return bool(re.match(r"^([-*•]|\d+[.)])\s+", stripped))


def _clean_list_item(line):
    return re.sub(r"^([-*•]|\d+[.)])\s+", "", line.strip())


def _clean_render_text(text):
    cleaned = text.strip()

    # Drop markdown horizontal rules like ---, ***, ___
    if re.match(r"^\s*([-*_]\s*){3,}\s*$", cleaned):
        return ""

    # Remove markdown heading markers like ## Heading
    cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", cleaned)

    # Convert common markdown emphasis markers into plain text
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"__(.*?)__", r"\1", cleaned)
    cleaned = re.sub(r"\*(.*?)\*", r"\1", cleaned)
    cleaned = re.sub(r"_(.*?)_", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)

    # Simplify latex-like inline math patterns such as ($\text{Y}$)
    cleaned = re.sub(r"\\text\{([^}]*)\}", r"\1", cleaned)
    cleaned = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", cleaned)
    cleaned = re.sub(r"\$(.*?)\$", r"\1", cleaned)

    # Remove leftover escape slashes and repeated markdown stars
    cleaned = cleaned.replace("\\", "")
    cleaned = re.sub(r"\*{2,}", "", cleaned)
    cleaned = re.sub(r"\s+[-*]\s+", " ", cleaned)

    return re.sub(r"\s+", " ", cleaned).strip()


def _wrap_code_text(code_text, width=72):
    wrapped_lines = []
    for raw_line in code_text.splitlines():
        line = raw_line.rstrip()
        indent = len(line) - len(line.lstrip(" "))
        prefix = " " * min(indent, 12)
        content = line.lstrip(" ") or " "
        wrapped = textwrap.wrap(
            content,
            width=max(18, width - len(prefix)),
            replace_whitespace=False,
            drop_whitespace=False,
            break_long_words=True,
            break_on_hyphens=False,
        )
        if not wrapped:
            wrapped_lines.append("")
            continue
        for part in wrapped:
            wrapped_lines.append(f"{prefix}{part}")
    return "\n".join(wrapped_lines)


def _detect_language(code_text):
    """Heuristically detect language for the header label."""
    if re.search(r"\bdef\b|\bimport\b|\bprint\s*\(", code_text):
        return "Python"
    if re.search(r"\bpublic\s+class\b|\bSystem\.out\b", code_text):
        return "Java"
    if re.search(r"#include|std::|cout\s*<<", code_text):
        return "C++"
    if re.search(r"\bfunction\b|\bconsole\.log\b|\bconst\b|\blet\b", code_text):
        return "JavaScript"
    if re.search(r"\bSELECT\b|\bFROM\b|\bWHERE\b", code_text, re.IGNORECASE):
        return "SQL"
    if re.search(r"\bfn\s+\w+\b|\blet\s+mut\b", code_text):
        return "Rust"
    return "Code"


def _colorize_line(line):
    """
    Return (text, color) for a code line using simple pattern matching.
    We keep it to one dominant color per line for PDF simplicity.
    """
    stripped = line.strip()

    # Comments
    if re.match(r"^\s*(#|//|--)", line):
        return line, COLOR_COMMENT

    # String lines (dominant content is a string)
    if re.search(r'["\'].*["\']', line) and not re.match(r"^\s*(def|class|import|from|if|for|while|return)\b", line):
        return line, COLOR_STRING

    # Keywords
    if re.match(r"^\s*(def|class|import|from|if|elif|else|for|while|return|try|except|finally|with|as|pass|break|continue|raise|yield|lambda|and|or|not|in|is)\b", line):
        return line, COLOR_KEYWORD

    # Numbers-heavy lines
    if re.match(r"^\s*[\d\.\-+]+\s*$", stripped):
        return line, COLOR_NUMBER

    # Builtin functions
    if re.match(r"^\s*(print|len|range|type|list|dict|set|tuple|int|float|str|bool|input|open|map|filter|zip|enumerate)\s*\(", line):
        return line, COLOR_BUILTIN

    # Punctuation-heavy (operators / assignments)
    if re.search(r"[=+\-*/<>!&|^]{2,}", line):
        return line, COLOR_PUNCT

    return line, CODE_TEXT


def _append_code_block(content, code_text, styles):
    """Render a beautiful dark-theme code block with syntax-hint coloring."""
    cleaned_code = code_text.strip("\n")
    if not cleaned_code:
        return

    lang = _detect_language(cleaned_code)
    wrapped_text = _wrap_code_text(cleaned_code, width=76)
    code_lines = wrapped_text.splitlines()

    # ── Build a table: [gutter | code line] ─────────────────────────────────
    GUTTER_W = 28
    row_data = []
    row_styles = []

    for i, raw_line in enumerate(code_lines):
        line_text, line_color = _colorize_line(raw_line)
        line_num = Paragraph(
            f'<font color="#3C4858">{i + 1}</font>',
            ParagraphStyle(
                f"Gutter{i}",
                fontName="Courier",
                fontSize=7,
                leading=10.5,
                textColor=colors.HexColor("#3C4858"),
                backColor=CODE_HEADER_BG,
                alignment=2,  # right-align
            ),
        )
        # Escape XML special chars for Paragraph
        safe_line = escape(raw_line) if raw_line.strip() else " "
        # Convert reportlab color to #rrggbb for XML font tag
        try:
            hex_color = "#" + line_color.hexval()[2:]
        except Exception:
            hex_color = "#C9D1D9"
        # Build colored Paragraph
        code_para = Paragraph(
            f'<font name="Courier" color="{hex_color}">{safe_line}</font>',
            ParagraphStyle(
                f"CodeLine{i}",
                fontName="Courier",
                fontSize=8.5,
                leading=10.5,
                textColor=line_color,
                backColor=CODE_BG,
                leftIndent=4,
            ),
        )
        row_data.append([line_num, code_para])

    if not row_data:
        return

    # ── Header row ─────────────────────────────────────────────────────────
    header_para = Paragraph(
        f'<font name="Helvetica-Bold" color="#58A6FF">⬡  {lang}</font>'
        f'<font name="Helvetica" color="#8B949E">  •  {len(code_lines)} lines</font>',
        ParagraphStyle(
            "CodeHeaderInner",
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=CODE_HEADER_FG,
            backColor=CODE_HEADER_BG,
            leftIndent=6,
        ),
    )
    # Header spans full width
    header_row = [[header_para, ""]]

    all_rows = header_row + row_data

    # Determine available page width (approximate)
    page_width = 504  # letter width minus margins ~= 7in
    code_col_w = page_width - GUTTER_W

    tbl = Table(
        all_rows,
        colWidths=[GUTTER_W, code_col_w],
        repeatRows=1,
    )

    n = len(all_rows)
    tbl_style_cmds = [
        # Header row
        ("SPAN",        (0, 0), (1, 0)),
        ("BACKGROUND",  (0, 0), (1, 0), CODE_HEADER_BG),
        ("TOPPADDING",  (0, 0), (1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (1, 0), 5),
        # Gutter column
        ("BACKGROUND",  (0, 1), (0, n - 1), CODE_HEADER_BG),
        ("TOPPADDING",  (0, 1), (0, n - 1), 1),
        ("BOTTOMPADDING", (0, 1), (0, n - 1), 1),
        ("RIGHTPADDING", (0, 1), (0, n - 1), 4),
        # Code column
        ("BACKGROUND",  (1, 1), (1, n - 1), CODE_BG),
        ("TOPPADDING",  (1, 1), (1, n - 1), 1),
        ("BOTTOMPADDING", (1, 1), (1, n - 1), 1),
        ("LEFTPADDING", (1, 1), (1, n - 1), 4),
        # Outer border
        ("BOX",         (0, 0), (-1, -1), 1.5, CODE_BORDER),
        # Vertical divider between gutter and code
        ("LINEAFTER",   (0, 1), (0, n - 1), 0.5, colors.HexColor("#21262D")),
        # Alternating row tint
        *[
            ("BACKGROUND", (1, r), (1, r), colors.HexColor("#0D1117") if r % 2 == 1 else colors.HexColor("#111720"))
            for r in range(1, n)
        ],
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
    ]

    tbl.setStyle(TableStyle(tbl_style_cmds))

    try:
        content.append(KeepTogether([tbl]))
    except Exception:
        content.append(tbl)

    content.append(Spacer(1, 10))


def _append_regular_block(content, text, styles):
    blocks = re.split(r"\n\s*\n", text.strip())

    for block in blocks:
        lines = [_clean_render_text(line) for line in block.splitlines() if line.strip()]
        lines = [line for line in lines if line]
        if not lines:
            continue

        paragraph_buffer = []

        def flush_paragraph():
            if paragraph_buffer:
                paragraph = "<br/>".join(escape(line) for line in paragraph_buffer)
                content.append(Paragraph(paragraph, styles["body"]))
                content.append(Spacer(1, 5))
                paragraph_buffer.clear()

        for line in lines:
            if _is_list_item(line):
                flush_paragraph()
                bullet_text = escape(_clean_list_item(line))
                content.append(Paragraph(f"• {bullet_text}", styles["bullet"]))
            else:
                paragraph_buffer.append(line)

        flush_paragraph()
        content.append(Spacer(1, 3))


def _append_text_block(content, text, styles):
    parts = re.split(r"(```.*?```)", text.strip(), flags=re.DOTALL)

    for part in parts:
        if not part.strip():
            continue

        if part.startswith("```") and part.endswith("```"):
            code_text = re.sub(r"^```[a-zA-Z0-9_+-]*\n?", "", part)
            code_text = re.sub(r"\n?```$", "", code_text)
            _append_code_block(content, code_text, styles)
            continue

        _append_regular_block(content, part, styles)


def _add_section(content, title, text, styles):
    content.append(Spacer(1, 14))
    content.append(Paragraph(escape(title.upper()), styles["section_label"]))
    content.append(Spacer(1, 4))
    content.append(
        HRFlowable(
            width="100%",
            thickness=0.7,
            color=RULE_COLOR,
            spaceBefore=0,
            spaceAfter=9,
        )
    )
    _append_text_block(content, text, styles)


def _svg_to_png(svg_path):
    try:
        import cairosvg
        png_path = str(svg_path).replace(".svg", "_pdf.png")
        cairosvg.svg2png(url=str(svg_path), write_to=png_path, scale=3.0, dpi=300)
        return png_path
    except Exception:
        return None


def create_pdf(
    notes,
    importance,
    questions,
    filename="ExamGenie_Output.pdf",
    subject=None,
    mode=None,
    diagram_svg=None,
    diagram_svgs=None,
    diagram_pngs=None,
):
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=56,
        bottomMargin=56,
    )
    styles = _build_styles()
    content = []

    title_text = Path(filename).stem or "ExamGenie AI"
    content.append(Paragraph(escape(title_text), styles["title"]))

    metadata = [datetime.now().strftime("Generated on %d %b %Y")]
    if subject:
        metadata.insert(0, f"Subject: {subject}")
    if mode:
        metadata.append(f"Mode: {mode}")

    header_table = Table(
        [[Paragraph(" | ".join(escape(item) for item in metadata), styles["subtitle"]) ]],
        colWidths=[doc.width],
    )
    header_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                ("BOX", (0, 0), (-1, -1), 0.6, RULE_COLOR),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )

    content.append(header_table)
    content.append(Spacer(1, 14))

    _add_section(content, "Important Topics", importance, styles)

    png_sources = [p for p in (diagram_pngs or []) if p]
    svg_sources = [s for s in (diagram_svgs or []) if s]
    if not svg_sources and diagram_svg:
        svg_sources = [diagram_svg]

    if png_sources or svg_sources:
        content.append(Spacer(1, 14))
        content.append(Paragraph("TOPIC FLOWCHARTS", styles["section_label"]))
        content.append(Spacer(1, 4))
        content.append(
            HRFlowable(
                width="100%",
                thickness=0.7,
                color=RULE_COLOR,
                spaceBefore=0,
                spaceAfter=9,
            )
        )

        image_paths = list(png_sources)
        if not image_paths and svg_sources:
            for svg_source in svg_sources:
                png_path = _svg_to_png(svg_source)
                if png_path:
                    image_paths.append(png_path)

        for idx, image_path in enumerate(image_paths, start=1):
            if len(image_paths) > 1:
                content.append(Paragraph(f"Flowchart {idx}", styles["subtitle"]))
                content.append(Spacer(1, 3))

            # ── Aspect-ratio aware, full-width, high-quality embed ──────────
            try:
                from PIL import Image as PilImage
                with PilImage.open(image_path) as pil_img:
                    px_w, px_h = pil_img.size
                aspect = px_h / px_w if px_w > 0 else 0.6
            except Exception:
                aspect = 0.6   # safe fallback

            # Cap height so diagram never spills onto next page
            img_w = doc.width
            img_h = min(img_w * aspect, doc.height * 0.72)

            img = Image(image_path, width=img_w, height=img_h)
            img.hAlign = "CENTER"
            content.append(img)
            content.append(Spacer(1, 10))

    _add_section(content, "Notes", notes, styles)
    _add_section(content, "Questions", questions, styles)

    doc.build(content)
    return filename