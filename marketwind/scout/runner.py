"""Scout runner: assemble the pool (live) and evaluate the grounded floor (pure).

Grounded floor (spec §8, provisional 8/1/2 — revisit after first smoke run):
publish only if ALL hold, else the caller emits an honest-shortfall status.
"""

from __future__ import annotations

from marketwind.scout.domain import FloorResult, Source

MIN_GROUNDED_QUOTES = 8
MIN_PRIMARY_QUOTES = 1
MIN_INDEPENDENT_OUTLETS = 2


def evaluate_floor(sources: list[Source]) -> FloorResult:
    grounded = sum(len(s.quotes) for s in sources)
    primary = sum(
        1 for s in sources for q in s.quotes if q.attached_primary_url
    )
    outlets = len({s.domain for s in sources})
    passed = (
        grounded >= MIN_GROUNDED_QUOTES
        and primary >= MIN_PRIMARY_QUOTES
        and outlets >= MIN_INDEPENDENT_OUTLETS
    )
    return FloorResult(
        grounded_quotes=grounded,
        primary_traced_quotes=primary,
        independent_outlets=outlets,
        passed=passed,
    )
