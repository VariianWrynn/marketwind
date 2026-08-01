# Agent-operable deploy — repo guardrails + the deploy runbook

> **Read when:** changing the compose files, `DEPLOY.md`, or the preflight scripts; or before handing the report node to an agent to deploy or operate.

**Status:** complete (repo side). Branch `claude/gifted-goldwasser-c855d5`.
Spec: `docs/superpowers/specs/2026-08-01-agent-operable-deploy-design.md`.
Plan: `docs/superpowers/plans/2026-08-01-agent-operable-deploy.md`.

**What this delivers:** the report node is now deployed and operated by a Hermes agent whose
docker skill is a thin Docker CLI wrapper with no knowledge of this repo. That agent cannot
be relied on to know which of our commands are destructive, which env vars are load-bearing,
or that migrations exist. So the repo carries the knowledge instead: five structural
guardrails that make the dangerous thing hard and the necessary thing automatic, plus a
self-contained runbook at the repo root.

The guardrails deliberately **do not depend on the runbook being read.** `DEPLOY.md` makes a
correct deploy easy; the compose files make an incorrect one fail loudly.

## What was done

| Change | File | Commit | What it prevents |
|---|---|---|---|
| Migration runner raises on an empty migrations dir | `marketwind/storage/migrate.py` | `39df539` | Exit 0 against an unmigrated database — which would make the boot gate below bless an empty schema |
| Postgres data on a named volume | `docker-compose.yml` | `8ca38de` | `docker compose down` destroying the run ledger and report history |
| `app` health-gated on its own `/health` | `docker-compose.yml` | `6866df3` | A container that is "up" but cannot reach Postgres or Redis reading as healthy |
| One-shot `migrate` service gating `app` + `scheduler` | `docker-compose.yml` | `6d2dcaa` | The `0006` failure mode: new code, no migration run, crash at 07:00 (ADR-0004) |
| Loopback binds + scheduler delivery healthcheck | `deploy/report-node/docker-compose.prod.yml` | `5a41363` | Postgres/Redis published on all interfaces with guessable credentials; and a silently broken WeChat delivery path |
| `check_hermes.py` preflight | `deploy/report-node/check_hermes.py` | `68be016` | `hermes: not found` discovered mid-report instead of pre-deploy |
| `COMPOSE_PROJECT_NAME` pinned, `COMPOSE_FILE` shipped commented | `.env.example` | `5334c70` | A re-clone into a differently-named directory silently attaching an empty volume |
| Build context trimmed | `.dockerignore` | `f961772` | — (build speed; no correctness claim) |
| The runbook | `DEPLOY.md` | `c75be59` | An agent improvising a deploy from the compose files |
| Discoverability | `README.md`, `CLAUDE.md` §9 | `4a9984f` | A runbook no agent finds |
| ADR-0004 + `D-32` | `docs/adr/0004-stack-applies-migrations.md`, `DECISIONS.md` | `229291b` | Re-litigating the overturn of owner-run migrations |
| Corrections to the notes this invalidates | `deploy/report-node/README.md`, `docs/progress/cloud-cutover-aliyun.md` | `ebb508d` | Two documents still instructing a manual migrate run; and an HTTPS clone URL this network resets |

## Invariants proven

- A `migrate` container that exits 0 really did apply the schema (not "found nothing to do").
- `app` and `scheduler` cannot start against an unmigrated database.
- The prod override never publishes Postgres or Redis beyond loopback.
- The scheduler healthcheck exercises the venv **interpreter**, not just the hermes
  entrypoint — testing `HERMES_BIN` alone cannot see the ADR-0001 dangling-symlink failure.

## How to test

```
python -m pytest tests/deploy tests/storage/test_migrate_guard.py -q
python -m pytest deploy/report-node/tests -q
```

The second command needs an explicit path: `pyproject.toml` sets `testpaths = ["tests"]`, so
a bare `pytest` does not collect the `deploy/` suite.

**What is not unit-tested, on purpose:** Compose *merge* semantics. Whether `COMPOSE_FILE`
resolved, whether the merge actually produced `TZ: Asia/Shanghai` on `scheduler`, and whether
`OSS_BUCKET` interpolated are properties of the Docker Compose binary on the box, not of the
YAML — a unit test would only re-parse the file it just read. `DEPLOY.md` §5 gate 0
(`docker compose config`) covers this where it can actually be observed. Docker is not
available in the development worktree; no test here claims a `docker compose` result.

## Known caveats

- **`COMPOSE_FILE` ships commented out and the agent must uncomment it.** Active, it breaks
  the owner's Windows dev box three ways (path separator, `make dev` launching the prod
  stack, `${OSS_BUCKET:?}` hard-failing every compose command). Gate 0 catches the omission,
  which is why it is gate *0* and not gate 5.
- **`COMPOSE_FILE` is directory-sensitive.** Compose walks parent directories for
  `docker-compose.yml` but **not** for `.env`. Run from a subdirectory and you silently get
  the dev stack. `DEPLOY.md` §3 states this once, explicitly.
- **The named-volume switch orphans a pre-existing anonymous volume.** Data is not deleted,
  but it is no longer attached. Recovery is in `DEPLOY.md` §8:
  `docker run --rm -v <old-anon-volume>:/from -v marketwind_pgdata:/to alpine sh -c 'cp -a /from/. /to/'`.
  Does not apply to a fresh box.
- **Nothing enforces that the agent reads `DEPLOY.md`.** That is the reason the guardrails
  are structural. If you add a new operational requirement, put it in the compose files or a
  preflight — a line in the runbook is a hope, not a guarantee.
- **`OSS_BUCKET` must be set even though the bucket is owner-provisioned.** `${OSS_BUCKET:?}`
  makes Compose refuse *every* command, including `ps` and `config`, when it is unset.

## Out of scope

- The FC dead-man watcher (**G1.3**) — ping URLs remain unset.
- OSS bucket creation, the 14-day lifecycle rule, and the ECS RAM role — Aliyun console work,
  owner-only (`DEPLOY.md` §9).
- The WeCom webhook fallback (**G1.5**) — still `StubSink`.
- CI (**G2.7**) — these tests run locally; nothing runs them on push.
- The live unattended run itself. See G0.2 below.

## What this does *not* close

**G0.2 (deploy & run the daemon persistently) stays open.** A fresh box can now reach a
verified stack under agent control, with the schema applied automatically and the delivery
path guarded before and during operation. That is the precondition, not the proof. Only an
actual unattended live run — the daemon waking itself, producing a report, and pushing it
with no human in the loop — closes G0.2.
