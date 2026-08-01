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
- **Prod requires two `-f` flags.** Omitting `deploy/report-node/docker-compose.prod.yml` silently drops `TZ=Asia/Shanghai` (cron is wall-clock — the pre-market report fires 8 hours off), `restart: unless-stopped` for `postgres`/`redis`/`app` (`scheduler` already carries it in the base file), the hermes uv-interpreter mount, and the backup sidecar.
- **Nothing creates the database schema.** `migrations/` holds six DDL files; no container applies them. A fresh box that skips this crash-loops on `relation "run_ledger" does not exist` — the first gap of the last cutover.
- **No `.dockerignore` exists**, so every build ships `.git`, `.pytest_cache`, `marketwind.egg-info`, `docs/`, `tests/` and `.env` into the build context.
- **`deploy/report-node/README.md` §5 clones over HTTPS**, which cannot work on this box.
- **`pyproject.toml` pins a static `version = "0.0.0"`** with no `setuptools-scm`, so excluding `.git` from the build context is safe.
- **Postgres and Redis are published on all interfaces** (`docker-compose.yml:8-9`, `18-19`) with credentials `marketwind:marketwind` and no Redis auth; the prod override does not restrict them.
- **`config.py` requires `redis_url` with no default and instantiates `Settings()` at import time**, so any container running a `marketwind.*` module needs `REDIS_URL` set whether or not it uses Redis. It sets `extra="ignore"`, so unrelated keys in `.env` are harmless.

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

`docker compose down` becomes non-destructive. Only `down -v` and `system prune --volumes` can now destroy the database, and both are named in `DEPLOY.md`'s prohibited list. A volume attached to a running container is never pruned regardless. Redis deliberately gets no volume — adding one would imply a durability guarantee the system does not rely on.

**This change orphans any database that already exists.** Switching from an anonymous to a named volume means the next `up` attaches an empty `pgdata`; the old data survives on disk as a dangling anonymous volume, but the stack comes up blank with no explanation offered to whoever is watching. That is harmless on the fresh ECS box this work targets — and *not* harmless on the owner's dev machine, or on any node that has run before. So: the spec asserts this is safe **only** on a node with no existing data, and `DEPLOY.md` §8 plus the progress note carry the one-time recovery for a node that has some — take a `pg_dump` first, or copy the old volume across:

```
docker run --rm -v <old-anon-volume>:/from -v marketwind_pgdata:/to alpine sh -c 'cp -a /from/. /to/'
```

### 3.2 `COMPOSE_FILE` in the environment

`.env.example` gains two lines:

```
COMPOSE_PROJECT_NAME=marketwind
# Report node ONLY — uncomment on the Linux box. Leave commented on dev machines.
#COMPOSE_FILE=docker-compose.yml:deploy/report-node/docker-compose.prod.yml
```

Compose reads both from `.env` in the project directory, so with `COMPOSE_FILE` active, bare `docker compose up -d`, `ps`, `logs`, and `exec` all resolve to the production stack. This is the highest-leverage change in the set: it makes the agent's most natural commands correct by default rather than depending on it reproducing two `-f` flags every time.

**`COMPOSE_FILE` ships commented out, and `DEPLOY.md` §3 makes uncommenting it an explicit, verified step.** Shipping it active would break the owner's Windows dev machine three ways: `COMPOSE_PATH_SEPARATOR` defaults to the OS path separator, so `:` is correct on the box but wrong on Windows (`;`), and the whole value would parse as one nonexistent filename; `make dev` (`Makefile:11`) would silently bring up the *prod* stack including the `backup` sidecar; and `docker-compose.prod.yml:31` uses the required interpolation `${OSS_BUCKET:?…}`, which makes **every** Compose command — including `ps`, `logs` and `config` — hard-fail while `OSS_BUCKET` is unset. The base file's own header promises it "serves local dev verbatim"; shipping this active would quietly end that.

That last point also constrains ordering on the node: `.env` must be fully populated *before* the first Compose command, and `OSS_BUCKET` must be set even though bucket provisioning is out of scope here. `DEPLOY.md` sets it to the intended `mw-deadman` regardless, so Compose resolves; the `backup` sidecar then fails loudly until the bucket exists, which is the documented intent.

**`COMPOSE_PROJECT_NAME` is pinned** because the named volume of §3.1 is `<project>_pgdata`, and the project name otherwise derives from the containing directory. A clone into `/opt/marketwind`, a re-clone landing in `marketwind-1`, or a directory rename would silently attach a *different, empty* volume — defeating the data guardrail precisely when someone is recovering from a problem. Unlike `COMPOSE_FILE`, this is safe and useful everywhere, so it ships active.

Both keys are inert to the application: `Settings` sets `extra="ignore"` (`config.py:44`), so adding them to `.env` cannot break pydantic-settings. (`extra="forbid"` would have made this section a stack-breaker.)

**Constraint this introduces:** commands must be run from the repository root. Compose walks parent directories looking for `docker-compose.yml`, but does **not** walk them looking for `.env` — so from a subdirectory the agent silently gets the dev stack. `DEPLOY.md` states this once, explicitly, and every command block in it assumes that working directory.

### 3.3 One-shot `migrate` service

A new service applies the schema and exits; `app` and `scheduler` gate on its success.

```yaml
  migrate:
    build: .
    command: ["python", "-m", "marketwind.storage.migrate"]
    environment:
      DATABASE_URL: postgresql://marketwind:marketwind@postgres:5432/marketwind
      REDIS_URL: redis://redis:6379/0
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

**`REDIS_URL` is mandatory here even though the migration runner never touches Redis.** `config.py:10` declares `redis_url: str` with no default and instantiates `settings = Settings()` at import time (line 47); `migrate.py:12` imports that module. `.env` is not in the image, so a `migrate` service given only `DATABASE_URL` dies in pydantic validation, never satisfies `service_completed_successfully`, and **blocks `app` and `scheduler` from ever starting** — a fresh box deploying to a dead stack. Verified by reproduction. No `depends_on` on `redis` is needed, since nothing connects.

`restart: "no"` is explicit as future-proofing. (It is not strictly operative today: the prod override sets `restart` per-service, so `migrate` would inherit nothing.)

**This overturns a documented decision** — migrations were "owner-run by design" — so it ships with **ADR-0004** in the same PR (§6). The evidence: the `0006` incident, where a node pulled new code, rebuilt, and lost a morning run because nobody re-ran migrate; and the shift to agent operation, which removes the human who was assumed to remember.

### 3.3.1 Close the silent-success path first

The gate in §3.3 is only worth its weight if a successful exit genuinely means "schema applied". Today it does not.

`migrate.py:14` computes `MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"`. In-container this lands on `/app/migrations` **only because** `python -m` puts the working directory first on `sys.path`, so `marketwind` resolves to `/app/marketwind` rather than the pip-installed copy — and `[tool.setuptools.packages.find]` installs `marketwind*` only, so `migrations/` is absent from `site-packages`. Any shift in resolution (a `working_dir:`, `PYTHONSAFEPATH`, `python -c` instead of `-m`) makes `MIGRATIONS_DIR` nonexistent, `glob` empty, and the runner print `no pending migrations` and **exit 0**. The gate passes, the services start against an empty database, and the failure resurfaces at 07:00.

That is a silent fail blessed by a gate — the exact inversion of this section's purpose, and of the project's standing "obvious fail welcomed, silent fail strongly unwelcomed" rule. So `migrate.py` gains a guard: **if `MIGRATIONS_DIR` does not exist, or contains no `*.sql`, raise and exit non-zero.** Roughly three lines, pinned by a test (§7). This is a prerequisite of §3.3, not an optional extra.

**Shared image tag: rejected.** An earlier draft gave all three build-based services `image: marketwind:local` "so the image is built once". That rationale is wrong — Compose issues one build per build-enabled service regardless of a shared tag; builds 2 and 3 are full layer-cache hits, and without `image:` the identical layers yield one image with three tags anyway, so there is no disk saving either. The only real cost is redundant build-context transfer, which §3.4 addresses directly and better. Dropped as an unjustified touch of two working services (Karpathy ③).

### 3.4 `.dockerignore`

New at repo root, excluding `.git`, `.env`, `.venv`, `**/__pycache__`, `**/*.pyc`, `.pytest_cache`, `marketwind.egg-info`, `docs/`, `tests/`, `deploy/`, `.claude/`. Cuts context-transfer time on every rebuild and keeps `.env` out of the build context — note that `.env` was never *in* the image (the Dockerfile does not COPY it), so this trims the tarball sent to the daemon rather than fixing an image-level leak.

**The `**/` prefixes are load-bearing.** `.dockerignore` patterns are anchored at the context root, so a bare `__pycache__` would miss `marketwind/__pycache__/`, which exists in this repo today. An implementer copying the list verbatim gets the wrong result without them. The root Dockerfile copies only `pyproject.toml`, `marketwind/`, `migrations/` and `citation/`, so none of these exclusions can affect the image. The `backup` sidecar builds from `deploy/report-node` as its own context and is unaffected by a root-level ignore file.

### 3.5 Healthcheck on `app`

The `app` service gains a healthcheck against its existing `GET /health` endpoint, which probes Postgres and Redis and already returns `200` when both are reachable and `503` otherwise (`gateway/app.py`) — exactly the contract a healthcheck needs.

**The probe must be stdlib Python, not `curl`.** The image is `python:3.11-slim`, which ships neither `curl` nor `wget`; a healthcheck reaching for either would fail permanently and report the app as unhealthy forever — precisely the false signal this section exists to eliminate. `urllib.request.urlopen` raises on a 503, so the non-zero exit falls out naturally:

```yaml
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
```

`start_period` is required so the container is not marked unhealthy while uvicorn is still binding. `localhost` is correct inside the container because uvicorn binds `0.0.0.0` (`Dockerfile:32`). The explicit `timeout=4` is redundant with Docker's own `timeout: 5s` but makes the intent legible and fails a beat sooner.

This gives the agent a machine-readable verdict from `docker compose ps` instead of requiring it to read logs and judge — the exact step where the last cutover misdiagnosed a stale log as a live crash-loop, and needed `docker inspect` restart-counts to settle.

### 3.6 Bind Postgres and Redis to loopback on the node

`docker-compose.yml:8-9` and `18-19` publish `5432:5432` and `6379:6379` on **all interfaces**, with credentials `marketwind:marketwind` and no Redis auth. The prod override does not restrict them. The Aliyun security group is currently the only thing between a trivially-guessable Postgres and the public internet.

The prod override gains:

```yaml
  postgres:
    ports: ["127.0.0.1:5432:5432"]
  redis:
    ports: ["127.0.0.1:6379:6379"]
```

Nothing legitimate breaks: inter-service traffic goes over the Compose network by service name, and `deploy/report-node/README.md:15` already establishes SSH tunnelling as the access pattern for reaching the box.

To be accurate about the threat rather than inflating it — Aliyun security groups are enforced in the network fabric, outside the VM, so the well-known "Docker's iptables rules bypass the host firewall" problem does **not** let a container punch through them. This is defence in depth against a security-group misconfiguration, not a live hole. It is also one line per service on a box being rebuilt anyway, which is the cheapest this fix will ever be.

## 4. `DEPLOY.md`

A new **root-level** file. Root placement is a deliberate exception to this project's "keep the root clean" convention: the document's entire purpose is to be found cold by a non-Claude agent that was never told where to look, and discoverability outranks tidiness for that one job. `SHOUTY.md` matches the existing root set (`CLAUDE.md`, `CITATION_CONTRACT.md`, `DECISIONS.md`, `ARCHITECTURE.md`). The name `AGENTS.md` is rejected: it signals general contributor guidance and would collide with `CLAUDE.md`'s declared role.

**Opening.** Addressed directly to its reader — *if you are an agent operating this repository on the deployment box, this is your file* — establishing that it is complete and self-contained, that the compose files are not to be improvised from, and that **any step whose output does not match what is written must stop and report rather than be worked around.**

**Required sections.**

1. **Preconditions** — what must already be true (Docker Engine + Compose v2, `Asia/Shanghai` timezone, SSH git auth, hermes installed and WeChat-authenticated).
2. **Get the code** — SSH clone, *not* HTTPS, with the reason stated so it is not "fixed" back.
3. **Configure** — copy `.env.example`, `chmod 600`, and a table of every variable: which are mandatory, which have working defaults, which only the owner can supply.
4. **Bring the stack up** — the single `docker compose up -d --build` that `COMPOSE_FILE` now makes correct.
5. **Verify** — an ordered gate list, each with its expected output. **Gate 0 is `docker compose config`, run before `up`**: it is the only cheap on-box check that mechanically proves `COMPOSE_FILE` resolved, the merge actually produced `TZ: Asia/Shanghai`, and `OSS_BUCKET` interpolated — the three things §7's hermetic tests structurally cannot cover. Then: `migrate` exited `0`; tables present; the per-service state table below; `check_keys.py` green; the hermes preflight green; `run_once --dry-run --floor-only` passing.

   **The gate list must state the expected state per service, not "all healthy."** Only `postgres`, `redis` and `app` have healthchecks (`scheduler` gains one per §5); `backup` has none and will sit at `running` forever. And `docker compose ps` hides exited containers by default, so `migrate` — which is *supposed* to be gone — will not appear at all; checking it needs `docker compose ps -a`. Left vague, both facts collide with this document's own "stop and report on any mismatch" rule and would abort a perfectly good deploy on a false negative, or send the agent off to "fix" a service whose absence is success.
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

This converts the ADR-0001 fragility — an interpreter living outside the mounted tree — from a mid-report `hermes: not found` into a pre-deploy failure with a named cause.

**A preflight alone does not meet the requirement, though.** The failure this section exists to prevent is the agent upgrading or reinstalling hermes *after* deploy, and a one-shot check before `up` cannot see that. `HERMES_BIN` is touched only at send time (`gateway/im/hermes_weixin.py` is the sole invocation; `factory.py` merely stores the string), so a severed delivery path stays invisible until 07:00. Note also that the `:ro` mount protects nothing here — the agent has root on the *host*, where the real files live.

So the `scheduler` service gains a healthcheck that tests the hermes entrypoint continuously, turning "the agent broke delivery" into a red row in `docker compose ps` within a minute. The floor is `test -x "$HERMES_BIN"`. Better, if available, is a cheap side-effect-free invocation (`--version` or `--help`), because that also exercises the *interpreter* — which is the actual ADR-0001 failure mode, and one that `test -x` cannot see. The plan determines which by checking what the installed hermes supports on the box; it must not assume a flag exists.

By the spec's own §1.1 principle — guardrails over prose wherever they can substitute — this is the load-bearing half of requirement 3, and worth more than the §3.5 `app` healthcheck. The documented half remains the `DEPLOY.md` prohibition on mutating hermes while the scheduler runs.

## 6. Documentation deliverables

Per `CLAUDE.md` §8.6, in the same PR:

- **This spec.**
- **Plan** — `docs/superpowers/plans/2026-08-01-agent-operable-deploy.md`.
- **ADR-0004** — `docs/adr/0004-stack-applies-migrations.md`, recording the overturn of owner-run migrations, its evidence, and what it costs (the stack now assumes it may write schema at boot; a bad migration blocks startup loudly rather than surfacing at first query — the intended trade).
- **`DECISIONS.md`** — a row referencing ADR-0004.
- **Progress note** — `docs/progress/agent-operable-deploy.md`.
- **`docs/GAPS.md`** — G0.2 (*deploy & run the daemon persistently*) is materially advanced but **not closed**; only an actual unattended live run closes it. The note must say exactly that rather than implying closure.

**Two existing documents are invalidated by §3.3 and must be corrected in the same PR** (`CLAUDE.md` §8.6: a PR updates the note it invalidates):

- **`deploy/report-node/README.md`** — §9 ("Apply DB migrations… Nothing runs this automatically") becomes flatly wrong and must be rewritten or removed. Its §5 HTTPS clone is corrected to SSH, and its two-`-f` commands in §8 and line 36 gain a note about `COMPOSE_FILE`.
- **`docs/progress/cloud-cutover-aliyun.md`** — line 15 records "No container runs `migrate` automatically (by design — idempotent, owner-run)", which *is* the decision being overturned, and line 31's "**Standing rule:** a PR that adds a `migrations/*.sql` needs a migrate run on the node" becomes obsolete. Both need updating rather than leaving a note that describes behaviour this PR replaces.

Note on process: "migrations are owner-run" is a *documented* decision (in the two files above), not a numbered `DECISIONS.md` entry — no D-number covers it. ADR-0004 is therefore more process than strictly required, but it is consistent with `CLAUDE.md` §3 and cheap. Its `DECISIONS.md` row sits closest to the resolved-infrastructure block (D-27..D-30).

## 7. Testing

The highest-value test here is **behavioural, not structural**: the §3.3.1 guard in `migrate.py`, which must exit non-zero when `MIGRATIONS_DIR` is missing or empty. That closes a real silent-success path, and it fails on a domain error rather than a structural one. It is the one test that would have caught something.

`pyyaml` is added as a dev dependency for a deliberately short list of structural tests. Keep only those pinning a constraint that is **non-obvious from reading the YAML**, since a test that restates the file it just parsed is tautological — `CLAUDE.md` §2 warns here specifically:

- `postgres` mounts a named volume declared at top level — guards a data-loss guardrail;
- `migrate` sets `REDIS_URL` — pins the §3.3 dead-stack trap, whose whole danger is that it looks unnecessary and invites deletion;
- `app`'s healthcheck test invokes `python` — pins §3.5 so no later edit reintroduces a `curl` probe the image cannot run;
- `.env.example` carries the `COMPOSE_FILE` line, commented, with both files in the correct order.

Dropped from the earlier draft: "a `migrate` service exists", "`app`/`scheduler` gate on it", and "the prod override sets `TZ`". The first two restate the YAML; the third **already passes today** (`docker-compose.prod.yml:16-17`) and so is not a RED at all — an earlier draft claimed every listed test was one, which was simply wrong. If kept anywhere, it is a characterization test explicitly labelled as passing on arrival, so no subagent breaks the prod override trying to manufacture a red.

**The RED must be an assertion, not a `KeyError`.** `compose["services"]["migrate"]` raises `KeyError` against today's files — structurally the same "proves nothing" failure as the `ImportError` that `CLAUDE.md` §8.2 rejects, since it fires identically for a good test and a broken one. Tests must read through `.get(...)` with defaults so the RED surfaces as `assert "migrate" in services`. This is exactly the softening the harness is contractually on the hook for, so the plan states it per-test rather than leaving it to the implementer.

`check_hermes.py` is tested with the stub-executable pattern already established in `deploy/report-node/tests/test_backup_script.py:11-30`, which transfers cleanly.

**Not unit-tested:** Compose's *merge* semantics, which need a live Docker daemon. §4's gate 0 covers this with `docker compose config` on the box, where the merged result is what actually matters.

## 8. Risks

- **`COMPOSE_FILE` is directory-sensitive.** An agent running Compose from outside the repo root gets the dev stack with no warning. Mitigated by stating the working directory once in `DEPLOY.md` and by every command block assuming it; not fully eliminable.
- **`COMPOSE_FILE` ships commented out (§3.2), so the agent must uncomment it** — a step it could skip, which would leave the whole guardrail inert. This is the price of not breaking the Windows dev box, and it is why gate 0 (`docker compose config`) exists: it catches the omission mechanically before `up`, rather than trusting the edit happened.
- **Auto-migration relies on a guard that does not exist yet.** §3.3's gate is only meaningful once §3.3.1 lands; implemented in the wrong order, the gate blesses an empty database. The plan must sequence the guard first.
- **Auto-migration widens boot-time blast radius.** A malformed migration now blocks `app` and `scheduler` from starting rather than failing at first query. This is the intended trade — loud and early over silent and mid-report — and is recorded in ADR-0004.
- **`DEPLOY.md` can rot**, exactly as `deploy/report-node/README.md`'s HTTPS clone did. Partly mitigated by moving traps into guardrails, so there is less prose left to go stale.
- **The agent may not read `DEPLOY.md` at all.** Nothing enforces it. This is why §3 does not depend on it.
