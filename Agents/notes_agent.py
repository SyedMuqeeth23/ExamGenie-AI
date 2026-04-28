from configur import chat_completion_with_retry, client as _default_client, MODEL as _default_model


MAX_CONTEXT_CHARS_PER_CALL = 7000


def _canonical_mode(mode):
    normalized_mode = (mode or "Last-Minute Prep").strip().lower()

    if normalized_mode in {"last-minute prep", "last minute prep", "crash"}:
        return "last-minute prep"

    if normalized_mode in {"night before the exam", "night before exam"}:
        return "night before the exam"

    if normalized_mode in {"deep focus", "deep"}:
        return "deep focus"

    return "last-minute prep"


def _mode_instruction(mode):
    normalized_mode = _canonical_mode(mode)

    if normalized_mode == "last-minute prep":
        return (
            "Last-Minute Prep Requirements:\n"
            "- Target length: about 3 pages of content (roughly 900-1200 words).\n"
            "- Focus on quick revision, only high-yield points and exam shortcuts.\n"
            "- Use compact bullets and short explanations."
        )

    if normalized_mode == "night before the exam":
        return (
            "Night Before the Exam Requirements:\n"
            "- Target length: about 5 pages of content (roughly 1500-2000 words).\n"
            "- Cover each topic clearly with examples and likely exam angles.\n"
            "- Add a short last-minute checklist at the end."
        )

    return (
        "Deep Focus Requirements:\n"
        "- Target length: about 10 pages of content (roughly 3000-4000 words).\n"
        "- Explain concepts in depth with detailed examples, comparisons, and edge cases.\n"
        "- Include deeper understanding notes and memory aids."
    )


def _chunk_context(context, max_chars=MAX_CONTEXT_CHARS_PER_CALL):
    text = (context or "").strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if len(paragraph) <= max_chars:
            current = paragraph
            continue

        # Hard split oversized paragraphs to keep each call within limits.
        for i in range(0, len(paragraph), max_chars):
            piece = paragraph[i : i + max_chars]
            if len(piece) == max_chars:
                last_space = piece.rfind(" ")
                if last_space > 0:
                    piece = piece[:last_space]
            chunks.append(piece.strip())
        current = ""

    if current:
        chunks.append(current)

    return [c for c in chunks if c]


def _call_notes_model(context_chunk, mode, mode_rules, client, model, part_index=None, total_parts=None):
    part_hint = ""
    if part_index is not None and total_parts is not None:
        part_hint = (
            f"\nThis is part {part_index} of {total_parts} from a larger source. "
            "Write coherent notes for this part, and avoid repeating generic intros."
        )

    prompt = f"""
    Create exam notes from the following content.

    Mode: {mode}

    Rules:
    - Keep it structured with clear headings and subheadings
    - Use bullet points where useful
    - Highlight important concepts and exam tips
    - Do not include markdown artifacts like ###, **, ---, or latex syntax

    {mode_rules}
    {part_hint}

    Content:
    {context_chunk}
    """

    response = chat_completion_with_retry(
        client,
        model,
        [
            {"role": "system", "content": "You are an expert teacher."},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content


def generate_notes(context, mode="Last-Minute Prep", client=None, model=None):
    client = client or _default_client
    model  = model  or _default_model
    mode_rules = _mode_instruction(mode)
    chunks = _chunk_context(context)

    if not chunks:
        return "No content was available to generate notes."

    if len(chunks) == 1:
        return _call_notes_model(chunks[0], mode, mode_rules, client, model)

    section_notes = []
    total = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        notes = _call_notes_model(
            chunk,
            mode,
            mode_rules,
            client,
            model,
            part_index=index,
            total_parts=total,
        )
        section_notes.append(f"Section {index}\n{notes.strip()}")

    return "\n\n".join(section_notes)