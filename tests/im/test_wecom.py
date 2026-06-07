"""WecomWebhook: single-URL httpx POST fallback (WeCom group-bot)."""
import json
from unittest.mock import patch, MagicMock

import httpx

from marketwind.gateway.im.wecom_webhook import WecomWebhook

URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test"


def _ok():
    r = MagicMock(spec=httpx.Response)
    r.status_code = 200
    r.raise_for_status = MagicMock()
    return r


def test_posts_to_configured_url_with_text():
    ch = WecomWebhook(webhook_url=URL)
    with patch("httpx.post", return_value=_ok()) as mp:
        res = ch.send("my message")
    assert res.ok is True
    assert mp.call_args.args[0] == URL
    assert "my message" in json.dumps(mp.call_args.kwargs.get("json"))


def test_returns_ok_false_on_http_error():
    ch = WecomWebhook(webhook_url=URL)
    err = MagicMock(spec=httpx.Response)
    err.status_code = 400
    err.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("400", request=MagicMock(), response=err))
    with patch("httpx.post", return_value=err):
        res = ch.send("x")
    assert res.ok is False


def test_returns_ok_false_on_transport_error():
    ch = WecomWebhook(webhook_url=URL)
    with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
        res = ch.send("x")
    assert res.ok is False
