"""run_pipeline: reuse evaluate_floor; gate before assembling; status on shortfall."""
import pytest

from marketwind.gateway.im.label import DEV_PREFIX
from marketwind.gateway.im.stub import StubSink
from marketwind.orchestration.runner import run_pipeline
from marketwind.scout.domain import Quote, Source
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


@pytest.mark.asyncio
async def test_sub_floor_emits_status_and_does_not_assemble():
    primary, dev = StubSink(), StubSink()
    called = {"assembled": False}

    async def make_body() -> str:
        called["assembled"] = True
        return "should-not-run"

    await run_pipeline(
        sources=_below_floor(), make_body=make_body,
        primary=primary, fallback=StubSink(), dev_channel=dev, trace_id="t-low",
    )
    assert primary.sent == []                       # nothing published
    assert called["assembled"] is False             # Writer never invoked
    assert len(dev.sent) == 1
    assert "t-low" in dev.sent[0]
    assert "grounded_quotes=5" in dev.sent[0]


@pytest.mark.asyncio
async def test_above_floor_assembles_labels_and_pushes():
    primary, dev = StubSink(), StubSink()

    async def make_body() -> str:
        return "科创50昨日收涨0.36%，成交额约3.24万亿元。[1]"

    await run_pipeline(
        sources=_above_floor(), make_body=make_body,
        primary=primary, fallback=StubSink(), dev_channel=dev, trace_id="t-ok",
    )
    assert len(primary.sent) == 1
    assert primary.sent[0].startswith(DEV_PREFIX)
    assert len(primary.sent[0]) <= 500
    assert dev.sent == []                            # no shortfall status
