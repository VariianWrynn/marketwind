# Dead-man's Switch Runbook — second-host liveness watchdog (G1.3)

> **Read when:** provisioning or maintaining the out-of-process watcher that closes the two residual silent-miss windows (W1 "node down & staying down", W2 "push channel down"). This is **owner-run ops**, executed once the second host is available. It does **not** block the daemon-side code, which is already built and tested offline.

**Spec:** `docs/superpowers/specs/2026-07-07-deadman-switch-design.md`.
**Design decisions:** self-hosted Healthchecks on an independent second host; alerts fan out to **email + Bark**, **never WeChat** (W2 is literally "the WeChat channel is down"); per-job checks (`premarket`, `main`); period = 1 day, grace ≈ 2–3 h.

## Operating principle

**The switch converts a silence into a loud external page.** The daemon checks in to Healthchecks **only after it has delivered a message to the owner** (a published report, or a status/heartbeat that actually sent). The absence of a check-in past the deadline is what pages you — from *outside* the node, so it survives a dead node (W1) or a dead push channel (W2). Every choice favors a loud false-positive over a silent miss.

**Scope boundary:** the code (`deadman.py` + the `dispatch_job`/`catch_up`/`run_scheduler` wiring) is buildable and fully tested **now**, offline, without the second host. This runbook is executed later, when the host is provisioned. Until the URLs are set, the switch is simply disabled (empty URL ⇒ no-op) — the daemon runs exactly as before.

**Pre-req:** the report node's daemon is running (`docs/runbooks/go-live-smoke.md` Stage 3 passed) and pushing real reports.

---

## Step 1 — Provision an independent second host

Stand up a **different box** from the report node. A watcher co-located on the report node dies *with* it, defeating the entire purpose (W1). Prefer a different provider/region; a cheap VPS or a home box suffices — the only hard requirement is independent failure.

- **PASS:** a second host reachable from your phone/email, on separate infrastructure from the report node.
- **FAIL (co-located):** **STOP.** A watcher that shares power/network/host with the report node cannot report on that node being down.

---

## Step 2 — Deploy Healthchecks on the second host

Bring up self-hosted Healthchecks as its own docker-compose stack on the second host (its own Postgres, its own web process). Follow the upstream Healthchecks self-host docs. No foreign SaaS (China-reachability + third-party-trust concerns — a locked decision).

- **PASS:** the Healthchecks web UI loads on the second host.

---

## Step 3 — Create the two per-job checks

In the Healthchecks UI, create **two** checks:

| Check name | Period | Grace |
|---|---|---|
| `premarket` | 1 day | 2–3 h |
| `main`      | 1 day | 2–3 h |

The grace absorbs the premarket anchor drift (US close + 2h), the freshness tolerance, and the retry budget — so a late-but-fine run never false-pages. Copy each check's **ping URL** (you set them on the report node in Step 5).

- **PASS:** two checks exist, each period = 1 day / grace 2–3 h, both ping URLs copied.

---

## Step 4 — Wire the alert integrations (email + Bark, never WeChat)

On both checks, attach two integrations for redundancy:

- **Email** → `chishencsz@icloud.com`.
- **Bark** (iOS push) → the owner's Bark server/key, via Healthchecks' webhook integration.

**Never** route these to WeChat/WeCom. W2 is the case where that very channel is down; a page riding it cannot escape.

- **PASS:** each check fans out to email + Bark.

---

## Step 5 — Set the URLs on the report node and restart

On the **report node**, set the two ping URLs in `.env`:

```
HEALTHCHECK_URL_PREMARKET=https://<second-host>/ping/<premarket-uuid>
HEALTHCHECK_URL_MAIN=https://<second-host>/ping/<main-uuid>
```

Restart the daemon so it picks up the new env:

```
docker compose up -d scheduler        # in-container path
# or restart the host-process daemon if using the Windows fallback
```

Empty/unset URLs keep the switch disabled; setting them arms it.

- **PASS:** the daemon restarts cleanly with both URLs set.

---

## Step 6 — Verify both directions

**Direction A — a real check-in turns the check green.** Let one delivered dispatch run (a published report, or force a heartbeat/status that actually sends). Confirm the corresponding check flips to **green (up)** in Healthchecks shortly after delivery.

**Direction B — a silence pages you.** Stop the daemon (or break the push channel) and let the deadline lapse (period + grace). Confirm **both email and Bark fire** for the affected check.

- **PASS:** delivered run → check green ∧ enforced silence past grace → email + Bark both page.
- **FAIL:** if a delivered run does *not* turn the check green, re-check the URL wiring (Step 5) and that delivery actually occurred. If the silence does *not* page, re-check the integrations (Step 4) and the period/grace (Step 3).

---

## What this closes / does not close

**Closes:** W1 (node down & staying down) and W2 (push channel down) — after this, a missing morning report reliably produces an external email + Bark page that does **not** depend on the node or its WeChat channel being alive.

**Does not close (accepted):** if the **second host** is also down at deadline, no page fires (the "watch the watcher" regress — bounded by choosing an independent, more-reliable host; a personal system does not chase infinite regress). A ping lost to a transient network blip while delivery *did* succeed causes a Healthchecks false-page — the *safe* direction (loud, self-corrects next day). Neither is a silent miss of the report itself.
