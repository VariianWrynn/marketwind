import asyncpg
import pytest
from datetime import date
from marketwind.config import settings
from marketwind.storage.migrate import apply_migrations


@pytest.fixture
async def conn():
    c = await asyncpg.connect(settings.database_url)
    await apply_migrations(c)
    try:
        yield c
    finally:
        await c.close()


async def test_unique_job_date_rejects_duplicate(conn):
    await conn.execute("delete from run_ledger where job_id='t-main';")
    await conn.execute(
        "insert into run_ledger (job_id, trading_date, status, trace_id)"
        " values ('t-main', $1, 'published', 'tr1');", date(2026, 6, 9))
    with pytest.raises(asyncpg.UniqueViolationError):
        await conn.execute(
            "insert into run_ledger (job_id, trading_date, status, trace_id)"
            " values ('t-main', $1, 'published', 'tr2');", date(2026, 6, 9))
    await conn.execute("delete from run_ledger where job_id='t-main';")
