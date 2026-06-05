"""Thin DeepSeek client (OpenAI-compatible chat completions) via httpx.

DeepSeek v4-pro is a reasoning model: budget max_tokens generously and read
choices[0].message.content (NOT reasoning_content). No `openai` dependency —
httpx is already present (Karpathy ②), matching scout/discover.py.
"""

from __future__ import annotations

import httpx

from marketwind.config import settings


def parse_chat_completion(payload: dict) -> str:
    """Return the assistant message content from an OpenAI-shape response."""
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("chat completion has no choices")
    content = choices[0].get("message", {}).get("content")
    if not content:
        raise ValueError("chat completion message has empty content")
    return content


async def call_deepseek(messages: list[dict]) -> str:  # pragma: no cover - live
    """POST messages to DeepSeek and return the message content string."""
    base = (settings.openai_base_url or "").rstrip("/")
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    body = {
        # v4-pro is a reasoning model: reasoning_tokens (~6k on a full pool) are
        # billed inside the completion budget BEFORE any JSON is emitted, so a
        # tight max_tokens truncates content to empty. Budget for reasoning +
        # output (found via the P1b live smoke).
        "model": settings.llm_model,
        "messages": messages,
        "max_tokens": 16000,
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(f"{base}/chat/completions", headers=headers, json=body)
        resp.raise_for_status()
        return parse_chat_completion(resp.json())
