"""Live-Postgres test for record_rejected_draft (rejected_drafts table)."""
import json

import asyncpg
import pytest

from marketwind.config import settings
from marketwind.storage.migrate import apply_migrations
from marketwind.storage.repo import record_rejected_draft
from marketwind.writer.domain import DraftClaim, DraftSentence, WriterOutput


@pytest.fixture
async def conn():
    c = await asyncpg.connect(settings.database_url)
    await apply_migrations(c)
    try:
        yield c
    finally:
        await c.close()


async def test_persists_rejected_draft(conn):
    await conn.execute("delete from rejected_drafts where trace_id='trace-rej';")
    output = WriterOutput(
        claims=[DraftClaim(local_id="c-002", statement="南芯科技6月16日收盘涨停。", quote_ids=["q1"])],
        sentences=[DraftSentence(sentence="南芯科技6月16日收盘涨停。", claim_ids=["c-002"],
                                 source_ids=["s1"], sentence_type="factual")],
    )
    await record_rejected_draft(conn, "trace-rej", output)
    row = await conn.fetchrow(
        "select draft_json from rejected_drafts where trace_id='trace-rej';"
    )
    assert row is not None
    raw = row["draft_json"]
    payload = raw if isinstance(raw, dict) else json.loads(raw)
    assert payload["claims"][0]["local_id"] == "c-002"
    assert payload["claims"][0]["statement"] == "南芯科技6月16日收盘涨停。"
    assert payload["sentences"][0]["sentence_type"] == "factual"
