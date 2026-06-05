"""HermesWeixin: thin httpx POST to iLink (field names confirmed during impl)."""
import json
from unittest.mock import patch, MagicMock

import httpx

from marketwind.gateway.im.hermes_weixin import HermesWeixin


def _ok():
    r = MagicMock(spec=httpx.Response)
    r.status_code = 200
    r.raise_for_status = MagicMock()
    return r


def test_send_posts_text_and_returns_ok():
    ch = HermesWeixin(account_id="acc123", token="tok456")
    with patch("httpx.post", return_value=_ok()) as mp:
        res = ch.send("test message")
    assert res.ok is True
    assert mp.called
    blob = json.dumps(mp.call_args.kwargs)
    assert "test message" in blob       # text is in the request somewhere
    assert "tok456" in blob             # token is presented


def test_send_returns_ok_false_on_http_error():
    ch = HermesWeixin(account_id="acc123", token="tok456")
    err = MagicMock(spec=httpx.Response)
    err.status_code = 500
    err.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=err))
    with patch("httpx.post", return_value=err):
        res = ch.send("x")
    assert res.ok is False


def test_send_returns_ok_false_on_transport_error():
    ch = HermesWeixin(account_id="acc123", token="tok456")
    with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
        res = ch.send("x")
    assert res.ok is False
