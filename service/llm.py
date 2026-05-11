"""LLM client wrapper for memex.

复用 /home/leon/llm-wiki/tools/_env.py 加载 mimo 凭据。
Provider 中立：mimo / OpenAI / DeepSeek / 任何 OpenAI-compat endpoint。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 复用 llm-wiki 的 env loader（暂时硬编码——P1 末改成 config）
_LLMWIKI_TOOLS = Path("/home/leon/llm-wiki/tools")
if str(_LLMWIKI_TOOLS) not in sys.path:
    sys.path.insert(0, str(_LLMWIKI_TOOLS))

from _env import load_mimo_env  # noqa: E402
from openai import OpenAI  # noqa: E402


DEFAULT_MODEL = "mimo-v2.5"


def get_client() -> OpenAI:
    """Build an OpenAI-compat client from env (mimo by default)."""
    api_key, base_url = load_mimo_env()
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
               不支持则 fallback to 普通 mode（让 caller 自己 parse）。
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
