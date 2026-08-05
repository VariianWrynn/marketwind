"""A live channel slot with nothing configured behind it (ADR-0005 option B).

Fills a primary/fallback slot that has no real channel. Unlike StubSink it reports
`ok=False`, so `send_with_fallback` raises instead of letting the run record
PUBLISHED for a message nobody received.
"""
from __future__ import annotations

from marketwind.gateway.im.base import SendResult


class UnconfiguredSink:
    def __init__(self, setting: str) -> None:
        self.setting = setting

    def send(self, text: str) -> SendResult:
        return SendResult(
            ok=False,
            error=f"no channel configured for this slot ({self.setting} unset) — message NOT delivered",
        )
