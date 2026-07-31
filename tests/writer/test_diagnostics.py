"""Tests for marketwind/writer/diagnostics.py — pool-funnel measurement.

TDD: tests were written before the real implementation and run against a
deliberately-wrong stub (all zeros / empty string) to establish the RED gate.
"""
from __future__ import annotations

from marketwind.writer.diagnostics import PoolFunnel, format_funnel, measure_funnel
from marketwind.writer.domain import (
    DraftClaim,
    DraftSentence,
    PooledQuote,
    PooledSource,
    WriterOutput,
)
from marketwind.writer.select import eligible_pool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _quote(qid: str, *, quant: bool, primary_url: str | None = None) -> PooledQuote:
    return PooledQuote(
        quote_id=qid,
        text="x",
        is_quantitative=quant,
        quote_type="data" if quant else "factual",
        attached_primary_url=primary_url,
        span_start=0,
        span_end=1,
    )


def _source(sid: str, domain: str, quotes: list[PooledQuote]) -> PooledSource:
    return PooledSource(
        source_id=sid,
        url=f"https://{domain}/a",
        domain=domain,
        is_primary=False,
        quotes=quotes,
        raw_content="raw",
    )


# ---------------------------------------------------------------------------
# Test 1: discriminating funnel — exercises the real eligible_pool filter
# ---------------------------------------------------------------------------

def _build_discriminating_raw() -> list[PooledSource]:
    """
    sohu.com      EXCLUDED  1 non-quant quote  → entire source dropped
    cls.cn        TRUSTED   1 quant quote       → survives (TRUSTED clears law3 without primary url)
    finance.eastmoney.com  SECONDARY  1 quant + 1 non-quant  → quant dropped, non-quant kept
    """
    s_sohu = _source("s-sohu", "sohu.com", [_quote("q-sohu-1", quant=False)])
    s_cls = _source("s-cls", "cls.cn", [_quote("q-cls-1", quant=True)])
    s_em = _source(
        "s-em",
        "finance.eastmoney.com",
        [
            _quote("q-em-quant", quant=True),
            _quote("q-em-nonquant", quant=False),
        ],
    )
    return [s_sohu, s_cls, s_em]


def test_measure_funnel_discriminating():
    """The main funnel test — pins exact counts through all three cross-sections."""
    raw = _build_discriminating_raw()
    elig = eligible_pool(raw)  # real filter, not hand-faked

    # WriterOutput: one factual sentence citing only the cls.cn source
    output = WriterOutput(
        claims=[DraftClaim("c-001", "cls quote", ["q-cls-1"])],
        sentences=[
            DraftSentence(
                sentence="cls fact",
                claim_ids=["c-001"],
                source_ids=["s-cls"],
                sentence_type="factual",
            )
        ],
    )

    funnel = measure_funnel(raw, elig, output)

    assert funnel == PoolFunnel(
        raw_sources=3,
        raw_quotes=4,
        raw_domains=3,
        eligible_sources=2,
        eligible_quotes=2,
        eligible_domains=2,
        quant_domains=1,
        cited_sources=1,
        cited_domains=1,
    )


# ---------------------------------------------------------------------------
# Test 2: structural sentences are NOT counted as citations
# ---------------------------------------------------------------------------

def test_structural_sentences_not_counted():
    """sentence_type='structural' must not affect cited_sources / cited_domains.

    The structural sentence below carries a real source_id on purpose. I8
    validation rejects a structural sentence bearing claim_ids but does NOT
    forbid source_ids (marketwind/writer/schema.py), so this shape does reach
    measure_funnel and the sentence_type guard is live, not defensive. With
    source_ids=[] the assertions below would hold even if that guard were
    deleted, making the test vacuous.

    If I8 is ever tightened to reject source_ids here, this test and that guard
    must be revisited together — the guard would become unreachable for
    schema-valid input. That tightening is an open owner's call; see
    docs/progress/writer-prompt-audit.md, "Out of scope / reverted".
    """
    s = _source("s1", "cls.cn", [_quote("q1", quant=True)])
    raw = [s]
    elig = eligible_pool(raw)

    output = WriterOutput(
        claims=[],
        sentences=[
            DraftSentence(
                sentence="intro",
                claim_ids=[],
                source_ids=["s1"],
                sentence_type="structural",
            )
        ],
    )

    funnel = measure_funnel(raw, elig, output)

    assert funnel.cited_sources == 0
    assert funnel.cited_domains == 0


# ---------------------------------------------------------------------------
# Test 3: unknown cited source_id is ignored, not fatal
# ---------------------------------------------------------------------------

def test_unknown_cited_source_ignored():
    """A factual sentence citing a source_id absent from raw must not raise.

    It still counts toward cited_sources (it is a distinct cited id),
    but cannot contribute a domain.
    """
    s = _source("s-known", "cls.cn", [_quote("q1", quant=True)])
    raw = [s]
    elig = eligible_pool(raw)

    output = WriterOutput(
        claims=[DraftClaim("c1", "stmt", ["q1"])],
        sentences=[
            DraftSentence(
                sentence="fact",
                claim_ids=["c1"],
                source_ids=["s-UNKNOWN"],  # not in raw pool
                sentence_type="factual",
            )
        ],
    )

    # Must not raise
    funnel = measure_funnel(raw, elig, output)

    assert funnel.cited_sources == 1   # distinct cited id counts
    assert funnel.cited_domains == 0   # domain cannot be resolved


# ---------------------------------------------------------------------------
# Test 4: format_funnel returns the exact greppable line
# ---------------------------------------------------------------------------

def test_format_funnel_exact_line():
    """format_funnel must return exactly the specified single-line format."""
    funnel = PoolFunnel(
        raw_sources=20,
        raw_quotes=150,
        raw_domains=20,
        eligible_sources=15,
        eligible_quotes=90,
        eligible_domains=15,
        quant_domains=8,
        cited_sources=1,
        cited_domains=1,
    )
    expected = (
        "pool funnel: raw 20 sources/150 quotes/20 domains"
        " | eligible 15/90/15 (quant domains 8)"
        " | cited 1 sources/1 domains"
    )
    assert format_funnel(funnel) == expected
