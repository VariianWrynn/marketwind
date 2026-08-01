# ADR-0004 — The stack applies DB migrations at boot; `app` and `scheduler` gate on it

**Status:** accepted
**Grantor:** project owner
**Date:** 2026-08-01
**Scope:** permanent
**Expiry condition:** revisit if a migration ever needs to run against live traffic in a way boot-time application cannot express — a long backfill, an online index build, anything that must not block startup. At that point split DDL from data migration via a new ADR rather than loosening this gate.

## Triggering situation

Two things, arriving together.

**The `0006` incident.** Migrations were owner-run by design: idempotent, applied by hand
after the first `up` and after any deploy that added migration files. That worked exactly as
long as someone remembered. PR #11 added `migrations/0006_i12_derived_metric.sql`, a node
pulled the new code and rebuilt without re-running the migration, and `persist_report`
failed at write time. It failed loudly — but loudly at 07:00, which is still a lost morning
run. `docs/progress/cloud-cutover-aliyun.md` records the standing rule that was supposed to
prevent exactly this: *a PR that adds a `migrations/*.sql` needs a migrate run on the node,
not just an image rebuild.* The rule was correct and it did not help, because a rule that
lives in a progress note is only as reliable as the operator's memory of having read it.

**The shift to agent operation.** The report node is now deployed and operated by an agent,
which removes the human that rule was addressed to. An agent following a runbook will do
what the runbook says; it will not independently recall a standing rule recorded in a
different document about an incident it was not present for. Any invariant that matters has
to be mechanical.

## Decision

A one-shot `migrate` compose service runs `python -m marketwind.storage.migrate` at boot.
`app` and `scheduler` declare `depends_on: {migrate: {condition: service_completed_successfully}}`
and therefore do not start until it exits 0.

The runner was already idempotent, so applying on every `up` is a no-op in the common case.
The manual `docker compose exec app python -m marketwind.storage.migrate` remains available
for a targeted re-run; it is simply no longer load-bearing.

## Precondition — this gate depends on ADR-0004's companion change

The gate is only meaningful because exit-0 now *means* "schema applied". Previously,
`apply_migrations` globbed `migrations/*.sql`, found nothing if the directory had moved,
printed "no pending migrations" and exited 0. Under that behaviour the new gate would
cheerfully bless an empty database and then start `app` and `scheduler` against it —
inverting this ADR's entire purpose and converting a loud failure into a silent one.

`pending_migration_paths()` closes that path: an empty result now raises rather than
returning `[]`. **Do not relax it.** If a future refactor makes an empty migrations
directory a legitimate state, this gate must be reconsidered at the same time.

## What it costs

The boot-time blast radius widens. A malformed migration previously surfaced at the first
query that touched the affected table; it now blocks `app` and `scheduler` from starting at
all. That is the intended trade — a stack that refuses to start is a better failure than a
stack that runs and produces a broken report at 07:00 — and it matches the project's
standing preference for obvious failure over silent degradation.

It also means a bad migration takes down a running deployment on the next `up`. The
mitigation is the same as for any other deploy-time break: the previous image is still
present, and `docker compose up -d` without `--build` restores it.

## Affected modules

| Module | Change |
|---|---|
| `docker-compose.yml` | new one-shot `migrate` service; `service_completed_successfully` gates on `app` and `scheduler` |
| `marketwind/storage/migrate.py` | `pending_migration_paths()` — raises instead of reporting success against an unmigrated database |
| `deploy/report-node/README.md` §9 | rewritten; no longer instructs a manual migrate run as a required step |
| `docs/progress/cloud-cutover-aliyun.md` | the "owner-run by design" row and the standing rule are marked superseded, not deleted — they remain accurate about the deploy they describe |
| `DEPLOY.md` | §5 gate 4 verifies the schema; §6 states that migrations need no separate deploy step |
