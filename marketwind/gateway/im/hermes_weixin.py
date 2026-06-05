"""Thin iLink send client (HermesWeixin). Send-only, static bearer token.

ENDPOINT and payload field names: CONFIRM against hermes iLink before finalizing
(see plan Task 5 note). Token presented as a bearer header by default.
"""
from __future__ import annotations

import httpx

from marketwind.gateway.im.base import SendResult

_ENDPOINT = "https://ilink.example/api/send"  # CONFIRM during implementation


class HermesWeixin:
    def __init__(self, *, account_id: str, token: str) -> None:
        self.account_id = account_id
        self.token = token

    def send(self, text: str) -> SendResult:
        try:
            resp = httpx.post(
                _ENDPOINT,
                headers={"Authorization": f"Bearer {self.token}"},
                json={"account_id": self.account_id, "content": text},
                timeout=10.0,
            )
            resp.raise_for_status()
            return SendResult(ok=True)
        except httpx.HTTPStatusError as e:
            return SendResult(ok=False, error=f"HTTP {e.response.status_code}")
        except httpx.TransportError as e:
            return SendResult(ok=False, error=str(e))
