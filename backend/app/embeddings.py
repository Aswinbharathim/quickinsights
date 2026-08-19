"""Embeddings — switchable between OpenAI and local sentence-transformers via
the Setup page (Admin -> Setup), stored in the metadata database rather than
.env — see app/store.py's get_app_settings_raw()."""
import logging
import os
import time

from app import store

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 5

_st_model_cache: tuple[str, object] | None = None


def _get_st_model(model_name: str, hf_token: str):
    global _st_model_cache
    if _st_model_cache is None or _st_model_cache[0] != model_name:
        if hf_token:
            os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token
        from sentence_transformers import SentenceTransformer

        _st_model_cache = (model_name, SentenceTransformer(model_name))
    return _st_model_cache[1]


def embed_texts(texts: list[str]) -> tuple[list[list[float]], int]:
    """Returns (vectors, tokens_used). tokens_used is 0 for local embeddings."""
    settings = store.get_app_settings_raw()

    if settings["embed_provider"] == "sentence-transformers":
        model = _get_st_model(settings["st_embed_model"], settings["hf_token"])
        vectors = model.encode(texts, show_progress_bar=False)
        return [v.tolist() for v in vectors], 0

    api_key = settings["openai_api_key"]
    if not api_key:
        raise RuntimeError(
            "No OpenAI API key configured. Add one in Admin -> Setup (required when the "
            "embedding provider is set to OpenAI)."
        )

    import openai
    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    last_error = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            resp = client.embeddings.create(model=settings["openai_embed_model"], input=texts)
            return [d.embedding for d in resp.data], resp.usage.total_tokens
        except (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError) as e:
            # A "Train all" on a large schema fans out hundreds of concurrent
            # embedding calls at once — bursting past OpenAI's rate limit on
            # the first attempt is expected, not a real failure. Back off and
            # retry instead of marking the table failed immediately.
            last_error = e
            logger.warning("Embedding call rate-limited/connection issue, retrying (attempt %d): %s", attempt + 1, e)
            time.sleep(min(2**attempt, 20))
        except openai.AuthenticationError:
            # Wrong/missing API key — retrying won't help, fail fast with a
            # clear reason instead of burning through all attempts silently.
            logger.exception("Embedding call failed — authentication error")
            raise
    logger.error("Embedding call failed after %d attempts -- %s", _MAX_ATTEMPTS, last_error)
    raise last_error


def embed_one(text: str) -> tuple[list[float], int]:
    vectors, tokens = embed_texts([text])
    return vectors[0], tokens


def embed_model_label() -> tuple[str, str]:
    """Returns (provider, model) for whichever embedding provider is
    currently configured — mirrors llm.model_label(), used to tag
    token_usage_events rows for embedding calls."""
    settings = store.get_app_settings_raw()
    if settings["embed_provider"] == "sentence-transformers":
        return "sentence-transformers", settings["st_embed_model"]
    return "openai", settings["openai_embed_model"]
