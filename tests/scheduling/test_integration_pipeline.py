# tests/scheduling/test_integration_pipeline.py
"""End-to-end OFFLINE integration: build_pool -> run_once -> run_pipeline -> StubSink.
Proves the whole P2a chain composes with no DB/network (all I/O via fakes)."""
from datetime import date, datetime, time, timedelta, timezone

from marketwind.gateway.im.stub import StubSink
from marketwind.scheduling.run_once import run_once
from marketwind.scout.domain import Quote
from marketwind.scout.gather import build_pool
from marketwind.scout.query import build_recap_queries
from marketwind.writer.domain import (
    DraftBundle, DraftClaim, DraftSentence, PooledQuote, PooledSource, WriterOutput,
)

_ANCHOR = datetime(2026, 6, 8, 22, 0, tzinfo=timezone.utc)   # 06:00 CST 2026-06-09
_NOW = _ANCHOR + timedelta(minutes=10)                       # fresh, on a session day
_PREV = date(2026, 6, 5)
_SESSIONS = [date(2026, 6, 8), date(2026, 6, 9)]
_CEIL = time(10, 0)
_QUERIES = build_recap_queries(_PREV)

_CLEAN_TEXT = "科创50涨0.36%"
_CLEAN_TEXT_LEN = len(_CLEAN_TEXT)


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


async def _persist_noop(_src):
    return None


async def _never() -> bool:
    return False


async def _fake_judge(prompt: str) -> str:
    return '{"violations": []}'


def _clean_pool() -> list[PooledSource]:
    pq = PooledQuote(
        quote_id="qq",
        text=_CLEAN_TEXT,
        is_quantitative=True,
        quote_type="data",
        attached_primary_url="http://primary",
        span_start=0,
        span_end=_CLEAN_TEXT_LEN,
    )
    return [PooledSource(
        source_id="s1",
        url="http://x/a",
        domain="x.com",
        is_primary=True,
        quotes=[pq],
        raw_content=_CLEAN_TEXT,
    )]


def _writer_output() -> WriterOutput:
    return WriterOutput(
        claims=[DraftClaim(local_id="c1", statement=_CLEAN_TEXT, quote_ids=["qq"])],
        sentences=[DraftSentence(
            sentence="科创50昨日收涨。",
            claim_ids=["c1"],
            source_ids=["s1"],
            sentence_type="factual",
        )],
    )


def _make_draft_fn(draft_calls: list):
    """Return a draft async fn that appends to draft_calls and returns a clean bundle."""
    async def _commit() -> str:
        return "report-id"

    async def _draft():
        draft_calls.append(1)
        return DraftBundle(
            output=_writer_output(),
            pool=_clean_pool(),
            body="科创50昨日收涨0.36%。[1]",
            reference="",
            commit=_commit,
        )
    return _draft


async def test_full_chain_publishes_labeled_brief_when_floor_clears():
    primary, draft_calls = StubSink(), []

    async def _gather():
        return await build_pool(prev_session=_PREV, search=_search_two_outlets(None),
                                fetch_page=_fetch_echo, parse=_parse_floor_clearing,
                                persist=_persist_noop, now=_NOW)

    async def _noop_record_fail(trace_id, violations):
        pass

    out = await run_once(_NOW, sessions=_SESSIONS, anchor=_ANCHOR, tolerance_min=90,
                         ceiling_cst=_CEIL, gather=_gather,
                         draft=_make_draft_fn(draft_calls),
                         judge=_fake_judge,
                         record_fail=_noop_record_fail,
                         already_published=_never,
                         primary=primary, fallback=StubSink(),
                         trace_id="integ", force_calendar=False)

    assert out.status == "published"
    assert draft_calls == [1]                                 # Writer ran
    assert primary.sent and primary.sent[0].startswith("【DEV / UNVERIFIED")


async def test_full_chain_routes_sub_floor_status_when_pool_thin():
    primary, draft_calls = StubSink(), []

    async def _gather():
        return await build_pool(prev_session=_PREV, search=_search_two_outlets(None),
                                fetch_page=_fetch_echo, parse=_parse_no_primary,
                                persist=_persist_noop, now=_NOW)

    async def _noop_record_fail(trace_id, violations):
        pass

    out = await run_once(_NOW, sessions=_SESSIONS, anchor=_ANCHOR, tolerance_min=90,
                         ceiling_cst=_CEIL, gather=_gather,
                         draft=_make_draft_fn(draft_calls),
                         judge=_fake_judge,
                         record_fail=_noop_record_fail,
                         already_published=_never,
                         primary=primary, fallback=StubSink(),
                         trace_id="integ", force_calendar=False)

    assert out.status == "sub_floor"
    assert out.detail                                         # reason is non-empty
    assert draft_calls == []                                  # Writer NEVER ran
    assert primary.sent == []                                 # nothing published
