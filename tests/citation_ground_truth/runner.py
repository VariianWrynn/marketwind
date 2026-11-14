#!/usr/bin/env python3
"""Ground-truth regression runner for MarketWind's citation contract.

Loads samples.json, runs all verifier checks (tier-1 deterministic + tier-2
with a fail-closed stub judge), and compares actual verdicts against expected.

Exit 0 = all samples match. Exit 1 = at least one mismatch.

Usage:
    python tests/citation_ground_truth/runner.py
    python tests/citation_ground_truth/runner.py --sample GT-R1  # run one
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from marketwind.verifier.checks import (
    check_derived_methodology,
    check_no_filler_attribution,
    check_no_first_person_inference,
    check_quant_has_primary,
    check_quotes_resolve,
    index_quotes,
)
from marketwind.verifier.domain import Violation
from marketwind.verifier.judge import check_no_contradiction, check_no_synthesis
from marketwind.writer.domain import (
    DraftClaim,
    DraftSentence,
    PooledQuote,
    PooledSource,
    WriterOutput,
)

_DEFAULT_SAMPLES = Path(__file__).parent / "samples.json"


def _fail_closed_judge(prompt: str) -> str:
    """Stub judge that always fails closed — returns empty violations.

    This means tier-2 checks (I1 synthesis, I10 contradiction) will produce
    no violations. Samples that depend on judge catches will pass tier-2,
    which is documented in their "note" field.
    """
    return json.dumps({"violations": []})


async def _async_judge(prompt: str) -> str:
    return _fail_closed_judge(prompt)


def _build_pool(raw_pool: list[dict]) -> list[PooledSource]:
    sources: list[PooledSource] = []
    for s in raw_pool:
        quotes = [
            PooledQuote(
                quote_id=q["quote_id"],
                text=q["text"],
                is_quantitative=q["is_quantitative"],
                quote_type=q.get("quote_type", "factual"),
                attached_primary_url=q.get("attached_primary_url"),
                span_start=0,
                span_end=len(q["text"]),
            )
            for q in s["quotes"]
        ]
        sources.append(PooledSource(
            source_id=s["source_id"],
            url=s["url"],
            domain=s["domain"],
            is_primary=s["is_primary"],
            quotes=quotes,
            raw_content=s["raw_content"],
        ))
    return sources


def _build_output(raw_claims: list[dict], raw_sentences: list[dict]) -> WriterOutput:
    claims = [
        DraftClaim(
            local_id=c["local_id"],
            statement=c["statement"],
            quote_ids=c["quote_ids"],
            category=c.get("category", "quantitative"),
            methodology=c.get("methodology"),
        )
        for c in raw_claims
    ]
    sentences = [
        DraftSentence(
            sentence=s["sentence"],
            claim_ids=s["claim_ids"],
            source_ids=s.get("source_ids", []),
            sentence_type=s.get("sentence_type", "factual"),
        )
        for s in raw_sentences
    ]
    return WriterOutput(claims=claims, sentences=sentences)


async def run_sample(sample: dict) -> tuple[bool, list[str], list[str], bool]:
    """Run one sample. Returns (passed, actual_checks, expected_checks, match)."""
    pool = _build_pool(sample["pool"])
    output = _build_output(sample["claims"], sample["sentences"])
    pool_index = index_quotes(pool)

    violations: list[Violation] = []
    violations.extend(check_quotes_resolve(output, pool_index))
    violations.extend(check_quant_has_primary(output, pool_index))
    violations.extend(check_no_filler_attribution(output, pool_index))
    violations.extend(check_no_first_person_inference(output, pool_index))
    violations.extend(check_derived_methodology(output, pool_index))
    violations.extend(await check_no_synthesis(output, judge=_async_judge))
    violations.extend(await check_no_contradiction(output, judge=_async_judge))

    actual_checks = sorted(set(v.check for v in violations))
    expected_checks = sorted(sample.get("expected_checks", []))
    actual_pass = len(violations) == 0
    expected_pass = sample["expected_pass"]

    checks_match = actual_checks == expected_checks
    pass_match = actual_pass == expected_pass
    match = checks_match and pass_match

    return match, actual_checks, expected_checks, actual_pass


async def main(
    filter_sample: str | None = None,
    samples_path: Path | None = None,
) -> int:
    path = samples_path or _DEFAULT_SAMPLES
    with open(path, encoding="utf-8") as f:
        samples = json.load(f)

    if filter_sample:
        samples = [s for s in samples if s["id"] == filter_sample]
        if not samples:
            print(f"ERROR: sample {filter_sample!r} not found", file=sys.stderr)
            return 1

    failures = 0
    for sample in samples:
        sid = sample["id"]
        match, actual, expected, actual_pass = await run_sample(sample)
        status = "PASS" if match else "FAIL"
        if not match:
            failures += 1
        print(f"  [{status}] {sid}: {sample['description']}")
        if not match:
            print(f"         expected_checks={expected} actual_checks={actual}")
            print(f"         expected_pass={sample['expected_pass']} actual_pass={actual_pass}")

    total = len(samples)
    print(f"\n{total - failures}/{total} samples passed")
    if failures:
        print(f"FAILED: {failures} sample(s) mismatched")
        return 1
    print("OK: all ground-truth samples match expected verdicts")
    return 0


if __name__ == "__main__":
    sample_arg = None
    samples_path_arg = None
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--sample" and i + 1 < len(sys.argv):
            sample_arg = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == "--samples" and i + 1 < len(sys.argv):
            samples_path_arg = Path(sys.argv[i + 1])
            i += 2
        else:
            i += 1
    sys.exit(asyncio.run(main(sample_arg, samples_path_arg)))
