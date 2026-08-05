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
git clone git@github.com:VariianWrynn/marketwind.git
cd marketwind
```
SSH, not HTTPS: this network resets `git`-over-HTTPS to `github.com:443` (`CLAUDE.md` §10).
Do not "fix" this back to an `https://` remote.

Updates later: `git pull && docker compose -f docker-compose.yml -f deploy/report-node/docker-compose.prod.yml up -d --build`.
> With `COMPOSE_FILE` uncommented in `.env`, a bare `docker compose up -d --build` is
> equivalent to the two-`-f` form spelled out here. See `DEPLOY.md` §3.

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
Creds persist under the mounted `~/.hermes` and survive restarts.

> **Owner responsibility — re-scan when a send fails `errcode=-14`** (see
> [ADR-0005](../../docs/adr/0005-ilink-session-expiry-model-corrected.md), which corrects the
> daily-keepalive instruction ADR-0002 assumed). Two separate things expire here, and only
> one of them is an owner task:
>
> - **Per-peer `context_token` — self-healing, no keepalive needed.** On `errcode=-14` the
>   adapter clears the stale token and retries the send **tokenless**, which iLink accepts
>   (`gateway/platforms/weixin.py` `_send_text_chunk`). Cron-initiated pushes therefore
>   survive a cold session with no recent inbound message. A daily keepalive refreshes only
>   this token — i.e. the one thing that no longer needs refreshing.
> - **The QR bot token (`WEIXIN_TOKEN`) — not self-healing.** It is written only by
>   `hermes gateway setup` on QR confirmation and is never refreshed by inbound traffic.
>   Once iLink kills it, even a tokenless send returns `errcode=-14 session timeout`, and
>   the only fix is a re-scan: `hermes gateway setup`.
>
> Upstream publishes no session TTL. Observed on this deployment: the token minted
> 2026-06-05 still authenticated on 2026-06-08 and was dead by 2026-08-05 after ~58 idle
> days — so the lifetime is **days-to-weeks, not hours**, with the upper bound unmeasured.
> `hermes send` does **not** need a running Gateway: it resolves `WEIXIN_TOKEN` /
> `WEIXIN_ACCOUNT_ID` from `~/.hermes/.env` and opens its own iLink session, so upstream
> issue #14452 (process isolation) does not apply to hermes_agent 0.15.2.

> ⚠ **WeChat is the ONLY delivery route — a dead session means no report that day.**
> `WECOM_WEBHOOK_URL` is deliberately left unset (ADR-0005 rejected option A), so the fallback
> slot holds an `UnconfiguredSink`. It reports `ok=False` instead of discarding silently, which
> makes the failure loud: the run records `FAILED_INFRA` in the ledger, and since the status
> message cannot be delivered either, the node never checks in and **the FC dead-man pages you
> over Bark**. You will not get the report, but you will always find out. Recovery is the
> re-scan above. Setting `WECOM_WEBHOOK_URL` later would let the day's report survive a dead
> session (gap **G1.5**) — a delivery upgrade, not a fix for the alerting, which works now.

## 8. Bring up the stack
```
docker compose -f docker-compose.yml -f deploy/report-node/docker-compose.prod.yml up -d --build
```
> Same as above: with `COMPOSE_FILE` set in `.env`, bare `docker compose up -d --build` works.

## 9. DB migrations — applied automatically (ADR-0004)
No manual step. A one-shot `migrate` service applies `migrations/*.sql` on every `up`, and
`app`/`scheduler` do not start until it exits `0`. A deploy that adds migration files needs
only `git pull && docker compose up -d --build`.

The manual invocation remains available for a targeted re-run (idempotent, safe):
```
docker compose -f docker-compose.yml -f deploy/report-node/docker-compose.prod.yml exec app python -m marketwind.storage.migrate
```
To confirm the schema landed, check `migrate` exited 0 — it is only visible with `-a`, since
a successful one-shot service is absent from a plain `docker compose ps`:
```
docker compose ps -a       # migrate -> Exited (0)
```

## 10. OSS lifecycle (bound backup cost)
In the OSS console for `mw-deadman`, add a lifecycle rule: prefix `backups/pg/`, expire after **14 days**.

## 11. Verify
- Run **`docs/runbooks/go-live-smoke.md` Stage 3** (autonomous trigger -> report -> WeChat push).
- Confirm a backup object appears: `backups/pg/marketwind-<today>.sql.gz` in `mw-deadman`.
- Confirm the FC watcher received a ping after a successful delivery (state object updated), and
  that a forced silence pages you via Bark.
