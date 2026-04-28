import os
import time
from openai import OpenAI

# ── Defaults (used when no UI override is provided) ───────────────────────────
LOCAL_MODEL        = "local-model"
OPENROUTER_MODEL   = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# Module-level fallback client (LM Studio).
client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")
MODEL  = LOCAL_MODEL


def get_local_models():
    """Return model IDs exposed by the local LM Studio OpenAI-compatible endpoint."""
    try:
        local_client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")
        response = local_client.models.list()
        return [model.id for model in response.data if getattr(model, "id", None)]
    except Exception:
        return []


def get_default_local_model():
    """Pick the best default local model for text generation."""
    model_ids = get_local_models()
    if not model_ids:
        return LOCAL_MODEL

    preferred_models = [
        model_id
        for model_id in model_ids
        if not any(token in model_id.lower() for token in {"embed", "embedding", "rerank"})
    ]

    return preferred_models[0] if preferred_models else model_ids[0]


def get_client(backend: str, api_key: str = "", model: str = ""):
    """
    Return a (client, model) tuple configured for the chosen backend.

    backend : "local"      → LM Studio at localhost:1234
              "openrouter" → OpenRouter API (requires api_key)
    """
    backend = (backend or "local").strip().lower()

    if backend == "openrouter":
        _client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key or OPENROUTER_API_KEY,
        )
        _model = model.strip() or OPENROUTER_MODEL
    else:
        _client = OpenAI(
            base_url="http://localhost:1234/v1",
            api_key="lm-studio",
        )
        _model = model.strip() or LOCAL_MODEL

    return _client, _model


def _fallback_models_for(model):
    normalized_model = (model or "").strip()

    fallback_map = {
        "openai/gpt-oss-120b:free": ["openai/gpt-4o-mini"],
        "openai/gpt-4o-mini": ["openai/gpt-oss-120b:free"],
    }

    return fallback_map.get(normalized_model, [])


def chat_completion_with_retry(client, model, messages, max_retries=3):
    """
    Call chat completions with simple retry for transient upstream/provider outages.
    """
    last_error = None
    attempted_models = []
    candidate_models = [model] + [m for m in _fallback_models_for(model) if m and m != model]

    for candidate_model in candidate_models:
        attempted_models.append(candidate_model)

        for attempt in range(max_retries):
            try:
                response = client.chat.completions.create(
                    model=candidate_model,
                    messages=messages,
                )
                return response
            except Exception as exc:
                last_error = exc
                error_text = str(exc).lower()

                auth_error = any(
                    marker in error_text
                    for marker in {
                        "401",
                        "missing authentication",
                        "invalid api key",
                        "unauthorized",
                        "authentication",
                    }
                )

                if auth_error:
                    raise RuntimeError(
                        "OpenRouter authentication failed. "
                        "Please add a valid OpenRouter API key in the sidebar (or OPENROUTER_API_KEY env). "
                        f"Details: {exc}"
                    )

                transient_error = any(
                    marker in error_text
                    for marker in {
                        "503",
                        "502",
                        "504",
                        "rate limit",
                        "temporarily unavailable",
                        "no healthy upstream",
                        "timeout",
                        "connection",
                    }
                )

                # Retry only for transient provider/network issues.
                if not transient_error or attempt == max_retries - 1:
                    break

                time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(
        "LLM provider is temporarily unavailable. "
        f"Tried models: {', '.join(attempted_models)}. "
        "Please try again in a few seconds or switch model/provider in sidebar. "
        f"Details: {last_error}"
    )
