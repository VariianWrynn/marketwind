# P1a — Scout (source acquisition)

> **Read when:** picking up Scout work, or before starting a layer that consumes the source pool.

**Status:** complete. Branch `p1a-scout` (PR #1 → `master`). Plan: `docs/superpowers/plans/2026-06-01-p1a-scout.md`.

**What P1a delivers:** assemble a domestic-only source pool for the previous trading session, extract span-exact grounded quotes, trace one media number to its primary disclosure, persist idempotently, and gate publication on a conjunctive grounded floor. Pure logic is unit-tested (53 tests); live I/O is `# pragma: no cover` and exercised by a manual smoke.

## What was done, by sub-phase

| Sub-phase | Module | What it does | Commit |
|---|---|---|---|
| Schema | `migrations/0002_p1_core.sql` | sources / quotes / claims / sentences tables | d385ecc, 551f88d |
| Domain | `scout/domain.py` | `Source`, `Quote`, `FloorResult` value objects | be703ce |
| Time parse | `scout/timeparse.py` | Chinese `publish_ts` parser; year-boundary rule; CN_TZ | 04c536f |
| Numbers | `scout/numbers.py` | Chinese financial-number detection → `is_quantitative` | 93be147 |
| Outlets | `scout/outlets.py` | URL → registrable domain (outlet identity) | bc082d1 |
| Clean/extract | `scout/clean.py` | clean once to frozen `raw_content`, span-exact sentence quotes (**RF-9**) | a27db84 |
| Persistence | `storage/repo.py` | upsert-by-url for Source+Quote, idempotent reruns | 3c3fe95 |
| Calendar | `scout/calendar.py` | A-share previous trading session (calendar-aware) | c42a514 |
| Discovery | `scout/query.py`, `scout/discover.py` | date-anchored recap queries + Bocha client | 8a307e1 |
| Fetch | `scout/fetch.py` | Playwright fetch: resource-block, layered wait, 15s ceiling, transient/permanent classify | ba4428d |
| Market | `scout/market.py` | akshare STAR50 numbers + `is_primary` scope rule | 125c8f8 |
| Primary trace | `scout/primary.py` | claim-type → primary venue routing (Gap-1); cninfo lookup | e4400d1 |
| Grounded floor | `scout/runner.py` | conjunctive 8/1/2 gate; empty fetch ≠ outlet | 63cfc09 |
| Fixtures | `scout/fixtures.py` | offline HTML → Source loader for dry-run extraction | e17090b |
| Live smoke | `scripts/smoke_p1a.py` (gitignored) | real end-to-end chain; saves scratch fixtures | (not committed) |

Review fixes (a54c6aa): primary-trace `str(None)` null handling; floor counts only sources that contributed a quote. Floor boundary tests expanded in 3aa9e5a.

## Key invariants proved here

- **RF-9:** `raw_content[span_start:span_end] == quote.text` exactly. Clean once, freeze, never re-normalize.
- **Grounded floor fails closed:** thin/unsourced coverage → `passed=False`, never fabricates to clear the gate.
- **Idempotent ingest:** re-running upsert by URL does not duplicate sources or append quotes.
- **Calendar-aware:** previous session is the real prior trading day, not naive day-minus-one.

## How to test

See the manual test procedure in the conversation record, or run:

```bash
docker compose up -d postgres redis
.venv\Scripts\python.exe -m marketwind.storage.migrate
.venv\Scripts\python.exe -m pytest tests/scout tests/scout/test_repo.py -v   # 53 tests
```

Live chain (needs BOCHA_API_KEY + Chromium): `PYTHONPATH=. .venv\Scripts\python.exe scripts/smoke_p1a.py`.

## Out of scope / known gaps

- `test_health.py` (P0) needs the FastAPI `app` container on :8000 — not required for Scout.
- Primary trace covers cninfo only. The enrichment wiring + number match-guard landed in `docs/progress/primary-tracing.md`; exchange/regulator venue lookups remain deferred there.
- Live per-site `publish_ts` parsing is per-source work deferred past the smoke.
