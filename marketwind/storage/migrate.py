"""Tiny idempotent SQL migration runner (asyncpg, no ORM).

Applies every ``migrations/*.sql`` not yet recorded in ``schema_migrations``,
in filename order, recording each version. Re-running is a no-op.
"""

import asyncio
from pathlib import Path

import asyncpg

from marketwind.config import settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def pending_migration_paths() -> list[Path]:
    """Every migration on disk, in filename order. Raises if there are none.

    An empty result means the directory moved, not that the schema is current, so
    returning it would let a caller exit 0 against an unmigrated database.
    """
    paths = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not paths:
        raise RuntimeError(
            f"no *.sql migrations under {MIGRATIONS_DIR} — refusing to report "
            "success against an unmigrated database"
        )
    return paths

# The bootstrap migration creates schema_migrations itself, so we ensure the
# table exists before consulting it.
_ENSURE_TABLE = """
create table if not exists schema_migrations (
    version text primary key,
    applied_at timestamptz not null default now()
);
"""


async def apply_migrations(conn: asyncpg.Connection) -> list[str]:
    """Apply pending migrations on an open connection. Returns versions applied."""
    await conn.execute(_ENSURE_TABLE)
    applied_rows = await conn.fetch("select version from schema_migrations;")
    already = {row["version"] for row in applied_rows}

    newly_applied: list[str] = []
    for path in pending_migration_paths():
        version = path.stem
        if version in already:
            continue
        sql = path.read_text(encoding="utf-8")
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute(
                "insert into schema_migrations (version) values ($1);", version
            )
        newly_applied.append(version)
    return newly_applied


async def run() -> None:
    """Connect using configured DATABASE_URL and apply pending migrations."""
    conn = await asyncpg.connect(settings.database_url)
    try:
        applied = await apply_migrations(conn)
    finally:
        await conn.close()
    if applied:
        print("applied migrations:", ", ".join(applied))
    else:
        print("no pending migrations")


if __name__ == "__main__":
    asyncio.run(run())
