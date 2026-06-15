"""Mechanical Scout gather: queries -> search -> fetch -> parse -> persist.

Control flow is unit-tested with injected seams; the live `gather_live` wiring
(Bocha + Playwright) is smoke-only. NOTE (P2a gap): quotes get
attached_primary_url=None — primary-tracing is unbuilt, so the live floor will
not pass yet; real delivery is proven via a seeded pool.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, datetime

from marketwind.scout.clean import clean_main_content, extract_quotes
from marketwind.scout.domain import Quote, Source
from marketwind.scout.outlets import domain_of
from marketwind.scout.query import build_constituent_queries, build_recap_queries

SearchFn = Callable[[str], Awaitable[list[tuple[str, str]]]]
FetchFn = Callable[[str], Awaitable[str]]
ParseFn = Callable[[str], tuple[str, list[Quote]]]
PersistFn = Callable[[Source], Awaitable[None]]


async def build_pool(*, prev_session: date, names: list[str] = (), search: SearchFn, fetch_page: FetchFn,
                     parse: ParseFn, persist: PersistFn, now: datetime) -> list[Source]:
    queries = build_recap_queries(prev_session) + build_constituent_queries(names, prev_session)
    seen: set[str] = set()
    out: list[Source] = []
    for query in queries:
        for url, _snippet in await search(query):
            if url in seen:
                continue
            seen.add(url)
            try:
                html = await fetch_page(url)
            except Exception:
                continue  # one bad page is skipped, not fatal
            raw, quotes = parse(html)
            if not quotes:
                continue
            src = Source(url=url, domain=domain_of(url), publish_ts=now,
                         raw_content=raw, quotes=quotes)
            await persist(src)
            out.append(src)
    return out


def default_parse(html: str) -> tuple[str, list[Quote]]:
    """Real clean+extract. May raise ValueError on empty extraction (caller skips)."""
    raw = clean_main_content(html)
    return raw, extract_quotes(raw)


async def gather_live(conn, *, now: datetime, prev_session: date) -> list[Source]:  # pragma: no cover - live
    """Wire real Bocha search + Playwright fetch + DB persist. Smoke-only."""
    from playwright.async_api import async_playwright

    from marketwind.scout import discover, fetch
    from marketwind.scout.market import fetch_star50_constituents
    from marketwind.storage.repo import upsert_source

    async def _search(query: str) -> list[tuple[str, str]]:
        return await discover.search(query)

    def _safe_parse(html: str) -> tuple[str, list[Quote]]:
        try:
            return default_parse(html)
        except ValueError:
            return "", []

    async def _persist(src: Source) -> None:
        await upsert_source(conn, src)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context()

        async def _fetch(url: str) -> str:
            return await fetch.fetch_html(context, url)

        names = list(fetch_star50_constituents())
        try:
            return await build_pool(prev_session=prev_session, names=names, search=_search,
                                    fetch_page=_fetch, parse=_safe_parse,
                                    persist=_persist, now=now)
        finally:
            await browser.close()
