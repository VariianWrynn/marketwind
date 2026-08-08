# Tier 2: Quality & Verification Depth — Plan

**Date:** 2026-08-08
**Branch:** `feat/tier2-quality-and-verification-depth`

## Execution order

1. **G2.7** CI workflow — foundation for all subsequent verification
2. **G2.6** Ground-truth runner — gates contract changes
3. **G2.8** Prompt regression harness — gates prompt changes
4. **G2.4** Mojibake PDF tests — independent, quick
5. **G2.1 + I10** Cross-report storage + time_window — data foundation
6. **G2.2** Verifier Tier-3 invariants (I3b, I10, I11, I6)
7. **G2.3** Claim state machine
8. **G2.5** Per-site publish_ts parsing

## Commits

| # | Gap | Commit message prefix |
|---|-----|----------------------|
| 1 | G2.7 | `ci: add GitHub Actions workflow` |
| 2 | G2.6 | `feat(ground-truth): build regression runner` |
| 3 | G2.8 | `feat(prompt-regression): build eval-prompt harness` |
| 4 | G2.4 | `test(scout): prove mojibake/image-only PDFs fail closed` |
| 5 | G2.1 | `feat(storage): add pipeline_runs table + time_window field` |
| 6 | G2.2 | `feat(verifier): add Tier-3 invariant checks I3b, I10, I11, I6` |
| 7 | G2.3 | `feat(verifier): add claim state machine with failure-rate digest` |
| 8 | G2.5 | `feat(scout): per-site publish_ts parsing from HTML` |
| 9 | docs | `docs: close G2.x gaps, add design/plan/progress notes` |

## Test baseline

- Before: **391 passed**
- After: **430 passed** (+39 new tests)
- Regressions: 0
