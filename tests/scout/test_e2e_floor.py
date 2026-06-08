"""Integration test: enrich_primary closes the live-floor primary gap.

Proves end-to-end (no DB, no network — all seams injected, all data in-memory):

  BEFORE enrichment: a seeded pool with ≥8 grounded quotes / ≥2 independent
  outlets fails the floor (primary_traced_quotes == 0).

  AFTER enrichment: the same pool with one cninfo-traced quote attached passes
  the full conjunctive floor.

  BONUS path: a wrong-figure fetch leaves primary == 0 and the floor still
  fails (the match-guard bites end-to-end).
"""
from __future__ import annotations

from datetime import datetime, timezone, date

from marketwind.scout.domain import Quote, Source
from marketwind.scout.enrich import enrich_primary
from marketwind.scout.runner import evaluate_floor, MIN_GROUNDED_QUOTES

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------
NOW = datetime(2026, 6, 5, tzinfo=timezone.utc)
ON_DATE = date(2026, 6, 5)

# A single STAR50 constituent that the rules classifier knows about.
CONS = {"中芯国际": "688981"}

# The quantitative quote that will be traced: a 募资 figure (maps to "fundraising"
# → cninfo via primary_venue_for).
QUANT_TEXT = "中芯国际本次募集资金总额3.6亿元"
DISCLOSURE_MATCH = "本次募集资金总额360,000,000元"   # 3.6 × 1e8 == 360,000,000 → matches
DISCLOSURE_WRONG = "本次募集资金总额5亿元"            # 5e8 ≠ 3.6e8 → guard rejects

PRIMARY_URL = "https://www.cninfo.com.cn/new/disclosure/688981/announcement.html"


def _make_quote(text: str, quant: bool = True) -> Quote:
    return Quote(
        text=text,
        span_start=0,
        span_end=len(text),
        context_before=None,
        context_after=None,
        is_quantitative=quant,
    )


def _make_source(domain: str, quotes: list[Quote]) -> Source:
    return Source(
        url=f"https://{domain}/article",
        domain=domain,
        publish_ts=NOW,
        raw_content="content",
        quotes=quotes,
    )


# ---------------------------------------------------------------------------
# Pool builder: MIN_GROUNDED_QUOTES quotes spread across two independent outlets.
# One of those quotes is quantitative and names a STAR50 constituent;
# the rest are plain factual quotes (is_quantitative=False, no primary candidate).
# ---------------------------------------------------------------------------
def _build_pool() -> list[Source]:
    # One source with the traceable quantitative quote + several filler quotes.
    filler_quotes = [
        _make_quote(f"科创50指数第{i}条资讯", quant=False)
        for i in range(MIN_GROUNDED_QUOTES - 1)  # 7 fillers
    ]
    src_a = _make_source("news-a.example.com", [_make_quote(QUANT_TEXT)] + filler_quotes)

    # Second independent outlet — just filler quotes so outlet count ≥ 2.
    src_b = _make_source("news-b.example.com", [_make_quote("另一家媒体报道中芯国际动态", quant=False)])

    return [src_a, src_b]


# ---------------------------------------------------------------------------
# Async seam stubs
# ---------------------------------------------------------------------------
async def _classify_none(text: str):
    return None   # rules-only; no DeepSeek fallback needed


async def _trace_ok(claim_type: str, symbol: str, on_date: date) -> str | None:
    assert claim_type == "fundraising", f"unexpected claim_type={claim_type!r}"
    assert symbol == "688981", f"unexpected symbol={symbol!r}"
    return PRIMARY_URL


async def _fetch_match(url: str) -> str:
    return DISCLOSURE_MATCH


async def _fetch_wrong(url: str) -> str:
    return DISCLOSURE_WRONG


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_floor_fails_before_enrichment():
    """Baseline: without enrichment no quote has an attached_primary_url."""
    pool = _build_pool()
    result = evaluate_floor(pool)

    assert result.grounded_quotes >= MIN_GROUNDED_QUOTES, (
        f"fixture is under-seeded: only {result.grounded_quotes} grounded quotes"
    )
    assert result.independent_outlets >= 2, (
        f"fixture needs ≥2 outlets, got {result.independent_outlets}"
    )
    # Core assertion: floor must FAIL because no primary yet.
    assert result.primary_traced_quotes == 0
    assert result.passed is False


async def test_floor_passes_after_enrichment():
    """After enrichment the quantitative quote gets a verified primary URL
    and the full conjunctive floor clears."""
    pool = _build_pool()

    # Sanity: pool fails before enrichment.
    assert evaluate_floor(pool).passed is False

    enriched = await enrich_primary(
        pool,
        classify=_classify_none,
        trace=_trace_ok,
        fetch=_fetch_match,
        constituents=CONS,
        on_date=ON_DATE,
    )
    result = evaluate_floor(enriched)

    # Core before/after contrast.
    assert result.primary_traced_quotes >= 1, (
        f"expected ≥1 primary-traced quote after enrichment, got {result.primary_traced_quotes}"
    )
    assert result.passed is True, (
        f"floor should pass after enrichment: {result}"
    )


async def test_wrong_number_fetch_leaves_floor_failing():
    """Guard bites end-to-end: mismatched figure → no primary attach → floor still fails."""
    pool = _build_pool()

    enriched = await enrich_primary(
        pool,
        classify=_classify_none,
        trace=_trace_ok,
        fetch=_fetch_wrong,   # disclosure carries a DIFFERENT number
        constituents=CONS,
        on_date=ON_DATE,
    )
    result = evaluate_floor(enriched)

    assert result.primary_traced_quotes == 0
    assert result.passed is False, (
        f"floor should still fail when disclosure number mismatches: {result}"
    )
