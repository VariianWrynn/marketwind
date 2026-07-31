"""End-to-end Writer run: load pool → assemble → render → persist.

The LLM call is injected so the whole runner is testable offline with a stub;
the live entrypoint passes writer.client.call_deepseek.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date

from marketwind.storage.repo import load_pool, persist_report
from marketwind.writer.diagnostics import format_funnel, measure_funnel
from marketwind.writer.domain import DraftBundle
from marketwind.writer.render import render_brief, render_source_tail
from marketwind.writer.select import eligible_pool, officially_verified_claims
from marketwind.writer.writer import assemble

logger = logging.getLogger(__name__)

CallFn = Callable[[list[dict]], Awaitable[str]]


async def draft_report(conn, *, call: CallFn, session_date: date, max_chars: int = 500) -> DraftBundle:
    """Assemble and render without persisting. Returns a DraftBundle whose
    commit() thunk performs the single DB write — call it only after Verifier passes.
    """
    raw_pool = await load_pool(conn)
    # I3 mitigation (2026-06-17) — REVERTIBLE. The Writer was emitting Law-3 (I3)
    # violations by drafting quant claims from quotes with no primary trace (only
    # ~10 of thousands of quant quotes are primary-backed). eligible_pool drops
    # quant-without-primary quotes so I3 is structurally satisfied. To revert:
    # delete the next two lines and the `from ...select import eligible_pool` import;
    # the original behavior was just the unfiltered `pool = await load_pool(conn)`.
    pool = eligible_pool(raw_pool)
    output = await assemble(pool, call=call, session_date=session_date)
    official_ids = officially_verified_claims(output, pool)
    brief = render_brief(output, max_chars=max_chars, official_ids=official_ids)
    logger.info(format_funnel(measure_funnel(raw_pool, pool, output)))

    async def _commit() -> str:
        return await persist_report(conn, output.claims, brief.sentences)

    url_by_id = {s.source_id: s.url for s in pool}
    reference = render_source_tail(brief.footnotes, url_by_id)

    return DraftBundle(output=output, pool=pool, body=brief.body, reference=reference, commit=_commit)


async def run_writer(conn, *, call: CallFn, session_date: date, max_chars: int = 500) -> tuple[str, str]:
    """Returns (report_id, rendered brief body).

    WARNING — Law 5: this persists unconditionally (commit with no Verifier pass).
    It is a writer-only convenience for tests/diagnostics and must NOT be wired
    into the publication path. The live path is run_once -> run_pipeline, which
    drafts lazily and commits only after verify() passes.
    """
    bundle = await draft_report(conn, call=call, session_date=session_date, max_chars=max_chars)
    report_id = await bundle.commit()
    return report_id, bundle.body
