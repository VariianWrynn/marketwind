# tests/scheduling/test_run_once.py
import asyncio
from datetime import date, datetime, time, timedelta, timezone

from marketwind.gateway.im.stub import StubSink
from marketwind.scheduling.run_once import run_once
from marketwind.scout.domain import Quote, Source

_CN = timezone(timedelta(hours=8))
# Anchor 22:00 UTC = 06:00 CST on 2026-06-09; that CST date is the trading day.
_ANCHOR = datetime(2026, 6, 8, 22, 0, tzinfo=timezone.utc)
_NOW_FRESH = _ANCHOR + timedelta(minutes=10)          # 06:10 CST 2026-06-09
_SESSIONS = [date(2026, 6, 8), date(2026, 6, 9)]
_CEIL = time(10, 0)


def _q(text, *, primary=None):
    return Quote(text=text, span_start=0, span_end=len(text), context_before=None,
                 context_after=None, is_quantitative=False, attached_primary_url=primary)


def _passing_sources():
    now = datetime.now(timezone.utc)
    a = Source(url="https://a.cn/x", domain="a.cn", publish_ts=now, raw_content="...",
               quotes=[_q(f"甲{i}") for i in range(4)])
    a.quotes[0] = _q("甲0", primary="https://primary.gov.cn/d")
    b = Source(url="https://b.cn/y", domain="b.cn", publish_ts=now, raw_content="...",
               quotes=[_q(f"乙{i}") for i in range(4)])
    return [a, b]


def _gather_returning(sources, calls):
    async def _gather():
        calls.append(1)
        return sources
    return _gather


def _make_body(awaited):
    async def _mb():
        awaited.append(1)
        return "正文：科创50盘前。"
    return _mb


async def _run(now, *, gather, make_body, primary, fallback, dev, force=False,
               tol=90, anchor=_ANCHOR):
    await run_once(now, sessions=_SESSIONS, anchor=anchor, tolerance_min=tol,
                   ceiling_cst=_CEIL, gather=gather, make_body=make_body,
                   primary=primary, fallback=fallback, dev_channel=dev,
                   trace_id="t", force_calendar=force)


async def test_non_trading_day_skips_before_gather():
    dev, gcalls, awaited = StubSink(), [], []
    nonsession = datetime(2026, 6, 5, 22, 0, tzinfo=timezone.utc)  # -> 2026-06-06 CST (Sat), not in sessions
    await _run(nonsession, gather=_gather_returning([], gcalls),
               make_body=_make_body(awaited), primary=StubSink(),
               fallback=StubSink(), dev=dev, anchor=nonsession)
    assert gcalls == []           # gather never called
    assert awaited == []          # make_body never called
    assert dev.sent and "非交易日" in dev.sent[0]


async def test_stale_run_skips_before_gather():
    dev, gcalls, awaited = StubSink(), [], []
    late = _ANCHOR + timedelta(minutes=200)  # past 90-min tolerance
    await _run(late, gather=_gather_returning([], gcalls),
               make_body=_make_body(awaited), primary=StubSink(),
               fallback=StubSink(), dev=dev)
    assert gcalls == []
    assert awaited == []
    assert dev.sent and "超时" in dev.sent[0]


async def test_above_floor_publishes_dev_labeled_brief():
    primary, awaited, gcalls = StubSink(), [], []
    await _run(_NOW_FRESH, gather=_gather_returning(_passing_sources(), gcalls),
               make_body=_make_body(awaited), primary=primary,
               fallback=StubSink(), dev=StubSink())
    assert gcalls == [1]                                  # gather ran
    assert awaited == [1]                                 # make_body ran
    assert primary.sent and primary.sent[0].startswith("【DEV / UNVERIFIED")


async def test_sub_floor_routes_status_and_skips_writer():
    dev, primary, awaited, gcalls = StubSink(), StubSink(), [], []
    await _run(_NOW_FRESH, gather=_gather_returning([], gcalls),   # empty pool -> sub-floor
               make_body=_make_body(awaited), primary=primary,
               fallback=StubSink(), dev=dev)
    assert gcalls == [1]                                  # gather ran (needed for floor)
    assert awaited == []                                  # make_body NEVER awaited
    assert primary.sent == []                             # nothing published
    assert dev.sent and "sub-floor" in dev.sent[0]


async def test_force_calendar_runs_on_non_trading_day():
    primary, gcalls, awaited = StubSink(), [], []
    nonsession = datetime(2026, 6, 5, 22, 0, tzinfo=timezone.utc)  # 2026-06-06 CST (Sat)
    await _run(nonsession, gather=_gather_returning(_passing_sources(), gcalls),
               make_body=_make_body(awaited), primary=primary,
               fallback=StubSink(), dev=StubSink(), force=True, anchor=nonsession)
    assert gcalls == [1]                                  # calendar bypassed
    assert primary.sent and primary.sent[0].startswith("【DEV / UNVERIFIED")


async def test_single_flight_serializes_concurrent_runs():
    order = []
    gate = asyncio.Event()

    async def _slow_gather():
        order.append("enter")
        await gate.wait()
        order.append("exit")
        return []

    async def _quick_gather():
        order.append("second-enter")
        return []

    t1 = asyncio.create_task(_run(_NOW_FRESH, gather=_slow_gather,
                                  make_body=_make_body([]), primary=StubSink(),
                                  fallback=StubSink(), dev=StubSink()))
    await asyncio.sleep(0.01)  # let t1 acquire the lock + enter gather
    t2 = asyncio.create_task(_run(_NOW_FRESH, gather=_quick_gather,
                                  make_body=_make_body([]), primary=StubSink(),
                                  fallback=StubSink(), dev=StubSink()))
    await asyncio.sleep(0.01)
    gate.set()
    await asyncio.gather(t1, t2)
    # t2's gather must not start until t1 fully exits (lock held).
    assert order == ["enter", "exit", "second-enter"]
