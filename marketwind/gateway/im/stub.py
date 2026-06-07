from __future__ import annotations

from marketwind.gateway.im.base import SendResult


class StubSink:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[str] = []

    def send(self, text: str) -> SendResult:
        if self.fail:
            return SendResult(ok=False, error="configured failure")
        self.sent.append(text)
        return SendResult(ok=True)
