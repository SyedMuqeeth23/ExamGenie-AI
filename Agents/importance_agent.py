from configur import chat_completion_with_retry, client as _default_client, MODEL as _default_model


def _is_table_separator(line):
    """Return True for markdown table alignment rows like | :--- | --- | :---: |"""
    inner = line.replace("|", "").replace(" ", "")
    return bool(inner) and all(c in {"-", ":"} for c in inner)


def _normalize_importance_output(raw_text):
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return raw_text

    # Detect any markdown table (any line starting with | present anywhere).
    has_table = any(line.startswith("|") for line in lines)

    if has_table:
        bullets = []
        for line in lines:
            if not line.startswith("|"):
                # Keep non-table lines that look like plain bullet points already.
                if line.startswith("-") or line[0].isdigit():
                    bullets.append(line)
                continue

            # Skip separator rows like | :--- | --- |
            if _is_table_separator(line):
                continue

            cols = [col.strip() for col in line.strip("|").split("|")]
            # Skip header rows (contain "Topic" or "Importance")
            if any(c.lower() in {"topic", "importance", "importance score", "tag"} for c in cols):
                continue
            if len(cols) < 2:
                continue

            topic = cols[0]
            score = cols[1] if len(cols) > 1 else ""
            tag = cols[2] if len(cols) > 2 else ""

            if not topic:
                continue

            parts = topic
            if score:
                parts += f": {score}"
                if "/10" not in score:
                    parts += "/10"
            if tag:
                parts += f" ({tag})"
            bullets.append(f"- {parts}")

        return "\n".join(bullets) if bullets else raw_text

    # No table detected — strip any stray separator lines defensively.
    clean = [l for l in lines if not _is_table_separator(l)]
    return "\n".join(clean)

def predict_importance(topics, client=None, model=None):
    client = client or _default_client
    model  = model  or _default_model
    prompt = f"""
    Given these topics:
    {topics}

    Rank them based on exam importance.
    Return only plain bullet points in this exact format:
    - <Topic>: <score>/10 (<Tag>)
    Do not return markdown tables.
    """

    response = chat_completion_with_retry(
        client,
        model,
        [
            {"role": "system", "content": "You are an exam strategist."},
            {"role": "user", "content": prompt},
        ],
    )

    return _normalize_importance_output(response.choices[0].message.content)