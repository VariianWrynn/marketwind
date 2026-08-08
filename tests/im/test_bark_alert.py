"""BarkAlert: fire-and-forget iOS push via Bark."""
from unittest.mock import patch, MagicMock

import httpx

from marketwind.gateway.im.bark_alert import BarkAlert


def test_send_success():
    alert = BarkAlert(bark_url="https://api.day.app/mykey")
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    with patch("marketwind.gateway.im.bark_alert.httpx.post", return_value=mock_resp) as mock_post:
        res = alert.send("test message")
    assert res.ok is True
    assert res.error is None
    assert mock_post.call_args.kwargs["json"]["body"] == "test message"


def test_send_http_error():
    alert = BarkAlert(bark_url="https://api.day.app/mykey")
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "bad request", request=MagicMock(), response=mock_resp
    )
    with patch("marketwind.gateway.im.bark_alert.httpx.post", return_value=mock_resp):
        res = alert.send("test")
    assert res.ok is False
    assert "400" in (res.error or "")


def test_send_transport_error():
    alert = BarkAlert(bark_url="https://api.day.app/mykey")
    with patch(
        "marketwind.gateway.im.bark_alert.httpx.post",
        side_effect=httpx.ConnectError("connection refused"),
    ):
        res = alert.send("test")
    assert res.ok is False
    assert "connection refused" in (res.error or "")


def test_url_trailing_slash_stripped():
    alert = BarkAlert(bark_url="https://api.day.app/mykey/")
    assert alert.bark_url == "https://api.day.app/mykey"


def test_factory_build_alert_returns_none_when_empty():
    from marketwind.gateway.im.factory import build_alert

    class _S:
        bark_url = ""

    assert build_alert(_S()) is None


def test_factory_build_alert_returns_bark_when_configured():
    from marketwind.gateway.im.factory import build_alert

    class _S:
        bark_url = "https://api.day.app/mykey"

    result = build_alert(_S())
    assert isinstance(result, BarkAlert)
