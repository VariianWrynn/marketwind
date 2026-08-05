"""build_channels selects (primary, fallback) from settings.im_channel."""
import pytest

from marketwind.gateway.im.factory import build_channels
from marketwind.gateway.im.stub import StubSink
from marketwind.gateway.im.unconfigured import UnconfiguredSink
from marketwind.gateway.im.wecom_webhook import WecomWebhook
from marketwind.gateway.im.hermes_weixin import HermesWeixin


class _S:
    def __init__(self, **kw):
        self.im_channel = kw.get("im_channel", "stub")
        self.weixin_account_id = kw.get("weixin_account_id")
        self.weixin_token = kw.get("weixin_token")
        self.wecom_webhook_url = kw.get("wecom_webhook_url")
        self.hermes_bin = kw.get("hermes_bin", "hermes")
        self.weixin_target = kw.get("weixin_target", "weixin")


def test_stub_default():
    primary, fallback = build_channels(_S(im_channel="stub"))
    assert isinstance(primary, StubSink)
    assert isinstance(fallback, StubSink)


def test_hermes_primary_wecom_fallback():
    s = _S(im_channel="hermes_weixin", wecom_webhook_url="http://wecom")
    primary, fallback = build_channels(s)
    assert isinstance(primary, HermesWeixin)
    assert isinstance(fallback, WecomWebhook)


def test_hermes_without_wecom_gets_a_fallback_that_reports_failure():
    # ADR-0005 B: was StubSink, which returns ok=True while discarding — so a dead
    # WeChat session recorded PUBLISHED and the dead-man still checked in. The live
    # fallback slot must never be filled by a sink that silently accepts.
    primary, fallback = build_channels(_S(im_channel="hermes_weixin"))
    assert isinstance(primary, HermesWeixin)
    assert isinstance(fallback, UnconfiguredSink)
    assert fallback.send("body").ok is False


def test_wecom_without_url_raises():
    with pytest.raises(ValueError, match="WECOM_WEBHOOK_URL"):
        build_channels(_S(im_channel="wecom_webhook"))


def test_wecom_webhook_is_primary_hermes_is_fallback():
    # Unattended push channel is session-less WeCom-webhook; hermes/WeChat is the
    # warm two-way ConciergeBot channel and the fallback (was StubSink before).
    s = _S(im_channel="wecom_webhook", wecom_webhook_url="http://wecom")
    primary, fallback = build_channels(s)
    assert isinstance(primary, WecomWebhook)
    assert isinstance(fallback, HermesWeixin)
