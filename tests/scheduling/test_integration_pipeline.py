# tests/scheduling/test_integration_pipeline.py
"""End-to-end OFFLINE integration: build_pool -> run_once -> run_pipeline -> StubSink.
Proves the whole P2a chain composes with no DB/network (all I/O via fakes)."""
from datetime import date, datetime, time, timedelta, timezone

from marketwind.gateway.im.stub import StubSink
from marketwind.scheduling.run_once import run_once
from marketwind.scout.domain import Quote
from marketwind.scout.gather import build_pool
from marketwind.scout.query import build_recap_queries

_ANCHOR = datetime(2026, 6, 8, 22, 0, tzinfo=timezone.utc)   # 06:00 CST 2026-06-09
_NOW = _ANCHOR + timedelta(minutes=10)                       # fresh, on a session day
_PREV = date(2026, 6, 5)
_SESSIONS = [date(2026, 6, 8), date(2026, 6, 9)]
_CEIL = time(10, 0)
_QUERIES = build_recap_queries(_PREV)


def _q(text, *, primary=None):
    return Quote(text=text, span_start=0, span_end=len(text), context_before=None,
                 context_after=None, is_quantitative=False, attached_primary_url=primary)


def _search_two_outlets(query):
    # First query returns two distinct-domain urls; others empty.
    async def _s(q):
        if q == _QUERIES[0]:
            return [("https://a.cn/x", "s"), ("https://b.cn/y", "s")]
        return []
    return _s


async def _fetch_echo(url):
    return f"<html>{url}</html>"


def _parse_floor_clearing(html):
    # 4 quotes per page; the first carries a primary trace. Two pages -> 8 grounded,
    # 2 primary, 2 outlets -> clears the 8/1/2 floor.
    quotes = [_q("甲0", primary="https://primary.gov.cn/d")] + [_q(f"句{i}") for i in range(1, 4)]
    return ("raw:" + html, quotes)


def _parse_no_primary(html):
    # 4 quotes per page but NONE primary-traced -> primary_traced=0 -> sub-floor.
    return ("raw:" + html, [_q(f"句{i}") for i in range(4)])


def _make_body(awaited):
    async def _mb():
        awaited.append(1)
        return "正文：科创50盘前综述。"
    return _mb


async def _persist_noop(_src):
    return None


async def test_full_chain_publishes_labeled_brief_when_floor_clears():
    primary, dev, awaited = StubSink(), StubSink(), []

    async def _gather():
        return await build_pool(prev_session=_PREV, search=_search_two_outlets(None),
                                fetch_page=_fetch_echo, parse=_parse_floor_clearing,
                                persist=_persist_noop, now=_NOW)

    await run_once(_NOW, sessions=_SESSIONS, anchor=_ANCHOR, tolerance_min=90,
                   ceiling_cst=_CEIL, gather=_gather, make_body=_make_body(awaited),
                   primary=primary, fallback=StubSink(), dev_channel=dev,
                   trace_id="integ", force_calendar=False)

    assert awaited == [1]                                   # Writer ran
    assert primary.sent and primary.sent[0].startswith("【DEV / UNVERIFIED")
    assert dev.sent == []                                   # no shortfall status


async def test_full_chain_routes_sub_floor_status_when_pool_thin():
    primary, dev, awaited = StubSink(), StubSink(), []

    async def _gather():
        return await build_pool(prev_session=_PREV, search=_search_two_outlets(None),
                                fetch_page=_fetch_echo, parse=_parse_no_primary,
                                persist=_persist_noop, now=_NOW)

    await run_once(_NOW, sessions=_SESSIONS, anchor=_ANCHOR, tolerance_min=90,
                   ceiling_cst=_CEIL, gather=_gather, make_body=_make_body(awaited),
                   primary=primary, fallback=StubSink(), dev_channel=dev,
                   trace_id="integ", force_calendar=False)

    assert awaited == []                                    # Writer NEVER ran
    assert primary.sent == []                               # nothing published
    assert dev.sent and "sub-floor" in dev.sent[0]
