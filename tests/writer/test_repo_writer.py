"""Writer-side persistence tests (real Postgres via DATABASE_URL)."""

from datetime import datetime

import asyncpg
import pytest

from marketwind.config import settings
from marketwind.scout.domain import Quote, Source
from marketwind.scout.timeparse import CN_TZ
from marketwind.storage.migrate import apply_migrations
from marketwind.storage.repo import load_pool, upsert_source


@pytest.fixture
async def conn():
    c = await asyncpg.connect(settings.database_url)
    await apply_migrations(c)
    try:
        yield c
    finally:
        await c.close()


def _sample_source(url="https://m.cls.cn/a/1", raw="句子一。句子二涨0.36%。"):
    return Source(
        url=url, domain="m.cls.cn",
        publish_ts=datetime(2026, 5, 28, 15, 30, tzinfo=CN_TZ),
        raw_content=raw, byline="财联社", is_primary=False,
        quotes=[
            Quote("句子一。", 0, 4, None, "句子二涨0.36%。", False, "factual"),
            Quote("句子二涨0.36%。", 4, len(raw), "句子一。", None, True, "data",
                  attached_primary_url="https://cninfo.com.cn/x"),
        ],
    )


async def test_load_pool_returns_sources_with_real_ids(conn):
    await conn.execute("delete from sources;")
    sid = await upsert_source(conn, _sample_source())
    pool = await load_pool(conn)
    assert len(pool) == 1
    src = pool[0]
    assert src.source_id == sid
    assert src.domain == "m.cls.cn"
    assert len(src.quotes) == 2
    # quote ids are real uuids; one carries the primary trace
    assert all(q.quote_id for q in src.quotes)
    assert any(q.attached_primary_url for q in src.quotes)
