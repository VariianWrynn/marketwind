"""Post-gather primary-tracing pass (cninfo). For each quantitative quote:
rules-extract (claim_type, symbol) -> DeepSeek fallback if inconclusive ->
route (cninfo only) -> trace candidate disclosure -> fetch it -> confirm the
quote's number appears (match-guard) -> attach the URL. Any failure degrades
to no-attach (Iron Law 3: never attach a primary we did not number-verify).

classify/trace/fetch are injected async seams so the whole pass is offline-
testable; enrich_primary_live wires the real ones (smoke-only)."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import date

from marketwind.scout.amount import amount_matches
from marketwind.scout.claim_extract import ClaimRef, extract_claim
from marketwind.scout.domain import Quote, Source
from marketwind.scout.primary import primary_venue_for

ClassifyFn = Callable[[str], Awaitable[ClaimRef | None]]
TraceFn = Callable[[str, str, date], Awaitable[str | None]]
FetchFn = Callable[[str], Awaitable[str]]


async def _resolve(quote: Quote, *, classify: ClassifyFn, trace: TraceFn,
                   fetch: FetchFn, constituents: dict[str, str], on_date: date,
                   rel_tol: float) -> str | None:
    """Return a number-verified primary URL for this quote, or None."""
    if not quote.is_quantitative:
        return None
    ref = extract_claim(quote.text, constituents)
    if ref is None:
        ref = await classify(quote.text)
    if ref is None:
        return None
    if primary_venue_for(ref.claim_type) != "cninfo":
        return None  # exchange / regulator venues are out of scope (recorded gap)
    try:
        url = await trace(ref.claim_type, ref.symbol, on_date)
        if not url:
            return None
        disclosure = await fetch(url)
    except Exception:
        return None  # any live failure → no attach, never abort
    if not amount_matches(quote.text, disclosure, rel_tol=rel_tol):
        return None  # THE GUARD: disclosure must carry the quote's number
    return url


async def enrich_primary(sources: list[Source], *, classify: ClassifyFn,
                         trace: TraceFn, fetch: FetchFn,
                         constituents: dict[str, str], on_date: date,
                         rel_tol: float = 0.02) -> list[Source]:
    out: list[Source] = []
    for src in sources:
        new_quotes: list[Quote] = []
        for q in src.quotes:
            url = await _resolve(q, classify=classify, trace=trace, fetch=fetch,
                                 constituents=constituents, on_date=on_date,
                                 rel_tol=rel_tol)
            new_quotes.append(replace(q, attached_primary_url=url) if url else q)
        out.append(replace(src, quotes=new_quotes))
    return out
