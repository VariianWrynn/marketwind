# Report-node Aliyun Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the ops artifacts that let the existing MarketWind compose stack run 24/7 on a single Aliyun ECS box, with a nightly Postgres→OSS backup and a headless deploy runbook.

**Architecture:** The base `docker-compose.yml` (postgres, redis, app, scheduler) is left **verbatim** for local dev. A new `deploy/report-node/` directory holds all cloud-only concerns: a production compose override (restart policies + `TZ=Asia/Shanghai` + a `backup` sidecar), a small backup script + its image, and an owner runbook. The backup script is the only behavioral unit and gets real TDD; the Dockerfile/compose/docs are smoke- or config-validated. Backup and the (already-built) FC dead-man watcher both authenticate via ECS/FC **RAM roles** — no static keys.

**Tech Stack:** Docker Compose, POSIX shell (Alpine `sh`), `pg_dump` (postgres:16-alpine), Aliyun `ossutil` (ECS instance RAM role auth), pytest (subprocess-driven shell test).

**Design spec:** `docs/superpowers/specs/2026-07-08-report-node-aliyun-deployment-design.md`

**Cross-task contract (the controller owns these — keep consistent across tasks):**
- Backup script path: `deploy/report-node/backup.sh`, invoked as `sh backup.sh`, runs **one** backup and exits.
- Required env for the script: `DATABASE_URL`, `OSS_BUCKET`; optional `OSSUTIL_AUTH_ARGS` (word-split, may be empty).
- OSS object key (spec-critical literal): `oss://${OSS_BUCKET}/backups/pg/marketwind-$(date +%F).sql.gz`.
- Fail-loud contract: any failure (pg_dump OR upload) → **non-zero exit** ("obvious fail welcomed").
- The daily loop lives in the container `CMD`/compose, NOT in `backup.sh` (keeps the script testable).
- Production override is applied as: `docker compose -f docker-compose.yml -f deploy/report-node/docker-compose.prod.yml ...`.

**Vendor details to CONFIRM at implementation time (do not guess-and-ship — web-search per CLAUDE.md §8.7):**
- Exact `ossutil` download URL + version, and whether the static binary runs on `postgres:16-alpine` (musl). If musl fails, switch the Dockerfile base to `postgres:16` (debian).
- Exact `ossutil` RAM-role auth flags for `OSSUTIL_AUTH_ARGS` (the `--mode EcsRamRole` family). These stay behind the `OSSUTIL_AUTH_ARGS` seam so the tests never depend on them.

---

### Task 1: Backup script (behavioral TDD)

**Files:**
- Create: `deploy/report-node/backup.sh`
- Test: `deploy/report-node/tests/test_backup_script.py`

The test drives `backup.sh` as a subprocess with **fake** `pg_dump` and `ossutil` executables prepended to `PATH`, so it runs fully offline with no Postgres and no network. Requires a POSIX `sh` on PATH (Git Bash provides one on Windows).

- [ ] **Step 1: Write the failing test**

Create `deploy/report-node/tests/test_backup_script.py`:

```python
# deploy/report-node/tests/test_backup_script.py
import datetime
import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "backup.sh"


def _make_stub(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _env_with_stubs(tmp_path, *, pg_dump_rc=0, ossutil_rc=0):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "ossutil_args.txt"
    _make_stub(bin_dir / "pg_dump", f'echo "FAKE DUMP"\nexit {pg_dump_rc}\n')
    _make_stub(bin_dir / "ossutil", f'echo "$@" > "{args_file}"\nexit {ossutil_rc}\n')
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}" + env["PATH"]
    env["DATABASE_URL"] = "postgresql://u:p@postgres:5432/marketwind"
    env["OSS_BUCKET"] = "testbucket"
    env["OSSUTIL_AUTH_ARGS"] = "-e endpoint --mode EcsRamRole --ecs-role-name r"
    return env, args_file


def test_uploads_to_dated_oss_key(tmp_path):
    env, args_file = _env_with_stubs(tmp_path)
    result = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    today = datetime.date.today().isoformat()
    assert f"oss://testbucket/backups/pg/marketwind-{today}.sql.gz" in args_file.read_text()


def test_pg_dump_failure_exits_nonzero(tmp_path):
    env, _ = _env_with_stubs(tmp_path, pg_dump_rc=1)
    result = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert result.returncode != 0


def test_upload_failure_exits_nonzero(tmp_path):
    env, _ = _env_with_stubs(tmp_path, ossutil_rc=1)
    result = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert result.returncode != 0
```

- [ ] **Step 2: Run the test, watch it fail on the discriminating assertion**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q deploy/report-node/tests/test_backup_script.py -v`

Expected: `test_uploads_to_dated_oss_key` **FAILS on an assertion** — `backup.sh` does not exist, so `sh` exits 127 and `assert result.returncode == 0` fails (this is the real RED, not a collection error). Do not proceed until you have seen this assertion fail. (The two `!= 0` failure tests may pass trivially at this point; their discriminating check is Step 5.)

- [ ] **Step 3: Write the minimal script**

Create `deploy/report-node/backup.sh` (no pipe — so `set -e` alone catches a `pg_dump` failure; portable POSIX `sh`):

```sh
#!/bin/sh
# One-shot Postgres backup -> gzip -> OSS. Fails loud (non-zero exit) on ANY error.
# The daily loop lives in the container CMD / compose, not here (keeps this testable).
set -eu

: "${DATABASE_URL:?DATABASE_URL required}"
: "${OSS_BUCKET:?OSS_BUCKET required}"

DATE="$(date +%F)"
REMOTE="oss://${OSS_BUCKET}/backups/pg/marketwind-${DATE}.sql.gz"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

pg_dump "$DATABASE_URL" > "$WORK/dump.sql"
gzip -c "$WORK/dump.sql" > "$WORK/dump.sql.gz"
ossutil cp "$WORK/dump.sql.gz" "$REMOTE" ${OSSUTIL_AUTH_ARGS:-}

echo "backup uploaded: $REMOTE"
```

- [ ] **Step 4: Run the tests, verify all pass**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q deploy/report-node/tests/test_backup_script.py -v`
Expected: 3 passed.

- [ ] **Step 5: Confirm the failure-path tests actually discriminate (retroactive RED)**

The two `!= 0` tests could pass for the wrong reason. Prove they bite: temporarily add a line `pg_dump ... || true` (swallow the failure) after the `pg_dump` line, re-run — `test_pg_dump_failure_exits_nonzero` must now FAIL. Revert the change. (Do the analogous check for `ossutil` if unsure.) This is the mutation check required by CLAUDE.md §8.2.

- [ ] **Step 6: Commit**

```bash
git add deploy/report-node/backup.sh deploy/report-node/tests/test_backup_script.py
git commit -m "feat(deploy): add fail-loud pg_dump->OSS backup script with tests"
```

---

### Task 2: Backup sidecar Dockerfile (smoke)

**Files:**
- Create: `deploy/report-node/Dockerfile`

A Dockerfile is a build artifact, not a behavioral unit — verification is a build smoke test (image builds, required tools present). CONFIRM the `ossutil` URL/version and musl compatibility before relying on it (see the vendor-details note at the top).

- [ ] **Step 1: Write the Dockerfile**

Create `deploy/report-node/Dockerfile`:

```dockerfile
# Backup sidecar for the report node: pg_dump (from the postgres image) + ossutil.
# The build context is deploy/report-node/ (see docker-compose.prod.yml), so
# `COPY backup.sh` resolves to deploy/report-node/backup.sh.
FROM postgres:16-alpine

# ossutil: static Linux amd64 binary. CONFIRM URL/version + musl compatibility at build time;
# if the static binary fails on alpine/musl, change the base image to `postgres:16` (debian).
ARG OSSUTIL_VERSION=1.7.19
RUN apk add --no-cache curl \
 && curl -fsSL -o /usr/local/bin/ossutil \
      "https://gosspublic.alicdn.com/ossutil/${OSSUTIL_VERSION}/ossutil-v${OSSUTIL_VERSION}-linux-amd64" \
 && chmod +x /usr/local/bin/ossutil

COPY backup.sh /usr/local/bin/backup.sh
RUN chmod +x /usr/local/bin/backup.sh

# Daily loop. A single backup failure logs loud to stderr but does NOT kill the loop
# (backups are best-effort; report delivery is the safety-critical path the FC watcher covers).
CMD ["sh", "-c", "while true; do /usr/local/bin/backup.sh || echo 'BACKUP FAILED (see logs above)' >&2; sleep \"${BACKUP_INTERVAL_SECONDS:-86400}\"; done"]
```

- [ ] **Step 2: Build smoke test (requires Docker; this is the one build-time gate)**

Run:
```bash
docker build -t mw-backup-sidecar deploy/report-node
docker run --rm --entrypoint sh mw-backup-sidecar -c "pg_dump --version && ossutil --version"
```
Expected: image builds; both version lines print. If the `ossutil` download 404s or the binary errors under musl, fix per the vendor note (correct URL/version, or switch base to `postgres:16`) and rebuild. If Docker is unavailable in this environment, record that this gate is deferred to the owner's box in the commit message and README, and do not claim it verified.

- [ ] **Step 3: Commit**

```bash
git add deploy/report-node/Dockerfile
git commit -m "feat(deploy): add backup sidecar Dockerfile (postgres-client + ossutil)"
```

---

### Task 3: Production compose override (config validation)

**Files:**
- Create: `deploy/report-node/docker-compose.prod.yml`

Base `docker-compose.yml` stays untouched (surgical — it serves local dev). This override adds the 24/7 hardening and the backup sidecar. `restart: unless-stopped` is added to `postgres`, `redis`, and `app` so a host reboot brings the whole stack back (`scheduler` already has it in the base); `TZ` is added to `scheduler` because its cron is wall-clock. Verification is `docker compose config`, which merges + validates the two files with **no containers** — a real check that needs only the Compose CLI.

- [ ] **Step 1: Write the override**

Create `deploy/report-node/docker-compose.prod.yml`:

```yaml
# Production overrides for the Aliyun report node. Apply on top of the base compose:
#   docker compose -f docker-compose.yml -f deploy/report-node/docker-compose.prod.yml up -d --build
# Base docker-compose.yml is unchanged (it serves local dev verbatim).
services:
  postgres:
    restart: unless-stopped

  redis:
    restart: unless-stopped

  app:
    restart: unless-stopped

  scheduler:
    # Cron is wall-clock; the cloud box must run Asia/Shanghai or reports fire 8h off.
    environment:
      TZ: Asia/Shanghai

  backup:
    build:
      context: deploy/report-node
    environment:
      DATABASE_URL: postgresql://marketwind:marketwind@postgres:5432/marketwind
      OSS_BUCKET: ${OSS_BUCKET:?set OSS_BUCKET in .env}
      OSSUTIL_AUTH_ARGS: ${OSSUTIL_AUTH_ARGS:-}
      BACKUP_INTERVAL_SECONDS: ${BACKUP_INTERVAL_SECONDS:-86400}
      TZ: Asia/Shanghai
    depends_on:
      postgres:
        condition: service_healthy
    restart: unless-stopped
```

- [ ] **Step 2: Validate the merged config**

Run (from repo root; `OSS_BUCKET` satisfies the `:?` guard):
```bash
OSS_BUCKET=testbucket docker compose -f docker-compose.yml -f deploy/report-node/docker-compose.prod.yml config
```
Expected: prints a merged config with **no error**, containing: a `backup` service; `restart: unless-stopped` under `postgres`, `redis`, `app`; and `TZ: Asia/Shanghai` under `scheduler` (alongside its existing env, proving the map merged rather than replaced). If the Compose CLI is unavailable here, record the gate as owner-deferred (as in Task 2) and do not claim it verified.

- [ ] **Step 3: Commit**

```bash
git add deploy/report-node/docker-compose.prod.yml
git commit -m "feat(deploy): add production compose override (restart, TZ, backup sidecar)"
```

---

### Task 4: Env template additions

**Files:**
- Modify: `.env.example` (append a new section at the end)

Document the new deployment env vars as commented lines (no real secrets — this file is committed). The FC ping URLs already have a section in `.env.example`; add a note there that the value now points at the FC endpoint, and add a new report-node section for TZ + backup.

- [ ] **Step 1: Append the report-node section to `.env.example`**

Add at the end of `.env.example`:

```
# --- Aliyun report-node deployment (deploy/report-node/, prod compose override) ---
# TZ=Asia/Shanghai   # host + scheduler + backup timezone; cron is wall-clock, MUST be set on the cloud box.
#
# Nightly Postgres backup sidecar -> OSS. Auth is the ECS INSTANCE RAM ROLE (no static keys):
# attach a role granting oss:PutObject on mw-deadman/backups/* to the ECS instance.
# OSS_BUCKET=mw-deadman
# OSSUTIL_AUTH_ARGS=-e oss-cn-beijing-internal.aliyuncs.com --mode EcsRamRole --ecs-role-name <instance-ram-role>
#   # ^ CONFIRM the exact ossutil RAM-role flags against current ossutil docs before first run.
# BACKUP_INTERVAL_SECONDS=86400
#
# FC dead-man watcher: point the HEALTHCHECK_URL_* vars above at the FC `ping` endpoint from `s deploy`,
# e.g. HEALTHCHECK_URL_PREMARKET=https://<fc-ping-url>?job=premarket  (and ...?job=main for MAIN).
```

- [ ] **Step 2: Verify — vars present, no secrets committed**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q deploy/report-node/tests` (confirms Task 1 still green) and visually confirm `.env.example` contains `OSS_BUCKET`, `OSSUTIL_AUTH_ARGS`, `BACKUP_INTERVAL_SECONDS`, `TZ` — all commented, no real key values.

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "docs(deploy): document report-node TZ + OSS backup env vars"
```

---

### Task 5: Owner deploy runbook

**Files:**
- Create: `deploy/report-node/README.md`

The owner-run provisioning guide. Docs task — verify by reading for completeness and correct cross-references (no code test).

- [ ] **Step 1: Write the runbook**

Create `deploy/report-node/README.md`:

```markdown
# MarketWind report node — Aliyun deploy runbook (owner-run)

Runs the full stack (postgres, redis, app, scheduler) 24/7 on one ECS box so the
pre-market and 07:00 reports fire and push over WeChat with no local machine on.
Design: `docs/superpowers/specs/2026-07-08-report-node-aliyun-deployment-design.md`.
Monitoring is the FC dead-man watcher (`deploy/deadman-fc/`).

## 1. Provision ECS
- Region **cn-beijing** (same as bucket `mw-deadman` + FC watcher → free internal OSS traffic).
- **2 vCPU / 4 GB** (e.g. `ecs.u1`), **40 GB ESSD**, Alibaba Cloud Linux 3 or Ubuntu 22.04, pay-as-you-go.
- Bind an **Elastic IP** for stable SSH.

## 2. Security group
- Inbound: allow **SSH (22) from your IP only**. Deny all other inbound.
- Do NOT expose 8000 publicly. Reach the app via SSH tunnel: `ssh -L 8000:localhost:8000 <user>@<eip>`.
- Outbound: allow all (data sources, DeepSeek, hermes/WeChat, Bark, OSS). No ICP 备案 needed.

## 3. Attach an instance RAM role (backup auth, no static keys)
- Create a RAM role assumable by ECS with a policy granting `oss:PutObject` on
  `acs:oss:*:*:mw-deadman/backups/*`. Attach it to the instance.
- Put its name in `OSSUTIL_AUTH_ARGS` (`--ecs-role-name <role>`) in `.env` (step 6).

## 4. Install Docker
```
# Alibaba Cloud Linux / CentOS-like:
sudo yum install -y docker && sudo systemctl enable --now docker
# Docker Compose plugin: install docker-compose-plugin per Aliyun mirror docs.
sudo timedatectl set-timezone Asia/Shanghai   # cron is wall-clock — required
```

## 5. Get the code (private git remote)
```
git clone https://github.com/VariianWrynn/marketwind.git
cd marketwind
```
Updates later: `git pull && docker compose -f docker-compose.yml -f deploy/report-node/docker-compose.prod.yml up -d --build`.

## 6. Configure secrets
```
cp .env.example .env && chmod 600 .env
```
Fill in: DeepSeek key (`OPENAI_API_KEY`/`OPENAI_BASE_URL`), `BOCHA_API_KEY`, `TZ=Asia/Shanghai`,
`OSS_BUCKET=mw-deadman`, `OSSUTIL_AUTH_ARGS` (internal endpoint + `--mode EcsRamRole --ecs-role-name <role>`),
and the FC ping URLs (`HEALTHCHECK_URL_PREMARKET`/`_MAIN`) once `s deploy` has run.
> CONFIRM the exact `ossutil` RAM-role flags against current ossutil docs before first run.

## 7. Log in to WeChat (headless, one-time)
```
hermes gateway setup   # renders a terminal QR over SSH — scan with your phone
```
Creds persist under the mounted `~/.hermes` and survive restarts. Keep the session warm
with the daily clawbot keepalive (ADR-0002); hard expiry (`errcode=-14`) needs a re-scan —
the FC watcher pages you if a report silently fails to deliver.

## 8. Bring up the stack
```
docker compose -f docker-compose.yml -f deploy/report-node/docker-compose.prod.yml up -d --build
```

## 9. OSS lifecycle (bound backup cost)
In the OSS console for `mw-deadman`, add a lifecycle rule: prefix `backups/pg/`, expire after **14 days**.

## 10. Verify
- Run **`docs/runbooks/go-live-smoke.md` Stage 3** (autonomous trigger → report → WeChat push).
- Confirm a backup object appears: `backups/pg/marketwind-<today>.sql.gz` in `mw-deadman`.
- Confirm the FC watcher received a ping after a successful delivery (state object updated), and
  that a forced silence pages you via Bark.
```

- [ ] **Step 2: Verify cross-references resolve**

Confirm these referenced paths exist: `docs/superpowers/specs/2026-07-08-report-node-aliyun-deployment-design.md`, `deploy/deadman-fc/`, `docs/runbooks/go-live-smoke.md`, `docs/adr/0002-wechat-primary-wecom-backup.md` (ADR-0002). The git clone URL is `https://github.com/VariianWrynn/marketwind.git`.

- [ ] **Step 3: Commit**

```bash
git add deploy/report-node/README.md
git commit -m "docs(deploy): add owner-run Aliyun report-node deploy runbook"
```

---

## Final verification (after all tasks)

- [ ] Run the backup test suite: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q deploy/report-node/tests` → 3 passed.
- [ ] Confirm base `docker-compose.yml` is unchanged: `git diff --stat HEAD~5 -- docker-compose.yml` shows no changes to it (all deltas live in `deploy/report-node/` + `.env.example`).
- [ ] Dispatch a final code review over the whole `deploy/report-node/` addition.
```
