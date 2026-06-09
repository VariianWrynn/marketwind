"""P1c orchestrator: grounded-floor gate -> assemble -> label -> push."""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from marketwind.gateway.im.base import IMChannel, SendResult
from marketwind.gateway.im.label import apply_label
from marketwind.scout.domain import Source
from marketwind.scout.runner import evaluate_floor
from marketwind.verifier.domain import Violation
from marketwind.verifier.verifier import verify
from marketwind.writer.domain import DraftBundle


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


def _verify_status(result, trace_id: str) -> str:
    checks = ",".join(sorted({v.check for v in result.violations}))
    n = len(result.violations)
    return (f"[MarketWind] verifier gate failed trace_id={trace_id} "
            f"checks={checks} ({n} violations) — brief NOT published")


async def run_pipeline(
    *,
    sources: list[Source],
    draft: Callable[[], Awaitable[DraftBundle]],
    judge: Callable[[str], Awaitable[str]],
    record_fail: Callable[[str, list[Violation]], Awaitable[None]],
    primary: IMChannel,
    fallback: IMChannel,
    dev_channel: IMChannel,
    trace_id: str,
) -> None:
    """Grounded-floor gate -> draft -> verifier gate -> commit -> label -> push.

    Sub-floor: emit status to dev_channel and return WITHOUT calling draft().
    Verifier fail: call record_fail, emit status to dev_channel, return WITHOUT publishing.
    Pass: commit(), label, push.
    """
    # 1. Floor gate (unchanged)
    floor = evaluate_floor(sources)
    if not floor.passed:
        dev_channel.send(_status_message(floor, trace_id))
        return

    # 2. Draft
    bundle = await draft()

    # 3. Verifier gate (hardcoded — not injectable, cannot be bypassed)
    result = await verify(bundle.output, bundle.pool, judge=judge)
    if not result.passed:
        await record_fail(trace_id, result.violations)
        dev_channel.send(_verify_status(result, trace_id))
        return

    # 4. Commit then publish
    await bundle.commit()
    labeled = apply_label(bundle.body)
    send_with_fallback(labeled, primary=primary, fallback=fallback, trace_id=trace_id)
