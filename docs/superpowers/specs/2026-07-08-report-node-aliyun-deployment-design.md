# MarketWind report node — Aliyun deployment design (G1.x ops)

> **Read when:** deploying or operating the live MarketWind report node on Aliyun, or debugging why the autonomous morning report did or did not run from the cloud box.

**Status:** design approved 2026-07-08. Supersedes the implicit "runs on the owner's local machine" assumption. The FC dead-man watcher (`deploy/deadman-fc/`, spec `2026-07-07-deadman-fc-watcher-design.md`) is the external monitor for this node.

**Goal:** run the entire MarketWind stack (Postgres, Redis, FastAPI app, autonomous scheduler) 24/7 on a single Aliyun cloud box so the pre-market and 07:00 reports fire and push over WeChat without any local machine turned on.

---

## Why

The owner will not have a local machine powered on at report time (pre-market ≈ US-close+2h, main = 07:00 Asia/Shanghai). The scheduler is a defining feature of this project (CLAUDE.md §6) — it must run on always-on infrastructure. This design moves the existing `docker-compose.yml` stack onto one Aliyun ECS instance in the same region (cn-beijing) as the already-provisioned OSS bucket and FC watcher.

**Non-goals / YAGNI (DECISIONS.md — personal/demo project, not 99% uptime):** no Kubernetes, no multi-node HA, no autoscaling, no managed RDS/Redis (self-hosted in compose is fine at this scale), no load balancer, no ICP 备案 (the app is not served to the public web).

---

## §1 Compute

- **1× Aliyun ECS**, pay-as-you-go, region **cn-beijing** (same region as bucket `mw-deadman` and the FC watcher → free internal OSS traffic, low latency).
- **2 vCPU / 4 GB** (`ecs.e-*` or `ecs.u1` economy family), **40 GB ESSD** system disk.
- **OS:** Alibaba Cloud Linux 3 (or Ubuntu 22.04) — headless, SSH only, no GUI desktop.
- **Docker + Docker Compose plugin**; `systemctl enable docker` so the daemon restarts on reboot.
- **`TZ=Asia/Shanghai`** at the host level AND in the scheduler service — the scheduler's cron is wall-clock; a default-UTC box would fire the reports 8 hours off. This is a correctness requirement, not a preference.
- **Elastic IP (EIP)** bound to the instance so SSH and the FC ping URLs have a stable address.

## §2 Network / security group

- **Inbound:** SSH (22) from the **owner's IP only** (or a narrow range). Everything else denied inbound.
- **App port 8000** is **not** publicly exposed — reach the ConciergeBot/MCP UI via an SSH tunnel (`ssh -L 8000:localhost:8000`). Keeps the follow-up surface private with zero备案 burden.
- **Outbound:** open (needs akshare/data sources, DeepSeek API, hermes/WeChat gateway, Bark, OSS).
- No ICP 备案 required — nothing is served to the public web.

## §3 Services (the stack)

Reuse the existing **4-service `docker-compose.yml` verbatim** (`postgres` 16-alpine, `redis` 7-alpine, `app` FastAPI :8000, `scheduler` autonomous daemon) with two surgical hardening edits:

- Add **`restart: unless-stopped`** to the `app` service (it currently has none; `scheduler` already has it). Survives crashes and host reboots.
- Add **`TZ: Asia/Shanghai`** to the `scheduler` environment (and rely on the host TZ) so cron fires at the intended wall-clock time.

**Secrets** (DeepSeek key, DB password, Bark key, FC ping URLs, hermes dir) live in a **`.env` file on the box, `chmod 600`**, never committed. The owner populates it from `.env.example`.

**WeChat / hermes login (the crux of headless operation):**
- `hermes gateway setup` renders a **terminal QR** over SSH (no GUI needed) — the owner scans it once with their phone.
- Creds persist under the mounted `~/.hermes` (host dir → `${HERMES_HOST_DIR:-./hermes-creds}:/root/.hermes:ro` per the existing compose), so they survive container restarts.
- The **daily clawbot keepalive** (ADR-0002, owner-run inbound activity) keeps the iLink session warm; it is orthogonal to hosting and remains an owner action. Hard expiry (`errcode=-14`) still requires a re-scan — the **FC watcher pages the owner** if a report silently fails to deliver.

## §4 Backup

- A **compose sidecar service `backup`** (in `deploy/report-node/`): a small container running a sleep-loop that once per day runs `pg_dump` → `gzip` → uploads to `oss://mw-deadman/backups/pg/marketwind-<date>.sql.gz`.
- **Auth via the ECS instance RAM role** (no static keys, mirroring the FC design): attach a RAM role to the instance granting `oss:PutObject` scoped to `mw-deadman/backups/*`; `ossutil` picks up the instance-role STS token automatically.
- **OSS lifecycle rule:** expire `backups/pg/` objects after **14 days** (bounded cost, enough to recover from a bad day).
- **Redis is not backed up** — it holds only ephemeral queue/cache state, reconstructible on restart (YAGNI).

## §5 Code delivery — private git remote (chosen)

- Push the repo to a **private git remote** (GitHub private repo or Aliyun Codeup).
- On the box: `git clone` once, then updates are `git pull && docker compose up -d --build`.
- Chosen over rsync because it gives versioned, auditable deploys and a trivial rollback (`git checkout <sha>`), and the box already needs outbound git for nothing else costly.
- **Owner-run step:** creating the private repo and providing push credentials is the owner's action; the harness cannot create the remote. The remote URL is needed before the first push.

## §6 Ops / runbook

- Write an owner-run deploy runbook to **`deploy/report-node/README.md`**: provision ECS → security group → attach instance RAM role → install Docker → clone repo → populate `.env` → `hermes gateway setup` (scan QR) → `docker compose up -d` → verify.
- **Verification** reuses **`docs/runbooks/go-live-smoke.md` Stage 3** (autonomous trigger fires, report generates, WeChat push lands).
- **Monitoring** is the already-built **FC dead-man watcher**: the node's scheduler pings the FC `ping` endpoint on every successful delivery; a missed check-in past `period+grace` pages the owner via Bark. Wire the two ping URLs into the node `.env` after `s deploy`.

---

## Buildable artifacts (what implementation produces)

- `deploy/report-node/` — new directory:
  - backup sidecar `Dockerfile` (ossutil + postgres-client + a sleep-loop `backup.sh`),
  - `backup.sh` (daily `pg_dump | gzip | ossutil cp` to the dated OSS key),
  - a `docker-compose.override.yml` (or documented compose additions) contributing the `backup` service + the `app` `restart:` / `scheduler` `TZ:` hardening,
  - `README.md` owner deploy runbook.
- No changes to report-generation logic — this is pure ops/hosting.

## Accepted non-closure

- A **provider-wide Aliyun outage** taking down both the node and FC at report time fires no page (same bounded watch-the-watcher regress already accepted in the FC watcher spec — a personal system does not chase infinite regress).
- **Hard WeChat session expiry** (`errcode=-14`) still needs an owner re-scan; the FC watcher makes that failure loud rather than silent, which is the contract.
