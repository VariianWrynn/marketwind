"""Schema + repository tests for Scout persistence (real Postgres via DATABASE_URL)."""

import asyncpg
import pytest

from marketwind.config import settings
from marketwind.storage.migrate import apply_migrations


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
