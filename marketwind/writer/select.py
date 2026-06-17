"""Writer-input pool filter: enforce Law 3 structurally before drafting.

I3 mitigation (2026-06-17): the Writer was drafting quantitative claims from
quotes with no primary trace, because only a tiny fraction of quant quotes are
primary-backed. Dropping quant-without-primary quotes from the pool makes the
I3 check (no quantitative claim without a primary source) impossible to violate.
Revertible: stop calling eligible_pool in marketwind/writer/runner.py.

Tier-aware (2026-06-17): sources classified EXCLUDED are dropped in full before
any quote-level filtering; TRUSTED-or-above domain quant quotes pass Law 3 even
without an attached_primary_url (per clears_law3 semantics).
"""
from __future__ import annotations

from dataclasses import replace

from marketwind.scout.source_tier import SourceTier, classify, clears_law3
from marketwind.writer.domain import PooledSource


def eligible_pool(pool: list[PooledSource]) -> list[PooledSource]:
    """Drop EXCLUDED-tier sources entirely, then drop quantitative quotes that
    do not clear Law 3 (no attached primary, source not is_primary, and domain
    below TRUSTED). Keep non-quant quotes unconditionally for surviving sources.
    Drop any source left with zero quotes."""
    out: list[PooledSource] = []
    for s in pool:
        if classify(s.domain) == SourceTier.EXCLUDED:
            continue
        kept = [
            q for q in s.quotes
            if (not q.is_quantitative) or clears_law3(s.domain, s.is_primary, q.attached_primary_url)
        ]
        if kept:
            out.append(replace(s, quotes=kept))
    return out
