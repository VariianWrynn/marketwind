"""Writer-input pool filter: enforce Law 3 structurally before drafting.

I3 mitigation (2026-06-17): the Writer was drafting quantitative claims from
quotes with no primary trace, because only a tiny fraction of quant quotes are
primary-backed. Dropping quant-without-primary quotes from the pool makes the
I3 check (no quantitative claim without a primary source) impossible to violate.
Revertible: stop calling eligible_pool in marketwind/writer/runner.py.
"""
from __future__ import annotations

from dataclasses import replace

from marketwind.writer.domain import PooledSource


def eligible_pool(pool: list[PooledSource]) -> list[PooledSource]:
    """Drop quantitative quotes lacking a primary trace (Law 3: they can never
    lawfully back a quant claim). Keep non-quant quotes and primary-backed quant
    quotes (attached_primary_url set, or the source itself is_primary). Drop any
    source left with zero quotes."""
    out: list[PooledSource] = []
    for s in pool:
        kept = [
            q for q in s.quotes
            if (not q.is_quantitative) or q.attached_primary_url or s.is_primary
        ]
        if kept:
            out.append(replace(s, quotes=kept))
    return out
