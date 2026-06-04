"""Writer assembly: pool → prompt → LLM call → I8-validated WriterOutput.

The LLM call is injected (`call`) so this is testable offline with a stub; the
live wiring passes writer.client.call_deepseek.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from marketwind.writer.domain import PooledSource, WriterOutput
from marketwind.writer.prompt import build_writer_prompt
from marketwind.writer.schema import parse_and_validate

CallFn = Callable[[list[dict]], Awaitable[str]]


async def assemble(pool: list[PooledSource], *, call: CallFn) -> WriterOutput:
    messages = build_writer_prompt(pool)
    raw = await call(messages)
    valid_quote_ids = {q.quote_id for s in pool for q in s.quotes}
    valid_source_ids = {s.source_id for s in pool}
    return parse_and_validate(raw, valid_quote_ids, valid_source_ids)
