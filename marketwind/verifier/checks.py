"""Tier-1 deterministic checks for the Law-5 publication gate. No LLM, no I/O."""

from __future__ import annotations

import re

from marketwind.scout.source_tier import clears_law3
from marketwind.verifier.domain import Violation
from marketwind.writer.domain import PooledQuote, PooledSource, WriterOutput

# ---------------------------------------------------------------------------
# Spec-critical literals — verbatim from spec, do not edit tokens
# ---------------------------------------------------------------------------

_FILLER = re.compile(r"据报道|业内人士|市场认为|普遍预期|通常来说|分析人士|知情人士|接近.{0,8}的人士|有消息称")
_FIRST_PERSON = re.compile(r"系统认为|分析显示|综合判断|经测算|研究表明")


# ---------------------------------------------------------------------------
# Index helper
# ---------------------------------------------------------------------------

def index_quotes(
    pool: list[PooledSource],
) -> dict[str, tuple[PooledQuote, PooledSource]]:
    """Map each quote_id to (quote, owning_source)."""
    idx: dict[str, tuple[PooledQuote, PooledSource]] = {}
    for source in pool:
        for quote in source.quotes:
            idx[quote.quote_id] = (quote, source)
    return idx


# ---------------------------------------------------------------------------
# Check 1 — RF-3/RF-9: independent quote re-resolution
# ---------------------------------------------------------------------------

def check_quotes_resolve(
    output: WriterOutput,
    pool_index: dict[str, tuple[PooledQuote, PooledSource]],
) -> list[Violation]:
    violations: list[Violation] = []
    for claim in output.claims:
        for qid in claim.quote_ids:
            if qid not in pool_index:
                violations.append(Violation(
                    check="RF-3",
                    locus=claim.local_id,
                    detail=f"quote_id {qid!r} not found in pool",
                ))
            else:
                quote, source = pool_index[qid]
                extracted = source.raw_content[quote.span_start:quote.span_end]
                if extracted != quote.text:
                    violations.append(Violation(
                        check="RF-3",
                        locus=claim.local_id,
                        detail=(
                            f"quote_id {qid!r} span mismatch: "
                            f"raw_content[{quote.span_start}:{quote.span_end}]="
                            f"{extracted!r} != text={quote.text!r}"
                        ),
                    ))
    return violations


# ---------------------------------------------------------------------------
# Check 2 — I3/RF-6: quantitative claims must have a primary source
# ---------------------------------------------------------------------------

def check_quant_has_primary(
    output: WriterOutput,
    pool_index: dict[str, tuple[PooledQuote, PooledSource]],
) -> list[Violation]:
    violations: list[Violation] = []
    for claim in output.claims:
        has_quant = False
        has_primary = False
        for qid in claim.quote_ids:
            if qid not in pool_index:
                continue
            quote, source = pool_index[qid]
            if quote.is_quantitative:
                has_quant = True
            if clears_law3(source.domain, source.is_primary, quote.attached_primary_url):
                has_primary = True
        if has_quant and not has_primary:
            violations.append(Violation(
                check="I3",
                locus=claim.local_id,
                detail=(
                    f"claim {claim.local_id!r} has quantitative quote(s) "
                    "but no primary source or attached_primary_url"
                ),
            ))
    return violations


# ---------------------------------------------------------------------------
# Check 3 — RF-4: no filler attribution phrases
# ---------------------------------------------------------------------------

def check_no_filler_attribution(
    output: WriterOutput,
    pool_index: dict[str, tuple[PooledQuote, PooledSource]],
) -> list[Violation]:
    violations: list[Violation] = []
    for i, sent in enumerate(output.sentences):
        m = _FILLER.search(sent.sentence)
        if m:
            violations.append(Violation(
                check="RF-4",
                locus=f"sentence[{i}]",
                detail=f"filler token {m.group()!r} in sentence",
            ))
    for claim in output.claims:
        m = _FILLER.search(claim.statement)
        if m:
            violations.append(Violation(
                check="RF-4",
                locus=claim.local_id,
                detail=f"filler token {m.group()!r} in claim statement",
            ))
    return violations


# ---------------------------------------------------------------------------
# Check 4 — RF-10/Law-4: no first-person inference phrases
# ---------------------------------------------------------------------------

def check_no_first_person_inference(
    output: WriterOutput,
    pool_index: dict[str, tuple[PooledQuote, PooledSource]],
) -> list[Violation]:
    violations: list[Violation] = []
    for i, sent in enumerate(output.sentences):
        m = _FIRST_PERSON.search(sent.sentence)
        if m:
            violations.append(Violation(
                check="RF-10",
                locus=f"sentence[{i}]",
                detail=f"first-person inference token {m.group()!r} in sentence",
            ))
    for claim in output.claims:
        m = _FIRST_PERSON.search(claim.statement)
        if m:
            violations.append(Violation(
                check="RF-10",
                locus=claim.local_id,
                detail=f"first-person inference token {m.group()!r} in claim statement",
            ))
    return violations


# ---------------------------------------------------------------------------
# Check 5 — I12: derived_metric claims must carry a methodology label
# ---------------------------------------------------------------------------

def check_derived_methodology(
    output: WriterOutput,
    pool_index: dict[str, tuple[PooledQuote, PooledSource]],
) -> list[Violation]:
    violations: list[Violation] = []
    for claim in output.claims:
        if claim.category == "derived_metric":
            if claim.methodology is None or claim.methodology.strip() == "":
                violations.append(Violation(
                    check="I12",
                    locus=claim.local_id,
                    detail=(
                        f"claim {claim.local_id!r} is category 'derived_metric' "
                        "but has no methodology label"
                    ),
                ))
    return violations
