"""End-to-end Writer run: load pool → assemble → render → persist.

The LLM call is injected so the whole runner is testable offline with a stub;
the live entrypoint passes writer.client.call_deepseek.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from marketwind.storage.repo import load_pool, persist_report
from marketwind.writer.render import render_brief
from marketwind.writer.writer import assemble

CallFn = Callable[[list[dict]], Awaitable[str]]


async def run_writer(conn, *, call: CallFn, max_chars: int = 500) -> tuple[str, str]:
    """Returns (report_id, rendered brief body)."""
    pool = await load_pool(conn)
    output = await assemble(pool, call=call)
    brief = render_brief(output, max_chars=max_chars)
    report_id = await persist_report(conn, output.claims, brief.sentences)
    return report_id, brief.body
