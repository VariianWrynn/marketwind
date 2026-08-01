# Agent-operable deploy — design

> **Read when:** changing the compose files, `DEPLOY.md`, the hermes mount wiring, or anything about how a third-party agent brings the report node up. Companion to `docs/progress/cloud-cutover-aliyun.md` (what the first cutover cost) and `deploy/report-node/README.md` (owner-facing provisioning).

**Date:** 2026-08-01 · **Status:** design approved, pending implementation

---

## 1. Context

The Aliyun ECS report node is being rebuilt from scratch. This time the deploy and ongoing operation are driven by a **Nous Research Hermes agent already resident on the box**, using its `devops-docker-management` skill. That skill is a thin wrapper over the Docker CLI — container lifecycle, `exec`/`logs`/`inspect`, image build/pull, `compose up|down|ps|logs|exec|run|config`, `volume`/`network`, and `system df|prune`. It carries no repository knowledge, and its own documentation names data destruction as its top risk.

The agent additionally has **full root shell** on the box (verified by the owner): arbitrary commands as uid 0, package install, `systemctl`, filesystem writes, and `git` over SSH. Git over HTTPS times out — the standard China-network failure already recorded in `CLAUDE.md` §10.

**The defining constraint: the deploying agent is also a production dependency.** The same `/root/.hermes` install that runs the deploy is what MarketWind shells out to for WeChat delivery — the `scheduler` bind-mounts it read-only and invokes `/root/.hermes/hermes-agent/venv/bin/hermes` (ADR-0001). An agent that upgrades, reinstalls, or re-authenticates itself can silently sever the report's only delivery path.

### 1.1 Two failure classes

| Class | Description | Countermeasure |
|---|---|---|
| **A — agent does the wrong thing** | A plausible Docker command silently degrades or destroys the deployment | Repo guardrails (§3): make the wrong command harmless or impossible |
| **B — agent doesn't know what to do** | No agent-facing procedure exists; guidance is spread across three owner-facing docs, one of which is wrong | `DEPLOY.md` (§4): one self-contained, verifiable procedure |

Guardrails are preferred wherever they can substitute for documentation. A document cannot stop `docker compose down`; a named volume can make it survivable.

### 1.2 Established facts

- **Postgres has no volume.** `docker-compose.yml` declares no `volumes:` for the service and there is no top-level `volumes:` block, so its data lives on an anonymous volume. `down` then `up` yields an empty database.
- **Postgres is the only stateful service.** Redis is referenced solely by the health probe and by a P3 Streams *plan* (`scheduling/trigger.py` docstring); nothing durable is stored in it today.
- **Prod requires two `-f` flags.** Omitting `deploy/report-node/docker-compose.prod.yml` silently drops `TZ=Asia/Shanghai` (cron is wall-clock — the pre-market report fires 8 hours off), every `restart: unless-stopped`, the hermes uv-interpreter mount, and the backup sidecar.
- **Nothing creates the database schema.** `migrations/` holds six DDL files; no container applies them. A fresh box that skips this crash-loops on `relation "run_ledger" does not exist` — the first gap of the last cutover.
- **No `.dockerignore` exists**, so every build ships `.git`, `.pytest_cache`, `marketwind.egg-info`, `docs/`, `tests/` and `.env` into the build context.
- **`deploy/report-node/README.md` §5 clones over HTTPS**, which cannot work on this box.
- **`pyproject.toml` pins a static `version = "0.0.0"`** with no `setuptools-scm`, so excluding `.git` from the build context is safe.

## 2. Goals and non-goals

**Goals.** A fresh ECS box reaches a verified running stack, driven by an agent, with no step depending on recall; the destructive commands in the agent's own toolkit become survivable; the agent cannot break its own delivery path without being told first.

**Non-goals.** The dead-man FC watcher (G1.3), OSS bucket and RAM-role provisioning, the WeCom fallback (G1.5), CI (G2.7), and any change to report logic. No deploy script or wrapper CLI — `COMPOSE_FILE` achieves the same result with a stock Compose feature.

## 3. Repo guardrails

### 3.1 Named volume for Postgres

`docker-compose.yml` gains, on the `postgres` service and at top level:

```yaml
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

`docker compose down` becomes non-destructive. Only `down -v` and `system prune --volumes` can now destroy the database, and both are named in `DEPLOY.md`'s prohibited list. Redis deliberately gets no volume — adding one would imply a durability guarantee the system does not rely on.

### 3.2 `COMPOSE_FILE` in the environment

`.env.example` gains, with an explanatory comment:

```
COMPOSE_FILE=docker-compose.yml:deploy/report-node/docker-compose.prod.yml
```

Compose reads `COMPOSE_FILE` from `.env` in the project directory, so bare `docker compose up -d`, `ps`, `logs`, and `exec` all resolve to the production stack. This is the highest-leverage change in the set: it makes the agent's most natural commands correct by default rather than depending on it reproducing two `-f` flags every time. The separator is `:` (Linux `COMPOSE_PATH_SEPARATOR`).

**Constraint this introduces:** commands must be run from the repository root, since that is where Compose looks for `.env`. `DEPLOY.md` states this once, explicitly, and every command block in it assumes that working directory.

### 3.3 One-shot `migrate` service

A new service applies the schema and exits; `app` and `scheduler` gate on its success.

```yaml
  migrate:
    image: marketwind:local
    build: .
    command: ["python", "-m", "marketwind.storage.migrate"]
    environment:
      DATABASE_URL: postgresql://marketwind:marketwind@postgres:5432/marketwind
    depends_on:
      postgres:
        condition: service_healthy
    restart: "no"
```

`app` and `scheduler` each add:

```yaml
    depends_on:
      migrate:
        condition: service_completed_successfully
```

(retaining their existing `postgres`/`redis` health conditions).

`restart: "no"` is explicit because the prod override applies `unless-stopped` per-service and a one-shot must not inherit a restart policy by future accident.

**This overturns a documented decision** — migrations were "owner-run by design" — so it ships with **ADR-0004** in the same PR (§6). The evidence: the `0006` incident, where a node pulled new code, rebuilt, and lost a morning run because nobody re-ran migrate; and the shift to agent operation, which removes the human who was assumed to remember.

**Shared image tag.** All three build-based services (`app`, `scheduler`, `migrate`) get `image: marketwind:local` so the image is built once rather than per-service. This touches two existing services, which is a deliberate departure from strict surgical scope: adding a third build-based service is what makes the duplicate-build cost concrete, on a 2-vCPU box whose builds also fetch Chromium. Flagged here so it can be vetoed independently of the rest.

### 3.4 `.dockerignore`

New at repo root, excluding `.git`, `.env`, `.venv`, `__pycache__`, `*.pyc`, `.pytest_cache`, `marketwind.egg-info`, `docs/`, `tests/`, `deploy/`, `.claude/`. Cuts context-transfer time on every rebuild and keeps `.env` out of the build context. The root Dockerfile copies only `pyproject.toml`, `marketwind/`, `migrations/` and `citation/`, so none of these exclusions can affect the image. The `backup` sidecar builds from `deploy/report-node` as its own context and is unaffected by a root-level ignore file.

### 3.5 Healthcheck on `app`

The `app` service gains a healthcheck against its existing `GET /health` endpoint, which probes Postgres and Redis and already returns `200` when both are reachable and `503` otherwise (`gateway/app.py`) — exactly the contract a healthcheck needs.

**The probe must be stdlib Python, not `curl`.** The image is `python:3.11-slim`, which ships neither `curl` nor `wget`; a healthcheck reaching for either would fail permanently and report the app as unhealthy forever — precisely the false signal this section exists to eliminate. `urllib.request.urlopen` raises on a 503, so the non-zero exit falls out naturally:

```yaml
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
```

`start_period` is required so the container is not marked unhealthy while uvicorn is still binding.

This gives the agent a machine-readable verdict from `docker compose ps` instead of requiring it to read logs and judge — the exact step where the last cutover misdiagnosed a stale log as a live crash-loop, and needed `docker inspect` restart-counts to settle.

## 4. `DEPLOY.md`

A new **root-level** file. Root placement is a deliberate exception to this project's "keep the root clean" convention: the document's entire purpose is to be found cold by a non-Claude agent that was never told where to look, and discoverability outranks tidiness for that one job. `SHOUTY.md` matches the existing root set (`CLAUDE.md`, `CITATION_CONTRACT.md`, `DECISIONS.md`, `ARCHITECTURE.md`). The name `AGENTS.md` is rejected: it signals general contributor guidance and would collide with `CLAUDE.md`'s declared role.

**Opening.** Addressed directly to its reader — *if you are an agent operating this repository on the deployment box, this is your file* — establishing that it is complete and self-contained, that the compose files are not to be improvised from, and that **any step whose output does not match what is written must stop and report rather than be worked around.**

**Required sections.**

1. **Preconditions** — what must already be true (Docker Engine + Compose v2, `Asia/Shanghai` timezone, SSH git auth, hermes installed and WeChat-authenticated).
2. **Get the code** — SSH clone, *not* HTTPS, with the reason stated so it is not "fixed" back.
3. **Configure** — copy `.env.example`, `chmod 600`, and a table of every variable: which are mandatory, which have working defaults, which only the owner can supply.
4. **Bring the stack up** — the single `docker compose up -d --build` that `COMPOSE_FILE` now makes correct.
5. **Verify** — an ordered gate list, each with its expected output: all services healthy in `docker compose ps`; `migrate` exited `0`; tables present; `check_keys.py` green; the hermes preflight green; `run_once --dry-run --floor-only` passing.
6. **Routine operations** — update/redeploy, read logs, restart one service, inspect the DB.
7. **Prohibited operations** — with the consequence of each, not just the rule.
8. **When something is wrong** — the four known failure signatures from the cutover note (missing tables, missing Chromium, missing `citation/`, hermes not resolvable), each with its diagnostic and fix.
9. **Escalate to the owner** — the human-only steps: secret values, `hermes gateway setup` QR scan, Aliyun console work.

**Prohibited operations** (§7) covers at minimum: `docker compose down -v` and `docker system prune` in any form; printing, echoing, or committing `.env`; writing anything under `/root/.hermes`; upgrading or reinstalling hermes, or re-running `gateway setup`, while the scheduler is running; `--send-real` without explicit owner instruction; and loosening the freshness ceiling to force an off-hours run (`--force-fresh` is the designed override and keeps the verifier gate).

**Relationship to existing docs.** `deploy/report-node/README.md` remains the owner-facing provisioning guide — ECS sizing, security groups, RAM roles, OSS lifecycle — and its HTTPS clone in §5 is corrected to SSH as part of this work. `DEPLOY.md` links to it for provisioning rather than duplicating it.

### 4.1 Discoverability edits

- **`README.md`** — a pointer directly beneath the intro, above the fold, naming `DEPLOY.md` as authoritative for the report node and `deploy/report-node/README.md` as owner-facing provisioning; plus a `DEPLOY.md` entry in the **Repository map** block, which the project treats as the source of truth for "where is X".
- **`CLAUDE.md` §9** — a `DEPLOY.md` row in the document map, `Read when: deploying or operating the ECS report node`. `CLAUDE.md` is the declared first read for Claude-family agents; a deploy document reachable only from `README.md` would be invisible to agents following that map.

## 5. Hermes self-preservation

A preflight check — `deploy/report-node/check_hermes.py`, sibling to the existing `check_keys.py`, stdlib-only and runnable before anything is built — resolves `HERMES_BIN`, confirms it exists and is executable, follows its venv interpreter to a real path, and asserts that path falls under the directory the prod override mounts (`HERMES_UV_PYTHON_DIR`). It prints a PASS/FAIL row per check and exits non-zero on any failure, matching `check_keys.py`'s contract.

This converts the ADR-0001 fragility — an interpreter living outside the mounted tree — from a mid-report `hermes: not found` into a pre-deploy failure with a named cause. It is the mechanical half of the self-preservation rule; the documented half is the `DEPLOY.md` prohibition on mutating hermes while the scheduler runs.

## 6. Documentation deliverables

Per `CLAUDE.md` §8.6, in the same PR:

- **This spec.**
- **Plan** — `docs/superpowers/plans/2026-08-01-agent-operable-deploy.md`.
- **ADR-0004** — `docs/adr/0004-stack-applies-migrations.md`, recording the overturn of owner-run migrations, its evidence, and what it costs (the stack now assumes it may write schema at boot; a bad migration blocks startup loudly rather than surfacing at first query — the intended trade).
- **`DECISIONS.md`** — a row referencing ADR-0004.
- **Progress note** — `docs/progress/agent-operable-deploy.md`.
- **`docs/GAPS.md`** — G0.2 (*deploy & run the daemon persistently*) is materially advanced but **not closed**; only an actual unattended live run closes it. The note must say exactly that rather than implying closure.

## 7. Testing

`pyyaml` is added as a dev dependency. Hermetic tests parse the compose files directly and assert:

- `postgres` mounts a named volume, and that volume is declared at top level;
- a `migrate` service exists, runs the migrate module, and carries `restart: "no"`;
- `app` and `scheduler` both gate on `migrate` with `service_completed_successfully`;
- the prod override sets `TZ: Asia/Shanghai` on `scheduler`;
- `app` declares a healthcheck whose test invokes `python`, pinning the §3.5 constraint so a later edit cannot reintroduce a `curl` probe the image cannot run;
- `.env.example` contains the `COMPOSE_FILE` line naming both files in the correct order.

Each fails on an assertion against today's files, which is a genuine RED under `CLAUDE.md` §8.2 — not an import error. `check_hermes.py` is tested with the stub-executable pattern already established in `deploy/report-node/tests/test_backup_script.py`.

**Not unit-tested:** Compose's *merge* semantics, which need a live Docker daemon. `DEPLOY.md`'s verify section covers this with `docker compose config` run on the box, where the merged result is what actually matters.

## 8. Risks

- **`COMPOSE_FILE` is directory-sensitive.** An agent running Compose from outside the repo root gets the dev stack with no warning. Mitigated by stating the working directory once in `DEPLOY.md` and by every command block assuming it; not fully eliminable.
- **Auto-migration widens boot-time blast radius.** A malformed migration now blocks `app` and `scheduler` from starting rather than failing at first query. This is the intended trade — loud and early over silent and mid-report — and is recorded in ADR-0004.
- **`DEPLOY.md` can rot**, exactly as `deploy/report-node/README.md`'s HTTPS clone did. Partly mitigated by moving traps into guardrails, so there is less prose left to go stale.
- **The agent may not read `DEPLOY.md` at all.** Nothing enforces it. This is why §3 does not depend on it.
