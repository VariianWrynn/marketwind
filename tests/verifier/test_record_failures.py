"""Live-Postgres tests for record_verifier_failures (claim_failures table)."""

import asyncpg
import pytest

from marketwind.config import settings
from marketwind.storage.migrate import apply_migrations
from marketwind.storage.repo import record_verifier_failures
from marketwind.verifier.domain import Violation


@pytest.fixture
async def conn():
    c = await asyncpg.connect(settings.database_url)
    await apply_migrations(c)
    try:
        yield c
    finally:
        await c.close()


async def test_writes_rows(conn):
    await conn.execute("delete from claim_failures;")
    violations = [
        Violation("I3", "c-001", "no primary"),
        Violation("RF-4", "sentence[0]", "filler"),
    ]
    await record_verifier_failures(conn, "trace-xyz", violations)

    rows = await conn.fetch(
        "select check_name, locus, detail from claim_failures"
        " where trace_id='trace-xyz' order by check_name;"
    )
    assert len(rows) == 2
    assert rows[0]["check_name"] == "I3"
    assert rows[0]["locus"] == "c-001"
    assert rows[0]["detail"] == "no primary"
    assert rows[1]["check_name"] == "RF-4"
    assert rows[1]["locus"] == "sentence[0]"
    assert rows[1]["detail"] == "filler"


async def test_empty_writes_nothing(conn):
    await conn.execute("delete from claim_failures;")
    await record_verifier_failures(conn, "trace-xyz", [])
    count = await conn.fetchval("select count(*) from claim_failures;")
    assert count == 0
