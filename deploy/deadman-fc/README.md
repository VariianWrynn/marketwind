# Dead-man's Switch — FC Watcher Deploy Runbook

> This is the **production replacement** for the local Healthchecks rehearsal
> (`docs/runbooks/deadman-switch.md`). Same two-direction liveness guarantee,
> no second host required — Aliyun Function Compute is the independent executor.

**Pre-req:** the report-node daemon is running and pushing real reports
(`docs/runbooks/go-live-smoke.md` Stage 3 passed).

---

## Environment variables

| Variable | Description |
|---|---|
| `OSS_BUCKET` | Private OSS bucket name (e.g. `mw-deadman-state`) |
| `OSS_ENDPOINT` | OSS internal or public endpoint for the bucket's region |
| `FC_SERVICE_ROLE_ARN` | RAM role ARN granted to both FC functions (read/write on bucket) |
| `BARK_BASE_URL` | Base URL of your Bark server (e.g. `https://api.day.app`) |
| `BARK_KEY` | Bark device key |

**Secrets are never committed.** Export all variables in your shell before running `s deploy`.

---

## Steps

### Step 1 — Create a private OSS bucket in a domestic region

Create an OSS bucket (e.g. `mw-deadman-state`) in the same domestic region as your FC
deployment (e.g. `cn-hangzhou`). Set ACL to **private**.

- **PASS:** bucket exists, ACL is private, region matches the `vars.region` in `s.yaml`.
- **FAIL:** public bucket or cross-region mismatch — **STOP**, fix before continuing.

---

### Step 2 — Create and assign the FC service RAM role; export its ARN

Create a RAM role with a **Function Compute** trust policy. Attach an inline policy granting
`oss:GetObject`, `oss:PutObject`, `oss:DeleteObject` on `acs:oss:*:*:<OSS_BUCKET>/*` and
`acs:oss:*:*:<OSS_BUCKET>`.

```bash
export FC_SERVICE_ROLE_ARN="acs:ram::<account-id>:role/<role-name>"
```

- **PASS:** the role exists, trust policy allows `fc.aliyuncs.com`, bucket policy is attached, ARN exported.
- **FAIL:** trust policy missing or wrong service principal — the runtime `context.credentials` will not be issued; Bark pushes will silently fail to write state.

---

### Step 3 — Export the remaining secrets

```bash
export OSS_BUCKET="mw-deadman-state"
export OSS_ENDPOINT="https://oss-cn-hangzhou-internal.aliyuncs.com"   # use internal endpoint inside FC
export BARK_BASE_URL="https://api.day.app"
export BARK_KEY="<your-bark-key>"
```

- **PASS:** all five variables set; `echo $BARK_KEY` prints the key (non-empty).

---

### Step 4 — Deploy with `s deploy`

```bash
cd deploy/deadman-fc
s deploy --use-local -y
```

- **PASS:** both `deadman-ping` and `deadman-check` show `deployed` in the output; FC console lists both functions with their triggers active.
- **FAIL:** schema mismatch or missing variable — read the `s` error, check the schema note at the top of `s.yaml`, and confirm against the installed `s`/`fc3` version (`s --version`).

---

### Step 5 — Wire the ping URLs into the report node

Copy the two HTTP-trigger URLs from the `s deploy` output (or the FC console) into the report
node's `.env`:

```
HEALTHCHECK_URL_PREMARKET=https://<ping-trigger-url>?job=premarket
HEALTHCHECK_URL_MAIN=https://<ping-trigger-url>?job=main
```

Restart the daemon:

```bash
docker compose up -d scheduler
```

- **PASS:** daemon restarts cleanly; both env vars are non-empty.

---

### Step 6 — Verify both directions

**Direction A — check-in turns the state green.**
Let one delivered dispatch run (published report or forced heartbeat). Immediately after:

```bash
# using oss2 CLI or FC console object browser
# confirm state/premarket.json (or state/main.json) has a fresh last_ping timestamp
```

**Direction B — silence pages you.**
Temporarily set `GRACE_SECONDS` to a small value (e.g. `60`), redeploy, wait for the next
hourly `check` invocation, confirm a single Bark push fires. Then restore `GRACE_SECONDS`
to `10800` and redeploy.

- **PASS:** Direction A → `state/<job>.json` updated with a `last_ping` within seconds of delivery.
  Direction B → exactly one Bark push fires; `alerted` flag in the state object flips to `true`
  and no second push fires until the flag is reset by a fresh ping.
- **FAIL (Direction A):** URL wiring wrong or daemon did not deliver — check Step 5 and daemon logs.
- **FAIL (Direction B):** Bark push missing — check `BARK_KEY`/`BARK_BASE_URL` env vars and the
  `check` function's invocation logs in the FC console.
