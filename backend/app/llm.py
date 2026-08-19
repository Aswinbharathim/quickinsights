"""LLM dispatch — OpenAI or Claude, switchable via the Setup page (Admin ->
Setup), stored in the metadata database rather than .env — see app/store.py's
get_app_settings_raw()."""
from app import store


def call_openai(system_prompt: str, user_prompt: str, settings: dict | None = None) -> tuple[str, int, int]:
    settings = settings or store.get_app_settings_raw()
    api_key = settings["openai_api_key"]
    if not api_key:
        raise RuntimeError(
            "No OpenAI API key configured. Add one in Admin -> Setup (required when the "
            "LLM provider is set to OpenAI)."
        )

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=settings["openai_chat_model"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
    )
    usage = resp.usage
    text = resp.choices[0].message.content.strip()
    return text, usage.prompt_tokens, usage.completion_tokens


def call_claude(system_prompt: str, user_prompt: str, settings: dict | None = None) -> tuple[str, int, int]:
    settings = settings or store.get_app_settings_raw()
    api_key = settings["anthropic_api_key"]
    if not api_key:
        raise RuntimeError(
            "LLM provider is set to Claude, but no Anthropic API key is configured. "
            "Add one in Admin -> Setup."
        )

    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=settings["claude_model"],
        max_tokens=1024,
        temperature=0,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "".join(block.text for block in msg.content if block.type == "text").strip()
    return text, msg.usage.input_tokens, msg.usage.output_tokens


def llm_generate(system_prompt: str, user_prompt: str) -> tuple[str, int, int]:
    """Dispatch to whichever provider is configured. Returns (text, prompt_tokens, completion_tokens)."""
    settings = store.get_app_settings_raw()
    if settings["llm_provider"] == "anthropic":
        return call_claude(system_prompt, user_prompt, settings)
    return call_openai(system_prompt, user_prompt, settings)


def model_label() -> str:
    settings = store.get_app_settings_raw()
    return settings["openai_chat_model"] if settings["llm_provider"] == "openai" else settings["claude_model"]


def provider_and_model_label() -> tuple[str, str]:
    """Returns (provider, model) for whichever LLM provider is currently
    configured — mirrors embeddings.embed_model_label(), used to tag
    token_usage_events rows for chat/training LLM calls."""
    settings = store.get_app_settings_raw()
    provider = settings["llm_provider"]
    model = settings["openai_chat_model"] if provider == "openai" else settings["claude_model"]
    return provider, model
