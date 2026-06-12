"""Manual entrypoint: run the exact scheduled path by hand.

  python -m marketwind.scheduling.run_once            # real send
  ... --dry-run                                       # route to StubSink
  ... --force-calendar                                # run on a non-trading day (implies --dry-run)
  ... --force-calendar --send-real                    # forced AND real send
"""
from __future__ import annotations

import argparse

from marketwind.scout.domain import FloorResult


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="marketwind.scheduling.run_once")
    p.add_argument("--force-calendar", action="store_true",
                   help="run even on a non-trading day (implies --dry-run unless --send-real)")
    p.add_argument("--dry-run", action="store_true", help="route sends to StubSink")
    p.add_argument("--send-real", action="store_true",
                   help="with --force-calendar, actually send instead of dry-run")
    p.add_argument("--floor-only", action="store_true",
                   help="probe the grounded floor and exit; burns zero DeepSeek tokens")
    return p


def floor_line(result: FloorResult) -> str:
    """One human-readable line summarising the FloorResult."""
    return (
        f"grounded={result.grounded_quotes} "
        f"primary={result.primary_traced_quotes} "
        f"outlets={result.independent_outlets} "
        f"passed={result.passed}"
    )


def floor_exit_code(result: FloorResult) -> int:
    """0 if the floor check passed, 1 otherwise."""
    return 0 if result.passed else 1


def want_real_send(args: argparse.Namespace) -> bool:
    """Real send unless dry-run; --force-calendar defaults to dry-run unless
    --send-real. --dry-run always wins."""
    if args.dry_run:
        return False
    if args.force_calendar and not args.send_real:
        return False
    return True


async def floor_probe() -> int:  # pragma: no cover - live
    """Probe the grounded floor and return an exit code; burns zero DeepSeek tokens."""
    from datetime import datetime, timezone

    import asyncpg

    from marketwind.config import settings
    from marketwind.scout.calendar import live_prev_trading_session
    from marketwind.scout.gather import gather_live
    from marketwind.scout.enrich import enrich_primary_live
    from marketwind.scout.runner import evaluate_floor

    now = datetime.now(timezone.utc)
    prev = live_prev_trading_session(now.date())

    conn = await asyncpg.connect(settings.database_url)
    try:
        pool = await gather_live(conn, now=now, prev_session=prev)
        sources = await enrich_primary_live(conn, pool, on_date=prev)
        result = evaluate_floor(sources)
        print(floor_line(result))
        return floor_exit_code(result)
    finally:
        await conn.close()


async def main(argv: list[str] | None = None) -> None:  # pragma: no cover - live
    import asyncio
    from datetime import datetime, time, timezone

    import asyncpg

    from marketwind.config import settings
    from marketwind.gateway.im.factory import build_channels
    from marketwind.gateway.im.stub import StubSink
    from marketwind.scheduling.anchor import anchor_utc
    from marketwind.scheduling.run_once import run_once
    from marketwind.scout.calendar import live_prev_trading_session, _load_sessions
    from marketwind.scout.gather import gather_live
    from marketwind.scout.enrich import enrich_primary_live

    args = build_parser().parse_args(argv)
    now = datetime.now(timezone.utc)
    sessions = list(_load_sessions())
    prev = live_prev_trading_session(now.date())
    anchor = anchor_utc(now.date(), 18, 0, "America/New_York")  # pre-market anchor

    if want_real_send(args):
        live = settings.model_copy(update={"im_channel": "hermes_weixin"})
        primary, fallback = build_channels(live)
    else:
        primary, fallback = StubSink(), StubSink()

    conn = await asyncpg.connect(settings.database_url)
    try:
        async def _gather():
            pool = await gather_live(conn, now=now, prev_session=prev)
            return await enrich_primary_live(conn, pool, on_date=prev)

        from marketwind.writer.client import call_deepseek
        from marketwind.writer.runner import draft_report
        from marketwind.verifier.runner import call_judge
        from marketwind.storage.repo import record_verifier_failures

        async def _draft():
            return await draft_report(conn, call=call_deepseek)

        async def _record_fail(trace_id, violations):
            await record_verifier_failures(conn, trace_id, violations)

        hh, mm = (int(x) for x in settings.freshness_ceiling_cst.split(":"))
        await run_once(now, sessions=sessions, anchor=anchor,
                       tolerance_min=settings.premarket_tolerance_min,
                       ceiling_cst=time(hh, mm), gather=_gather,
                       draft=_draft, judge=call_judge, record_fail=_record_fail,
                       primary=primary, fallback=fallback,
                       trace_id=f"manual-{now:%Y%m%dT%H%M%S}",
                       force_calendar=args.force_calendar)
    finally:
        await conn.close()


async def run_scheduler() -> None:  # pragma: no cover - live
    import asyncio
    from datetime import datetime, time, timezone

    import asyncpg

    from marketwind.config import settings
    from marketwind.gateway.im.factory import build_channels
    from marketwind.scheduling.dispatch import catch_up, dispatch_job
    from marketwind.scheduling.scheduler import assert_timing_safe, build_scheduler
    from marketwind.scout.calendar import live_prev_trading_session, _load_sessions
    from marketwind.scout.gather import gather_live
    from marketwind.scout.enrich import enrich_primary_live
    from marketwind.writer.client import call_deepseek
    from marketwind.writer.runner import draft_report
    from marketwind.verifier.runner import call_judge
    from marketwind.storage.repo import record_verifier_failures

    live = settings.model_copy(update={"im_channel": "wecom_webhook"})
    primary, fallback = build_channels(live)

    conn = await asyncpg.connect(settings.database_url)
    try:
        sessions = list(_load_sessions())
        now = datetime.now(timezone.utc)
        hh, mm = (int(x) for x in settings.freshness_ceiling_cst.split(":"))
        ceiling = time(hh, mm)
        prev = live_prev_trading_session(now.date())

        assert_timing_safe(
            misfire_grace_s=settings.misfire_grace_s,
            max_transient_retries=settings.max_transient_retries,
            backoff_ceiling_s=settings.backoff_ceiling_s,
            tolerance_min=settings.main_tolerance_min,
        )

        # _gather takes the gather instant + prev session explicitly so each cron
        # fire pulls *that day's* data. Capturing boot-time now/prev in the closure
        # would make a long-running daemon serve stale boot-day data — a freshness
        # violation (CLAUDE.md §7: never pass yesterday's data off as today's).
        async def _gather(g_now, g_prev):
            pool = await gather_live(conn, now=g_now, prev_session=g_prev)
            return await enrich_primary_live(conn, pool, on_date=g_prev)

        async def _draft():
            return await draft_report(conn, call=call_deepseek)

        async def _record_fail(trace_id, violations):
            await record_verifier_failures(conn, trace_id, violations)

        # Boot reconciliation: boot-time now/prev is correct here.
        await catch_up(
            now=now, conn=conn, sessions=sessions,
            premarket_tol_min=settings.premarket_tolerance_min,
            main_tol_min=settings.main_tolerance_min,
            ceiling_cst=ceiling,
            gather=lambda: _gather(now, prev), draft=_draft, judge=call_judge,
            record_fail=_record_fail,
            primary=primary, fallback=fallback,
            trace_id=f"boot-{now:%Y%m%dT%H%M%S}",
            retries=settings.max_transient_retries,
            backoff_s=settings.backoff_ceiling_s,
            window=5,
        )

        async def _dispatch(job_id: str) -> None:
            fire_now = datetime.now(timezone.utc)
            fire_prev = live_prev_trading_session(fire_now.date())
            await dispatch_job(
                job_id,
                now=fire_now,
                conn=conn,
                sessions=sessions,
                trigger="cron",
                premarket_tol_min=settings.premarket_tolerance_min,
                main_tol_min=settings.main_tolerance_min,
                ceiling_cst=ceiling,
                gather=lambda: _gather(fire_now, fire_prev), draft=_draft,
                judge=call_judge, record_fail=_record_fail,
                primary=primary, fallback=fallback,
                trace_id=f"cron-{job_id}-{fire_now:%Y%m%dT%H%M%S}",
                retries=settings.max_transient_retries,
                backoff_s=settings.backoff_ceiling_s,
            )

        sched = build_scheduler(dispatch=_dispatch, misfire_grace_s=settings.misfire_grace_s)
        sched.start()
        await asyncio.Event().wait()
    finally:
        await conn.close()


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys
    _args = build_parser().parse_args()
    if _args.floor_only:
        raise SystemExit(asyncio.run(floor_probe()))
    asyncio.run(main())
