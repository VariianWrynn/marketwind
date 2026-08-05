"""Live integration tests for HermesWeixin — send real messages to WeChat.

Run with: pytest tests/im/test_hermes_weixin_live.py -m live -v
Requires: WEIXIN_TOKEN, WEIXIN_ACCOUNT_ID, WEIXIN_CHAT_ID in env (or .env).
Skipped automatically when credentials are missing or hermes module unavailable.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest

from marketwind.gateway.im.hermes_weixin import HermesWeixin, _HERMES_SITE_PACKAGES

pytestmark = pytest.mark.live

_TOKEN = os.getenv("WEIXIN_TOKEN", "")
_ACCOUNT_ID = os.getenv("WEIXIN_ACCOUNT_ID", "")
_CHAT_ID = os.getenv("WEIXIN_CHAT_ID", "")

_has_creds = bool(_TOKEN and _ACCOUNT_ID and _CHAT_ID)
_has_hermes = os.path.isdir(_HERMES_SITE_PACKAGES)

skip_no_creds = pytest.mark.skipif(not _has_creds, reason="WEIXIN_* credentials not set")
skip_no_hermes = pytest.mark.skipif(not _has_hermes, reason="hermes site-packages not found")


def _ensure_hermes_importable():
    if _HERMES_SITE_PACKAGES not in sys.path:
        sys.path.insert(0, _HERMES_SITE_PACKAGES)


@skip_no_hermes
def test_hermes_weixin_module_importable():
    """send_weixin_direct can be imported from hermes' weixin adapter."""
    _ensure_hermes_importable()
    from gateway.platforms.weixin import send_weixin_direct
    assert callable(send_weixin_direct)


@skip_no_hermes
def test_ilink_api_reachable():
    """iLink bot getconfig endpoint responds — proves network + token are valid."""
    _ensure_hermes_importable()
    import asyncio
    import aiohttp
    from gateway.platforms.weixin import (
        _api_post, EP_GET_CONFIG, _base_info,
    )

    async def _check():
        async with aiohttp.ClientSession(trust_env=True) as session:
            return await _api_post(
                session,
                base_url="https://ilinkai.weixin.qq.com",
                endpoint=EP_GET_CONFIG,
                payload={"ilink_user_id": _CHAT_ID},
                token=_TOKEN,
                timeout_ms=10_000,
            )

    result = asyncio.run(_check())
    assert isinstance(result, dict)
    assert "ret" in result or "config" in result or "errcode" in result


@skip_no_creds
@skip_no_hermes
def test_hermes_weixin_send_live():
    """HermesWeixin.send() delivers a real message to WeChat."""
    ch = HermesWeixin(token=_TOKEN, account_id=_ACCOUNT_ID, chat_id=_CHAT_ID)
    tag = uuid.uuid4().hex[:8]
    result = ch.send(f"[MarketWind live test] 集成测试 {tag}，请忽略。")
    assert result.ok is True, f"send failed: {result.error}"


@skip_no_creds
@skip_no_hermes
def test_hermes_weixin_long_message_live():
    """HermesWeixin.send() handles a longer formatted message."""
    ch = HermesWeixin(token=_TOKEN, account_id=_ACCOUNT_ID, chat_id=_CHAT_ID)
    tag = uuid.uuid4().hex[:8]
    report = (
        f"[MarketWind live test {tag}]\n\n"
        "【测试报告摘要】\n"
        "- 科创50指数：测试数据\n"
        "- 成交额：测试数据\n"
        "- 本消息为自动化集成测试，请忽略。"
    )
    result = ch.send(report)
    assert result.ok is True, f"send failed: {result.error}"
