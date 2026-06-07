"""WecomWebhook: WeCom group-bot webhook fallback channel.
Docs: https://developer.work.weixin.qq.com/document/path/91770
"""
from __future__ import annotations

import httpx

from marketwind.gateway.im.base import SendResult


class WecomWebhook:
    def __init__(self, *, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def send(self, text: str) -> SendResult:
        try:
            resp = httpx.post(
                self.webhook_url,
                json={"msgtype": "text", "text": {"content": text}},
                timeout=10.0,
            )
            resp.raise_for_status()
            return SendResult(ok=True)
        except httpx.HTTPStatusError as e:
            return SendResult(ok=False, error=f"HTTP {e.response.status_code}")
        except httpx.TransportError as e:
            return SendResult(ok=False, error=str(e))
