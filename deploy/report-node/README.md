# MarketWind report node — Aliyun deploy runbook (owner-run)

Runs the full stack (postgres, redis, app, scheduler) 24/7 on one ECS box so the
pre-market and 07:00 reports fire and push over WeChat with no local machine on.
Design: `docs/superpowers/specs/2026-07-08-report-node-aliyun-deployment-design.md`.
Monitoring is the FC dead-man watcher (`deploy/deadman-fc/`).

## 1. Provision ECS
- Region **cn-beijing** (same as bucket `mw-deadman` + FC watcher -> free internal OSS traffic).
- **2 vCPU / 4 GB** (e.g. `ecs.u1`), **40 GB ESSD**, Alibaba Cloud Linux 3 or Ubuntu 22.04, pay-as-you-go.
- Bind an **Elastic IP** for stable SSH.

## 2. Security group
- Inbound: allow **SSH (22) from your IP only**. Deny all other inbound.
- Do NOT expose 8000 publicly. Reach the app via SSH tunnel: `ssh -L 8000:localhost:8000 <user>@<eip>`.
- Outbound: allow all (data sources, DeepSeek, hermes/WeChat, Bark, OSS). No ICP filing needed.

## 3. Attach an instance RAM role (backup auth, no static keys)
- Create a RAM role assumable by ECS with a policy granting `oss:PutObject` on
  `acs:oss:*:*:mw-deadman/backups/*`. Attach it to the instance.
- Put its name in `OSSUTIL_AUTH_ARGS` (`--ecs-role-name <role>`) in `.env` (step 6).

## 4. Install Docker
```
# Alibaba Cloud Linux / CentOS-like:
sudo yum install -y docker && sudo systemctl enable --now docker
# Docker Compose plugin: install docker-compose-plugin per Aliyun mirror docs.
sudo timedatectl set-timezone Asia/Shanghai   # cron is wall-clock -- required
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
> CONFIRM the exact ossutil 2.x RAM-role flags against current ossutil docs before first run.

Then verify the external API keys authenticate before building anything (stdlib-only,
no venv needed) — it exits non-zero and prints a FAIL row for any bad/expired key:
```
python3 deploy/report-node/check_keys.py   # checks DeepSeek + Bocha (+ Bark if set)
```

## 7. Log in to WeChat (headless, one-time)
```
hermes gateway setup   # renders a terminal QR over SSH -- scan with your phone
```
Creds persist under the mounted `~/.hermes` and survive restarts. Keep the session warm
with the daily clawbot keepalive (ADR-0002); hard expiry (`errcode=-14`) needs a re-scan --
the FC watcher pages you if a report silently fails to deliver.

## 8. Bring up the stack
```
docker compose -f docker-compose.yml -f deploy/report-node/docker-compose.prod.yml up -d --build
```

## 9. OSS lifecycle (bound backup cost)
In the OSS console for `mw-deadman`, add a lifecycle rule: prefix `backups/pg/`, expire after **14 days**.

## 10. Verify
- Run **`docs/runbooks/go-live-smoke.md` Stage 3** (autonomous trigger -> report -> WeChat push).
- Confirm a backup object appears: `backups/pg/marketwind-<today>.sql.gz` in `mw-deadman`.
- Confirm the FC watcher received a ping after a successful delivery (state object updated), and
  that a forced silence pages you via Bark.
