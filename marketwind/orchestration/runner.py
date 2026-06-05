"""P1c orchestrator: grounded-floor gate -> assemble -> label -> push."""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from marketwind.gateway.im.base import IMChannel, SendResult
from marketwind.gateway.im.label import apply_label
from marketwind.scout.domain import Source
from marketwind.scout.runner import evaluate_floor


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


def _status_message(floor, trace_id: str) -> str:
    return (f"[MarketWind] sub-floor shortfall trace_id={trace_id} "
            f"grounded_quotes={floor.grounded_quotes} "
            f"primary_traced_quotes={floor.primary_traced_quotes} "
            f"independent_outlets={floor.independent_outlets} — brief NOT published")


async def run_pipeline(*, sources: list[Source],
                       make_body: Callable[[], Awaitable[str]],
                       primary: IMChannel, fallback: IMChannel,
                       dev_channel: IMChannel, trace_id: str) -> None:
    """Grounded-floor gate (reuse evaluate_floor) -> assemble -> label -> push.

    Sub-floor: emit status with trace_id to dev_channel and return WITHOUT
    assembling a brief (spec section 8). make_body is lazy so a shortfall costs no
    Writer/DeepSeek call.
    """
    floor = evaluate_floor(sources)
    if not floor.passed:
        dev_channel.send(_status_message(floor, trace_id))
        return
    body = await make_body()
    labeled = apply_label(body)
    send_with_fallback(labeled, primary=primary, fallback=fallback, trace_id=trace_id)
