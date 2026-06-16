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
TraceFn = Callable[[str, str, date], Awaitable[list[str]]]
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
        candidates = await trace(ref.claim_type, ref.symbol, on_date)
    except Exception:
        return None  # a trace failure degrades safely
    for url in candidates:
        try:
            disclosure = await fetch(url)
        except Exception:
            continue  # this candidate's fetch failed → try the next
        if amount_matches(quote.text, disclosure, rel_tol=rel_tol):
            return url  # THE GUARD: disclosure must carry the quote's number
    return None


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


async def enrich_primary_live(conn, sources, *, on_date):  # pragma: no cover - live
    """Wire the real cninfo trace + disclosure-PDF fetch + live STAR50
    constituent map. The DeepSeek fallback classifier is stubbed to None this
    phase (rules-only live). The disclosure fetch is plain HTTP (httpx) →
    derive PDF URL → download → pypdf extract; no Playwright in the enrich pass
    (gather_live still uses Playwright separately). Smoke-only."""
    import httpx

    from marketwind.scout.cninfo_pdf import fetch_cninfo_disclosure
    from marketwind.scout.market import fetch_star50_constituents
    from marketwind.scout.primary import trace_to_primary
    from marketwind.storage.repo import persist_enriched

    constituents = fetch_star50_constituents()

    async def _classify(text):
        return None  # DeepSeek fallback is a follow-up; rules-only live for now

    async def _trace(claim_type, symbol, d):
        return await trace_to_primary(claim_type, symbol, d)

    async with httpx.AsyncClient(follow_redirects=True, timeout=30,
                                 headers={"User-Agent": "Mozilla/5.0"}) as client:
        async def _fetch(url):
            return await fetch_cninfo_disclosure(client, url)

        enriched = await enrich_primary(sources, classify=_classify, trace=_trace,
                                        fetch=_fetch, constituents=constituents,
                                        on_date=on_date)
        await persist_enriched(conn, enriched)
        return enriched
