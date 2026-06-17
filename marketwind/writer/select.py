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

from marketwind.scout.source_tier import SourceTier, classify, clears_law3, is_officially_verified
from marketwind.writer.domain import PooledSource, WriterOutput


def officially_verified_claims(output: WriterOutput, pool: list[PooledSource]) -> set[str]:
    """Return the set of claim.local_id for every claim backed by ≥1 quote whose
    owning source satisfies is_officially_verified(domain, is_primary, attached_primary_url).
    """
    # Build quote_id -> (quote, source) index from the pool
    index: dict[str, tuple] = {
        q.quote_id: (q, s)
        for s in pool
        for q in s.quotes
    }
    result: set[str] = set()
    for claim in output.claims:
        for qid in claim.quote_ids:
            if qid in index:
                quote, source = index[qid]
                if is_officially_verified(source.domain, source.is_primary, quote.attached_primary_url):
                    result.add(claim.local_id)
                    break
    return result


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
