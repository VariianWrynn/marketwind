"""run_pipeline: returns RunOutcome; check-before-send guards duplicate publish."""
import pytest

from marketwind.gateway.im.base import SendResult
from marketwind.gateway.im.label import DEV_PREFIX
from marketwind.gateway.im.stub import StubSink
from marketwind.orchestration.runner import run_pipeline
from marketwind.scheduling.outcome import PUBLISHED, SUB_FLOOR, VERIFY_FAIL
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


def _make_bundle(pool: list[PooledSource], reference: str = "") -> tuple[DraftBundle, dict]:
    """Return (bundle, spy) where spy["commit_calls"] increments on each commit()."""
    spy = {"commit_calls": 0}

    async def _commit() -> str:
        spy["commit_calls"] += 1
        return "report-id"

    bundle = DraftBundle(
        output=_writer_output(),
        pool=pool,
        body="科创50昨日收涨0.36%。[1]",
        reference=reference,
        commit=_commit,
    )
    return bundle, spy


async def _fake_judge(prompt: str) -> str:
    return '{"violations": []}'


async def _never() -> bool:
    return False


async def _always() -> bool:
    return True


async def _noop_record(trace_id: str, violations) -> None:
    pass


# ── sub-floor: returns SUB_FLOOR, publishes nothing, does NOT call draft ──────

@pytest.mark.asyncio
async def test_sub_floor_returns_outcome_no_publish():
    primary = StubSink()
    draft_calls = {"n": 0}

    async def _draft_should_not_run() -> DraftBundle:
        draft_calls["n"] += 1
        bundle, _ = _make_bundle(_clean_pool())
        return bundle

    out = await run_pipeline(
        sources=_below_floor(),
        draft=_draft_should_not_run,
        judge=_fake_judge,
        record_fail=_noop_record,
        already_published=_never,
        primary=primary,
        fallback=StubSink(),
        trace_id="t-low",
    )
    assert out.status == SUB_FLOOR
    assert "grounded_quotes" in out.detail
    assert primary.sent == []
    assert draft_calls["n"] == 0


# ── verify-fail: returns VERIFY_FAIL with tripped check in detail, records ────

@pytest.mark.asyncio
async def test_verify_fail_returns_outcome_and_records():
    primary = StubSink()
    bundle, commit_spy = _make_bundle(_i3_pool())
    recorded: list[tuple] = []

    async def record_fail(*args):
        recorded.append(args)

    async def draft() -> DraftBundle:
        return bundle

    out = await run_pipeline(
        sources=_above_floor(),
        draft=draft,
        judge=_fake_judge,
        record_fail=record_fail,
        already_published=_never,
        primary=primary,
        fallback=StubSink(),
        trace_id="t-fail",
    )
    assert out.status == VERIFY_FAIL
    assert "I3" in out.detail
    assert len(recorded) == 1
    rf_call = recorded[0]
    assert len(rf_call) == 3
    assert rf_call[0] == "t-fail"
    assert any(v.check == "I3" for v in rf_call[1])
    assert rf_call[2] is bundle.output
    assert primary.sent == []
    assert commit_spy["commit_calls"] == 0


# ── above-floor: publishes the brief AND returns PUBLISHED ────────────────────

@pytest.mark.asyncio
async def test_pass_publishes_and_returns_published():
    primary = StubSink()
    bundle, commit_spy = _make_bundle(_clean_pool())
    record_fail_calls: list = []

    async def draft() -> DraftBundle:
        return bundle

    async def record_fail(trace_id, violations) -> None:
        record_fail_calls.append((trace_id, violations))

    out = await run_pipeline(
        sources=_above_floor(),
        draft=draft,
        judge=_fake_judge,
        record_fail=record_fail,
        already_published=_never,
        primary=primary,
        fallback=StubSink(),
        trace_id="t-ok",
    )
    assert out.status == PUBLISHED
    assert primary.sent and primary.sent[0].startswith(DEV_PREFIX)
    assert commit_spy["commit_calls"] == 1
    assert record_fail_calls == []


# ── check-before-send: already published → skip commit+publish, still PUBLISHED

@pytest.mark.asyncio
async def test_already_published_skips_send():
    primary = StubSink()
    bundle, commit_spy = _make_bundle(_clean_pool())
    draft_calls = {"n": 0}

    async def draft() -> DraftBundle:
        draft_calls["n"] += 1
        return bundle

    out = await run_pipeline(
        sources=_above_floor(),
        draft=draft,
        judge=_fake_judge,
        record_fail=_noop_record,
        already_published=_always,
        primary=primary,
        fallback=StubSink(),
        trace_id="t-dup",
    )
    assert out.status == PUBLISHED
    assert draft_calls["n"] == 1       # guard fires AFTER verify, not as early short-circuit
    assert primary.sent == []          # no duplicate brief
    assert commit_spy["commit_calls"] == 0   # and no second commit


# ── reference message tests ───────────────────────────────────────────────────

class _RefFailSink:
    """Succeeds on the report body, fails on the reference (header contains 来源)."""
    def __init__(self):
        self.sent = []
    def send(self, text):
        if "来源" in text:
            return SendResult(ok=False, error="ref boom")
        self.sent.append(text)
        return SendResult(ok=True)


@pytest.mark.asyncio
async def test_reference_sent_as_second_message():
    primary = StubSink()
    bundle, _ = _make_bundle(_clean_pool(), reference="—— 来源 ——\n[1] x.com — http://x/a")

    async def draft() -> DraftBundle:
        return bundle

    out = await run_pipeline(
        sources=_above_floor(), draft=draft, judge=_fake_judge,
        record_fail=_noop_record, already_published=_never,
        primary=primary, fallback=StubSink(), trace_id="t-ref",
    )
    assert out.status == PUBLISHED
    assert out.detail is None
    assert len(primary.sent) == 2
    assert primary.sent[0].startswith(DEV_PREFIX)
    assert primary.sent[1] == "—— 来源 ——\n[1] x.com — http://x/a"


@pytest.mark.asyncio
async def test_empty_reference_sends_only_one_message():
    primary = StubSink()
    bundle, _ = _make_bundle(_clean_pool(), reference="")

    async def draft() -> DraftBundle:
        return bundle

    out = await run_pipeline(
        sources=_above_floor(), draft=draft, judge=_fake_judge,
        record_fail=_noop_record, already_published=_never,
        primary=primary, fallback=StubSink(), trace_id="t-noref",
    )
    assert out.status == PUBLISHED
    assert len(primary.sent) == 1


@pytest.mark.asyncio
async def test_reference_send_failure_is_published_with_detail():
    primary, fallback = _RefFailSink(), _RefFailSink()
    bundle, _ = _make_bundle(_clean_pool(), reference="—— 来源 ——\n[1] x.com — http://x/a")

    async def draft() -> DraftBundle:
        return bundle

    out = await run_pipeline(
        sources=_above_floor(), draft=draft, judge=_fake_judge,
        record_fail=_noop_record, already_published=_never,
        primary=primary, fallback=fallback, trace_id="t-reffail",
    )
    assert out.status == PUBLISHED
    assert "source-reference message FAILED" in out.detail
    assert "t-reffail" in out.detail
    assert primary.sent and primary.sent[0].startswith(DEV_PREFIX)
