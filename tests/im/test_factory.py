"""build_channels selects (primary, fallback) from settings.im_channel."""
import pytest

from marketwind.gateway.im.factory import build_channels
from marketwind.gateway.im.stub import StubSink
from marketwind.gateway.im.wecom_webhook import WecomWebhook
from marketwind.gateway.im.hermes_weixin import HermesWeixin


class _S:
    def __init__(self, **kw):
        self.im_channel = kw.get("im_channel", "stub")
        self.weixin_account_id = kw.get("weixin_account_id")
        self.weixin_token = kw.get("weixin_token")
        self.wecom_webhook_url = kw.get("wecom_webhook_url")


def test_stub_default():
    primary, fallback = build_channels(_S(im_channel="stub"))
    assert isinstance(primary, StubSink)
    assert isinstance(fallback, StubSink)


def test_hermes_primary_wecom_fallback():
    s = _S(im_channel="hermes_weixin", weixin_account_id="a", weixin_token="t",
           wecom_webhook_url="http://wecom")
    primary, fallback = build_channels(s)
    assert isinstance(primary, HermesWeixin)
    assert isinstance(fallback, WecomWebhook)


def test_hermes_without_token_raises():
    with pytest.raises(ValueError, match="WEIXIN"):
        build_channels(_S(im_channel="hermes_weixin"))
