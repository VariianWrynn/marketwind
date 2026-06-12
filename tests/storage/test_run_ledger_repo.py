import asyncpg
import pytest
from datetime import date
from marketwind.config import settings
from marketwind.storage.migrate import apply_migrations
from marketwind.storage.repo import record_run, get_run_status

_D = date(2026, 6, 9)


@pytest.fixture
async def conn():
    c = await asyncpg.connect(settings.database_url)
    await apply_migrations(c)
    try:
        yield c
    finally:
        await c.close()


async def test_record_then_read_status(conn):
    await conn.execute("delete from run_ledger where job_id='r-main';")
    inserted = await record_run(conn, job_id="r-main", trading_date=_D,
                                status="published", trace_id="tr", detail=None)
    assert inserted is True
    assert await get_run_status(conn, job_id="r-main", trading_date=_D) == "published"
    await conn.execute("delete from run_ledger where job_id='r-main';")


async def test_second_record_conflicts_returns_false(conn):
    await conn.execute("delete from run_ledger where job_id='r-dup';")
    assert await record_run(conn, job_id="r-dup", trading_date=_D,
                            status="published", trace_id="a") is True
    assert await record_run(conn, job_id="r-dup", trading_date=_D,
                            status="published", trace_id="b") is False  # on conflict do nothing
    await conn.execute("delete from run_ledger where job_id='r-dup';")


async def test_missing_row_is_none(conn):
    assert await get_run_status(conn, job_id="r-absent", trading_date=_D) is None
