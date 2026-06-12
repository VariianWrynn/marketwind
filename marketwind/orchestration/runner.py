"""P2b orchestrator: floor/verify gates -> check-before-send -> publish; returns RunOutcome."""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from marketwind.gateway.im.base import IMChannel, SendResult
from marketwind.gateway.im.label import apply_label
from marketwind.scheduling.outcome import PUBLISHED, SUB_FLOOR, VERIFY_FAIL, RunOutcome
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


async def run_pipeline(
    *,
    sources: list[Source],
    draft: Callable[[], Awaitable[DraftBundle]],
    judge: Callable[[str], Awaitable[str]],
    record_fail: Callable[[str, list[Violation]], Awaitable[None]],
    already_published: Callable[[], Awaitable[bool]],
    primary: IMChannel,
    fallback: IMChannel,
    trace_id: str,
) -> RunOutcome:
    """Grounded-floor gate -> draft -> verifier gate -> check-before-send -> commit -> label -> push.

    Sub-floor: return SUB_FLOOR, do NOT call draft().
    Verifier fail: call record_fail, return VERIFY_FAIL. No publish.
    Already published: return PUBLISHED without commit or send (idempotent).
    Pass: commit(), label, push, return PUBLISHED.
    """
    # 1. Floor gate
    floor = evaluate_floor(sources)
    if not floor.passed:
        detail = (
            f"grounded_quotes={floor.grounded_quotes} "
            f"primary_traced_quotes={floor.primary_traced_quotes} "
            f"independent_outlets={floor.independent_outlets} — brief NOT published"
        )
        return RunOutcome(SUB_FLOOR, detail=detail)

    # 2. Draft
    bundle = await draft()

    # 3. Verifier gate (hardcoded — Law 5, cannot be bypassed)
    result = await verify(bundle.output, bundle.pool, judge=judge)
    if not result.passed:
        await record_fail(trace_id, result.violations)
        checks = ",".join(sorted({v.check for v in result.violations}))
        n = len(result.violations)
        detail = f"checks={checks} ({n} violations)"
        return RunOutcome(VERIFY_FAIL, detail=detail)

    # 4. Check-before-send (idempotency guard)
    if await already_published():
        return RunOutcome(PUBLISHED)

    # 5. Commit then publish (Law-5 ordering: persist before push)
    await bundle.commit()
    labeled = apply_label(bundle.body)
    send_with_fallback(labeled, primary=primary, fallback=fallback, trace_id=trace_id)
    return RunOutcome(PUBLISHED)
