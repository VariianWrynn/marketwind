"""Writer-side persistence tests (real Postgres via DATABASE_URL)."""

from datetime import date, datetime

import asyncpg
import pytest

from marketwind.config import settings
from marketwind.scout.domain import Quote, Source
from marketwind.scout.timeparse import CN_TZ
from marketwind.storage.migrate import apply_migrations
from marketwind.storage.repo import load_pool, upsert_source
from marketwind.writer.domain import DraftClaim
from marketwind.writer.render import render_brief
from marketwind.writer.runner import run_writer
from marketwind.writer.writer import assemble
from marketwind.storage.repo import persist_report


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
    # raw_content is carried into the pool (verifier re-resolution prerequisite)
    assert src.raw_content == "句子一。句子二涨0.36%。"
    # re-resolution invariant: every quote's span slices back to its text
    for q in src.quotes:
        assert src.raw_content[q.span_start:q.span_end] == q.text


async def test_persist_report_writes_claims_and_sentences(conn):
    await conn.execute("delete from sources;")
    await conn.execute("delete from claims;")
    await conn.execute("delete from sentences;")
    sid = await upsert_source(conn, _sample_source())
    pool = await load_pool(conn)
    qid = pool[0].quotes[0].quote_id

    from marketwind.writer.domain import DraftSentence, WriterOutput
    out = WriterOutput(
        claims=[DraftClaim("c-001", "句子一陈述", [qid])],
        sentences=[DraftSentence("句子一。", ["c-001"], [sid], "factual")],
    )
    brief = render_brief(out)
    report_id = await persist_report(conn, out.claims, brief.sentences)

    n_claims = await conn.fetchval("select count(*) from claims;")
    n_sent = await conn.fetchval(
        "select count(*) from sentences where report_id = $1;", report_id
    )
    assert n_claims == 1 and n_sent == 1
    row = await conn.fetchrow(
        "select claim_ids, source_ids, rendered_text from sentences where report_id=$1;",
        report_id,
    )
    assert len(row["claim_ids"]) == 1          # mapped to a real uuid
    assert str(row["source_ids"][0]) == sid
    assert row["rendered_text"].endswith("[1]")  # renderer marker persisted


async def test_run_writer_end_to_end_with_stub(conn, fixtures_dir_writer):
    import json
    await conn.execute("delete from sources;")
    await conn.execute("delete from claims;")
    await conn.execute("delete from sentences;")
    await upsert_source(conn, _sample_source())
    pool = await load_pool(conn)
    # The sample source has 2 quotes; aliases are q1, q2 for source s1.
    # Stub returns alias ids — assemble maps them back to real uuids.
    sid = pool[0].source_id  # real uuid (for asserting DB write)
    content = json.dumps({
        "claims": [{"id": "c-001", "statement": "句子一陈述", "quote_ids": ["q1"]}],
        "sentences": [{"sentence": "句子一。", "claim_ids": ["c-001"],
                       "source_ids": ["s1"], "sentence_type": "factual"}],
    })

    async def stub_call(messages):
        return content

    report_id, body = await run_writer(conn, call=stub_call, session_date=date(2026, 7, 23))
    assert body.endswith("[1]")
    n_sent = await conn.fetchval(
        "select count(*) from sentences where report_id=$1;", report_id
    )
    assert n_sent == 1
    # persisted sentence carries real source uuid (mapped back by assemble)
    row = await conn.fetchrow(
        "select source_ids from sentences where report_id=$1;", report_id
    )
    assert str(row["source_ids"][0]) == sid
