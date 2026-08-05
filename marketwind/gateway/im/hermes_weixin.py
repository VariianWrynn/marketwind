"""HermesWeixin: send via hermes' iLink bot API (send_weixin_direct).

ADR-0001 originally specified the ``hermes send`` CLI, but that subcommand
does not exist.  The verified path is ``send_weixin_direct`` from hermes'
weixin platform adapter — it handles context-token recovery, aiohttp session
lifecycle, and message formatting internally.

Credentials come from config (env vars WEIXIN_TOKEN, WEIXIN_ACCOUNT_ID,
WEIXIN_CHAT_ID), not from this process's memory.
"""
from __future__ import annotations

import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from marketwind.gateway.im.base import SendResult

_HERMES_SITE_PACKAGES = "/opt/hermes-agent/.venv/lib/python3.11/site-packages"
_TIMEOUT_S = 30


class HermesWeixin:
    def __init__(
        self,
        *,
        token: str = "",
        account_id: str = "",
        chat_id: str = "",
        **_legacy: object,
    ) -> None:
        self.token = token
        self.account_id = account_id
        self.chat_id = chat_id

    def send(self, text: str) -> SendResult:
        if not self._ensure_importable():
            return SendResult(ok=False, error="hermes weixin module not available")
        if not self.token:
            return SendResult(ok=False, error="WEIXIN_TOKEN not configured")
        if not self.account_id:
            return SendResult(ok=False, error="WEIXIN_ACCOUNT_ID not configured")
        if not self.chat_id:
            return SendResult(ok=False, error="WEIXIN_CHAT_ID not configured")

        try:
            from gateway.platforms.weixin import send_weixin_direct

            result = self._run(send_weixin_direct(
                extra={"account_id": self.account_id},
                token=self.token,
                chat_id=self.chat_id,
                message=text,
            ))
        except ImportError as e:
            return SendResult(ok=False, error=f"import failed: {e}")
        except Exception as e:
            return SendResult(ok=False, error=f"send failed: {e}")

        if result.get("error"):
            return SendResult(ok=False, error=result["error"])
        return SendResult(ok=True)

    @staticmethod
    def _ensure_importable() -> bool:
        if _HERMES_SITE_PACKAGES not in sys.path and os.path.isdir(_HERMES_SITE_PACKAGES):
            sys.path.insert(0, _HERMES_SITE_PACKAGES)
        return _HERMES_SITE_PACKAGES in sys.path

    @staticmethod
    def _run(coro):  # type: ignore[no-untyped-def]
        """Bridge sync send() to async send_weixin_direct in a worker thread."""
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=_TIMEOUT_S)
