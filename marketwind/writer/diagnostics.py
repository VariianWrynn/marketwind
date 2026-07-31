"""Pool-funnel diagnostics for the Writer.

Pure — no I/O, no DB, no LLM.  Measures three cross-sections of the source
pool (raw / eligible / cited) so the collapse seen in issue #14 is visible on
every run instead of inferred after the fact.
"""
from __future__ import annotations

from dataclasses import dataclass

from marketwind.writer.domain import PooledSource, WriterOutput


@dataclass(frozen=True)
class PoolFunnel:
    raw_sources: int
    raw_quotes: int
    raw_domains: int
    eligible_sources: int
    eligible_quotes: int
    eligible_domains: int
    quant_domains: int
    cited_sources: int
    cited_domains: int


def measure_funnel(
    raw: list[PooledSource],
    eligible: list[PooledSource],
    output: WriterOutput,
) -> PoolFunnel:
    """Measure how many sources/quotes/domains survive each filtering stage.

    raw_domains matches evaluate_floor's outlet rule: only sources with at least
    one quote are counted, so the number is directly comparable to the floor's
    reported outlets value.
    """
    # --- raw cross-section ---
    raw_sources = len(raw)
    raw_quotes = sum(len(s.quotes) for s in raw)
    raw_domains = len({s.domain for s in raw if s.quotes})

    # --- eligible cross-section ---
    eligible_sources = len(eligible)
    eligible_quotes = sum(len(s.quotes) for s in eligible)
    eligible_domains = len({s.domain for s in eligible})
    quant_domains = len(
        {s.domain for s in eligible if any(q.is_quantitative for q in s.quotes)}
    )

    # --- cited cross-section ---
    # domain lookup over the raw pool (superset of eligible); unknown ids are ignored
    raw_domain_by_id: dict[str, str] = {s.source_id: s.domain for s in raw}

    cited_source_ids: set[str] = set()
    cited_domain_set: set[str] = set()
    for sent in output.sentences:
        if sent.sentence_type != "factual":
            continue
        for sid in sent.source_ids:
            cited_source_ids.add(sid)
            domain = raw_domain_by_id.get(sid)
            if domain is not None:
                cited_domain_set.add(domain)

    return PoolFunnel(
        raw_sources=raw_sources,
        raw_quotes=raw_quotes,
        raw_domains=raw_domains,
        eligible_sources=eligible_sources,
        eligible_quotes=eligible_quotes,
        eligible_domains=eligible_domains,
        quant_domains=quant_domains,
        cited_sources=len(cited_source_ids),
        cited_domains=len(cited_domain_set),
    )


def format_funnel(funnel: PoolFunnel) -> str:
    """Return a single greppable log line summarising the funnel."""
    return (
        f"pool funnel: raw {funnel.raw_sources} sources/{funnel.raw_quotes} quotes"
        f"/{funnel.raw_domains} domains"
        f" | eligible {funnel.eligible_sources}/{funnel.eligible_quotes}"
        f"/{funnel.eligible_domains} (quant domains {funnel.quant_domains})"
        f" | cited {funnel.cited_sources} sources/{funnel.cited_domains} domains"
    )
