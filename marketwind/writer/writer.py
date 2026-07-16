"""Writer assembly: pool → prompt → LLM call → I8-validated WriterOutput.

The LLM call is injected (`call`) so this is testable offline with a stub; the
live wiring passes writer.client.call_deepseek.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from marketwind.writer.domain import DraftClaim, DraftSentence, PooledSource, WriterOutput
from marketwind.writer.prompt import alias_pool, build_writer_prompt
from marketwind.writer.schema import parse_and_validate

CallFn = Callable[[list[dict]], Awaitable[str]]


async def assemble(pool: list[PooledSource], *, call: CallFn) -> WriterOutput:
    messages = build_writer_prompt(pool)
    raw = await call(messages)

    # Validate against alias id-sets (what the model sees and cites)
    rows, q_map, s_map = alias_pool(pool)
    validated = parse_and_validate(raw, set(q_map), set(s_map))

    # Map alias ids back to real DB UUIDs so downstream (render, persist) is unchanged
    remapped_claims = [
        DraftClaim(
            local_id=c.local_id,
            statement=c.statement,
            quote_ids=[q_map[a] for a in c.quote_ids],
            category=c.category,
            methodology=c.methodology,
        )
        for c in validated.claims
    ]
    remapped_sentences = [
        DraftSentence(
            sentence=s.sentence,
            claim_ids=s.claim_ids,
            source_ids=[s_map[a] for a in s.source_ids],
            sentence_type=s.sentence_type,
        )
        for s in validated.sentences
    ]
    return WriterOutput(claims=remapped_claims, sentences=remapped_sentences)
