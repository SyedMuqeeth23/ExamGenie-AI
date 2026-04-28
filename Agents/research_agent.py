from configur import chat_completion_with_retry, client as _default_client, MODEL as _default_model

def research_topics(topics, client=None, model=None):
    client = client or _default_client
    model  = model  or _default_model
    context = ""

    for topic in topics:
        response = chat_completion_with_retry(
            client,
            model,
            [
                {"role": "system", "content": "You are a helpful academic research assistant."},
                {"role": "user", "content": f"Explain {topic} in short for exam preparation."},
            ],
        )
        context += f"\n{topic}:\n{response.choices[0].message.content}\n"

    return context