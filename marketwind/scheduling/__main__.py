"""Manual entrypoint: run the exact scheduled path by hand.

  python -m marketwind.scheduling.run_once            # real send
  ... --dry-run                                       # route to StubSink
  ... --force-calendar                                # run on a non-trading day (implies --dry-run)
  ... --force-calendar --send-real                    # forced AND real send
"""
from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="marketwind.scheduling.run_once")
    p.add_argument("--force-calendar", action="store_true",
                   help="run even on a non-trading day (implies --dry-run unless --send-real)")
    p.add_argument("--dry-run", action="store_true", help="route sends to StubSink")
    p.add_argument("--send-real", action="store_true",
                   help="with --force-calendar, actually send instead of dry-run")
    return p


def want_real_send(args: argparse.Namespace) -> bool:
    """Real send unless dry-run; --force-calendar defaults to dry-run unless
    --send-real. --dry-run always wins."""
    if args.dry_run:
        return False
    if args.force_calendar and not args.send_real:
        return False
    return True


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
    dev = StubSink()

    conn = await asyncpg.connect(settings.database_url)
    try:
        async def _gather():
            return await gather_live(conn, now=now, prev_session=prev)

        async def _make_body():
            from marketwind.writer.client import call_deepseek
            from marketwind.writer.runner import run_writer
            _id, body = await run_writer(conn, call=call_deepseek)
            return body

        hh, mm = (int(x) for x in settings.freshness_ceiling_cst.split(":"))
        await run_once(now, sessions=sessions, anchor=anchor,
                       tolerance_min=settings.premarket_tolerance_min,
                       ceiling_cst=time(hh, mm), gather=_gather, make_body=_make_body,
                       primary=primary, fallback=fallback, dev_channel=dev,
                       trace_id=f"manual-{now:%Y%m%dT%H%M%S}",
                       force_calendar=args.force_calendar)
    finally:
        await conn.close()


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    asyncio.run(main())
