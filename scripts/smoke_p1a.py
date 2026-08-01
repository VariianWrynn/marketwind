"""P1a live smoke (Task 15) — run the real Scout chain end-to-end, read output.

NOT part of the test suite (gitignored). Exercises: prev-session -> recap
queries -> Bocha search -> Playwright fetch -> clean/extract -> upsert ->
grounded-floor. Saves 1-2 real fetched pages to tests/scout/fixtures/.

Run:  .venv/Scripts/python.exe scripts/smoke_p1a.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

import asyncpg
from playwright.async_api import async_playwright

from marketwind.config import settings
from marketwind.scout.calendar import live_prev_trading_session
from marketwind.scout.clean import clean_main_content, extract_quotes
from marketwind.scout.discover import search
from marketwind.scout.domain import Source
from marketwind.scout.fetch import fetch_html
from marketwind.scout.outlets import domain_of
from marketwind.scout.primary import trace_to_primary
from marketwind.scout.query import build_recap_queries
from marketwind.scout.runner import evaluate_floor
from marketwind.scout.timeparse import CN_TZ
from marketwind.storage.repo import upsert_source

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "scout" / "fixtures"

# Domestic-only: per ARCHITECTURE Gap-2 we never crawl overseas sites.
_DOMESTIC_SUFFIXES = (".cn", ".com.cn", ".net.cn")
_DOMESTIC_HOSTS = {
    "finance.sina.com.cn", "cls.cn", "m.cls.cn", "eastmoney.com",
    "cnstock.com", "stcn.com", "yicai.com", "jrj.com.cn", "10jqka.com.cn",
}


def _is_domestic(url: str) -> bool:
    d = domain_of(url)
    return d in _DOMESTIC_HOSTS or d.endswith(_DOMESTIC_SUFFIXES)


async def main() -> int:
    prev = live_prev_trading_session(datetime.now(CN_TZ).date())
    print(f"[1] prev_trading_session = {prev}")

    queries = build_recap_queries(prev)
    # Smoke-only: add date-free recap queries so we exercise real extraction
    # even when the (simulated) prev-session date has little live coverage yet.
    queries = queries + ["科创50 收盘 复盘 涨跌", "科创板 成交额 权重股 表现"]
    print(f"[2] recap queries: {queries}")

    # Gather hits across queries, domestic only, de-duped by url.
    hits: dict[str, str] = {}
    for q in queries:
        try:
            for url, snippet in await search(q, count=8):
                if _is_domestic(url) and url not in hits:
                    hits[url] = snippet
        except Exception as e:  # noqa: BLE001 - smoke: report and continue
            print(f"    search failed for {q!r}: {e}")
    print(f"[3] domestic hits: {len(hits)}")
    for u in list(hits)[:10]:
        print(f"      {u}")

    if not hits:
        print("no domestic hits — cannot smoke the fetch path")
        return 1

    ingested = datetime.now(CN_TZ)
    sources: list[Source] = []
    saved = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        for i, url in enumerate(list(hits)[:6]):
            try:
                html = await fetch_html(context, url)
            except Exception as e:  # noqa: BLE001
                print(f"    fetch failed {url}: {e}")
                continue
            try:
                raw = clean_main_content(html)
            except ValueError as e:
                print(f"    clean empty {url}: {e}")
                continue
            quotes = extract_quotes(raw)
            src = Source(
                url=url,
                domain=domain_of(url),
                publish_ts=ingested,  # smoke: real publish_ts parsing is per-site
                raw_content=raw,
                byline=None,
                is_primary=False,
                quotes=quotes,
            )
            sources.append(src)
            print(f"    [{src.domain}] {len(quotes)} quotes, raw {len(raw)} chars")
            # Save first 2 real pages as offline fixtures.
            if saved < 2:
                (FIXTURES / f"live_recap_{saved}.html").write_text(html, encoding="utf-8")
                saved += 1
        await context.close()
        await browser.close()

    # [4] one primary trace (mechanism check) — attach to a quantitative quote.
    try:
        primary_url = await trace_to_primary("earnings", "688981", prev)  # SMIC
    except Exception as e:  # noqa: BLE001
        primary_url = None
        print(f"    trace_to_primary errored (expected for smoke): {e}")
    print(f"[4] trace_to_primary -> {primary_url}")
    if primary_url:
        for s in sources:
            for j, qt in enumerate(s.quotes):
                if qt.is_quantitative:
                    s.quotes[j] = qt.__class__(
                        text=qt.text, span_start=qt.span_start, span_end=qt.span_end,
                        context_before=qt.context_before, context_after=qt.context_after,
                        is_quantitative=qt.is_quantitative, quote_type="data",
                        attached_primary_url=primary_url,
                    )
                    break
            else:
                continue
            break

    # [5] upsert
    conn = await asyncpg.connect(settings.database_url)
    try:
        for s in sources:
            await upsert_source(conn, s)
        n_src = await conn.fetchval("select count(*) from sources;")
        n_q = await conn.fetchval("select count(*) from quotes;")
        n_primary = await conn.fetchval(
            "select count(*) from quotes where attached_primary_url is not null;"
        )
    finally:
        await conn.close()
    print(f"[5] upserted. sources={n_src} quotes={n_q} primary_traced={n_primary}")

    # [6] floor
    floor = evaluate_floor(sources)
    print(f"[6] floor: {floor}")
    print(f"    saved {saved} fixture page(s) to {FIXTURES}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
