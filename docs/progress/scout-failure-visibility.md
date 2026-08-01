# Scout failure visibility — unreachable sources reach the database

> **Read when:** touching the Scout gather/enrich swallow paths, adding a new
> injected seam to `build_pool`/`enrich_primary`, or asking why `fetch_failures`
> exists next to `claim_failures`.

**Status:** complete. Spec: `docs/superpowers/specs/2026-08-01-scout-fetch-failures-design.md`.
Full suite green — **364 passed** with live Postgres + Redis (migration `0007` applied).
**No `docs/GAPS.md` entry is closed by this** — none covered it; it surfaced from a
ruff `S110`/`S112` sweep on 2026-08-01, not from the deferred-work list.

**No separate plan doc:** single-seam change, four files, settled in one design
exchange with the owner (Option A of two presented). The spec carries the whole
design; a plan would have restated it.

**What this delivers:** three Scout paths that caught every exception and moved on
silently now report the failure, and the live wiring writes it to Postgres. The
degradation behaviour is unchanged — one bad page still does not abort a run —
but a *systemic* outage is no longer indistinguishable from a quiet news day.
That distinction matters because the grounded floor gates on primary count: "no
disclosures existed" and "we could not reach the disclosure venue" produced the
same thin pool before this, and only the second means the report is wrong.

## What was done

| Area | File | What it does |
|---|---|---|
| Seam | `scout/gather.py` | `FailureFn` type + `on_failure` param on `build_pool`, defaulting to a no-op |
| Seam | `scout/enrich.py` | same on `enrich_primary`, forwarded to `_resolve` |
| Report sites | `scout/gather.py:52`, `scout/enrich.py:46,52` | each `except` now awaits `on_failure(stage, locus, repr(exc))` before degrading |
| Schema | `migrations/0007_fetch_failures.sql` | `fetch_failures` table, mirroring the `claim_failures` shape |
| Write helper | `storage/repo.py` | `record_fetch_failure(conn, *, stage, locus, detail)` |
| Live wiring | `gather_live`, `enrich_primary_live` | `_on_failure` closure binds `conn` to the recorder |

Stages recorded:

| stage | locus | raised by |
|---|---|---|
| `gather_fetch` | page URL | `fetch_page(url)` |
| `enrich_trace` | `"{claim_type}:{symbol}"` | `trace(...)` |
| `enrich_fetch` | disclosure URL | `fetch(url)` |

## Key invariants proved here

- **Degradation is preserved, not replaced.** Every pre-existing enrich/gather
  test passed untouched — the `on_failure` default is a no-op, so offline callers
  keep the old behaviour and the recorder is purely additive.
- **The seam design survives.** `build_pool`/`enrich_primary` still hold no DB
  handle; the recorder arrives as an injected callback exactly like `persist`.
  That is what keeps the whole Scout control flow offline-testable.
- **The record is not silent-on-write.** `record_fetch_failure` does not swallow
  its own exceptions — a broken recorder fails the run loudly rather than
  quietly dropping the evidence it exists to keep.

## Verification

RED was watched on all three behavioural tests before implementing: the
`on_failure` parameter was added to the signatures but left uncalled, so each
test failed on `AssertionError: expected 1 reported failure, got []` — an
assertion for the right reason, not an `ImportError`/`TypeError`.

The two live-Postgres tests had no watched RED (the table did not exist, which
errors rather than asserts), so the retroactive check from `CLAUDE.md` §8.2 was
run instead: swapping `locus`/`detail` in the `insert` made `test_writes_row`
fail on its assertion, confirming the test discriminates. Mutation reverted.

Corroborating signal: ruff's `S110` (`try-except-pass`) and `S112`
(`try-except-continue`) findings disappeared from both files — the linter agrees
the handlers are no longer silent.

## Out of scope

- **`scout/fetch.py:57`** untouched. That `except` is the "page never reaches
  network-idle" wait fallback, not a lookup failure — the DOM is already loaded
  and the fetch goes on to succeed. Recording it would generate noise on healthy
  runs.
- **`trace_id`.** Scout has none threaded into it; the id lives in the
  orchestration/scheduling layer. The table correlates by `created_at` instead.
- **Alerting / thresholds.** This lands the record only. Deciding that "N
  failures in one run" should abort or page the owner is a separate call, and is
  the natural follow-up if these rows prove informative.
- **`BLE001`.** The three handlers are still `except Exception`. Narrowing them
  is a different question from making them audible.

## How to test

```
export DATABASE_URL='postgresql://marketwind:marketwind@localhost:5432/marketwind'
export REDIS_URL='redis://localhost:6379/0'
python -m pytest tests/scout/test_gather_tier.py tests/scout/test_enrich.py -q  # seam, offline
python -m pytest tests/storage/test_fetch_failures.py -q                        # migration + insert, real Postgres
```
