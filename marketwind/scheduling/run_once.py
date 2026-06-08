"""run_once: the autonomous single-run heart. Calendar+freshness gates ->
gather -> reuse run_pipeline (floor gate -> label -> push). Single-flight lock."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, time

from marketwind.gateway.im.base import IMChannel
from marketwind.orchestration.runner import run_pipeline
from marketwind.scheduling.anchor import freshness_ok
from marketwind.scout.calendar import is_trading_session
from marketwind.scout.domain import Source
from marketwind.scout.timeparse import CN_TZ

_RUN_LOCK = asyncio.Lock()


def _nontrading_status(now: datetime, trace_id: str) -> str:
    return f"[MarketWind] {now.astimezone(CN_TZ):%Y-%m-%d} 非交易日，跳过 trace_id={trace_id}"


def _stale_status(reason: str, trace_id: str) -> str:
    return f"[MarketWind] 简报超时跳过 trace_id={trace_id}: {reason}"


async def run_once(now: datetime, *,
                   sessions: list,
                   anchor: datetime,
                   tolerance_min: int,
                   ceiling_cst: time,
                   gather: Callable[[], Awaitable[list[Source]]],
                   make_body: Callable[[], Awaitable[str]],
                   primary: IMChannel,
                   fallback: IMChannel,
                   dev_channel: IMChannel,
                   trace_id: str,
                   force_calendar: bool = False) -> None:
    async with _RUN_LOCK:
        if not force_calendar and not is_trading_session(now.astimezone(CN_TZ).date(), sessions):
            dev_channel.send(_nontrading_status(now, trace_id))
            return
        fresh, reason = freshness_ok(now, anchor, tolerance_min=tolerance_min,
                                     ceiling_cst=ceiling_cst)
        if not fresh:
            dev_channel.send(_stale_status(reason, trace_id))
            return
        sources = await gather()
        await run_pipeline(sources=sources, make_body=make_body,
                           primary=primary, fallback=fallback,
                           dev_channel=dev_channel, trace_id=trace_id)
