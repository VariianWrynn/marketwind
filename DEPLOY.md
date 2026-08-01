# DEPLOY.md — deploying and operating MarketWind on the report node

> **Read when:** you are deploying, updating, or operating the stack on the Aliyun ECS
> report node. Not needed for local development (`docker compose up` at the repo root
> covers that).

**If you are an agent operating this repository on the deployment box, this is your file.**
Read it start to finish before running anything. Three rules govern everything below:

1. **This file is complete and self-contained.** Every command you need is written here.
   You do not need to read the compose files, the Dockerfile, or the application source
   to deploy this stack.
2. **Do not improvise from the compose files.** `docker-compose.yml` and
   `deploy/report-node/docker-compose.prod.yml` encode failure modes that cost real
   morning reports to discover. Their comments say which. Do not simplify, inline, or
   "clean up" any of it as part of a deploy.
3. **If a step's output does not match what is written here, STOP and report it.** Do not
   work around it, do not retry with different flags, do not delete the thing that is
   complaining. A mismatch means either the box differs from what this file assumes or
   something is genuinely broken — both need a human. This system publishes financial
   content that its reader acts on with real money; a deploy that "mostly worked" is
   worse than one that stopped.

---

## 1. Preconditions

Confirm all four before starting. If any is missing, that is an escalation (§9), not
something to install your way around.

| Precondition | Check | Expected |
|---|---|---|
| Docker Engine + Compose v2 | `docker compose version` | `Docker Compose version v2.x` |
| Host timezone is `Asia/Shanghai` | `timedatectl \| grep "Time zone"` | `Time zone: Asia/Shanghai` |
| SSH git auth as the repo owner | `ssh -T git@github.com` | `Hi VariianWrynn! You've successfully authenticated` |
| hermes installed and WeChat-authenticated | `ls /root/.hermes/hermes-agent/venv/bin/hermes` | the file exists |

The timezone matters because both report triggers are wall-clock cron. On a UTC box the
reports fire eight hours off, silently and every day.

## 2. Get the code

```
git clone git@github.com:VariianWrynn/marketwind.git
cd marketwind
```

**Use SSH, not HTTPS.** Git over HTTPS is reset on this network — `github.com:443` returns
`Recv failure: Connection was reset` or times out, while SSH on port 22 is reliable
(`CLAUDE.md` §10). If you find an HTTPS clone URL elsewhere in this repo, it is stale; do
not "fix" this line back to `https://`.

## 3. Configure

```
cp .env.example .env && chmod 600 .env
```

**Then uncomment the `COMPOSE_FILE` line in `.env`.** It ships commented out because an
active value breaks local development on the owner's machine. On this box it is required:

```
COMPOSE_FILE=docker-compose.yml:deploy/report-node/docker-compose.prod.yml
```

With it set, a bare `docker compose ...` resolves to the production stack. Every command in
this file assumes that. Without it you get the development stack — which publishes Postgres
and Redis on all interfaces and omits the scheduler's delivery healthcheck — and nothing
will tell you.

**Run every command from the repository root.** Compose walks parent directories looking
for `docker-compose.yml`, but it does **not** walk them looking for `.env`. From a
subdirectory it therefore finds the base compose file, fails to find your `.env`, and
silently brings up the development stack.

Now fill in the values:

| Variable | Who supplies it | What breaks without it |
|---|---|---|
| `OPENAI_API_KEY` | owner (**required**) | every report fails at the DeepSeek call |
| `OPENAI_BASE_URL` | **required**, defaulted to `https://api.deepseek.com` | as above |
| `BOCHA_API_KEY` | owner (**required**) | Scout gathers nothing; the grounded floor never passes |
| `HERMES_HOST_DIR` | **required**, defaulted to `/root/.hermes` | the WeChat credentials are not mounted; delivery fails |
| `HERMES_BIN` | **required**, defaulted to the venv entrypoint | `hermes: not found` mid-report; `scheduler` never goes healthy |
| `TZ` | **required**, `Asia/Shanghai` | both cron triggers fire eight hours off |
| `OSS_BUCKET` | owner (**required**) | see the note below — **every** compose command hard-fails |
| `HERMES_UV_PYTHON_DIR` | defaulted | only override if `uv` placed the interpreter elsewhere (§5, gate 2 tells you) |
| `WEIXIN_TARGET` | defaulted to `weixin` | — |
| `BACKUP_INTERVAL_SECONDS` | defaulted to `86400` | — |
| `OSSUTIL_AUTH_ARGS` | owner | the nightly backup cannot authenticate to OSS |
| `BARK_KEY`, `BARK_BASE_URL` | owner, optional | backup failures and dead-man alerts go nowhere |
| `HEALTHCHECK_URL_PREMARKET`, `HEALTHCHECK_URL_MAIN` | owner, optional | the dead-man watcher cannot detect a silent miss |

**`OSS_BUCKET` must be set even though provisioning the bucket is out of scope for you.**
The prod override declares it as `${OSS_BUCKET:?...}`, and a required-but-unset
interpolation makes Compose refuse **every** command — including read-only ones like
`docker compose ps` and `docker compose config`. An unset value does not merely disable
backups; it makes the stack unoperable. `.env.example` ships `OSS_BUCKET=mw-deadman`, which
is correct for this deployment.

## 4. Bring the stack up

```
docker compose up -d --build
```

The first build is slow — it installs Chromium for Playwright from the npmmirror CDN.

## 5. Verify

Run these in order. Each gate has an expected output; a gate that does not match is a stop.

### Gate 0 — before `up`: prove the merge resolved

```
docker compose config
```

This is the only cheap on-box check that mechanically proves your configuration is what you
think it is. In the output, confirm all three:

- the `backup` service is present — if it is missing, `COMPOSE_FILE` did not take effect and
  you are looking at the development stack;
- `services.scheduler.environment.TZ` is `Asia/Shanghai`;
- `services.backup.environment.OSS_BUCKET` shows a real bucket name, not an error.

If the command itself errors with `required variable OSS_BUCKET is missing`, return to §3.

### Gate 1 — external API keys authenticate

```
python3 deploy/report-node/check_keys.py
```

Expected: `ALL CHECKS PASSED`. `Bark` may show `SKIP`; that is fine and never fails the run.
Any `FAIL` row names the key that is wrong or expired — that is an escalation (§9).

### Gate 2 — the WeChat delivery path resolves

```
python3 deploy/report-node/check_hermes.py
```

Expected: `ALL CHECKS PASSED` across `HERMES_BIN`, `venv interpreter`, and
`interpreter under mount`. This runs before the containers matter, and it exists because
the alternative is discovering the same problem as `hermes: not found` in the middle of the
07:00 report. If `interpreter under mount` fails, its detail line prints the directory the
interpreter actually resolves to — put that value in `HERMES_UV_PYTHON_DIR` in `.env` and
re-run.

### Gate 3 — every service is in its expected state

```
docker compose ps -a
```

Match this table **exactly**:

| Service | Expected state | Note |
|---|---|---|
| `postgres` | `Up (healthy)` | |
| `redis` | `Up (healthy)` | |
| `migrate` | `Exited (0)` | **Only visible with `-a`.** Its absence from a plain `docker compose ps` is success, not a fault |
| `app` | `Up (healthy)` | |
| `scheduler` | `Up (healthy)` | healthy ⇒ the hermes entrypoint *and* its interpreter resolve |
| `backup` | `Up` | has no healthcheck; it logs failures until the OSS bucket exists, which is the documented intent |

**"Everything healthy" is not the criterion.** `backup` has no healthcheck and will never
report healthy, and `migrate` is *supposed* to be gone. Match the table, not a vibe.

### Gate 4 — the schema is applied

```
docker compose exec postgres psql -U marketwind -d marketwind -c '\dt'
```

Expected: the listing includes `run_ledger` and `schema_migrations`. Migrations are applied
by the `migrate` service on every `up`; `app` and `scheduler` are blocked from starting
until it exits 0 (ADR-0004), so if you got past gate 3 this gate should be a formality.

### Gate 5 — the pipeline reaches live data

```
docker compose exec scheduler python -m marketwind.scheduling --floor-only
```

Expected: one line of the form `grounded=<n> primary=<n> outlets=<n> passed=<True|False>`.
This probes the grounded floor and exits; it burns zero DeepSeek tokens.

**What this gate proves is that the line printed at all** — that the container reaches
Postgres, reaches the data sources through the China network, and loads its configuration.
`passed=False` and a non-zero exit are a statement about today's available sources, not
about your deploy. A traceback, however, is a stop.

## 6. Routine operations

**Update and redeploy.**

```
git pull
docker compose up -d --build
```

Migrations apply automatically on every `up`, so a deploy that adds files under
`migrations/` needs no separate step. (This was not always true — older notes in this repo
describe a manual `exec app python -m marketwind.storage.migrate`. That step is obsolete.)

**Read the logs.**

```
docker compose logs -f scheduler        # the daemon that produces and sends reports
docker compose logs --tail=100 backup   # nightly Postgres dump to OSS
```

**Restart one service.**

```
docker compose restart scheduler
```

**Inspect the database.**

```
docker compose exec postgres psql -U marketwind -d marketwind
```

## 7. Prohibited operations

Do not run any of these. Each has caused, or would cause, unrecoverable loss.

| Command | Consequence |
|---|---|
| `docker compose down -v` | Destroys the `pgdata` volume — the entire run ledger and report history. Plain `docker compose down` is safe; the `-v` is what kills it |
| `docker system prune` (any form, any flag) | Same outcome by a different route, and it will look like routine cleanup in your logs |
| `cat .env`, `echo $OPENAI_API_KEY`, committing `.env` | Leaks live API keys and, through them, billable spend |
| Writing anything under `/root/.hermes` | That directory is the live WeChat session, not scratch space |
| Upgrading, reinstalling, or re-running `hermes gateway setup` while the scheduler runs | Severs delivery. **You are running on the same hermes install the scheduler shells out to.** Escalate before touching it |
| `--send-real` without explicit owner instruction | Pushes to the owner's real WeChat |
| Loosening the freshness ceiling to force an off-hours run | Publishes stale data as current. `--force-fresh` is the designed override and keeps the verifier gate; use it instead |

## 8. When something is wrong

| Symptom | Diagnostic | Fix |
|---|---|---|
| `scheduler` crash-loops with `UndefinedTableError: relation "run_ledger" does not exist` | `docker compose ps -a` — did `migrate` exit 0? | It did not. Read `docker compose logs migrate`. Do **not** create tables by hand |
| `Executable doesn't exist at .../chrome-headless-shell` | `docker compose exec scheduler ls <the directory the error names>` | Chromium did not install during the build — the browser binary comes from the npmmirror CDN and that step can fail on a flaky network. Rebuild: `docker compose build --no-cache scheduler` |
| `FileNotFoundError: '/app/citation/rationalization-table.md'` | `docker compose exec scheduler ls /app/citation` | The image predates `COPY citation`. You are building from a stale branch — rebuild from `master` |
| `hermes: not found`, or delivery fails | `python3 deploy/report-node/check_hermes.py` | Follow the failing row's detail (§5, gate 2) |
| `scheduler` unhealthy **but** `check_hermes.py` is green | `docker compose exec scheduler ls -l $(dirname $HERMES_BIN)` | The venv layout differs from the assumed `<venv>/bin/python`. **Report this — do not delete the healthcheck.** It is the only continuous proof that delivery works |

**One-time note for a node that already held data before the named-volume change.** Earlier
versions of `docker-compose.yml` gave Postgres an anonymous volume. Moving to the named
`pgdata` volume attaches a fresh, empty one; the old data is orphaned, not deleted. Take a
`pg_dump` first, or copy the old volume across:

```
docker run --rm -v <old-anon-volume>:/from -v marketwind_pgdata:/to alpine sh -c 'cp -a /from/. /to/'
```

On a fresh box this does not apply.

## 9. Escalate to the owner

These are human-only. Stop and report; do not attempt them.

- **Secret values** — API keys, tokens, anything that goes in `.env` as a credential.
- **The `hermes gateway setup` QR scan** — requires a phone to scan a terminal QR code.
- **The daily WeChat keepalive** — the iLink session goes cold after roughly 24 hours with
  no inbound message, and a proactive push then fails. Keeping it warm is a manual owner
  task (ADR-0002); there is no automated warmer.
- **Aliyun console work** — the instance RAM role, creating the OSS bucket, and its 14-day
  `backups/pg/` lifecycle rule.
- **Flipping `REPORT_DEV_LABEL` to `false`** — that removes the DEV/UNVERIFIED prefix from
  published reports. Owner decision, made after eyeballing a verified report.

---

**Relationship to other docs.** `deploy/report-node/README.md` is the owner-facing
*provisioning* guide: ECS sizing, security groups, the RAM role, the OSS bucket and its
lifecycle rule. It covers building the box; this file covers deploying and operating the
stack on a box that already exists. The two are linked, not duplicated.
