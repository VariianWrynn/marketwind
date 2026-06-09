# Verifier — the Law-5 publication gate (Tier 1 + Tier 2)

> **Read when:** picking up Verifier work, or before changing anything between the Writer draft and IM publication.

**Status:** complete. Branch `verifier-law5-gate`. Spec: `docs/superpowers/specs/2026-06-09-verifier-law5-gate-design.md`. Plan: `docs/superpowers/plans/2026-06-09-verifier-law5-gate.md`.

**What it delivers:** a fresh, independent, **fail-closed** pass over the structured Writer output, inserted between the Writer draft and publication. Six checks (four deterministic, two DeepSeek-judge). Any check fires → the brief is **not** published; the violations are recorded to `claim_failures` and a dev-channel status message (with `trace_id` and the tripped checks) goes out instead. The gate is **hardcoded** into `run_pipeline` (called directly like `evaluate_floor`, not an injected seam), so no caller can wire a pipeline that skips it — this is what makes Iron Law 5 *structural*.

## What was done, by task

| Task | Module | What it does | Commit |
|---|---|---|---|
| Value objects | `verifier/domain.py` | `Violation(check, locus, detail)`, `VerifyResult(passed, violations)` — frozen, no I/O | bafb308 |
| Pool plumbing | `writer/domain.py`, `storage/repo.py` | `PooledQuote.span_start/span_end`, `PooledSource.raw_content`; `load_pool` widened to fetch them (no schema change) | 2940aee |
| Tier-1 checks | `verifier/checks.py` | `index_quotes` + 4 pure checks: RF-3 (quote re-resolution), I3 (quant→primary), RF-4 (filler), RF-10 (first-person) | 0186987 |
| Tier-2 judge | `verifier/judge.py` | I1 (synthesis), I10 (contradiction) via injected async judge seam; fails closed → `judge_unavailable` | f507954 |
| Aggregator | `verifier/verifier.py` | `verify(output, pool, *, judge)` runs all 6, `passed == (violations == [])` | 809d75a |
| Failure store | `migrations/0003_verifier_failures.sql`, `storage/repo.py` | `claim_failures` table + `record_verifier_failures` (one row per Violation) | 8cc45d8 |
| Deferred persist | `writer/domain.py`, `writer/runner.py` | `DraftBundle(output, pool, body, commit)`; `draft_report` renders without persisting; `commit()` thunk persists only after verify passes | 20c6714 |
| The gate | `orchestration/runner.py` | hardcoded `verify` call in `run_pipeline`; on fail → `record_fail` + dev status + no publish; on pass → `commit()` + label + push | 7fd9168 |
| Seam wiring | `scheduling/run_once.py`, `scheduling/__main__.py`, `verifier/runner.py` | thread `draft`/`judge`/`record_fail` through `run_once`; live `call_judge` (reuses `call_deepseek`); live `__main__` closures | b83e28b |

## The six checks

**Tier 1 — deterministic (pure functions, no LLM):**
- **RF-3 `check_quotes_resolve`** — every quote a claim references re-resolves independently: `source.raw_content[span_start:span_end] == quote.text` (literal slice, no normalization). Missing quote_id or mismatch → violation.
- **I3 `check_quant_has_primary`** — any claim referencing a quantitative quote must reference ≥1 quote with a primary (`attached_primary_url` set, or owning source `is_primary`). The Law-3 keystone the cninfo-PDF limb feeds.
- **RF-4 `check_no_filler_attribution`** — no anonymous-filler attribution (据报道 / 业内人士 / 市场认为 / …) in any sentence or claim statement.
- **RF-10 `check_no_first_person_inference`** — no first-person model inference (系统认为 / 分析显示 / 经测算 / …).

**Tier 2 — DeepSeek judge (injected async seam, flags only — never rewrites):**
- **I1 `check_no_synthesis`** — no single sentence fuses two distinct claims.
- **I10 `check_no_contradiction`** — no two claim statements assert contradictory facts (coarse; time-window precision is a Tier-3 gap).

## Key invariants proved here

- **Fail closed, always.** Judge unavailable / unparseable verdict → `judge_unavailable` violation (never "pass on doubt"). A quote that won't re-resolve, a quantitative claim with no primary → no publish.
- **The gate is structural (Law 5).** `verify` is imported and called *directly* inside `run_pipeline`; it is not an injected seam, so no caller can skip it. Mirrors the existing hardcoded `evaluate_floor` gate. (Mutation-checked: defeating the `if not result.passed` branch turns the verify-fail test red on `primary.sent == []`.)
- **Persistence after verification.** `persist_report` runs only via `bundle.commit()`, after the Verifier passes. A report that fails verification is never persisted or published — only its violations land in `claim_failures`.
- **Independence.** `verify` takes the structured `WriterOutput` + the `pool` and rebuilds its own quote/source index; it trusts no Writer internal state.
- **No model laundering (Law 4).** The judge only flags; deterministic checks are regex/equality only.

## How to test

```bash
.venv/Scripts/python.exe -m pytest tests/verifier tests/orchestration tests/scheduling tests/writer -v   # all offline
```
Migration `0003_verifier_failures.sql` auto-applies via `marketwind.storage.migrate` (globs `migrations/*.sql` in filename order). The live judge (`verifier/runner.py::call_judge`) and live `__main__` wiring are `# pragma: no cover` — exercised only by the manual scheduled-path entrypoint.

## Out of scope — recorded Tier-3 gaps (deferred, not silently dropped)

Each needs Claim metadata the Writer does not emit, network/history, or the claim state machine:
- **I12** (derived_metric methodology) — Writer emits no `category`/`methodology`.
- **I3b** (corroboration ≥ 2 or attributed_single) and **I2** (corroboration dedup) — Writer emits no `corroboration_status`.
- **I10 time-window precision** — Writer emits no `time_window` (current I10 is coarse).
- **I6** (90-day freshness search) and **I11** (cross-report consistency) — need network / report history.
- **Claim state machine** (drafted→verified/failed→rewritten, retry ≤ 1), **failure-rate thresholds**, **re-run loops**, **800-char digest** — Tier 3.
- The `claim_failures` weekly-review feedback loop is the minimal persistence only; the full state machine remains Tier-3.
