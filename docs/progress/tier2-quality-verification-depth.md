# Tier 2: Quality & Verification Depth — Progress

**Date:** 2026-08-08
**Status:** Complete
**PR:** #23

## Summary

| Gap | Module | What it does | Tests |
|-----|--------|-------------|-------|
| G2.7 | `.github/workflows/ci.yml` | Advisory CI: pytest + Postgres + Redis service containers | N/A (workflow) |
| G2.6 | `tests/citation_ground_truth/runner.py` | 13 labeled samples → verifier checks → expected verdict comparison | `make test-gt` |
| G2.8 | `tests/prompt_regression/runner.py` | Frozen pool → DeepSeek → 7 assertions → baseline comparison | `make eval-prompt` |
| G2.4 | `tests/scout/test_cninfo_pdf.py` | Image-only + garbled PDF → no-attach (fail-closed) | 3 new tests |
| G2.1 | `migrations/0008`, `storage/repo.py` | `pipeline_runs` table + `time_window` field through full chain | 4 repo + 2 schema tests |
| G2.2 | `verifier/checks.py`, `verifier/judge.py` | I3b corroboration, I10 time-window, I11 cross-report, I6 freshness | 10 new tests |
| G2.3 | `verifier/claim_state.py`, `migrations/0009` | State field, retry ≤ 1, failure-rate digest (10%/25%) | 10 new tests |
| G2.5 | `scout/publish_ts.py` | Per-site HTML timestamp parsers for 7 domestic outlets | 10 new tests |

## Invariants proved

- **G2.6:** Flipping a sample label → runner exits 1 (mechanical criterion verified)
- **G2.8:** Missing API key → exit 1 with clear message (never silent skip)
- **G2.4:** Image-only PDF → empty extract → no-attach through full enrich_primary path
- **G2.2 I3b:** Single-source quant claim without attribution → violation
- **G2.2 I11:** DB lookup failure → `I11_unavailable` violation (fail closed)
- **G2.2 I6:** Search failure → `I6` violation (fail closed)
- **G2.3:** Failure rate ≥ 25% → halt flag; ≥ 10% → warn flag
- **G2.5:** Unknown domain → None; garbled HTML → None; parser exception → None

## How to test

```bash
make test          # 430 passed
make test-gt       # 13/13 samples passed
make eval-prompt   # 7/7 assertions passed (requires API key)
```

## Out of scope

- Real judge integration for I1/I10 (deferred — requires production DeepSeek judge)
- WeCom webhook backup channel (separate gap)
- OCR for image-only PDFs (Iron Law 3 risk — permanent limitation)
- Branch protection enforcement (account limitation — CI advisory only)
