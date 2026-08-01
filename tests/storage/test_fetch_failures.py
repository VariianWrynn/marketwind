"""Live-Postgres tests for record_fetch_failure (fetch_failures table)."""

import asyncpg
import pytest

from marketwind.config import settings
from marketwind.storage.migrate import apply_migrations
from marketwind.storage.repo import record_fetch_failure


@pytest.fixture
async def conn():
    c = await asyncpg.connect(settings.database_url)
    await apply_migrations(c)
    try:
        yield c
    finally:
        await c.close()


async def test_writes_row(conn):
    await conn.execute("delete from fetch_failures;")
    await record_fetch_failure(
        conn, stage="gather_fetch", locus="https://x.cn/a", detail="RuntimeError('boom')"
    )

    rows = await conn.fetch("select stage, locus, detail from fetch_failures;")
    assert len(rows) == 1
    assert rows[0]["stage"] == "gather_fetch"
    assert rows[0]["locus"] == "https://x.cn/a"
    assert rows[0]["detail"] == "RuntimeError('boom')"


async def test_rows_accumulate_across_stages(conn):
    """An outage writes many rows; the weekly read must see each stage."""
    await conn.execute("delete from fetch_failures;")
    await record_fetch_failure(conn, stage="gather_fetch", locus="https://x.cn/a", detail="e1")
    await record_fetch_failure(conn, stage="enrich_trace", locus="earnings:688981", detail="e2")
    await record_fetch_failure(conn, stage="enrich_fetch", locus="https://cninfo.com.cn/d", detail="e3")

    stages = [r["stage"] for r in await conn.fetch(
        "select stage from fetch_failures order by stage;"
    )]
    assert stages == ["enrich_fetch", "enrich_trace", "gather_fetch"]
