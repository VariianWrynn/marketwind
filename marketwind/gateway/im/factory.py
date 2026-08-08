"""Config-driven IM channel selection (D-17: channels are pluggable)."""
from __future__ import annotations

from marketwind.gateway.im.base import IMChannel
from marketwind.gateway.im.bark_alert import BarkAlert
from marketwind.gateway.im.hermes_weixin import HermesWeixin
from marketwind.gateway.im.stub import StubSink
from marketwind.gateway.im.wecom_webhook import WecomWebhook


def build_channels(settings) -> tuple[IMChannel, IMChannel]:
    """Return (primary, fallback). Stub by default; hermes->wecom for live."""
    if settings.im_channel == "stub":
        return StubSink(), StubSink()
    if settings.im_channel == "hermes_weixin":
        primary = HermesWeixin(
            token=settings.weixin_token or "",
            account_id=settings.weixin_account_id or "",
            chat_id=settings.weixin_chat_id or "",
        )
        fallback = (WecomWebhook(webhook_url=settings.wecom_webhook_url)
                    if settings.wecom_webhook_url else StubSink())
        return primary, fallback
    if settings.im_channel == "wecom_webhook":
        if not settings.wecom_webhook_url:
            raise ValueError("WECOM_WEBHOOK_URL required for wecom_webhook")
        primary = WecomWebhook(webhook_url=settings.wecom_webhook_url)
        fallback = HermesWeixin(
            token=settings.weixin_token or "",
            account_id=settings.weixin_account_id or "",
            chat_id=settings.weixin_chat_id or "",
        )
        return primary, fallback
    raise ValueError(f"unknown im_channel: {settings.im_channel}")


def build_alert(settings) -> BarkAlert | None:
    """Return a BarkAlert if bark_url is configured, else None."""
    if settings.bark_url:
        return BarkAlert(bark_url=settings.bark_url)
    return None
