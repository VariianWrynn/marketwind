# I12 — Derived-metric methodology enforcement

> **Read when:** touching the claim schema (category/methodology), the Writer prompt, or the Verifier's Law-5 gate.

**Status:** complete. Branch `claude/eloquent-kare-c3d8b2`. Plan: `docs/superpowers/plans/2026-07-16-i12-derived-metric-methodology.md`. Full suite green (339 passed).

**What this delivers:** end-to-end enforcement of Invariant I12 (`CITATION_CONTRACT.md:158`, decision D-12). A `derived_metric` claim — a source's own computation over base data (e.g. 长鑫 "日赚 3.6 亿", 合计减持额) — must now carry a `methodology` label stating the basis, or the report fails the Law-5 publication gate. Before this, a bare derived number passed the Verifier unlabeled.

## What was done, by task

| Task | Module | What it does | Commit |
|---|---|---|---|
| Domain | `writer/domain.py` | `DraftClaim` gains `category` (default `quantitative`) + `methodology` (nullable) | 679e968 |
| Schema | `writer/schema.py` | I8 parse reads both fields; enum-validates `category` (9 values); does **not** reject derived-without-methodology (Verifier's call) | e2a4727 |
| Writer remap | `writer/writer.py` | alias→uuid remap carries `category`/`methodology` through (else silently dropped) | 1c89f96 |
| Verifier check | `verifier/checks.py` | new `check_derived_methodology` → `Violation(check="I12", …)` when `derived_metric` and methodology blank/None | 5a79dbd |
| Verifier wiring | `verifier/verifier.py` | I12 is the 7th check in `verify()`, alongside the Tier-1 checks | bb0c9fa |
| Writer prompt | `writer/prompt.py` | `_OUTPUT_SPEC` teaches the model to emit `category`/`methodology` + the derived-metric rule | bc1b193 |
| DB | `migrations/0006_i12_derived_metric.sql`, `storage/repo.py` | `claims` gains `category`/`methodology` columns + enum & implication CHECK constraints; `persist_report` writes them | e97b5ad |

## Key invariants proved here

- **I12 (the guard):** `category == 'derived_metric'` ⟹ `methodology` is non-empty. Enforced deterministically in the Verifier; a violation fails the whole report (Law 5).
- **Enforcement placement (Q2):** the I8 schema only parses + enum-validates — it does **not** reject a derived-without-methodology claim. I12 is a *graded* claim-level failure (`failure-handling.md:25`), so the Verifier owns the reject; the DB CHECK (`claims_derived_needs_methodology`) is a last-resort integrity backstop, not the primary gate.
- **Surgical schema growth (Q1):** `category` is optional and defaults to `quantitative`; the Writer is not forced into 9-way classification of every claim. Only claims it explicitly marks `derived_metric` are subject to I12. Existing positional `DraftClaim(...)` call sites were unaffected (trailing defaulted fields).
- **Field survives the full path:** parse → remap → verify → persist all carry `category`/`methodology`; a dedicated remap test pins the step most likely to silently drop them.

## Locked interpretations (agreed with owner 2026-07-16)

- **Q1** category optional, defaults to `quantitative`.
- **Q2** enforcement lives in the Verifier; schema parses only; DB CHECK is a backstop.
- **Q3** the deterministic check is `derived_metric ⟹ methodology non-empty` (matches the DB CHECK `CITATION_CONTRACT.md:123` verbatim). "State the basis in the body" is satisfied by the Writer also populating `methodology`.

## Not run (no harness exists yet)

- `make test-gt` (ground-truth regression) and `make eval-prompt` (prompt regression) are still stubbed (`not implemented until P2`); `tests/citation_ground_truth/` holds only `samples.md`, and `tests/prompt_regression/` only a `.gitkeep`. No automated regression could be executed for the prompt change — flagged rather than skipped silently.

## How to test

```
export DATABASE_URL='postgresql://marketwind:marketwind@localhost:5432/marketwind'
export REDIS_URL='redis://localhost:6379/0'
python -m pytest tests/writer tests/verifier -q          # I12 unit + schema + prompt + persist
python -m pytest tests/writer/test_repo_writer.py -q     # DB migration + CHECK constraint (real Postgres)
```
