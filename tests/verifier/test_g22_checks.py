"""Tests for G2.2 verifier checks: I3b corroboration, I10 time-window, I11 cross-report, I6 freshness."""

from __future__ import annotations

import pytest

from marketwind.verifier.checks import check_corroboration, index_quotes
from marketwind.verifier.judge import check_cross_report_consistency, check_freshness
from marketwind.writer.domain import (
    DraftClaim,
    DraftSentence,
    PooledQuote,
    PooledSource,
    WriterOutput,
)


# ---------------------------------------------------------------------------
# I3b corroboration
# ---------------------------------------------------------------------------

def _pool(domain: str, primary: bool = False, quant: bool = True):
    q = PooledQuote(
        quote_id="q1", text="test", is_quantitative=quant,
        quote_type="factual", attached_primary_url="http://p" if primary else None,
        span_start=0, span_end=4,
    )
    return [PooledSource(
        source_id="s1", url="http://x", domain=domain,
        is_primary=primary, quotes=[q], raw_content="test",
    )]


def test_i3b_fires_single_source_no_attribution():
    pool = _pool("example.com")
    idx = index_quotes(pool)
    output = WriterOutput(
        claims=[DraftClaim(local_id="c1", statement="test", quote_ids=["q1"])],
        sentences=[DraftSentence(sentence="test。", claim_ids=["c1"],
                                 source_ids=["s1"], sentence_type="factual")],
    )
    violations = check_corroboration(output, idx)
    assert len(violations) == 1
    assert violations[0].check == "I3b"


def test_i3b_passes_with_attribution_prefix():
    pool = _pool("example.com")
    idx = index_quotes(pool)
    output = WriterOutput(
        claims=[DraftClaim(local_id="c1", statement="test", quote_ids=["q1"])],
        sentences=[DraftSentence(sentence="据公告，test。", claim_ids=["c1"],
                                 source_ids=["s1"], sentence_type="factual")],
    )
    violations = check_corroboration(output, idx)
    assert len(violations) == 0


def test_i3b_passes_two_independent_sources():
    q1 = PooledQuote(quote_id="q1", text="a", is_quantitative=True,
                     quote_type="factual", attached_primary_url=None,
                     span_start=0, span_end=1)
    q2 = PooledQuote(quote_id="q2", text="b", is_quantitative=True,
                     quote_type="factual", attached_primary_url=None,
                     span_start=0, span_end=1)
    pool = [
        PooledSource(source_id="s1", url="http://a", domain="a.cn",
                     is_primary=False, quotes=[q1], raw_content="a"),
        PooledSource(source_id="s2", url="http://b", domain="b.cn",
                     is_primary=False, quotes=[q2], raw_content="b"),
    ]
    idx = index_quotes(pool)
    output = WriterOutput(
        claims=[DraftClaim(local_id="c1", statement="test", quote_ids=["q1", "q2"])],
        sentences=[DraftSentence(sentence="test。", claim_ids=["c1"],
                                 source_ids=["s1", "s2"], sentence_type="factual")],
    )
    violations = check_corroboration(output, idx)
    assert len(violations) == 0


def test_i3b_skips_non_quantitative():
    pool = _pool("example.com", quant=False)
    idx = index_quotes(pool)
    output = WriterOutput(
        claims=[DraftClaim(local_id="c1", statement="test", quote_ids=["q1"])],
        sentences=[DraftSentence(sentence="test。", claim_ids=["c1"],
                                 source_ids=["s1"], sentence_type="factual")],
    )
    violations = check_corroboration(output, idx)
    assert len(violations) == 0


# ---------------------------------------------------------------------------
# I11 cross-report consistency
# ---------------------------------------------------------------------------

async def test_i11_no_prior_reports_passes():
    output = WriterOutput(
        claims=[DraftClaim(local_id="c1", statement="test", quote_ids=[])],
        sentences=[],
    )

    async def recent():
        return []

    async def judge(_p):
        return '{"violations": []}'

    violations = await check_cross_report_consistency(output, recent_claims=recent, judge=judge)
    assert len(violations) == 0


async def test_i11_unavailable_fails_closed():
    output = WriterOutput(
        claims=[DraftClaim(local_id="c1", statement="test", quote_ids=[])],
        sentences=[],
    )

    async def recent():
        raise ConnectionError("db down")

    async def judge(_p):
        return '{"violations": []}'

    violations = await check_cross_report_consistency(output, recent_claims=recent, judge=judge)
    assert len(violations) == 1
    assert violations[0].check == "I11_unavailable"


# ---------------------------------------------------------------------------
# I6 freshness
# ---------------------------------------------------------------------------

async def test_i6_no_freshness_indicator_passes():
    output = WriterOutput(
        claims=[DraftClaim(local_id="c1", statement="营收增长20%", quote_ids=[])],
        sentences=[],
    )

    async def search(_s):
        raise RuntimeError("should not be called")

    violations = await check_freshness(output, search=search)
    assert len(violations) == 0


async def test_i6_freshness_indicator_with_fresher_data_fires():
    output = WriterOutput(
        claims=[DraftClaim(local_id="c1", statement="目前持股比例为7.9%", quote_ids=[])],
        sentences=[],
    )

    async def search(_s):
        return [("2026-05-20", "最新持股7.0%")]

    violations = await check_freshness(output, search=search)
    assert len(violations) == 1
    assert violations[0].check == "I6"


async def test_i6_freshness_indicator_no_fresher_data_passes():
    output = WriterOutput(
        claims=[DraftClaim(local_id="c1", statement="目前持股比例为7.9%", quote_ids=[])],
        sentences=[],
    )

    async def search(_s):
        return []

    violations = await check_freshness(output, search=search)
    assert len(violations) == 0


async def test_i6_search_failure_fails_closed():
    output = WriterOutput(
        claims=[DraftClaim(local_id="c1", statement="目前持股比例为7.9%", quote_ids=[])],
        sentences=[],
    )

    async def search(_s):
        raise RuntimeError("network down")

    violations = await check_freshness(output, search=search)
    assert len(violations) == 1
    assert violations[0].check == "I6"
    assert "network down" in violations[0].detail
