# Dead-man's switch — out-of-process liveness watchdog (G1.3 / P2b item E)

> **Read when:** working on the check-in path, the second-host Healthchecks watcher, or investigating why a missing morning report did (or did not) page the owner externally.

**Status:** daemon-side code complete + tested offline, 2026-07-07. **Production watcher = the Aliyun FC serverless watchdog** (spec `docs/superpowers/specs/2026-07-07-deadman-fc-watcher-design.md`, code `deploy/deadman-fc/`, deploy `deploy/deadman-fc/README.md`) — built + tested offline (17 tests). The local Healthchecks run below was a **rehearsal**, not the deployed watcher; it superseded the original second-host Healthchecks plan. Owner-run deploy is deferred — the switch is disabled (empty URL ⇒ no-op) until the owner sets the `ping` URLs. Daemon spec: `docs/superpowers/specs/2026-07-07-deadman-switch-design.md`. Plan: `docs/superpowers/plans/2026-07-07-deadman-switch.md`.

**What it delivers:** the daemon checks in to an external Healthchecks watchdog **iff it delivered a message to the owner**. The *absence* of a check-in past the deadline becomes a loud email + Bark page that originates **outside** the node — the only design that can report on a dead node (W1) or a dead push channel (W2).

## What was done, by task

| Task | Module | What it does | Commit |
|---|---|---|---|
| 1 | `scheduling/deadman.py` + `tests/scheduling/test_deadman.py` | `check_in(url, *, post=_http_post)`: empty/None URL → no-op; else best-effort ping that swallows + loudly logs every error, never raising into the caller. `_http_post` = stdlib `urllib.request.urlopen` (`# pragma: no cover`); `post` injectable for offline tests. | `18bf8b1` |
| 2 | `config.py` + `tests/scheduling/test_config_p2a.py` | `healthcheck_url_premarket` / `healthcheck_url_main`, default `""` (disabled). | `39356f7` |
| 3 | `scheduling/dispatch.py` (`dispatch_job`) + tests | `if inserted: check_in(healthcheck_url)` placed immediately after the existing status-send. One line realizes the whole §2 contract. | `60ea3f9` |
| 4 | `scheduling/dispatch.py` (`catch_up`) + tests | Routes the per-job URL into today's boot delegation; the past-date `missed` reconciliation never pings. | `c97e91e` |
| 5 | `scheduling/__main__.py` (`run_scheduler`) | Builds the `{premarket, main}` URL dict from settings; threads it into `catch_up` + each cron `_dispatch`, mirroring `label_prefix`. `main()` leaves URLs unset. | `b7bc7ea` |
| 6 | `docker-compose.yml`, `.env.example` | `HEALTHCHECK_URL_PREMARKET` / `HEALTHCHECK_URL_MAIN` env passthroughs (default empty). | `5de11b1` |
| 7 | `docs/runbooks/deadman-switch.md` | Owner-run six-step provisioning runbook (independent host → Healthchecks → two checks → email/Bark → set URLs → verify both directions). | `cc4c49e` |

## Key invariants proved here

- **Ping iff a message reached the owner (the crux, §2).** The only two things that suppress a check-in are exactly W1 (nothing ran) and W2 (nothing delivered). A *delivered* `failed_infra`/status/skip still pings — it proves the node is alive and the channel works, and the owner already got the loud message the normal way, so the switch must not *also* fire.
- **W2 needs no branch.** On total channel failure `send_with_fallback` **raises**; because the ping is placed strictly *after* the send, the raise propagates before `check_in` is reached → no ping → the watchdog pages. (`test_both_channels_down_does_not_ping` — the assertion that matters most.)
- **Best-effort, biased to false-page over silent-miss.** `check_in` never raises into `dispatch_job`; a ping lost while delivery succeeded causes a Healthchecks false-page — the safe direction (loud, self-corrects next day). No retries/jitter/circuit-breaker (YAGNI).
- **Disable gate.** Empty URL ⇒ no-op, so offline tests / `--dry-run` / local / the manual `main()` entrypoint never ping.
- **Past-date reconciliation never pings.** `catch_up`'s direct `missed` writes are reconciliation records, not today's live delivery — a missed past day must not satisfy today's external deadline.

## How to test

```bash
PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/scheduling
```

Offline, no live network: `check_in` takes an injectable `post`; the `dispatch_job`/`catch_up` send path is stub-driven. 73 scheduling tests green (incl. `test_deadman.py`, the four `dispatch_job` ping-contract tests, and the two `catch_up` routing/no-ping tests).

## Live rehearsal — real Healthchecks, real HTTP path (2026-07-07)

Closed the one seam the offline tests can't reach: the `# pragma: no cover` `_http_post` → real Healthchecks ingest → status transition. Stood up self-hosted Healthchecks in Docker on this machine (`docker.1ms.run/healthchecks/healthchecks:latest`, sqlite, port 8001), created the two per-job checks (`premarket`/`main`, period 1 day / grace 3 h) via the Django ORM, and drove the **actual production `check_in()`** — not a mock — against it.

| Direction | Action | Result |
|---|---|---|
| **A — delivered run → green** | `check_in('http://localhost:8001/ping/<premarket-uuid>')` (real urllib POST) | `premarket`: `new → up`, `n_pings=1`; untouched `main` stayed `new` (clean control) |
| **B — silence → down** | backdate `last_ping` past timeout+grace, recompute `alert_after` | `get_status()` → `down` (the state that fires email + Bark) |

The container was a **co-located throwaway** (torn down + volume removed after) — it proves the mechanism, it is **not** the production watcher. A watcher on the report node dies *with* it and cannot cover W1; the real deployment must be off-node (see runbook / deployment decision below).

Environment notes for anyone repeating this: Docker Hub is unreachable from here (GFW) — use the `docker.1ms.run` mirror. In Git Bash, prefix any `docker` command that has leading-slash container paths with `MSYS_NO_PATHCONV=1`, else MSYS rewrites `/data/hc.sqlite` → `C:/Program Files/Git/data/...`. Healthchecks `timeout`/`grace` are `DurationField`s — assign `timedelta`, not int seconds.

## Out of scope / deferred

- **Aliyun FC watcher deploy** — owner-run ops, `deploy/deadman-fc/README.md` (OSS bucket + RAM role + Bark key + `s deploy` + wire the two `ping` URLs). This is the production replacement for the second-host Healthchecks plan; the code ships and is testable without it.
- **Accepted non-closure:** a provider-wide Aliyun outage taking down FC at deadline fires no page (bounded watch-the-watcher regress; FC's managed multi-AZ is an independent failure domain from the single node, which is what W1 requires — a personal system does not chase infinite regress).
