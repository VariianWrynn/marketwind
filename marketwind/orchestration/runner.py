"""P1c orchestrator: grounded-floor gate -> assemble -> label -> push."""
from __future__ import annotations

from marketwind.gateway.im.base import IMChannel, SendResult


def send_with_fallback(text: str, *, primary: IMChannel, fallback: IMChannel,
                       trace_id: str) -> None:
    """Try primary; on failure try fallback; if both fail raise with trace_id."""
    res: SendResult = primary.send(text)
    if res.ok:
        return
    res = fallback.send(text)
    if res.ok:
        return
    raise RuntimeError(f"both IM channels failed for trace_id={trace_id}: {res.error}")
