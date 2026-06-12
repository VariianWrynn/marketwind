"""Per-job anchor + tolerance resolution (P2b item A).

Later tasks in P2b will add catch_up to this file.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time

from marketwind.scheduling.anchor import anchor_utc
from marketwind.scheduling.outcome import (
    RunOutcome,
    PUBLISHED,
    SKIPPED_CALENDAR,
    SKIPPED_STALE,
    SUB_FLOOR,
    VERIFY_FAIL,
    MISSED,
    FAILED_INFRA,
)
from marketwind.scheduling.run_once import run_once
from marketwind.storage.repo import record_run, get_run_status
from marketwind.orchestration.runner import send_with_fallback
from marketwind.scout.timeparse import CN_TZ

# Exceptions treated as transient infrastructure failures — eligible for retry.
# RuntimeError is included because send_with_fallback raises RuntimeError when
# both IM channels fail, which is a transient infra problem worth retrying.
# Note: asyncpg.PostgresConnectionError is intentionally omitted to avoid a
# hard import dependency on asyncpg; callers may add it if asyncpg is available.
_TRANSIENT = (ConnectionError, TimeoutError, asyncio.TimeoutError, OSError, RuntimeError)


@dataclass(frozen=True)
class JobPlan:
    job_id: str
    anchor: datetime
    tolerance_min: int
    ceiling_cst: time
    trading_date: date


def resolve_job(
    job_id: str,
    now: datetime,
    *,
    premarket_tol_min: int,
    main_tol_min: int,
    ceiling_cst: time,
) -> JobPlan:
    """Return a JobPlan giving this job its own anchor, tolerance, and trading date.

    - "main"      → 07:00 Asia/Shanghai anchor, main_tol_min tolerance
    - "premarket" → 18:00 America/New_York anchor, premarket_tol_min tolerance
    - anything else → ValueError
    """
    trading_date: date = now.astimezone(CN_TZ).date()

    if job_id == "main":
        anchor = anchor_utc(trading_date, 7, 0, "Asia/Shanghai")
        tolerance_min = main_tol_min
    elif job_id == "premarket":
        anchor = anchor_utc(trading_date, 18, 0, "America/New_York")
        tolerance_min = premarket_tol_min
    else:
        raise ValueError(f"unknown job_id: {job_id!r}")

    return JobPlan(
        job_id=job_id,
        anchor=anchor,
        tolerance_min=tolerance_min,
        ceiling_cst=ceiling_cst,
        trading_date=trading_date,
    )


def _status_text(outcome: RunOutcome, plan: "JobPlan", trace_id: str) -> str | None:
    """Build the owner-visible status message for an outcome, or None if silent."""
    s = outcome.status
    if s == PUBLISHED:
        return None
    if s == SKIPPED_CALENDAR:
        return f"[MarketWind·heartbeat] {plan.trading_date} 非交易日，跳过 trace_id={trace_id}"
    if s == SKIPPED_STALE:
        return f"[MarketWind] 简报超时跳过 trace_id={trace_id}: {outcome.detail}"
    if s == SUB_FLOOR:
        return f"[MarketWind] sub-floor shortfall trace_id={trace_id} {outcome.detail} — brief NOT published"
    if s == VERIFY_FAIL:
        return f"[MarketWind] verifier gate failed trace_id={trace_id} {outcome.detail} — brief NOT published"
    if s == MISSED:
        return f"[MarketWind] 错过发布窗口（节点离线）trace_id={trace_id}: {outcome.detail}"
    if s == FAILED_INFRA:
        return f"[MarketWind] ⚠ 基础设施失败，重试耗尽 trace_id={trace_id}: {outcome.detail}"
    # Unknown status — surface it loudly
    return f"[MarketWind] unknown status={s!r} trace_id={trace_id}"


async def dispatch_job(
    job_id: str,
    *,
    now: datetime,
    conn,
    sessions: list,
    trigger: str,
    premarket_tol_min: int,
    main_tol_min: int,
    ceiling_cst: time,
    gather,
    draft,
    judge,
    record_fail,
    primary,
    fallback,
    trace_id: str,
    retries: int,
    backoff_s: float,
) -> RunOutcome:
    """Single entry point for cron and boot dispatchers.

    1. Resolve the job plan (anchor, tolerance, trading_date).
    2. No-op guard: if ledger already has a terminal row, return it unchanged
       (no new row, no message).
    3. Run run_once directly (retry loop added in Task 8).
    4. Boot + SKIPPED_STALE → relabel to MISSED.
    5. Record-then-send: write the ledger row BEFORE sending any message.
    6. Send status message if applicable (PUBLISHED is silent).
    7. Return the outcome.
    """
    plan = resolve_job(
        job_id, now,
        premarket_tol_min=premarket_tol_min,
        main_tol_min=main_tol_min,
        ceiling_cst=ceiling_cst,
    )

    # --- No-op guard ---
    existing = await get_run_status(conn, job_id=job_id, trading_date=plan.trading_date)
    if existing is not None:
        return RunOutcome(existing)

    # --- already_published closure for run_once ---
    async def _already() -> bool:
        return (
            await get_run_status(conn, job_id=job_id, trading_date=plan.trading_date)
        ) == PUBLISHED

    # --- Retry loop (Task 8) ---
    # Only one retry loop exists here; the send failover inside send_with_fallback
    # is bounded and loop-free, so the existing single-budget assert_timing_safe(...)
    # in scheduler.py already bounds the timing.  This is a deliberate, flagged
    # decision — do not "fix" assert_timing_safe.
    outcome: RunOutcome  # assigned inside the loop before break
    for attempt in range(retries + 1):
        try:
            outcome = await run_once(
                now,
                sessions=sessions,
                anchor=plan.anchor,
                tolerance_min=plan.tolerance_min,
                ceiling_cst=plan.ceiling_cst,
                gather=gather,
                draft=draft,
                judge=judge,
                record_fail=record_fail,
                already_published=_already,
                primary=primary,
                fallback=fallback,
                trace_id=trace_id,
            )
            break  # success — exit the retry loop
        except _TRANSIENT as e:
            if attempt < retries:
                await asyncio.sleep(backoff_s)
            else:
                # Retries exhausted — escalate to FAILED_INFRA for durable record + loud page
                outcome = RunOutcome(FAILED_INFRA, detail=f"{type(e).__name__}: {e}")
                break
        except Exception as e:
            # Unknown / non-transient exception — fail closed immediately; likely a bug
            outcome = RunOutcome(FAILED_INFRA, detail=f"{type(e).__name__}: {e}")
            break

    # --- boot + stale → missed relabel ---
    if trigger == "boot" and outcome.status == SKIPPED_STALE:
        outcome = RunOutcome(MISSED, detail=outcome.detail)

    # --- Single ledger write (MUST happen before send) ---
    await record_run(
        conn,
        job_id=job_id,
        trading_date=plan.trading_date,
        status=outcome.status,
        trace_id=trace_id,
        detail=outcome.detail,
    )

    # --- Single status send ---
    text = _status_text(outcome, plan, trace_id)
    if text is not None:
        send_with_fallback(text, primary=primary, fallback=fallback, trace_id=trace_id)

    return outcome
