"""Schema + repository tests for Scout persistence (real Postgres via DATABASE_URL)."""

from dataclasses import replace
from datetime import datetime

import asyncpg
import pytest

from marketwind.config import settings
from marketwind.scout.domain import Quote, Source
from marketwind.scout.timeparse import CN_TZ
from marketwind.storage.migrate import apply_migrations
from marketwind.storage.repo import load_pool, persist_enriched, upsert_source


@pytest.fixture
async def conn():
    c = await asyncpg.connect(settings.database_url)
    try:
        await apply_migrations(c)
        yield c
    finally:
        await c.close()


async def test_p1_core_tables_exist(conn):
    for table in ("sources", "quotes", "claims", "sentences"):
        reg = await conn.fetchval(f"select to_regclass('public.{table}') is not null;")
        assert reg is True, f"{table} missing"


def _sample_source(url="https://m.cls.cn/a/1", raw="句子一。句子二涨0.36%。"):
    return Source(
        url=url,
        domain="m.cls.cn",
        publish_ts=datetime(2026, 5, 28, 15, 30, tzinfo=CN_TZ),
        raw_content=raw,
        byline="财联社",
        is_primary=False,
        quotes=[
            Quote("句子一。", 0, 4, None, "句子二涨0.36%。", False, "factual"),
            Quote("句子二涨0.36%。", 4, len(raw), "句子一。", None, True, "data"),
        ],
    )


async def test_upsert_inserts_source_and_quotes(conn):
    await conn.execute("delete from sources;")  # clean slate (cascades to quotes)
    sid = await upsert_source(conn, _sample_source())
    n_src = await conn.fetchval("select count(*) from sources;")
    n_q = await conn.fetchval("select count(*) from quotes where source_id = $1;", sid)
    assert n_src == 1
    assert n_q == 2


async def test_upsert_same_url_is_idempotent(conn):
    await conn.execute("delete from sources;")
    sid1 = await upsert_source(conn, _sample_source())
    sid2 = await upsert_source(conn, _sample_source())  # same url, second run
    n_src = await conn.fetchval("select count(*) from sources;")
    n_q = await conn.fetchval("select count(*) from quotes;")
    assert n_src == 1, "same URL must not duplicate the source"
    assert n_q == 2, "quotes must be replaced, not appended"
    assert sid1 == sid2


async def test_persist_enriched_survives_load_pool_roundtrip(conn):
    await conn.execute("delete from sources;")  # clean slate (cascades to quotes)
    src = _sample_source()                       # quant quote, attached_primary_url=None
    await upsert_source(conn, src)               # as gather persists it (no primary yet)
    enriched = replace(src, quotes=[
        replace(q, attached_primary_url="https://static.cninfo.com.cn/x.PDF")
        if q.is_quantitative else q
        for q in src.quotes
    ])
    await persist_enriched(conn, [enriched])     # the fix under test
    pool = await load_pool(conn)
    quant = [q for s in pool for q in s.quotes if q.is_quantitative]
    assert quant, "expected at least one quantitative quote in the loaded pool"
    assert quant[0].attached_primary_url == "https://static.cninfo.com.cn/x.PDF"
