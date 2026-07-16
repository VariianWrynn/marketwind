"""Tests for verify() aggregator — Tier-1 + Tier-2 combined."""

from __future__ import annotations

from marketwind.verifier.domain import VerifyResult
from marketwind.verifier.verifier import verify
from marketwind.writer.domain import (
    DraftClaim,
    DraftSentence,
    PooledQuote,
    PooledSource,
    WriterOutput,
)


# ---------------------------------------------------------------------------
# Fake judge helpers
# ---------------------------------------------------------------------------

async def _judge_clean(_prompt: str) -> str:
    return '{"violations": []}'


async def _judge_synthesis_flagged(_prompt: str) -> str:
    # Returns one I1 violation only when called for synthesis check;
    # contradiction check gets the same canned response — that's fine,
    # we only assert on the set of check codes present.
    return '{"violations": [{"locus": "c-001", "detail": "融合"}]}'


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

def _make_clean_pool() -> tuple[WriterOutput, list[PooledSource]]:
    """A WriterOutput + pool with no violations of any kind."""
    text = "营收同比增长20%"
    quote = PooledQuote(
        quote_id="q-001",
        text=text,
        is_quantitative=True,
        quote_type="data",
        attached_primary_url="https://example.com/primary",
        span_start=0,
        span_end=len(text),
    )
    source = PooledSource(
        source_id="s-001",
        url="https://example.com/primary",
        domain="example.com",
        is_primary=True,
        quotes=[quote],
        raw_content=text,
    )
    claim = DraftClaim(
        local_id="c-001",
        statement="公司营收同比增长20%。",
        quote_ids=["q-001"],
    )
    sentence = DraftSentence(
        sentence="公司营收同比增长20%。",
        claim_ids=["c-001"],
        source_ids=["s-001"],
        sentence_type="factual",
    )
    output = WriterOutput(claims=[claim], sentences=[sentence])
    return output, [source]


def _make_cross_tier_pool() -> tuple[WriterOutput, list[PooledSource]]:
    """Trips I3 (quant with no primary) at Tier-1; judge also flags I1."""
    text = "营收增长30%"
    quote = PooledQuote(
        quote_id="q-002",
        text=text,
        is_quantitative=True,          # quantitative ...
        quote_type="data",
        attached_primary_url=None,     # ... but no primary URL
        span_start=0,
        span_end=len(text),
    )
    source = PooledSource(
        source_id="s-002",
        url="https://secondary.example.com/",
        domain="secondary.example.com",
        is_primary=False,              # not primary either
        quotes=[quote],
        raw_content=text,
    )
    claim = DraftClaim(
        local_id="c-001",
        statement="营收增长30%，市场预期良好。",
        quote_ids=["q-002"],
    )
    sentence = DraftSentence(
        sentence="营收增长30%，市场预期良好。",
        claim_ids=["c-001"],
        source_ids=["s-002"],
        sentence_type="factual",
    )
    output = WriterOutput(claims=[claim], sentences=[sentence])
    return output, [source]


# ---------------------------------------------------------------------------
# Test: clean case → passed True, no violations
# ---------------------------------------------------------------------------

async def test_verify_clean_passes():
    output, pool = _make_clean_pool()
    result = await verify(output, pool, judge=_judge_clean)
    assert isinstance(result, VerifyResult)
    assert result.passed is True
    assert result.violations == []


# ---------------------------------------------------------------------------
# Test: cross-tier aggregation — I3 from Tier-1, I1 from Tier-2 judge
# ---------------------------------------------------------------------------

async def test_verify_cross_tier_aggregation():
    output, pool = _make_cross_tier_pool()
    result = await verify(output, pool, judge=_judge_synthesis_flagged)
    assert result.passed is False
    check_codes = {v.check for v in result.violations}
    assert "I3" in check_codes, f"Expected I3 in {check_codes}"
    assert "I1" in check_codes, f"Expected I1 in {check_codes}"


# ---------------------------------------------------------------------------
# Test: I12 — derived_metric claim without methodology fails the gate
# ---------------------------------------------------------------------------

async def test_verify_flags_i12_derived_without_methodology():
    text = "长鑫日赚3.6亿元"
    quote = PooledQuote(quote_id="q-001", text=text, is_quantitative=True,
                        quote_type="data", attached_primary_url="https://cninfo.com.cn/x",
                        span_start=0, span_end=len(text))
    source = PooledSource(source_id="s-001", url="https://cninfo.com.cn/x",
                          domain="cninfo.com.cn", is_primary=True, quotes=[quote],
                          raw_content=text)
    claim = DraftClaim("c-001", "长鑫存储去年日赚3.6亿元。", ["q-001"],
                       category="derived_metric")  # methodology missing
    sentence = DraftSentence("长鑫存储去年日赚3.6亿元。", ["c-001"], ["s-001"], "factual")
    out = WriterOutput(claims=[claim], sentences=[sentence])
    result = await verify(out, [source], judge=_judge_clean)
    assert result.passed is False
    assert "I12" in {v.check for v in result.violations}
