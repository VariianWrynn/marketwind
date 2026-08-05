"""HermesWeixin: thin wrapper over hermes' send_weixin_direct API."""
import types
from unittest.mock import patch, MagicMock

from marketwind.gateway.im.hermes_weixin import HermesWeixin

_CREDS = dict(token="tok", account_id="acct", chat_id="chat")


def _stub_weixin_module():
    """Build a sys.modules patch that makes 'from gateway.platforms.weixin import send_weixin_direct' resolve."""
    gw = types.ModuleType("gateway")
    gw_plat = types.ModuleType("gateway.platforms")
    gw_weixin = types.ModuleType("gateway.platforms.weixin")
    gw_weixin.send_weixin_direct = MagicMock()
    gw.platforms = gw_plat
    gw_plat.weixin = gw_weixin
    return {"gateway": gw, "gateway.platforms": gw_plat, "gateway.platforms.weixin": gw_weixin}


def _make(**overrides):
    return HermesWeixin(**{**_CREDS, **overrides})


def test_send_success():
    ch = _make()
    with patch.object(ch, "_ensure_importable", return_value=True), \
         patch.object(ch, "_run", return_value={"success": True}), \
         patch.dict("sys.modules", _stub_weixin_module()):
        res = ch.send("hello")
    assert res.ok is True
    assert res.error is None


def test_missing_token():
    res = HermesWeixin(account_id="a", chat_id="c").send("x")
    assert res.ok is False
    assert "WEIXIN_TOKEN" in (res.error or "")


def test_missing_account_id():
    res = HermesWeixin(token="t", chat_id="c").send("x")
    assert res.ok is False
    assert "WEIXIN_ACCOUNT_ID" in (res.error or "")


def test_missing_chat_id():
    res = HermesWeixin(token="t", account_id="a").send("x")
    assert res.ok is False
    assert "WEIXIN_CHAT_ID" in (res.error or "")


def test_hermes_module_not_available():
    ch = _make()
    with patch.object(ch, "_ensure_importable", return_value=False):
        res = ch.send("x")
    assert res.ok is False
    assert "not available" in (res.error or "")


def test_error_dict_surfaces():
    ch = _make()
    with patch.object(ch, "_ensure_importable", return_value=True), \
         patch.object(ch, "_run", return_value={"error": "iLink rate limited"}), \
         patch.dict("sys.modules", _stub_weixin_module()):
        res = ch.send("x")
    assert res.ok is False
    assert "rate limited" in (res.error or "")


def test_exception_surfaces():
    ch = _make()
    with patch.object(ch, "_ensure_importable", return_value=True), \
         patch.object(ch, "_run", side_effect=RuntimeError("connection refused")), \
         patch.dict("sys.modules", _stub_weixin_module()):
        res = ch.send("x")
    assert res.ok is False
    assert "connection refused" in (res.error or "")


def test_legacy_kwargs_accepted():
    """Old factory passed hermes_bin= and target= — must not raise."""
    ch = HermesWeixin(token="t", account_id="a", chat_id="c", hermes_bin="hermes", target="weixin")
    assert ch.token == "t"
