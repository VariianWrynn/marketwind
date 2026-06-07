"""IMChannel protocol + SendResult."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SendResult:
    ok: bool
    error: str | None = None


class IMChannel(Protocol):
    def send(self, text: str) -> SendResult: ...
