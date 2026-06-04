"""Bocha (博查) web-search discovery client. Returns (url, snippet) hits.

Snippets are for discovery only — they NEVER enter a Quote (full text via fetch).
"""

from __future__ import annotations

import httpx

from marketwind.config import settings

_BOCHA_URL = "https://api.bochaai.com/v1/web-search"


def parse_bocha_response(payload: dict) -> list[tuple[str, str]]:
    values = (
        payload.get("data", {}).get("webPages", {}).get("value", [])
    )
    return [(v["url"], v.get("snippet", "")) for v in values if v.get("url")]


async def search(query: str, count: int = 10) -> list[tuple[str, str]]:  # pragma: no cover - live
    headers = {"Authorization": f"Bearer {settings.bocha_api_key}"}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            _BOCHA_URL, headers=headers, json={"query": query, "count": count}
        )
        resp.raise_for_status()
        return parse_bocha_response(resp.json())
