"""Provider abstraction over the official OpenAI and Anthropic SDKs.

Exposes a single async generator, ``stream_chat``, that yields text deltas.
The rest of the app is provider-agnostic; swap providers via LLM_PROVIDER.
"""

from __future__ import annotations

from typing import AsyncIterator

import config

# Clients are created lazily so importing this module never requires a key
# for the provider you are not using.
_openai_client = None
_anthropic_client = None


def _get_openai():
    global _openai_client
    if _openai_client is None:
        from openai import AsyncOpenAI

        _openai_client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    return _openai_client


def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        from anthropic import AsyncAnthropic

        _anthropic_client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    return _anthropic_client


async def _stream_openai(
    system: str, messages: list[dict]
) -> AsyncIterator[str]:
    client = _get_openai()
    stream = await client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[{"role": "system", "content": system}, *messages],
        max_completion_tokens=config.MAX_TOKENS,
        stream=True,
    )
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content


async def _stream_anthropic(
    system: str, messages: list[dict]
) -> AsyncIterator[str]:
    client = _get_anthropic()
    kwargs: dict = {
        "model": config.ANTHROPIC_MODEL,
        "max_tokens": config.MAX_TOKENS,
        "system": system,
        "messages": messages,
    }
    if config.ANTHROPIC_THINKING:
        kwargs["thinking"] = {"type": "adaptive"}

    async with client.messages.stream(**kwargs) as stream:
        async for text in stream.text_stream:
            yield text


async def stream_chat(system: str, messages: list[dict]) -> AsyncIterator[str]:
    """Stream a completion for the configured provider.

    Args:
        system: The system prompt (components 1 + 4: Goal + Work assignment).
        messages: Full conversation history as ``[{"role", "content"}, ...]``
            with roles ``user``/``assistant`` (multi-turn memory).
    """
    if config.LLM_PROVIDER == "anthropic":
        async for text in _stream_anthropic(system, messages):
            yield text
    else:
        async for text in _stream_openai(system, messages):
            yield text
