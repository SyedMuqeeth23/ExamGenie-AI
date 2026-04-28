from configur import chat_completion_with_retry, client as _default_client, MODEL as _default_model


def _question_requirements(mode):
    normalized_mode = (mode or "Last-Minute Prep").strip().lower()

    if normalized_mode == "last-minute prep":
        return {
            "saq": 3,
            "laq": 3,
            "code": 3,
        }

    if normalized_mode == "night before the exam":
        return {
            "saq": 5,
            "laq": 5,
            "code": 5,
        }

    return {
        "saq": 10,
        "laq": 10,
        "code": 10,
    }


def generate_questions(topics, mode="Last-Minute Prep", client=None, model=None):
    client = client or _default_client
    model = model or _default_model
    counts = _question_requirements(mode)
    prompt = f"""
    Generate exam questions for the following topics, treating each topic as a separate module:
    {topics}

    Study mode: {mode}

    For EACH module/topic include at minimum:
    - 2 MCQs (with 4 options labeled A B C D and the correct answer)
    - {counts['saq']} Short answer questions
    - {counts['laq']} Long answer questions
    - {counts['code']} Code-based questions

    Rules:
    - Group questions clearly by module name using this exact heading format: Module: <Topic Name>
    - Create separate sections titled MCQs, SAQs, LAQs, and Code Questions inside each module
    - Number questions sequentially within each section starting from 1
    - Keep SAQs and LAQs on their own lines
    - For every code-based question, include a real code snippet inside triple backticks so it can be rendered cleanly in the PDF
    - Code questions can ask the student to write, debug, trace, complete, or explain the code
    - Do not use markdown tables or latex
    """

    response = chat_completion_with_retry(
        client,
        model,
        [
            {"role": "system", "content": "You are a university examiner."},
            {"role": "user", "content": prompt},
        ],
    )

    return response.choices[0].message.content