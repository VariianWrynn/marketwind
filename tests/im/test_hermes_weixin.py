"""HermesWeixin: thin wrapper over the installed `hermes send` CLI (ADR-0001)."""
import json
from unittest.mock import MagicMock, patch

from marketwind.gateway.im.hermes_weixin import HermesWeixin


def _completed(returncode=0, stdout=b"", stderr=b""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def test_send_invokes_cli_and_returns_ok():
    ch = HermesWeixin(hermes_bin="hermes", target="weixin")
    ok_json = json.dumps({"success": True, "platform": "weixin"}).encode("utf-8")
    with patch("subprocess.run", return_value=_completed(0, ok_json)) as mr:
        res = ch.send("测试 message")
    assert res.ok is True
    cmd = mr.call_args.args[0]
    assert cmd[0] == "hermes"
    assert cmd[1] == "send"
    assert "--to" in cmd and "weixin" in cmd
    # body is piped as UTF-8 on stdin, never as a shell arg
    assert mr.call_args.kwargs["input"] == "测试 message".encode("utf-8")


def test_send_returns_ok_false_on_nonzero_exit():
    ch = HermesWeixin()
    with patch("subprocess.run", return_value=_completed(1, b"", b"delivery failed")):
        res = ch.send("x")
    assert res.ok is False
    assert "delivery failed" in (res.error or "")


def test_send_returns_ok_false_when_json_reports_failure():
    ch = HermesWeixin()
    bad = json.dumps({"success": False, "error": "no target"}).encode("utf-8")
    with patch("subprocess.run", return_value=_completed(0, bad)):
        res = ch.send("x")
    assert res.ok is False


def test_send_returns_ok_false_when_binary_missing():
    ch = HermesWeixin(hermes_bin="nonexistent-hermes")
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        res = ch.send("x")
    assert res.ok is False


def test_nonzero_exit_surfaces_stdout_json_error():
    """On non-zero exit, prefer stdout JSON 'error' field over stderr / 'exit N'."""
    ch = HermesWeixin()
    stdout_json = b'{"error": "iLink sendmessage rate limited: ret=-2 errcode=None errmsg=rate limited"}'
    with patch("subprocess.run", return_value=_completed(1, stdout_json, b"")):
        res = ch.send("hi")
    assert res.ok is False
    assert "rate limited" in res.error


def test_nonzero_exit_falls_back_to_stderr_when_stdout_not_json():
    """Precedence rule 2/3: non-JSON stdout → fall back to stderr (or 'exit N')."""
    ch = HermesWeixin()
    with patch("subprocess.run", return_value=_completed(1, b"not json", b"delivery failed")):
        res = ch.send("x")
    assert res.ok is False
    assert "delivery failed" in (res.error or "")


def test_nonzero_exit_falls_back_to_exit_code_when_both_empty():
    """Precedence rule 3: no stdout JSON, no stderr → 'exit N'."""
    ch = HermesWeixin()
    with patch("subprocess.run", return_value=_completed(2, b"", b"")):
        res = ch.send("x")
    assert res.ok is False
    assert "exit 2" in (res.error or "")
