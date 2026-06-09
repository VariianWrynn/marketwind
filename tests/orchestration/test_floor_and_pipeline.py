"""run_pipeline: reuse evaluate_floor; gate before assembling; status on shortfall."""
import pytest

from marketwind.gateway.im.label import DEV_PREFIX
from marketwind.gateway.im.stub import StubSink
from marketwind.orchestration.runner import run_pipeline
from marketwind.scout.domain import Quote, Source
from marketwind.writer.domain import (
    DraftBundle, DraftClaim, DraftSentence, PooledQuote, PooledSource, WriterOutput,
)
from datetime import datetime, timezone


def _src(domain: str, n_quotes: int, *, primary_urls: int = 0) -> Source:
    quotes = []
    for i in range(n_quotes):
        quotes.append(Quote(
            text=f"q{i}", span_start=0, span_end=2, context_before=None,
            context_after=None, is_quantitative=True,
            attached_primary_url=("http://primary" if i < primary_urls else None),
        ))
    return Source(url=f"http://{domain}/a", domain=domain,
                  publish_ts=datetime.now(timezone.utc), raw_content="x" * 50,
                  quotes=quotes)


def _above_floor() -> list[Source]:
    # 8 grounded, 1 primary, 2 outlets — exactly clears 8/1/2.
    return [_src("sina.com", 4, primary_urls=1), _src("eastmoney.com", 4)]


def _below_floor() -> list[Source]:
    # 5 quotes, 1 outlet — fails 8/1/2 on two dimensions.
    return [_src("sina.com", 5, primary_urls=1)]


_CLEAN_TEXT = "科创50涨0.36%"
_CLEAN_TEXT_LEN = len(_CLEAN_TEXT)


def _clean_pool() -> list[PooledSource]:
    """A PooledSource where raw_content[0:len] == quote text, has primary → clean."""
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


def _make_bundle(pool: list[PooledSource]) -> tuple[DraftBundle, dict]:
    """Return (bundle, spy) where spy["commit_calls"] increments on each commit()."""
    spy = {"commit_calls": 0}

    async def _commit() -> str:
        spy["commit_calls"] += 1
        return "report-id"

    bundle = DraftBundle(
        output=_writer_output(),
        pool=pool,
        body="科创50昨日收涨0.36%。[1]",
        commit=_commit,
    )
    return bundle, spy


async def _fake_judge(prompt: str) -> str:
    return '{"violations": []}'


@pytest.mark.asyncio
async def test_sub_floor_emits_status_and_does_not_assemble():
    primary, dev = StubSink(), StubSink()
    draft_calls = {"n": 0}

    async def draft() -> DraftBundle:
        draft_calls["n"] += 1
        bundle, _ = _make_bundle(_clean_pool())
        return bundle

    await run_pipeline(
        sources=_below_floor(),
        draft=draft,
        judge=_fake_judge,
        record_fail=None,  # must never be called
        primary=primary,
        fallback=StubSink(),
        dev_channel=dev,
        trace_id="t-low",
    )
    assert primary.sent == []                       # nothing published
    assert draft_calls["n"] == 0                    # Writer never invoked
    assert len(dev.sent) == 1
    assert "t-low" in dev.sent[0]
    assert "grounded_quotes=5" in dev.sent[0]


@pytest.mark.asyncio
async def test_verify_fail_blocks_publish_and_records():
    """Verifier gate: I3-tripping bundle → no publish, record_fail called, dev message sent."""
    primary, dev = StubSink(), StubSink()
    bundle, commit_spy = _make_bundle(_i3_pool())
    record_fail_calls: list[tuple] = []

    async def draft() -> DraftBundle:
        return bundle

    async def record_fail(trace_id: str, violations) -> None:
        record_fail_calls.append((trace_id, violations))

    await run_pipeline(
        sources=_above_floor(),
        draft=draft,
        judge=_fake_judge,
        record_fail=record_fail,
        primary=primary,
        fallback=StubSink(),
        dev_channel=dev,
        trace_id="t-fail",
    )

    assert primary.sent == []                        # nothing published
    assert len(dev.sent) == 1
    assert "t-fail" in dev.sent[0]
    assert "verifier gate failed" in dev.sent[0]
    assert "I3" in dev.sent[0]

    assert len(record_fail_calls) == 1
    rf_trace, rf_violations = record_fail_calls[0]
    assert rf_trace == "t-fail"
    assert len(rf_violations) > 0
    assert any(v.check == "I3" for v in rf_violations)

    assert commit_spy["commit_calls"] == 0           # commit NOT called


@pytest.mark.asyncio
async def test_above_floor_assembles_labels_and_pushes():
    primary, dev = StubSink(), StubSink()
    bundle, commit_spy = _make_bundle(_clean_pool())
    record_fail_calls: list = []

    async def draft() -> DraftBundle:
        return bundle

    async def record_fail(trace_id, violations) -> None:
        record_fail_calls.append((trace_id, violations))

    await run_pipeline(
        sources=_above_floor(),
        draft=draft,
        judge=_fake_judge,
        record_fail=record_fail,
        primary=primary,
        fallback=StubSink(),
        dev_channel=dev,
        trace_id="t-ok",
    )

    assert len(primary.sent) == 1
    assert primary.sent[0].startswith(DEV_PREFIX)
    assert len(primary.sent[0]) <= 500
    assert dev.sent == []                            # no status message
    assert commit_spy["commit_calls"] == 1           # commit WAS called
    assert record_fail_calls == []                   # record_fail NOT called
