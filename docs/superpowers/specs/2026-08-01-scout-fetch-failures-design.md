# Scout fetch/lookup failures reach the database

> **Read when:** touching the Scout gather/enrich swallow paths, or reviewing why
> `fetch_failures` exists alongside `claim_failures`.

Status: accepted 2026-08-01.

## Problem

Three places in Scout catch every exception and move on without recording
anything:

| Site | Swallowed |
|---|---|
| `marketwind/scout/gather.py:45` | a page fetch failed → skip the URL |
| `marketwind/scout/enrich.py:40` | the cninfo trace failed → no primary |
| `marketwind/scout/enrich.py:45` | a disclosure fetch failed → try next candidate |

Each is deliberate and correct as *degradation*: one bad page must not abort a
run. The defect is that the degradation is **invisible**. A single dead URL and a
total cninfo outage produce the same observable result — a thinner pool — so a
systemic failure is indistinguishable from "the news was quiet today". For a
report whose floor gate depends on primary count, that is the difference between
"no disclosures existed" and "we could not reach the disclosure venue", and only
the second one means the report is wrong.

## Constraint that shapes the design

`build_pool` and `enrich_primary` take injected seams (`search`, `fetch_page`,
`parse`, `persist` / `classify`, `trace`, `fetch`) and hold **no database
handle** — that is what makes them offline-testable. Only the `_live` wrappers
(`gather_live(conn, …)`, `enrich_primary_live(conn, …)`) have `conn`.

So the recorder must arrive the same way every other side effect does: as an
injected callback, not a connection threaded into pure control flow.

## Design

**One new seam.** `on_failure(stage, locus, detail)` — an async callback added to
`build_pool` and `enrich_primary`, defaulting to a no-op so every existing
caller and test is unaffected. `enrich_primary` forwards it to `_resolve`.

```python
FailureFn = Callable[[str, str, str], Awaitable[None]]  # stage, locus, detail
```

| stage | locus | raised by |
|---|---|---|
| `gather_fetch` | the page URL | `fetch_page(url)` |
| `enrich_trace` | `"{claim_type}:{symbol}"` | `trace(...)` |
| `enrich_fetch` | the disclosure URL | `fetch(url)` |

`detail` is `repr(exc)` — the exception type is the diagnostic signal (a
`TimeoutError` across every URL reads very differently from scattered 404s).

**One new table.** `migrations/0007_fetch_failures.sql`, mirroring the shape of
`claim_failures`:

```sql
create table if not exists fetch_failures (
    failure_id uuid primary key default gen_random_uuid(),
    stage      text not null,
    locus      text not null,
    detail     text not null,
    created_at timestamptz not null default now()
);
```

**One new repo helper.** `record_fetch_failure(conn, *, stage, locus, detail)`,
wired into `on_failure` inside `gather_live` and `enrich_primary_live`.

## Rejected alternatives

**Reuse `claim_failures`.** Zero migration, but that table is the Verifier's
rejection log, reviewed weekly per `CLAUDE.md` §8.5. Mixing "a website was down"
into "the Verifier rejected this claim" makes the weekly review noisier and its
`trace_id` column meaningless for Scout rows.

**Thread `conn` into `build_pool`/`enrich_primary`.** Destroys the seam design
that makes the whole Scout control flow unit-testable offline.

**Log to stdout only.** Leaves nothing to review after the process exits, and the
requirement was explicitly a database record.

## Deliberately out of scope

- **`marketwind/scout/fetch.py:57`** stays untouched. That `except` is the
  "page never reaches network-idle" wait fallback, not a lookup failure — the
  DOM is already loaded and the fetch goes on to succeed. Recording it would
  generate noise on healthy runs.
- **`trace_id`.** Scout has no `trace_id` threaded into it; the id lives in the
  orchestration/scheduling layer. Adding one is a wider change than this
  warrants, so the table correlates by `created_at` instead.
- **Alerting/thresholds.** This lands the record. Deciding that "N failures in
  one run" should abort or page is a separate call.

## Testing

Behavioral RED, offline, via the injected seam: make each seam raise and assert
`on_failure` was called with the exact `(stage, locus)` and a `detail` carrying
the exception. A live-Postgres test covers `record_fetch_failure` following the
`tests/verifier/test_record_failures.py` fixture pattern.
