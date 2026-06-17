# ADR-0003 — CSRC-designated & curated-trusted outlets are "primary-grade" for the I3 gate

**Status:** accepted
**Grantor:** project owner
**Date:** 2026-06-17
**Scope:** permanent
**Expiry condition:** revisit if a designated/trusted outlet is caught mis-transcribing a number that reaches a published report, or once Phase B (cninfo-direct via akshare) restores a real supply of Tier-0 primaries — at which point the gate threshold could be tightened back toward DESIGNATED/OFFICIAL via a new ADR.

## Triggering situation

Iron Law 3 (no quantitative claim without a primary source) stayed strict, but the
**live supply of Tier-0 primaries is near zero**. The real-Bocha spike (2026-06-17)
established that Bocha **ignores the `site:` operator**, **cannot reach `cninfo.com.cn`
at all**, and official venue / regulator domains barely surface; trusted financial
outlets (Sina 财经, 第一财经, 财联社, 中证网, 上证, 证券时报) **dominate** results.
With I3 requiring a literal attached primary (or `is_primary`), virtually every
quantitative claim drafted from the live pool failed I3 — the gate was starved, not
because the numbers were wrong, but because the only domains that carry them are
disclosure media, not the disclosing entity's own host. "Go straight for official
disclosure via Bocha" is dead; cninfo-direct must wait for akshare (Phase B).

## Decision

Recognise a tier *between* "the company itself" and "random aggregator": CSRC-designated
disclosure media. Ground the model in statute (CSRC Information-Disclosure Provisions +
Securities Law Art. 86), not taste. Five tiers: OFFICIAL(4) / DESIGNATED(3) / TRUSTED(2)
/ SECONDARY(1) / EXCLUDED(0). Two predicates fall out:

- **primary-grade** (clears the I3 *gate*): `attached_primary_url is not None OR
  is_primary OR tier ≥ TRUSTED`. A Sina/中证网 number may now lawfully back a claim.
- **officially-verified** (earns the reader *badge* `✓官方核实`): `… OR tier ≥
  DESIGNATED`. TRUSTED clears the gate but **NOT** the badge.

The Tier-0 "Primary source" glossary definition does **not** move — the company itself,
its filings, the regulators. The badge is the honest reader signal separating
"may back a number" (primary-grade) from "officially corroborated" (officially-verified).
Default-deny: an unknown domain is EXCLUDED and can never back a number; recall widens
only by a reviewed list edit, never by accident. The badge is mechanical / non-LLM, so
it does not engage Law 4.

## Residual risk (accepted)

A designated or trusted outlet may occasionally **mis-transcribe a number** — a
calculated risk the owner takes **knowingly**. The mitigation is the tier gap itself:
a TRUSTED-only number clears the gate but is *not* badged as officially verified, so the
reader sees exactly how strong the corroboration is. If a mis-transcription is ever
caught reaching a published report, the expiry condition above triggers a tightening ADR.

## Ground-truth regression gap (surfaced, not hidden)

The contract bump to **v0.5** *should* be regression-gated by the
`tests/citation_ground_truth/` sample set (CLAUDE.md §8.2; DECISIONS ADR step 3) — but
**that regression is not yet built**: `make test-gt` is a P2 stub (`exit 1`) and the
directory holds only `samples.md` (labeled samples, no runner). So this contract change
**cannot be mechanically regression-gated** today. Per "silent-fail strongly unwelcomed",
this is recorded loudly here and as gap **G2.6** in `docs/GAPS.md` rather than faked as a
green run. The change only *widens* an allowance (a quant claim on a TRUSTED+ domain now
satisfies `has_primary`); it cannot make a previously-passing sample newly fail I3. The
real, runnable gate used at execution was the full existing pytest suite.

## Affected modules

| Module | Change |
|---|---|
| `marketwind/scout/source_tier.py` | **new** — `SourceTier` enum + `classify` + `clears_law3` + `is_officially_verified` |
| `marketwind/writer/select.py` | `eligible_pool` drops EXCLUDED sources whole, keeps TRUSTED+ quant; new `officially_verified_claims` helper |
| `marketwind/verifier/checks.py` | `check_quant_has_primary` uses `clears_law3` (same predicate as the Writer's pool filter) |
| `marketwind/scout/gather.py` | `build_pool` marks OFFICIAL-domain sources `is_primary=True` at ingest |
| `marketwind/writer/render.py`, `marketwind/writer/runner.py` | `✓官方核实` badge injection + wiring |
| `citation/glossary.md` | new "Source tiers" block (Tier-0 "Primary source" unchanged) |
| `CITATION_CONTRACT.md` | I3 annotated; version 0.4 → 0.5 |

## Relationship to DECISIONS.md

**Refines D-7 and D-5** (quantitative / policy claims need a primary) by *defining* what
"primary-grade" means for the I3 gate — it does **not** overturn them. The requirement
that a quant claim have a primary still holds; ADR-0003 only widens the set of sources
that qualify as primary-grade, and adds the badge to keep the genuine-primary signal
honest. Consistent with D-1 (pool-only), D-3/Law-4 (no model inference — the badge is
mechanical), and the default-deny posture throughout.
