"""HermesWeixin: thin wrapper over hermes' send_weixin_direct API."""
import pytest
import types
from unittest.mock import patch, MagicMock

from marketwind.gateway.im.hermes_weixin import HermesWeixin

_CREDS = dict(token="tok", account_id="acct", chat_id="chat")


@pytest.fixture(autouse=True)
def _no_hermes_env(monkeypatch):
    """Point _HERMES_ENV_FILE at a nonexistent path so the parser returns {}.

    Uses the env-file path (not a function patch) so parser tests can still
    exercise real _load_hermes_env by re-monkeypatching the path.
    """
    monkeypatch.setattr(
        "marketwind.gateway.im.hermes_weixin._HERMES_ENV_FILE",
        "/nonexistent/hermes/env",
    )


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


def test_hermes_env_file_takes_precedence_over_constructor():
    """Live hermes file wins over stale constructor values — the fix for the silent-drop bug."""
    with patch(
        "marketwind.gateway.im.hermes_weixin._load_hermes_env",
        return_value={
            "WEIXIN_TOKEN": "live_token",
            "WEIXIN_ACCOUNT_ID": "live_acct",
            "WEIXIN_HOME_CHANNEL": "live_chat",
        },
    ):
        ch = HermesWeixin(token="stale_tok", account_id="stale_acct", chat_id="stale_chat")
    assert ch.token == "live_token"
    assert ch.account_id == "live_acct"
    assert ch.chat_id == "live_chat"


def test_constructor_is_fallback_when_hermes_file_missing():
    with patch("marketwind.gateway.im.hermes_weixin._load_hermes_env", return_value={}):
        ch = HermesWeixin(token="tok", account_id="acct", chat_id="chat")
    assert ch.token == "tok"
    assert ch.account_id == "acct"
    assert ch.chat_id == "chat"


def test_load_hermes_env_parses_weixin_keys_only(tmp_path, monkeypatch):
    """Parser extracts only the three WEIXIN_* keys, skips comments/blanks."""
    from marketwind.gateway.im import hermes_weixin as mod

    env = tmp_path / ".env"
    env.write_text(
        "# comment line\n"
        "WEIXIN_TOKEN=abc\n"
        "WEIXIN_ACCOUNT_ID=def\n"
        "WEIXIN_HOME_CHANNEL=ghi\n"
        "OPENAI_API_KEY=ignored\n"
        "\n"
        "WEIXIN_DM_POLICY=open\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_HERMES_ENV_FILE", str(env))
    result = mod._load_hermes_env()
    assert result == {
        "WEIXIN_TOKEN": "abc",
        "WEIXIN_ACCOUNT_ID": "def",
        "WEIXIN_HOME_CHANNEL": "ghi",
    }


def test_load_hermes_env_missing_file_returns_empty(tmp_path, monkeypatch):
    from marketwind.gateway.im import hermes_weixin as mod

    monkeypatch.setattr(mod, "_HERMES_ENV_FILE", str(tmp_path / "nonexistent"))
    assert mod._load_hermes_env() == {}
