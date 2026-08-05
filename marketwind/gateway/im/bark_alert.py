"""BarkAlert: fire-and-forget iOS push via Bark (github.com/Finb/Bark).

Not an IM channel — an out-of-band alert when primary delivery fails.
Uses POST with JSON body so Chinese text encodes cleanly.
"""
from __future__ import annotations

import logging

import httpx

from marketwind.gateway.im.base import SendResult

logger = logging.getLogger(__name__)

_TIMEOUT_S = 10


class BarkAlert:
    def __init__(self, *, bark_url: str) -> None:
        self.bark_url = bark_url.rstrip("/")

    def send(self, text: str) -> SendResult:
        try:
            resp = httpx.post(
                self.bark_url,
                json={"body": text, "title": "MarketWind"},
                timeout=_TIMEOUT_S,
            )
            resp.raise_for_status()
            return SendResult(ok=True)
        except httpx.HTTPStatusError as e:
            logger.warning("bark alert HTTP %s", e.response.status_code)
            return SendResult(ok=False, error=f"HTTP {e.response.status_code}")
        except httpx.TransportError as e:
            logger.warning("bark alert transport error: %s", e)
            return SendResult(ok=False, error=str(e))
