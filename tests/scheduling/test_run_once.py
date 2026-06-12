# tests/scheduling/test_run_once.py
import asyncio
from datetime import date, datetime, time, timedelta, timezone

from marketwind.gateway.im.stub import StubSink
from marketwind.scheduling.outcome import RunOutcome
from marketwind.scheduling.run_once import run_once
from marketwind.scout.domain import Quote, Source
from marketwind.writer.domain import (
    DraftBundle, DraftClaim, DraftSentence, PooledQuote, PooledSource, WriterOutput,
)

_CN = timezone(timedelta(hours=8))
# Anchor 22:00 UTC = 06:00 CST on 2026-06-09; that CST date is the trading day.
_ANCHOR = datetime(2026, 6, 8, 22, 0, tzinfo=timezone.utc)
_NOW_FRESH = _ANCHOR + timedelta(minutes=10)          # 06:10 CST 2026-06-09
_SESSIONS = [date(2026, 6, 8), date(2026, 6, 9)]
_CEIL = time(10, 0)

_CLEAN_TEXT = "科创50涨0.36%"
_CLEAN_TEXT_LEN = len(_CLEAN_TEXT)


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


def _clean_pool() -> list[PooledSource]:
    """A PooledSource where raw_content[0:len] == quote text, has primary -> clean."""
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


def _i3_pool() -> list[PooledSource]:
    """Same shape but no primary — only I3 fires."""
    pq = PooledQuote(
        quote_id="qq",
        text=_CLEAN_TEXT,
        is_quantitative=True,
        quote_type="data",
        attached_primary_url=None,
        span_start=0,
        span_end=_CLEAN_TEXT_LEN,
    )
    return [PooledSource(
        source_id="s1",
        url="http://x/a",
        domain="x.com",
        is_primary=False,
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


def _make_clean_bundle() -> tuple[DraftBundle, dict]:
    spy = {"commit_calls": 0}

    async def _commit() -> str:
        spy["commit_calls"] += 1
        return "report-id"

    bundle = DraftBundle(
        output=_writer_output(),
        pool=_clean_pool(),
        body="科创50昨日收涨0.36%。[1]",
        commit=_commit,
    )
    return bundle, spy


def _make_i3_bundle() -> tuple[DraftBundle, dict]:
    spy = {"commit_calls": 0}

    async def _commit() -> str:
        spy["commit_calls"] += 1
        return "report-id"

    bundle = DraftBundle(
        output=_writer_output(),
        pool=_i3_pool(),
        body="科创50昨日收涨0.36%。[1]",
        commit=_commit,
    )
    return bundle, spy


async def _fake_judge(prompt: str) -> str:
    return '{"violations": []}'


def _draft(draft_calls, bundle=None):
    """Factory: returns an async draft fn that appends to draft_calls and returns bundle."""
    async def _d():
        draft_calls.append(1)
        if bundle is not None:
            return bundle
        b, _ = _make_clean_bundle()
        return b
    return _d


async def _never() -> bool:
    return False


async def _run(now, *, gather, draft, primary, fallback, force=False,
               tol=90, anchor=_ANCHOR, judge=None, record_fail=None,
               already_published=None):
    if judge is None:
        judge = _fake_judge
    if record_fail is None:
        async def record_fail(trace_id, violations):
            pass
    if already_published is None:
        already_published = _never
    return await run_once(now, sessions=_SESSIONS, anchor=anchor, tolerance_min=tol,
                          ceiling_cst=_CEIL, gather=gather, draft=draft,
                          judge=judge, record_fail=record_fail,
                          primary=primary, fallback=fallback,
                          already_published=already_published,
                          trace_id="t", force_calendar=force)


async def test_non_trading_day_returns_skipped_calendar():
    gcalls, draft_calls = [], []
    nonsession = datetime(2026, 6, 5, 22, 0, tzinfo=timezone.utc)  # -> 2026-06-06 CST (Sat), not in sessions
    out = await _run(nonsession, gather=_gather_returning([], gcalls),
                     draft=_draft(draft_calls), primary=StubSink(),
                     fallback=StubSink(), anchor=nonsession)
    assert out.status == "skipped_calendar"
    assert gcalls == []           # gather never called
    assert draft_calls == []      # draft never called


async def test_stale_run_returns_skipped_stale():
    gcalls, draft_calls = [], []
    late = _ANCHOR + timedelta(minutes=200)  # past 90-min tolerance
    out = await _run(late, gather=_gather_returning([], gcalls),
                     draft=_draft(draft_calls), primary=StubSink(),
                     fallback=StubSink())
    assert out.status == "skipped_stale"
    assert gcalls == []
    assert draft_calls == []


async def test_above_floor_publishes_and_returns_published():
    primary, draft_calls, gcalls = StubSink(), [], []
    out = await _run(_NOW_FRESH, gather=_gather_returning(_passing_sources(), gcalls),
                     draft=_draft(draft_calls), primary=primary,
                     fallback=StubSink())
    assert out.status == "published"
    assert gcalls == [1]                                   # gather ran
    assert draft_calls == [1]                              # draft ran
    assert primary.sent and primary.sent[0].startswith("【DEV / UNVERIFIED")


async def test_sub_floor_returns_outcome_and_skips_writer():
    primary, draft_calls, gcalls = StubSink(), [], []
    out = await _run(_NOW_FRESH, gather=_gather_returning([], gcalls),   # empty pool -> sub-floor
                     draft=_draft(draft_calls), primary=primary,
                     fallback=StubSink())
    assert out.status == "sub_floor"
    assert gcalls == [1]                                   # gather ran (needed for floor)
    assert draft_calls == []                               # draft NEVER awaited
    assert primary.sent == []                              # nothing published


async def test_force_calendar_runs_on_non_trading_day():
    primary, gcalls, draft_calls = StubSink(), [], []
    nonsession = datetime(2026, 6, 5, 22, 0, tzinfo=timezone.utc)  # 2026-06-06 CST (Sat)
    out = await _run(nonsession, gather=_gather_returning(_passing_sources(), gcalls),
                     draft=_draft(draft_calls), primary=primary,
                     fallback=StubSink(), force=True, anchor=nonsession)
    assert out.status == "published"
    assert gcalls == [1]                                   # calendar bypassed
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
                                  draft=_draft([]), primary=StubSink(),
                                  fallback=StubSink()))
    await asyncio.sleep(0.01)  # let t1 acquire the lock + enter gather
    t2 = asyncio.create_task(_run(_NOW_FRESH, gather=_quick_gather,
                                  draft=_draft([]), primary=StubSink(),
                                  fallback=StubSink()))
    await asyncio.sleep(0.01)
    gate.set()
    await asyncio.gather(t1, t2)
    # t2's gather must not start until t1 fully exits (lock held).
    assert order == ["enter", "exit", "second-enter"]


async def test_verify_fail_returns_outcome():
    """Verifier gate in run_once: I3-tripping bundle -> no publish, record_fail called."""
    primary = StubSink()
    bundle, commit_spy = _make_i3_bundle()
    draft_calls = []
    record_fail_calls: list = []

    async def _record_fail(trace_id, violations):
        record_fail_calls.append((trace_id, violations))

    async def _d():
        draft_calls.append(1)
        return bundle

    out = await _run(_NOW_FRESH,
                     gather=_gather_returning(_passing_sources(), []),
                     draft=_d, primary=primary, fallback=StubSink(),
                     record_fail=_record_fail)

    assert out.status == "verify_fail"
    assert "I3" in out.detail
    assert primary.sent == []                              # no publish
    assert len(record_fail_calls) == 1
    rf_trace, rf_violations = record_fail_calls[0]
    assert rf_trace == "t"
    assert any(v.check == "I3" for v in rf_violations)
    assert commit_spy["commit_calls"] == 0                 # commit NOT called
