import re
import shutil
import subprocess
from pathlib import Path

import streamlit as st

from configur import OPENROUTER_API_KEY, get_client, get_default_local_model, get_local_models
from Agents.syllabus_agent import analyze_syllabus
from Agents.research_agent import research_topics
from Agents.notes_agent import generate_notes
from Agents.importance_agent import predict_importance
from Agents.question_agent import generate_questions
from Utilies.pdf_generator import create_pdf


CYBER_NEON_THEME = {
    "bg": (
        "radial-gradient(circle at 15% 20%, rgba(0, 255, 220, 0.18), transparent 42%),"
        "radial-gradient(circle at 80% 15%, rgba(255, 0, 140, 0.18), transparent 36%),"
        "linear-gradient(135deg, #04040b 0%, #0a1023 55%, #050814 100%)"
    ),
    "surface": "rgba(7, 14, 35, 0.78)",
    "text": "#E9F7FF",
    "muted": "#B7D5E8",
    "primary": "#00FFD0",
    "accent": "#FF008C",
    "border": "rgba(0, 255, 220, 0.34)",
    "shadow": "0 0 40px rgba(0, 255, 220, 0.14)",
}


def _extract_topic_items(topics_text, fallback_units):
    if isinstance(topics_text, (list, tuple, set)):
        raw_candidates = [str(item) for item in topics_text]
    else:
        raw_text = str(topics_text or "")
        raw_candidates = re.split(r"[\n,;]+", raw_text)

    cleaned_topics = []
    seen = set()

    for candidate in raw_candidates:
        line = candidate.strip()
        if not line:
            continue

        # Ignore markdown table separators/headers.
        if line.startswith("|"):
            continue
        if set(line.replace(" ", "")) <= {"-", ":", "|"}:
            continue

        # Remove common bullet/number prefixes.
        line = re.sub(r"^[-*•]\s+", "", line)
        line = re.sub(r"^\d+[.)]\s+", "", line)
        line = re.sub(r"^Topic\s*:\s*", "", line, flags=re.IGNORECASE)

        line = re.sub(r"\s+", " ", line).strip(" -")
        if not line:
            continue

        key = line.lower()
        if key in seen:
            continue

        seen.add(key)
        cleaned_topics.append(line)

    if cleaned_topics:
        return cleaned_topics

    # Fallback to direct input units when model output is empty/unexpected.
    return [unit.strip() for unit in fallback_units if unit.strip()]


def _build_topic_mermaid(subject, topic_items):
    """
    Fallback topic map — clean top-down tree matching the screenshot style:
    pink/magenta root → lavender level-2 → light purple level-3 nodes.
    """
    root = (subject or "Subject").replace('"', "'").replace("\n", " ")
    lines = [
        "%%{init: {'theme': 'base', 'themeVariables': {",
        "  'primaryColor': '#E040FB',",
        "  'primaryTextColor': '#1a0030',",
        "  'primaryBorderColor': '#1a0030',",
        "  'lineColor': '#555',",
        "  'secondaryColor': '#D1C4E9',",
        "  'tertiaryColor': '#EDE7F6',",
        "  'background': '#ffffff',",
        "  'fontFamily': 'Arial, sans-serif'",
        "}}}%%",
        "flowchart TD",
        f'    ROOT["{root}"]',
        "    classDef rootStyle fill:#E040FB,stroke:#1a0030,stroke-width:3px,color:#1a0030,font-weight:bold,font-size:15px;",
        "    classDef level2   fill:#D1C4E9,stroke:#7B1FA2,stroke-width:2px,color:#1a0030,font-size:13px;",
        "    classDef level3   fill:#EDE7F6,stroke:#9C27B0,stroke-width:1.5px,color:#1a0030,font-size:12px;",
        "    class ROOT rootStyle;",
    ]

    # Split topics into logical groups of ~3 for level-2 branching
    group_size = max(1, min(4, len(topic_items) // 3 + 1))
    groups = [topic_items[i:i + group_size] for i in range(0, len(topic_items), group_size)]

    for g_idx, group in enumerate(groups, start=1):
        group_label = group[0].replace('"', "'")
        group_id = f"G{g_idx}"
        lines.append(f'    ROOT --> {group_id}["{group_label}"]')
        lines.append(f"    class {group_id} level2;")
        for t_idx, topic in enumerate(group[1:], start=1):
            safe = topic.replace('"', "'")
            node_id = f"G{g_idx}T{t_idx}"
            lines.append(f'    {group_id} --> {node_id}["{safe}"]')
            lines.append(f"    class {node_id} level3;")

    return "\n".join(lines)


def _generate_ai_diagram(subject, topic_items, client, model):
    """
    Ask the LLM to produce a domain-aware hierarchical Mermaid diagram
    styled exactly like the screenshot: pink root, lavender level-2,
    light-purple level-3, clean top-down tree with labelled edges.
    Returns a validated mermaid string, or None on failure.
    """
    topics_str = ", ".join(topic_items)

    # Build a concrete style example the LLM can mirror exactly
    style_header = """\
%%{init: {'theme': 'base', 'themeVariables': {
  'primaryColor': '#E040FB',
  'primaryTextColor': '#1a0030',
  'primaryBorderColor': '#1a0030',
  'lineColor': '#555',
  'secondaryColor': '#D1C4E9',
  'tertiaryColor': '#EDE7F6',
  'background': '#ffffff',
  'fontFamily': 'Arial, sans-serif'
}}}%%
flowchart TD
    ROOT["ReadMe Documentation"]
    classDef rootStyle fill:#E040FB,stroke:#1a0030,stroke-width:3px,color:#1a0030,font-weight:bold;
    classDef level2   fill:#D1C4E9,stroke:#7B1FA2,stroke-width:2px,color:#1a0030;
    classDef level3   fill:#EDE7F6,stroke:#9C27B0,stroke-width:1.5px,color:#1a0030;
    class ROOT rootStyle;
    ROOT --> G1["Guides"]
    class G1 level2;
    G1 --> G1T1["Editor UI"]
    class G1T1 level3;
    G1T1 --> G1T2["Slash Commands"]
    class G1T2 level3;
    G1T2 --> G1T3["Mermaid Diagrams"]
    class G1T3 level3;
    G1T2 --> G1T4["Other Blocks"]
    class G1T4 level3;
    ROOT --> G2["API Reference"]
    class G2 level2;
    G2 --> G2T1["OpenAPI Spec"]
    class G2T1 level3;
    G2 --> G2T2["Manual Editor"]
    class G2T2 level3;"""

    prompt = f"""You are a Mermaid diagram expert. Generate a hierarchical flowchart for the subject "{subject}" covering these topics: {topics_str}.

CRITICAL STYLE RULES — follow these EXACTLY to match the target visual style:
1. Start with this EXACT theme header (copy it verbatim, only changing node content):
```
%%{{init: {{'theme': 'base', 'themeVariables': {{
  'primaryColor': '#E040FB',
  'primaryTextColor': '#1a0030',
  'primaryBorderColor': '#1a0030',
  'lineColor': '#555',
  'secondaryColor': '#D1C4E9',
  'tertiaryColor': '#EDE7F6',
  'background': '#ffffff',
  'fontFamily': 'Arial, sans-serif'
}}}}}}%%
```
2. Direction: `flowchart TD` (top-down ONLY, never LR)
3. Define exactly these 3 classDef styles:
   - `classDef rootStyle fill:#E040FB,stroke:#1a0030,stroke-width:3px,color:#1a0030,font-weight:bold;`  ← hot pink, for the ROOT only
   - `classDef level2   fill:#D1C4E9,stroke:#7B1FA2,stroke-width:2px,color:#1a0030;`  ← lavender, for main topic groups
   - `classDef level3   fill:#EDE7F6,stroke:#9C27B0,stroke-width:1.5px,color:#1a0030;`  ← light purple, for sub-topics
4. Node shapes: use ONLY rectangle `["label"]` for ALL nodes — NO circles, diamonds, or rounded shapes.
5. ROOT node = the subject "{subject}", assigned `class ROOT rootStyle;`
6. Level-2 nodes = major topic categories (3–5 groups), each branching from ROOT
7. Level-3 nodes = specific subtopics branching from their level-2 parent
8. Add domain-specific knowledge: for "{subject}", organize topics into meaningful logical groups with proper parent-child relationships that reflect real domain structure.
9. Use short, clear labels (max 4 words per node).
10. Produce at least 12 nodes total.
11. Output ONLY valid Mermaid syntax — no markdown fences, no explanation.

Here is a complete working example of the EXACT format to follow:
{style_header}

Now generate the diagram for "{subject}" with topics: {topics_str}"""

    try:
        from configur import chat_completion_with_retry
        response = chat_completion_with_retry(
            client,
            model,
            [
                {
                    "role": "system",
                    "content": (
                        "You are an expert Mermaid diagram generator. "
                        "You output ONLY valid Mermaid flowchart syntax, nothing else. "
                        "Never use markdown fences. Never explain. Just output the diagram."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        raw = response.choices[0].message.content.strip()

        # Strip markdown fences if the model added them anyway
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        raw = raw.strip()

        # Enforce correct direction — replace LR/RL/BT with TD
        raw = re.sub(r"flowchart\s+(LR|RL|BT)\b", "flowchart TD", raw)

        # Basic validation
        if raw.startswith("flowchart") or raw.startswith("%%"):
            return raw
        match = re.search(r"(%%\{.*?flowchart\s+\w+.*)", raw, re.DOTALL)
        if match:
            return match.group(1).strip()
        match = re.search(r"(flowchart\s+\w+.*)", raw, re.DOTALL)
        if match:
            return match.group(1).strip()
        return None
    except Exception:
        return None


def _build_topic_graphviz(subject, topic_items):
    root = (subject or "Subject").replace('"', "'")
    lines = [
        "digraph TopicMap {",
        "rankdir=TD;",
        "graph [bgcolor=white, ranksep=0.8, nodesep=0.5, splines=ortho];",
        'node [shape=box, style="filled", fontname="Arial", fontsize=13];',
        f'ROOT [label="{root}", fillcolor="#E040FB", color="#1a0030", fontcolor="#1a0030", penwidth=3, fontsize=15, fontname="Arial Bold"];',
    ]

    group_size = max(1, min(4, len(topic_items) // 3 + 1))
    groups = [topic_items[i:i + group_size] for i in range(0, len(topic_items), group_size)]

    for g_idx, group in enumerate(groups, start=1):
        group_label = group[0].replace('"', "'")
        group_id = f"G{g_idx}"
        lines.append(f'{group_id} [label="{group_label}", fillcolor="#D1C4E9", color="#7B1FA2", fontcolor="#1a0030"];')
        lines.append(f"ROOT -> {group_id};")
        for t_idx, topic in enumerate(group[1:], start=1):
            safe = topic.replace('"', "'")
            node_id = f"G{g_idx}T{t_idx}"
            lines.append(f'{node_id} [label="{safe}", fillcolor="#EDE7F6", color="#9C27B0", fontcolor="#1a0030"];')
            lines.append(f"{group_id} -> {node_id};")

    lines.append("}")
    return "\n".join(lines)


def _required_pdf_diagram_count(mode):
    normalized_mode = (mode or "Last-Minute Prep").strip().lower()
    return 1 if normalized_mode == "last-minute prep" else 3


def _build_pdf_diagram_specs(subject, topic_items, mode, client=None, model=None):
    count = _required_pdf_diagram_count(mode)

    if client and model:
        ai_overview = _generate_ai_diagram(subject, topic_items, client, model)
        overview_mermaid = ai_overview if ai_overview else _build_topic_mermaid(subject, topic_items)
    else:
        overview_mermaid = _build_topic_mermaid(subject, topic_items)

    specs = [("overview", overview_mermaid)]
    if count == 1:
        return specs

    split_idx = max(1, len(topic_items) // 2)
    first_group = topic_items[:split_idx] or topic_items
    second_group = topic_items[split_idx:] or topic_items

    if client and model:
        core_ai = _generate_ai_diagram(f"{subject} - Core Concepts", first_group, client, model)
        adv_ai = _generate_ai_diagram(f"{subject} - Advanced Topics", second_group, client, model)
        specs.append(("core", core_ai if core_ai else _build_topic_mermaid(f"{subject} - Core", first_group)))
        specs.append(("advanced", adv_ai if adv_ai else _build_topic_mermaid(f"{subject} - Advanced", second_group)))
    else:
        specs.append(("core", _build_topic_mermaid(f"{subject} - Core", first_group)))
        specs.append(("advanced", _build_topic_mermaid(f"{subject} - Advanced", second_group)))

    return specs[:count]


def _write_puppeteer_config(diagrams_dir: Path) -> Path:
    """
    Write a puppeteer config that sets a large viewport so mermaid-cli
    renders at full resolution instead of the tiny default 800×600.
    Returns the path to the config file.
    """
    import json
    cfg = {
        "args": ["--no-sandbox", "--disable-setuid-sandbox"],
        "defaultViewport": {
            "width": 2400,
            "height": 1800,
            "deviceScaleFactor": 3,   # 3× = effectively 300 DPI
        },
    }
    cfg_path = diagrams_dir / "puppeteer_cfg.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    return cfg_path


def _compile_mermaid_to_svg(mermaid_text, output_stem):
    diagrams_dir = Path("docs") / "diagrams" / "generated"
    diagrams_dir.mkdir(parents=True, exist_ok=True)

    safe_stem = re.sub(r"[^a-zA-Z0-9_-]", "_", output_stem or "ExamGenie_Notes")
    mmd_path  = diagrams_dir / f"{safe_stem}_topics.mmd"
    svg_path  = diagrams_dir / f"{safe_stem}_topics.svg"

    mmd_path.write_text(mermaid_text, encoding="utf-8")

    if shutil.which("npx") is None:
        return None, "npx was not found. Install Node.js to enable SVG compilation."

    puppeteer_cfg = _write_puppeteer_config(diagrams_dir)

    cmd = [
        "npx", "-y", "@mermaid-js/mermaid-cli",
        "-i", str(mmd_path),
        "-o", str(svg_path),
        "-b", "white",
        "--puppeteerConfigFile", str(puppeteer_cfg),
        "--width",  "2400",
        "--height", "1800",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        error_msg = (result.stderr or result.stdout or "Unknown Mermaid compile error").strip()
        return None, error_msg

    return svg_path, None


def _compile_mermaid_to_png(mermaid_text, output_stem):
    diagrams_dir = Path("docs") / "diagrams" / "generated"
    diagrams_dir.mkdir(parents=True, exist_ok=True)

    safe_stem = re.sub(r"[^a-zA-Z0-9_-]", "_", output_stem or "ExamGenie_Notes")
    mmd_path  = diagrams_dir / f"{safe_stem}_topics.mmd"
    png_path  = diagrams_dir / f"{safe_stem}_topics.png"

    mmd_path.write_text(mermaid_text, encoding="utf-8")

    if shutil.which("npx") is None:
        return None, "npx was not found. Install Node.js to enable PNG compilation."

    puppeteer_cfg = _write_puppeteer_config(diagrams_dir)

    cmd = [
        "npx", "-y", "@mermaid-js/mermaid-cli",
        "-i", str(mmd_path),
        "-o", str(png_path),
        "-b", "white",
        "--puppeteerConfigFile", str(puppeteer_cfg),
        "--width",  "2400",
        "--height", "1800",
        "--scale",  "3",          # 3× pixel density → sharp crisp output
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        # Fallback: try without --scale (older mermaid-cli versions don't support it)
        cmd_fallback = [
            "npx", "-y", "@mermaid-js/mermaid-cli",
            "-i", str(mmd_path),
            "-o", str(png_path),
            "-b", "white",
            "--puppeteerConfigFile", str(puppeteer_cfg),
            "--width",  "2400",
            "--height", "1800",
        ]
        result = subprocess.run(cmd_fallback, capture_output=True, text=True, check=False)

    if result.returncode != 0:
        error_msg = (result.stderr or result.stdout or "Unknown Mermaid compile error").strip()
        return None, error_msg

    # ── Post-process: use Pillow to resample to 300 DPI so PDF embeds cleanly ──
    try:
        from PIL import Image as PilImage
        img = PilImage.open(png_path)
        img.save(png_path, dpi=(300, 300), optimize=True)
    except Exception:
        pass  # Pillow not installed — still usable, just no DPI metadata

    return png_path, None


def _apply_theme():
    theme = CYBER_NEON_THEME

    st.markdown(
        f"""
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700;800&family=Space+Grotesk:wght@500;700&display=swap');

            :root {{
                --bg: {theme['bg']};
                --surface: {theme['surface']};
                --text: {theme['text']};
                --muted: {theme['muted']};
                --primary: {theme['primary']};
                --accent: {theme['accent']};
                --border: {theme['border']};
                --shadow: {theme['shadow']};
                --field-bg: rgba(236, 247, 255, 0.92);
                --field-text: #081224;
                --field-placeholder: #4b607e;
            }}

            .stApp {{
                background: var(--bg);
                color: var(--text);
                font-family: 'Manrope', sans-serif;
            }}

            [data-testid='stSidebar'] {{
                background:
                    radial-gradient(circle at 20% 12%, rgba(0, 255, 208, 0.2), transparent 35%),
                    radial-gradient(circle at 86% 85%, rgba(255, 0, 140, 0.2), transparent 38%),
                    linear-gradient(160deg, rgba(8, 16, 40, 0.96) 0%, rgba(7, 12, 30, 0.96) 100%);
                border-right: 1px solid rgba(0, 255, 208, 0.25);
            }}

            [data-testid='stSidebar'] .block-container {{
                padding-top: 1rem;
                padding-bottom: 1rem;
            }}

            [data-testid='stSidebar'] [data-testid='stWidgetLabel'] p {{
                color: #d6f6ff !important;
                font-size: 0.95rem !important;
                font-weight: 700 !important;
            }}

            [data-testid='stSidebar'] [data-testid='stTextInput'] input,
            [data-testid='stSidebar'] [data-testid='stSelectbox'] div[data-baseweb='select'] > div {{
                background: rgba(236, 247, 255, 0.92) !important;
                border-color: rgba(0, 255, 208, 0.28) !important;
                color: #081224 !important;
            }}

            [data-testid='stSidebar'] .stRadio label {{
                background: transparent !important;
                color: #dff7ff !important;
                border: none !important;
            }}

            [data-testid='stSidebar'] .stRadio label p {{
                color: #dff7ff !important;
                font-weight: 700 !important;
            }}

            [data-testid='stSidebar'] .stRadio [role='radiogroup'] {{
                padding: 0.4rem;
                border: 1px solid rgba(0, 255, 208, 0.22);
                border-radius: 12px;
                background: rgba(255, 255, 255, 0.06);
            }}

            [data-testid='stSidebar'] .stRadio [role='radiogroup'] > label:hover {{
                background: rgba(0, 255, 208, 0.14) !important;
                border-radius: 10px;
            }}

            .sidebar-panel {{
                border: 1px solid rgba(0, 255, 208, 0.32);
                border-radius: 16px;
                background: linear-gradient(145deg, rgba(8, 24, 56, 0.72), rgba(255, 255, 255, 0.08));
                box-shadow: 0 0 30px rgba(0, 255, 208, 0.12);
                padding: 0.85rem 0.9rem;
                margin-bottom: 0.85rem;
            }}

            .sidebar-panel h3 {{
                margin: 0;
                font-size: 1rem;
                letter-spacing: 0.01em;
                color: #ecfbff !important;
                font-family: 'Space Grotesk', sans-serif !important;
            }}

            .sidebar-panel p {{
                margin: 0.32rem 0 0;
                font-size: 0.82rem;
                color: #b7d5e8;
            }}

            .sidebar-badges {{
                display: flex;
                gap: 0.4rem;
                flex-wrap: wrap;
                margin-top: 0.48rem;
            }}

            .sidebar-badge {{
                border: 1px solid rgba(0, 255, 208, 0.38);
                border-radius: 999px;
                padding: 0.18rem 0.55rem;
                font-size: 0.72rem;
                color: #d9fbff;
                background: rgba(0, 255, 208, 0.12);
            }}

            .block-container {{
                padding-top: 2rem;
                padding-bottom: 2.2rem;
                max-width: 1120px;
            }}

            h1, h2, h3 {{
                color: var(--text) !important;
                font-family: 'Space Grotesk', sans-serif !important;
                letter-spacing: -0.02em;
            }}

            [data-testid='stWidgetLabel'] p {{
                color: #d7f2ff !important;
                font-size: 1.12rem !important;
                font-weight: 800 !important;
                letter-spacing: 0.01em;
            }}

            .hero-card {{
                border: 1px solid var(--border);
                background: linear-gradient(135deg, var(--surface) 0%, rgba(255,255,255,0.32) 100%);
                box-shadow: var(--shadow);
                border-radius: 20px;
                padding: 1.2rem 1.25rem;
                margin-bottom: 1rem;
                backdrop-filter: blur(8px);
                animation: rise 420ms ease-out;
            }}

            .tag-row {{
                display: flex;
                flex-wrap: wrap;
                gap: 0.5rem;
                margin-top: 0.7rem;
            }}

            .tag {{
                border: 1px solid var(--border);
                background: rgba(255, 255, 255, 0.38);
                color: var(--muted);
                border-radius: 999px;
                font-size: 0.96rem;
                font-weight: 700;
                padding: 0.38rem 0.9rem;
            }}

            [data-testid='stTextInput'] input,
            [data-testid='stTextArea'] textarea,
            [data-testid='stSelectbox'] div[data-baseweb='select'] > div {{
                border-radius: 14px !important;
                border: 1px solid var(--border) !important;
                background: var(--field-bg) !important;
                color: var(--field-text) !important;
                font-size: 1.03rem !important;
                font-weight: 600 !important;
            }}

            [data-testid='stTextInput'] input::placeholder,
            [data-testid='stTextArea'] textarea::placeholder {{
                color: var(--field-placeholder) !important;
                opacity: 1 !important;
            }}

            /* Hide any unlabeled internal text inputs (ghost bar above Subject). */
            [data-testid='stTextInput'] input[aria-label=''] {{
                display: none !important;
            }}

            [data-testid='stTextInput']:has(input[aria-label='']) {{
                display: none !important;
            }}

            [data-testid='stSelectbox'] div[data-baseweb='select'] span,
            [data-testid='stSelectbox'] [role='combobox'] {{
                color: var(--field-text) !important;
            }}

            .stButton > button,
            .stDownloadButton > button {{
                border-radius: 12px !important;
                border: 1px solid var(--border) !important;
                background: linear-gradient(135deg, var(--primary) 0%, var(--accent) 100%) !important;
                color: white !important;
                font-weight: 700 !important;
                box-shadow: 0 10px 22px rgba(0, 0, 0, 0.16);
            }}

            .stTabs [data-baseweb='tab-list'] {{
                gap: 0.55rem;
            }}

            .stTabs [data-baseweb='tab'] {{
                border-radius: 12px;
                border: 1px solid var(--border);
                background: rgba(255,255,255,0.18);
                color: var(--text);
            }}

            .stTabs [aria-selected='true'] {{
                background: rgba(255,255,255,0.65);
            }}

            .metric-chip {{
                border: 1px solid var(--border);
                border-radius: 12px;
                background: rgba(255, 255, 255, 0.34);
                padding: 0.55rem 0.8rem;
                color: var(--muted);
                font-size: 0.84rem;
                font-weight: 700;
                margin-bottom: 0.6rem;
                text-align: center;
            }}

            [data-testid='stVerticalBlockBorderWrapper'] {{
                border: 1px solid var(--border) !important;
                background: linear-gradient(180deg, var(--surface) 0%, rgba(255,255,255,0.14) 100%) !important;
                box-shadow: var(--shadow) !important;
                border-radius: 16px !important;
            }}

            @media (max-width: 900px) {{
                .block-container {{
                    padding-top: 1.1rem;
                    padding-bottom: 1.2rem;
                }}

                .hero-card {{
                    padding: 0.95rem 0.9rem;
                    border-radius: 14px;
                }}

                .hero-card h1 {{
                    font-size: 1.6rem !important;
                }}

                .hero-card p {{
                    font-size: 0.92rem !important;
                }}

                [data-testid='stWidgetLabel'] p {{
                    font-size: 1rem !important;
                }}

                .tag {{
                    font-size: 0.84rem;
                    padding: 0.32rem 0.74rem;
                }}

                .metric-chip {{
                    font-size: 0.78rem;
                }}
            }}

            @keyframes rise {{
                from {{
                    opacity: 0;
                    transform: translateY(8px);
                }}
                to {{
                    opacity: 1;
                    transform: translateY(0);
                }}
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ===============================
# 🎨 Page Config
# ===============================
st.set_page_config(
    page_title="ExamGenie AI",
    page_icon="📘",
    layout="wide"
)

_apply_theme()

blocked_local_models = {
    "text-embedding-nomic-embed-text-v1.5",
    "mistralai/mistral-7b-instruct",
    "meta-llama/llama-3-8b-instruct",
}

detected_local_models = [
    model_id
    for model_id in list(dict.fromkeys(get_local_models()))
    if model_id not in blocked_local_models
]
detected_local_model = get_default_local_model()

if detected_local_model not in detected_local_models:
    detected_local_model = detected_local_models[0] if detected_local_models else detected_local_model

if "local_model_value" not in st.session_state:
    st.session_state.local_model_value = detected_local_model
if "local_model_choice" not in st.session_state:
    st.session_state.local_model_choice = detected_local_model if detected_local_models else "Custom"
if "openrouter_model_value" not in st.session_state:
    st.session_state.openrouter_model_value = "openai/gpt-4o-mini"
if "openrouter_model_choice" not in st.session_state:
    st.session_state.openrouter_model_choice = "openai/gpt-4o-mini"
if "openrouter_api_key_value" not in st.session_state:
    st.session_state.openrouter_api_key_value = OPENROUTER_API_KEY
if "include_diagrams" not in st.session_state:
    st.session_state.include_diagrams = False

# ===============================
# ⚙️ LLM Sidebar
# ===============================
with st.sidebar:
    st.markdown(
        """
        <div class='sidebar-panel'>
            <h3>AI Control Deck</h3>
            <p>Select provider and model for this generation run.</p>
            <div class='sidebar-badges'>
                <span class='sidebar-badge'>LLM Model</span>
                <span class='sidebar-badge'>OpenRouter</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    llm_backend = st.radio(
        "Backend",
        ["LLM Model", "OpenRouter"],
        index=0,
        help="Local uses LM Studio running on your machine. OpenRouter uses cloud models.",
    )

    if llm_backend == "OpenRouter":
        openrouter_key = st.text_input(
            "OpenRouter API Key",
            type="password",
            key="openrouter_api_key_value",
            placeholder="sk-or-...",
            help="Get your key at https://openrouter.ai/keys",
        )
        openrouter_model_options = [
            "openai/gpt-4o-mini",
            "mistralai/mistral-7b-instruct",
            "meta-llama/llama-3-8b-instruct",
            "Custom",
        ]
        if st.session_state.openrouter_model_choice not in openrouter_model_options:
            st.session_state.openrouter_model_choice = "openai/gpt-4o-mini"

        selected_openrouter_model = st.selectbox(
            "Model",
            options=openrouter_model_options,
            key="openrouter_model_choice",
            help="Choose a model preset or select Custom to type any OpenRouter model.",
        )

        if selected_openrouter_model == "Custom":
            llm_model = st.text_input(
                "Custom model",
                key="openrouter_model_value",
                placeholder="e.g. openai/gpt-4o-mini",
                help="Any model available on OpenRouter. See https://openrouter.ai/models",
            )
        else:
            st.session_state.openrouter_model_value = selected_openrouter_model
            llm_model = selected_openrouter_model

        _backend_key = "openrouter"
        _api_key     = openrouter_key
        _model       = llm_model
    else:
        if detected_local_models:
            local_model_options = detected_local_models + ["Custom"]
            if st.session_state.local_model_choice not in local_model_options:
                st.session_state.local_model_choice = detected_local_model

            selected_local_model = st.selectbox(
                "Detected local models",
                options=local_model_options,
                key="local_model_choice",
                help="Choose a model detected from LM Studio, or switch to Custom to type one manually.",
            )

            if selected_local_model == "Custom":
                llm_model = st.text_input(
                    "Custom model name",
                    key="local_model_value",
                    placeholder="e.g. google/gemma-4-e2b",
                    help="Type any LM Studio model identifier manually.",
                )
            else:
                st.session_state.local_model_value = selected_local_model
                llm_model = selected_local_model

            st.caption(f"Available local models: {', '.join(detected_local_models)}")
        else:
            st.session_state.local_model_choice = "Custom"
            llm_model = st.text_input(
                "Model name",
                key="local_model_value",
                placeholder="e.g. local-model",
                help="The model identifier loaded in LM Studio.",
            )
            st.caption("No local models detected. Make sure LM Studio is running and a model is loaded.")
        _backend_key = "local"
        _api_key     = ""
        _model       = llm_model

    st.markdown(
        """
        <div class='sidebar-panel'>
            <p><strong>Tip:</strong> Settings apply to the next generation only. You can switch provider/model anytime.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

_llm_client, _llm_model = get_client(_backend_key, _api_key, _model)

# ===============================
# 🧾 Title
# ===============================
st.markdown(
    """
    <div class='hero-card'>
        <h1 style='margin:0;'>ExamGenie AI</h1>
        <p style='margin:0.3rem 0 0; color:var(--muted); font-size:1.01rem;'>
            Last-Minute Study Assistant that turns your topics into focused notes, important areas, and exam-ready questions.
        </p>
        <div class='tag-row'>
            <span class='tag'>Exam Focus</span>
            <span class='tag'>PDF Export</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ===============================
# 📥 Inputs
# ===============================
input_col, preview_col = st.columns([2.1, 1])

with input_col:
    with st.container(border=True):
        subject = st.text_input(
            "Subject",
            placeholder="Ex: Machine Learning",
            key="subject_value",
        )

        topics_input = st.text_area(
            "Topics (comma separated)",
            placeholder="Ex: Supervised Learning, Regression, Classification",
            height=130,
            key="topics_value",
        )

        mode = st.selectbox(
            "Study Mode",
            ["Last-Minute Prep", "Deep Focus", "Night Before the Exam"],
            key="mode_value",
        )

with preview_col:
    st.markdown("<div class='metric-chip'>Output: Notes + Importance + Questions</div>", unsafe_allow_html=True)
    st.markdown("<div class='metric-chip'>Mode Depth: Last-Minute Prep / Night Before the Exam / Deep Focus</div>", unsafe_allow_html=True)
    include_diagrams = st.toggle("Include diagrams / flowcharts", key="include_diagrams")
    st.markdown("<div class='metric-chip'>Diagrams are generated only when enabled</div>", unsafe_allow_html=True)
    st.markdown("<div class='metric-chip'>Ready for PDF download</div>", unsafe_allow_html=True)

# ===============================
# 🚀 Generate Button
# ===============================
generate_col, reset_col = st.columns([4, 1])

generate_clicked = generate_col.button("Generate Notes", use_container_width=True)
reset_clicked = reset_col.button("Reset", use_container_width=True)

if reset_clicked:
    st.session_state.subject_value = ""
    st.session_state.topics_value = ""
    st.session_state.mode_value = "Last-Minute Prep"
    st.rerun()

if generate_clicked:

    if not subject or not topics_input:
        st.warning("Please enter subject and topics")
    elif _backend_key == "openrouter" and not (_api_key or OPENROUTER_API_KEY):
        st.error("OpenRouter API key is required. Add it in the sidebar before generating.")

    else:
        progress = st.progress(0, text="Starting generation...")
        try:
            # Prepare input
            units = [u.strip() for u in topics_input.split(",") if u.strip()]

            progress.progress(12, text="Analyzing syllabus...")
            topics = analyze_syllabus(subject, units)
            topic_items = _extract_topic_items(topics, units)
            topic_items = topic_items[:14]
            topic_mermaid = None
            topic_graph_dot = None
            topic_mermaid_is_ai = False
            if include_diagrams:
                # Try AI-powered rich diagram first
                ai_diagram = _generate_ai_diagram(subject, topic_items, _llm_client, _llm_model)
                if ai_diagram:
                    topic_mermaid = ai_diagram
                    topic_mermaid_is_ai = True
                else:
                    topic_mermaid = _build_topic_mermaid(subject, topic_items)
                topic_graph_dot = _build_topic_graphviz(subject, topic_items)

            progress.progress(32, text="Researching topics...")
            context = research_topics(topics, client=_llm_client, model=_llm_model)

            progress.progress(55, text="Writing notes...")
            notes = generate_notes(context, mode, client=_llm_client, model=_llm_model)

            progress.progress(72, text="Scoring important topics...")
            importance = predict_importance(topics, client=_llm_client, model=_llm_model)

            progress.progress(86, text="Generating expected questions...")
            questions = generate_questions(topics, mode, client=_llm_client, model=_llm_model)

            safe_subject = re.sub(r"[^a-zA-Z0-9 _-]", "", subject).strip()
            safe_subject = re.sub(r"\s+", "_", safe_subject)
            pdf_file_name = f"{safe_subject or 'ExamGenie_Notes'}.pdf"

            progress.progress(95, text="Preparing PDF...")
            diagram_pngs_for_pdf = []
            if include_diagrams:
                diagram_specs = _build_pdf_diagram_specs(subject, topic_items, mode, client=_llm_client, model=_llm_model)
                for index, (label, mermaid_markup) in enumerate(diagram_specs, start=1):
                    png_path, _ = _compile_mermaid_to_png(
                        mermaid_markup,
                        f"{safe_subject or 'ExamGenie_Notes'}_{label}_{index}",
                    )
                    if png_path:
                        diagram_pngs_for_pdf.append(str(png_path))

            pdf_file = create_pdf(
                notes,
                importance,
                questions,
                filename=pdf_file_name,
                subject=subject,
                mode=mode,
                diagram_pngs=diagram_pngs_for_pdf,
            )

            progress.progress(100, text="Done")
            progress.empty()
        except Exception as exc:
            progress.empty()
            st.error(
                "LLM provider is temporarily unavailable right now. "
                "Please retry in a few seconds, change model, or switch backend in sidebar."
            )
            st.caption(f"Details: {exc}")
            st.stop()

        # ===============================
        # ✅ Success Message
        # ===============================
        st.success("✅ Notes Generated Successfully!")

        if include_diagrams:
            notes_tab, important_tab, questions_tab, diagram_tab = st.tabs(
                ["📖 Notes", "⭐ Important", "❓ Questions", "🧭 Topic Diagram"]
            )
        else:
            notes_tab, important_tab, questions_tab = st.tabs(
                ["📖 Notes", "⭐ Important", "❓ Questions"]
            )

        with notes_tab:
            with st.container(border=True):
                st.markdown(notes)

        with important_tab:
            with st.container(border=True):
                st.markdown(importance)

        with questions_tab:
            with st.container(border=True):
                st.markdown(questions)

        if include_diagrams and topic_mermaid:
            with diagram_tab:
                with st.container(border=True):
                    if topic_mermaid_is_ai:
                        st.markdown(
                            "<p style='color:#00FFD0;font-size:0.85rem;font-weight:700;margin-bottom:0.5rem;'>"
                            "✨ AI-generated domain-specific diagram</p>",
                            unsafe_allow_html=True,
                        )
                    png_path, png_error = _compile_mermaid_to_png(
                        topic_mermaid,
                        safe_subject or "ExamGenie_Notes",
                    )

                    if png_error is None:
                        st.image(str(png_path), use_container_width=True)
                        with open(png_path, "rb") as png_file:
                            st.download_button(
                                label="📥 Download Topic Diagram (.png)",
                                data=png_file,
                                file_name=Path(png_path).name,
                                mime="image/png",
                                use_container_width=True,
                            )
                    elif topic_graph_dot:
                        st.caption("⚠️ Mermaid compile unavailable — showing Graphviz fallback.")
                        st.graphviz_chart(topic_graph_dot, use_container_width=True)
                    else:
                        st.caption("⚠️ Install Node.js to render diagram as image.")

                    with st.expander("📄 View Mermaid source"):
                        st.code(topic_mermaid, language="text")

        # ===============================
        # 📥 Download PDF
        # ===============================
        with open(pdf_file, "rb") as f:
            st.download_button(
                label="📥 Download PDF",
                data=f,
                file_name=pdf_file_name,
                mime="application/pdf",
                use_container_width=True,
            )