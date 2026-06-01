"""Migration runner: applies 0001 and is idempotent against real Postgres.

Uses DATABASE_URL from the env (the compose Postgres, published to localhost).
"""

import asyncpg
import pytest

from marketwind.config import settings
from marketwind.storage.migrate import apply_migrations


@pytest.mark.asyncio
async def test_migrations_apply_and_are_idempotent():
    conn = await asyncpg.connect(settings.database_url)
    try:
        # First run applies the bootstrap migration.
        await apply_migrations(conn)

        exists = await conn.fetchval(
            "select to_regclass('public.schema_migrations') is not null;"
        )
        assert exists is True

        count_0001 = await conn.fetchval(
            "select count(*) from schema_migrations where version = '0001_schema_migrations';"
        )
        assert count_0001 == 1

        # Second run must be a no-op: no error, no duplicate row.
        applied_again = await apply_migrations(conn)
        assert applied_again == []

        count_after = await conn.fetchval(
            "select count(*) from schema_migrations where version = '0001_schema_migrations';"
        )
        assert count_after == 1
    finally:
        await conn.close()
