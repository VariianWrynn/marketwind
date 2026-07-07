"""run_once: the autonomous single-run heart. Calendar+freshness gates ->
gather -> reuse run_pipeline (floor gate -> label -> push). Single-flight lock."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, time

from marketwind.gateway.im.base import IMChannel
from marketwind.gateway.im.label import DEV_PREFIX
from marketwind.orchestration.runner import run_pipeline
from marketwind.scheduling.anchor import freshness_ok
from marketwind.scheduling.outcome import RunOutcome, SKIPPED_CALENDAR, SKIPPED_STALE
from marketwind.scout.calendar import is_trading_session
from marketwind.scout.domain import Source
from marketwind.scout.timeparse import CN_TZ
from marketwind.verifier.domain import Violation
from marketwind.writer.domain import DraftBundle, WriterOutput

_RUN_LOCK = asyncio.Lock()


async def run_once(now: datetime, *,
                   sessions: list,
                   anchor: datetime,
                   tolerance_min: int,
                   ceiling_cst: time,
                   gather: Callable[[], Awaitable[list[Source]]],
                   draft: Callable[[], Awaitable[DraftBundle]],
                   judge: Callable[[str], Awaitable[str]],
                   record_fail: Callable[[str, list[Violation], WriterOutput], Awaitable[None]],
                   already_published: Callable[[], Awaitable[bool]],
                   primary: IMChannel,
                   fallback: IMChannel,
                   trace_id: str,
                   force_calendar: bool = False,
                   force_fresh: bool = False,
                   label_prefix: str = DEV_PREFIX) -> RunOutcome:
    async with _RUN_LOCK:
        if not force_calendar and not is_trading_session(now.astimezone(CN_TZ).date(), sessions):
            return RunOutcome(SKIPPED_CALENDAR)
        fresh, reason = freshness_ok(now, anchor, tolerance_min=tolerance_min,
                                     ceiling_cst=ceiling_cst)
        if not force_fresh and not fresh:
            return RunOutcome(SKIPPED_STALE, detail=reason)
        sources = await gather()
        return await run_pipeline(sources=sources, draft=draft, judge=judge,
                                  record_fail=record_fail,
                                  already_published=already_published,
                                  primary=primary, fallback=fallback,
                                  trace_id=trace_id,
                                  label_prefix=label_prefix)
