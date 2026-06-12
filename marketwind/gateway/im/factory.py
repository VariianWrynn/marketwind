"""Config-driven IM channel selection (D-17: channels are pluggable)."""
from __future__ import annotations

from marketwind.gateway.im.base import IMChannel
from marketwind.gateway.im.hermes_weixin import HermesWeixin
from marketwind.gateway.im.stub import StubSink
from marketwind.gateway.im.wecom_webhook import WecomWebhook


def build_channels(settings) -> tuple[IMChannel, IMChannel]:
    """Return (primary, fallback). Stub by default; hermes->wecom for live."""
    if settings.im_channel == "stub":
        return StubSink(), StubSink()
    if settings.im_channel == "hermes_weixin":
        primary = HermesWeixin(hermes_bin=settings.hermes_bin, target=settings.weixin_target)
        fallback = (WecomWebhook(webhook_url=settings.wecom_webhook_url)
                    if settings.wecom_webhook_url else StubSink())
        return primary, fallback
    if settings.im_channel == "wecom_webhook":
        if not settings.wecom_webhook_url:
            raise ValueError("WECOM_WEBHOOK_URL required for wecom_webhook")
        # Session-less WeCom-webhook is the unattended primary; hermes/WeChat is
        # the warm two-way ConciergeBot channel and the fallback.
        primary = WecomWebhook(webhook_url=settings.wecom_webhook_url)
        fallback = HermesWeixin(hermes_bin=settings.hermes_bin, target=settings.weixin_target)
        return primary, fallback
    raise ValueError(f"unknown im_channel: {settings.im_channel}")
