# Source-tier primary-grade gate + officially-verified badge

> **Read when:** resuming the I3-clearance / primary-recall work, or wondering why Sina
> Finance is allowed to back a number. Follows `writer-i3-publish-path.md` (the two
> structural I3 fixes this extends). Spec + plan under `docs/superpowers/`.

**Status:** **complete (Phase A built, tests green)** — 2026-06-17. The *design sub-phase*
(spike + research + decisions + spec + plan) is recorded below; the **build record** (per-module,
commits, invariants) was appended after execution and is the last section of this note.

---

## What was done (design sub-phase)

| # | Activity | Outcome |
|---|---|---|
| 1 | **Real Bocha spike** (live API, cost ignored) | Bocha **ignores the `site:` operator**, **cannot reach `cninfo.com.cn` at all**, and official venue / regulator domains barely surface. Trusted financial outlets (Sina, 第一财经, 财联社, 中证网, 上证, 证券时报) **dominate** results. → "go straight for official disclosure via Bocha" is dead; cninfo-direct must use akshare (deferred Phase B). |
| 2 | **Source-classification research** (CSRC-designated media) | Grounded a 5-tier model in statute (CSRC Information-Disclosure Provisions + Securities Law Art. 86), not taste. Tiers: OFFICIAL(4) / DESIGNATED(3) / TRUSTED(2) / SECONDARY(1) / EXCLUDED(0). |
| 3 | **Tool-vs-agent decision** for webfetch | **Keep webfetch a fast tool**, not an agent. The problem is domain-targeting, not multi-hop reasoning; an agentic loop adds 3–20× latency/cost, wider attack surface, worse debuggability for no recall gain. |
| 4 | **Spec written** | `docs/superpowers/specs/2026-06-17-source-tier-primary-grade-design.md` — the 5-tier model, two predicates, exact domain lists, wiring, badge, Phase-B spike-gate, dropped levers, contract/ADR changes. |
| 5 | **Plan written** (controller altitude) | `docs/superpowers/plans/2026-06-17-source-tier-primary-grade.md` — contracts + RED assertions + spec-critical domain literals; implementation in prose per CLAUDE.md §2. |

## The design in one paragraph

I3 (no quant claim without a primary) stays strict, but the **live supply of Tier-0
primaries is near zero**. Resolution: recognise a tier *between* "the company itself" and
"random aggregator" — CSRC-designated disclosure media. Two predicates fall out:
**primary-grade** (clears the I3 *gate*: `attached_primary_url OR is_primary OR tier ≥
TRUSTED`) lets a Sina/中证网 number lawfully back a claim; **officially-verified** (earns the
reader *badge* `✓官方核实`: `… OR tier ≥ DESIGNATED`) celebrates only genuinely
primary-corroborated claims. TRUSTED clears the gate but **not** the badge. The Tier-0
"Primary source" glossary definition does **not** move.

## Key decisions / risks recorded

- **Owner accepts the residual risk** that a designated/trusted outlet occasionally
  mis-transcribes a number — a calculated risk, taken knowingly (→ ADR-0003 at execution).
- **Default-deny:** an unknown domain is EXCLUDED and can never back a number; recall is
  widened only by a reviewed list edit, never by accident.
- **Honesty gaps surfaced in the plan** (not hidden): `build_pool` has no `tests/scout/`
  unit file (Task 5 creates one); the mandated `tests/citation_ground_truth/` regression is
  an **unbuilt P2 stub** (`make test-gt` → `exit 1`), so the contract bump to v0.5 cannot be
  mechanically regression-gated — Task 7 records this loudly rather than faking a green run.

## Out of scope / deferred

- **Phase B — cninfo-direct via akshare** (true primary recall): spike-gated. B1 is a live
  go/no-go (does akshare return usable disclosure numbers for STAR50 constituents?) before
  any B2 code.
- **Dropped:** Bocha query-string biasing toward primary domains (spike proved near-zero ROI).

## Next

Execute the plan via subagent-driven development (Task 0 commits the two precursor fixes,
then Tasks 1–7). **Return here after execution and append the build record.**

---

## Build record (Phase A — executed 2026-06-17)

Executed via subagent-driven development (fresh Sonnet sub-agent per code task + controller
verify-then-commit; docs done inline). Every code task watched a real **assertion** RED
(not an ImportError) before GREEN. Phase B (cninfo-direct via akshare) remains spike-gated,
not started.

| Task | Module(s) | What it does | Commit |
|---|---|---|---|
| 1+2 | `scout/source_tier.py` (**new**) | `SourceTier` IntEnum (EXCLUDED 0 … OFFICIAL 4) + `classify(domain)` (denylist-first, suffix-match allowlists, default-deny) + `clears_law3` (gate, tier ≥ TRUSTED) + `is_officially_verified` (badge, tier ≥ DESIGNATED) | `9a37a27` |
| 3 | `writer/select.py` | `eligible_pool` drops EXCLUDED sources whole; keeps a quant quote iff `clears_law3(...)`; drops emptied sources | `3d5beca` |
| 4 | `verifier/checks.py` | `check_quant_has_primary` swaps the inline `attached_primary OR is_primary` for `clears_law3(...)` — same predicate as the Writer's pool filter | `ed0537c` |
| 5 | `scout/gather.py` | `build_pool` sets `is_primary = classify(domain) >= OFFICIAL` at `Source(...)` construction — activates the dead `is_primary` path | `c9a18d0` |
| 6 | `writer/select.py` + `render.py` + `runner.py` | `officially_verified_claims(output, pool)` → id set; `render_brief(..., official_ids=…)` injects `✓官方核实` after the `[n]` footnotes on factual sentences whose every claim is official; runner wires it through the filtered pool | `3c76a54` |
| 7 | `docs/adr/0003-*.md` (**new**), `citation/glossary.md`, `CITATION_CONTRACT.md` (v0.4→0.5), `DECISIONS.md` (D-5/D-7), `docs/GAPS.md` (G2.6), spec+plan | ADR-0003; 5-tier glossary block (Tier-0 "Primary source" left unchanged); I3 annotation + version bump; D-5/D-7 refined (not overturned); ground-truth-regression gap surfaced | `a6967a4` |

### Invariants proven

- **One predicate, two call sites.** Writer (`eligible_pool`) and Verifier
  (`check_quant_has_primary`) both gate on `clears_law3`, so a quant claim that survives
  selection **cannot** fail I3 — the structural guarantee from the prior I3 fix holds with
  the widened predicate. (`tests/writer/test_select.py`, `tests/verifier/test_checks.py`.)
- **Gate ≠ badge.** TRUSTED (e.g. `finance.sina.com.cn`) clears the I3 gate but does **not**
  earn `✓官方核实`; DESIGNATED+ earns both. The gap is the honest reader signal.
  (`test_trusted_clears_gate_but_not_badge`, `test_officially_verified_includes_designated_excludes_trusted_only`.)
- **Default-deny + denylist-first.** Unknown domains and denylisted forums are EXCLUDED;
  the denylist beats an allowlist suffix-match (`money.finance.sina.com.cn` → EXCLUDED even
  though `finance.sina.com.cn` is TRUSTED). (`tests/scout/test_source_tier.py`.)
- **Tier-0 definition unmoved.** "Primary source" in the glossary is unchanged; only
  "primary-*grade*" (the gate) widened. The badge is mechanical / non-LLM, so Law 4 is intact.

### Gate run (the real, runnable one today)

Full suite: **310 passed, 1 failed in ~308 s**. The single failure
(`tests/scout/test_cninfo_pdf.py::test_integration_pdf_number_match_attaches_primary`) is
**pre-existing and unrelated** to this work: `enrich.py` imports none of the changed modules,
and that test + its code path are byte-identical to the pre-work base. Root cause (diagnosed):
commit `51ce25b` made `_resolve` iterate `trace()`'s return as a list of candidate URLs, but
the test's stub `trace` still returns a single string `_DETAIL_OK`, so `_resolve` loops over
the string's characters and never matches. Production `trace_to_primary` correctly returns
`list[str]`; only the **test fixture is stale**. Surfaced loudly (not silently skipped) and
spun off as a separate one-line fixture fix. **No source-tier test fails.**

### Deferred / still open

- **Phase B — cninfo-direct via akshare** (true Tier-0 recall): spike-gated; B1 live go/no-go
  not yet run. The `is_primary`-at-ingest seam (Task 5) is what B2 would feed.
- **G2.6 — ground-truth regression runner unbuilt:** the v0.5 contract bump could not be
  mechanically sample-gated. Build the runner before the next contract-semantics change.
