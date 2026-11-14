"""HermesWeixin: send via hermes' iLink bot API (send_weixin_direct).

ADR-0001 originally specified the ``hermes send`` CLI, but that subcommand
does not exist.  The verified path is ``send_weixin_direct`` from hermes'
weixin platform adapter — it handles context-token recovery, aiohttp session
lifecycle, and message formatting internally.

Credential resolution: the **live hermes env file** (``/root/.hermes/.env``,
mounted ro from the host) is the source of truth — hermes rotates tokens, and
a stale copy in this process's env vars fails SILENTLY (iLink returns
``success: True`` but never delivers). Constructor args fall back when the
file is missing (e.g. a dev host without hermes installed).
"""
from __future__ import annotations

import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from marketwind.gateway.im.base import SendResult

_HERMES_SITE_PACKAGES = "/opt/hermes-agent/.venv/lib/python3.11/site-packages"
_HERMES_ENV_FILE = "/root/.hermes/.env"
_TIMEOUT_S = 30


def _load_hermes_env() -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines from the live hermes env file.

    Only ``WEIXIN_*`` keys are returned; comments and blank lines are skipped.
    Returns ``{}`` when the file is missing or unreadable (dev environments).
    """
    wanted = {"WEIXIN_TOKEN", "WEIXIN_ACCOUNT_ID", "WEIXIN_HOME_CHANNEL"}
    out: dict[str, str] = {}
    try:
        text = Path(_HERMES_ENV_FILE).read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in wanted:
            out[key] = value.strip()
    return out


class HermesWeixin:
    def __init__(
        self,
        *,
        token: str = "",
        account_id: str = "",
        chat_id: str = "",
        **_legacy: object,
    ) -> None:
        hermes_env = _load_hermes_env()
        self.token = hermes_env.get("WEIXIN_TOKEN") or token
        self.account_id = hermes_env.get("WEIXIN_ACCOUNT_ID") or account_id
        self.chat_id = hermes_env.get("WEIXIN_HOME_CHANNEL") or chat_id

    def send(self, text: str) -> SendResult:
        if not self.token:
            return SendResult(ok=False, error="WEIXIN_TOKEN not configured")
        if not self.account_id:
            return SendResult(ok=False, error="WEIXIN_ACCOUNT_ID not configured")
        if not self.chat_id:
            return SendResult(ok=False, error="WEIXIN_CHAT_ID not configured")
        if not self._ensure_importable():
            return SendResult(ok=False, error="hermes weixin module not available")

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
