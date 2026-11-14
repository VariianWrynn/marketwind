"""Law-5 publication gate: aggregates Tier-1 + Tier-2 checks into VerifyResult."""

from __future__ import annotations

from marketwind.verifier.checks import (
    check_corroboration,
    check_derived_methodology,
    check_no_filler_attribution,
    check_no_first_person_inference,
    check_quant_has_primary,
    check_quotes_resolve,
    index_quotes,
)
from marketwind.verifier.domain import Violation, VerifyResult
from marketwind.verifier.judge import (
    FreshnessSearchFn,
    JudgeFn,
    RecentClaimsFn,
    check_cross_report_consistency,
    check_freshness,
    check_no_contradiction,
    check_no_synthesis,
)
from marketwind.writer.domain import PooledSource, WriterOutput


async def verify(
    output: WriterOutput,
    pool: list[PooledSource],
    *,
    judge: JudgeFn,
    recent_claims: RecentClaimsFn | None = None,
    freshness_search: FreshnessSearchFn | None = None,
) -> VerifyResult:
    """Run all checks and return a single VerifyResult.

    Tier-1 checks are pure/synchronous; Tier-2 checks are async and fail closed.
    Order: quotes_resolve, quant_has_primary, no_filler_attribution,
           no_first_person_inference, derived_methodology, corroboration,
           no_synthesis, no_contradiction, cross_report_consistency, freshness.

    recent_claims and freshness_search are optional seams for I11/I6.
    When not provided, those checks are skipped (no violations).
    """
    pool_index = index_quotes(pool)

    violations: list[Violation] = []
    violations.extend(check_quotes_resolve(output, pool_index))
    violations.extend(check_quant_has_primary(output, pool_index))
    violations.extend(check_no_filler_attribution(output, pool_index))
    violations.extend(check_no_first_person_inference(output, pool_index))
    violations.extend(check_derived_methodology(output, pool_index))
    violations.extend(check_corroboration(output, pool_index))
    violations.extend(await check_no_synthesis(output, judge=judge))
    violations.extend(await check_no_contradiction(output, judge=judge))
    if recent_claims is not None:
        violations.extend(
            await check_cross_report_consistency(output, recent_claims=recent_claims, judge=judge)
        )
    if freshness_search is not None:
        violations.extend(await check_freshness(output, search=freshness_search))

    return VerifyResult(passed=(violations == []), violations=violations)
