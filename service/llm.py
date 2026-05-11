"""LLM client wrapper for memex.

Provider 中立：mimo / OpenAI / DeepSeek / 任何 OpenAI-compat endpoint。
凭据 + base_url 通过 service.config 解析 (env var > yaml > legacy fallback)。
"""
from __future__ import annotations

from openai import OpenAI

from .config import DEFAULT_MODEL, get_api_key, get_base_url


def get_client() -> OpenAI:
    """Build an OpenAI-compat client from resolved config."""
    api_key = get_api_key()
    base_url = get_base_url()
    return OpenAI(api_key=api_key, base_url=base_url)


def call_llm(
    system: str,
    user: str,
    model: str = DEFAULT_MODEL,
    json_mode: bool = True,
    client: OpenAI | None = None,
) -> str:
    """Single LLM call. Returns raw text content.

    json_mode: 优先 response_format={"type": "json_object"}，
               不支持则 fallback 普通 mode。
    """
    if client is None:
        client = get_client()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    kwargs = {"model": model, "messages": messages}
    if json_mode:
        try:
            resp = client.chat.completions.create(
                **kwargs, response_format={"type": "json_object"}
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            msg = str(e).lower()
            if not any(k in msg for k in ("response_format", "not support", "unsupported")):
                raise
            # fall through to no-json-mode
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""
