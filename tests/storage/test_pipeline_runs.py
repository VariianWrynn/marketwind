"""Tests for pipeline_runs storage (G2.1) and time_window field."""

from __future__ import annotations

from datetime import date

import asyncpg
import pytest

from marketwind.storage.repo import (
    load_recent_claims,
    persist_pipeline_run,
    persist_report,
)
from marketwind.writer.domain import DraftClaim, DraftSentence, RenderedSentence


@pytest.fixture
async def conn():
    c = await asyncpg.connect("postgresql://marketwind:marketwind@localhost:5432/marketwind")
    yield c
    await c.execute("delete from pipeline_runs;")
    await c.execute("delete from sentences;")
    await c.execute("delete from claims;")
    await c.close()


def _claim(local_id, statement="test", quote_ids=None, category="quantitative",
           methodology=None, time_window=None):
    return DraftClaim(
        local_id=local_id, statement=statement,
        quote_ids=quote_ids or [],
        category=category, methodology=methodology,
        time_window=time_window,
    )


def _rendered(text="test.", claim_ids=None, source_ids=None, position=0):
    return RenderedSentence(
        text=text, claim_ids=claim_ids or [], source_ids=source_ids or [],
        sentence_type="factual", position=position,
    )


async def test_persist_report_stores_time_window(conn):
    claims = [_claim("c-001", "test claim", time_window="2026-Q1")]
    sentences = [_rendered(claim_ids=["c-001"])]
    report_id = await persist_report(conn, claims, sentences)
    row = await conn.fetchrow(
        "select time_window from claims where statement = 'test claim';"
    )
    assert row is not None
    assert row["time_window"] == "2026-Q1"


async def test_persist_report_time_window_null_by_default(conn):
    claims = [_claim("c-001", "no time window claim")]
    sentences = [_rendered(claim_ids=["c-001"])]
    await persist_report(conn, claims, sentences)
    row = await conn.fetchrow(
        "select time_window from claims where statement = 'no time window claim';"
    )
    assert row is not None
    assert row["time_window"] is None


async def test_persist_pipeline_run_and_load_recent(conn):
    claims = [
        _claim("c-001", "day1 claim", time_window="2026-05-26"),
        _claim("c-002", "day1 other", time_window="2026-05-26"),
    ]
    sentences = [_rendered(claim_ids=["c-001", "c-002"])]
    report_id = await persist_report(conn, claims, sentences)

    claim_uuids = await conn.fetch(
        "select claim_id from claims where statement in ('day1 claim', 'day1 other');"
    )
    cids = [str(r["claim_id"]) for r in claim_uuids]

    await persist_pipeline_run(
        conn, report_id=report_id, trading_date=date(2026, 5, 26),
        job_id="main", claim_ids=cids,
    )

    recent = await load_recent_claims(conn, trading_date=date(2026, 5, 27), days_back=5)
    assert len(recent) == 2
    statements = {r["statement"] for r in recent}
    assert "day1 claim" in statements
    assert "day1 other" in statements


async def test_load_recent_claims_excludes_current_day(conn):
    claims = [_claim("c-001", "today claim")]
    sentences = [_rendered(claim_ids=["c-001"])]
    report_id = await persist_report(conn, claims, sentences)

    cid = await conn.fetchval(
        "select claim_id from claims where statement = 'today claim';"
    )
    await persist_pipeline_run(
        conn, report_id=report_id, trading_date=date(2026, 5, 27),
        job_id="main", claim_ids=[str(cid)],
    )

    recent = await load_recent_claims(conn, trading_date=date(2026, 5, 27), days_back=5)
    assert len(recent) == 0
