"""Per-job anchor + tolerance resolution (P2b item A).

catch_up added in Task 9 P2b: boot-time backward reconciliation.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
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
from marketwind.gateway.im.label import DEV_PREFIX
from marketwind.scheduling.run_once import run_once
from marketwind.storage.repo import record_run, get_run_status
from marketwind.orchestration.runner import send_with_fallback
from marketwind.scout.timeparse import CN_TZ
from marketwind.verifier.domain import Violation
from marketwind.writer.domain import WriterOutput

# Exceptions treated as transient infrastructure failures — eligible for retry.
# RuntimeError is included because send_with_fallback raises RuntimeError when
# both IM channels fail, which is a transient infra problem worth retrying.
# Note: asyncpg.PostgresConnectionError is intentionally omitted to avoid a
# hard import dependency on asyncpg; callers may add it if asyncpg is available.
_TRANSIENT = (ConnectionError, TimeoutError, asyncio.TimeoutError, OSError, RuntimeError)

# Detail recorded + surfaced when boot catch-up reconciles a past, never-run window.
_BOOT_RECONCILE_DETAIL = "boot reconcile: window closed unrun"


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
    record_fail: Callable[[str, list[Violation], WriterOutput], Awaitable[None]],
    primary,
    fallback,
    trace_id: str,
    retries: int,
    backoff_s: float,
    label_prefix: str = DEV_PREFIX,
) -> RunOutcome:
    """Single entry point for cron and boot dispatchers.

    1. Resolve the job plan (anchor, tolerance, trading_date).
    2. No-op guard: if ledger already has a terminal row, return it unchanged
       (no new row, no message).
    3. Run run_once with transient-retry (retries+1 attempts, flat backoff_s);
       exhausted transient or any unknown error escalates to FAILED_INFRA.
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
                label_prefix=label_prefix,
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
    inserted = await record_run(
        conn,
        job_id=job_id,
        trading_date=plan.trading_date,
        status=outcome.status,
        trace_id=trace_id,
        detail=outcome.detail,
    )

    # --- Single status send ---
    # Only the dispatcher that actually wrote the row pages. A False return means
    # a racing cron/boot dispatcher won the insert (both passed the no-op guard
    # before either recorded); it already pages, so suppress the duplicate to keep
    # status single-sender even under that race.
    text = _status_text(outcome, plan, trace_id)
    if inserted and text is not None:
        send_with_fallback(text, primary=primary, fallback=fallback, trace_id=trace_id)

    return outcome


async def catch_up(
    *,
    now,
    conn,
    sessions,
    premarket_tol_min,
    main_tol_min,
    ceiling_cst,
    gather,
    draft,
    judge,
    record_fail: Callable[[str, list[Violation], WriterOutput], Awaitable[None]],
    primary,
    fallback,
    trace_id,
    retries,
    backoff_s,
    window: int = 5,
    label_prefix: str = DEV_PREFIX,
) -> list[RunOutcome]:
    """Boot-time backward reconciliation (Task 9 P2b).

    Reconciles the last `window` trading dates so a multi-day outage produces
    a missed ledger row PER ABSENT DAY (not one misleading row).

    - A date already terminal in the ledger → skip (idempotent).
    - today with no row → delegate to dispatch_job(..., trigger="boot", ...).
    - Any PAST trading date with no row → write a missed row directly + owner page.
    """
    today = now.astimezone(CN_TZ).date()
    wdates = sorted(d for d in sessions if d <= today)[-window:]

    outcomes: list[RunOutcome] = []

    for job_id in ("premarket", "main"):
        for d in wdates:
            existing = await get_run_status(conn, job_id=job_id, trading_date=d)
            if existing is not None:
                # Already terminal — skip (idempotent)
                continue
            elif d == today:
                # Delegate today's run to dispatch_job (handles window/stale relabeling)
                outcome = await dispatch_job(
                    job_id,
                    now=now,
                    conn=conn,
                    sessions=sessions,
                    trigger="boot",
                    premarket_tol_min=premarket_tol_min,
                    main_tol_min=main_tol_min,
                    ceiling_cst=ceiling_cst,
                    gather=gather,
                    draft=draft,
                    judge=judge,
                    record_fail=record_fail,
                    primary=primary,
                    fallback=fallback,
                    trace_id=trace_id,
                    retries=retries,
                    backoff_s=backoff_s,
                    label_prefix=label_prefix,
                )
                outcomes.append(outcome)
            else:
                # Past date with no row — write missed directly (window is closed)
                inserted = await record_run(
                    conn,
                    job_id=job_id,
                    trading_date=d,
                    status=MISSED,
                    trace_id=trace_id,
                    detail=_BOOT_RECONCILE_DETAIL,
                )
                # Build a plan only so _status_text can render the owner message.
                # For a MISSED outcome _status_text uses only job_id/trading_date
                # (via detail+trace_id); the noon-CST anchor is arbitrary — it just
                # makes resolve_job derive trading_date == d.
                plan = resolve_job(
                    job_id,
                    datetime(d.year, d.month, d.day, 12, 0, tzinfo=CN_TZ),
                    premarket_tol_min=premarket_tol_min,
                    main_tol_min=main_tol_min,
                    ceiling_cst=ceiling_cst,
                )
                outcome = RunOutcome(MISSED, detail=_BOOT_RECONCILE_DETAIL)
                # Suppress the page if a racing boot dispatcher already wrote (and
                # paged for) this missed day — keeps reconciliation single-sender.
                text = _status_text(outcome, plan, trace_id)
                if inserted and text is not None:
                    send_with_fallback(text, primary=primary, fallback=fallback, trace_id=trace_id)
                outcomes.append(outcome)

    return outcomes
