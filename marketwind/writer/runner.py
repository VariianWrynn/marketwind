"""End-to-end Writer run: load pool → assemble → render → persist.

The LLM call is injected so the whole runner is testable offline with a stub;
the live entrypoint passes writer.client.call_deepseek.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from marketwind.storage.repo import load_pool, persist_report
from marketwind.writer.domain import DraftBundle
from marketwind.writer.render import render_brief
from marketwind.writer.select import eligible_pool
from marketwind.writer.writer import assemble

CallFn = Callable[[list[dict]], Awaitable[str]]


async def draft_report(conn, *, call: CallFn, max_chars: int = 500) -> DraftBundle:
    """Assemble and render without persisting. Returns a DraftBundle whose
    commit() thunk performs the single DB write — call it only after Verifier passes.
    """
    pool = await load_pool(conn)
    # I3 mitigation (2026-06-17) — REVERTIBLE. The Writer was emitting Law-3 (I3)
    # violations by drafting quant claims from quotes with no primary trace (only
    # ~10 of thousands of quant quotes are primary-backed). eligible_pool drops
    # quant-without-primary quotes so I3 is structurally satisfied. To revert:
    # delete the next line and the `from ...select import eligible_pool` import;
    # the original behavior was just the unfiltered `pool = await load_pool(conn)`.
    pool = eligible_pool(pool)
    output = await assemble(pool, call=call)
    brief = render_brief(output, max_chars=max_chars)

    async def _commit() -> str:
        return await persist_report(conn, output.claims, brief.sentences)

    return DraftBundle(output=output, pool=pool, body=brief.body, commit=_commit)


async def run_writer(conn, *, call: CallFn, max_chars: int = 500) -> tuple[str, str]:
    """Returns (report_id, rendered brief body).

    WARNING — Law 5: this persists unconditionally (commit with no Verifier pass).
    It is a writer-only convenience for tests/diagnostics and must NOT be wired
    into the publication path. The live path is run_once -> run_pipeline, which
    drafts lazily and commits only after verify() passes.
    """
    bundle = await draft_report(conn, call=call, max_chars=max_chars)
    report_id = await bundle.commit()
    return report_id, bundle.body
