"""Persistence for the Scout quote pool. Upsert-by-canonical-url (spec §5)."""

from __future__ import annotations

import asyncpg
import uuid

from marketwind.scout.domain import Source
from marketwind.verifier.domain import Violation
from marketwind.writer.domain import PooledQuote, PooledSource


async def upsert_source(conn: asyncpg.Connection, source: Source) -> str:
    """Insert or replace a Source by URL and (re)write its quotes. Returns source_id."""
    async with conn.transaction():
        source_id = await conn.fetchval(
            """
            insert into sources (url, domain, byline, publish_ts, is_primary, raw_content)
            values ($1, $2, $3, $4, $5, $6)
            on conflict (url) do update set
                domain = excluded.domain,
                byline = excluded.byline,
                publish_ts = excluded.publish_ts,
                is_primary = excluded.is_primary,
                raw_content = excluded.raw_content,
                ingested_at = now()
            returning source_id;
            """,
            source.url, source.domain, source.byline,
            source.publish_ts, source.is_primary, source.raw_content,
        )
        # Replace quotes wholesale (the source's raw_content may have changed).
        await conn.execute("delete from quotes where source_id = $1;", source_id)
        for q in source.quotes:
            await conn.execute(
                """
                insert into quotes (
                    source_id, text, span_start, span_end,
                    context_before, context_after, quote_type,
                    is_quantitative, attached_primary_url
                ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9);
                """,
                source_id, q.text, q.span_start, q.span_end,
                q.context_before, q.context_after, q.quote_type,
                q.is_quantitative, q.attached_primary_url,
            )
        return str(source_id)


async def load_pool(conn: asyncpg.Connection) -> list[PooledSource]:
    """Load the persisted quote pool with real DB UUIDs (Writer input)."""
    src_rows = await conn.fetch(
        "select source_id, url, domain, is_primary, raw_content from sources order by ingested_at;"
    )
    pool: list[PooledSource] = []
    for s in src_rows:
        q_rows = await conn.fetch(
            """
            select quote_id, text, is_quantitative, quote_type, attached_primary_url,
                   span_start, span_end
            from quotes where source_id = $1 order by span_start;
            """,
            s["source_id"],
        )
        quotes = [
            PooledQuote(
                quote_id=str(q["quote_id"]),
                text=q["text"],
                is_quantitative=q["is_quantitative"],
                quote_type=q["quote_type"],
                attached_primary_url=q["attached_primary_url"],
                span_start=q["span_start"],
                span_end=q["span_end"],
            )
            for q in q_rows
        ]
        pool.append(
            PooledSource(
                source_id=str(s["source_id"]),
                url=s["url"],
                domain=s["domain"],
                is_primary=s["is_primary"],
                quotes=quotes,
                raw_content=s["raw_content"],
            )
        )
    return pool


async def persist_report(conn, claims, rendered_sentences) -> str:
    """Insert claims (referenced by kept sentences) + sentences. Returns report_id."""
    report_id = uuid.uuid4()
    referenced = {cid for s in rendered_sentences for cid in s.claim_ids}
    async with conn.transaction():
        local_to_uuid: dict[str, object] = {}
        for c in claims:
            if c.local_id not in referenced:
                continue  # drop claims whose sentence was tail-dropped (no orphans)
            cid = await conn.fetchval(
                """
                insert into claims (statement, quote_ids)
                values ($1, $2::uuid[]) returning claim_id;
                """,
                c.statement, c.quote_ids,
            )
            local_to_uuid[c.local_id] = cid
        for s in rendered_sentences:
            await conn.execute(
                """
                insert into sentences
                    (report_id, claim_ids, source_ids, rendered_text, sentence_type, position)
                values ($1, $2::uuid[], $3::uuid[], $4, $5, $6);
                """,
                report_id,
                [local_to_uuid[c] for c in s.claim_ids],
                s.source_ids,
                s.text,
                s.sentence_type,
                s.position,
            )
    return str(report_id)


async def record_verifier_failures(
    conn, trace_id: str, violations: list[Violation]
) -> None:
    """Insert one claim_failures row per Violation. No-op if violations is empty."""
    if not violations:
        return
    await conn.executemany(
        "insert into claim_failures (trace_id, check_name, locus, detail)"
        " values ($1, $2, $3, $4);",
        [(trace_id, v.check, v.locus, v.detail) for v in violations],
    )
