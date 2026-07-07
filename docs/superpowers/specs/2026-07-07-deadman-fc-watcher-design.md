# Dead-man's switch watcher — Aliyun FC serverless implementation (G1.3)

> **Read when:** building, deploying, or changing the *external watcher* that receives the daemon's liveness check-ins and pages the owner when one goes missing. For the **daemon-side** check-in path (`deadman.check_in`, `dispatch_job` wiring) read `2026-07-07-deadman-switch-design.md` — that side is unchanged by this spec.

**Status:** design approved (2026-07-07 brainstorm). Scope: the **watcher only** — the receiving end of the check-in contract. The daemon-side code (already built + tested offline, see `docs/progress/deadman-switch.md`) is untouched.

**Goal:** implement the out-of-process watchdog as two small Aliyun Function Compute (FC) functions plus one OSS bucket, so the *absence* of a daily check-in becomes a Bark push that originates outside the report node — closing W1 (dead node) and W2 (dead push channel) without a second physical host.

**Through-line — "Obvious fail welcomed, silent fail strongly un-welcomed."** The watcher's sole purpose is to convert a silence (no check-in) into a loud external page. Every choice favors a loud false-positive over a silent miss.

---

## 0. Supersession — what this changes and why

This spec **supersedes the watcher-implementation decisions** locked in `2026-07-07-deadman-switch-design.md` §26–30 and the procedure in `docs/runbooks/deadman-switch.md`. It does **not** touch that spec's §2 check-in contract or §3 daemon code, which remain in force.

| Original decision (2026-07-07 spec) | Superseded by | Rationale |
|---|---|---|
| Watcher = self-hosted **Healthchecks** | Custom **FC functions** (`ping` + `check`) | Healthchecks is a stateful always-on Django+DB app — wrong shape for serverless; a purpose-built ~60-line watcher is simpler and cheaper. |
| **Second host** (a different box) | **Aliyun FC** serverless | Owner has no independent second machine. FC's managed multi-AZ runtime is a distinct failure domain from the single report node — it honors the *intent* (independent failure domain from the node), which is what W1 requires. |
| Alert fan-out = **email + Bark**, both | **Bark only** | Bark is the owner's existing independent iOS-push channel. Email/SMTP adds a credential + config surface for marginal redundancy on a personal project. |
| "No **foreign SaaS**" | *(unchanged — honored)* | Aliyun FC is domestic; this decision still holds. |

**No DECISIONS.md ADR is affected** — the superseded items were spec-local brainstorm decisions, not project-wide ADRs. This section is the audit trail. On approval, a supersession banner is added to the old spec + runbook, and `docs/GAPS.md` G1.3 + `docs/progress/deadman-switch.md` are updated to name the FC watcher as the production path.

**Accepted independence caveat:** if the report node also runs on Aliyun, FC and the node share a *provider*. They do not share a host, VM, process, or AZ, so W1 (this node dies) is still covered; only a provider-wide Aliyun outage escapes — the same bounded "watch-the-watcher" limit the original spec already accepted.

---

## 1. The contract this watcher must satisfy (inherited, unchanged)

From `2026-07-07-deadman-switch-design.md` §2: the daemon pings a per-job URL **iff a message actually reached the owner** that day. The watcher's job is the mirror image:

> For each job, if a check-in ping has **not** arrived within `period + grace` of the last one, page the owner via Bark — **unless the job has never checked in** (not yet armed).

Two jobs, each independently guaranteed: `premarket` and `main`. Period = 1 day, grace ≈ 3 h (absorbs the premarket anchor drift + freshness tolerance + retry budget; a late-but-fine run never false-pages).

---

## 2. Architecture

```
          report node daemon
                 │  GET …/ping?job=premarket   (only after a delivered outcome)
                 ▼
   ┌───────────────────────────┐         ┌──────────────────────────┐
   │  FC function: ping        │  write  │  OSS bucket              │
   │  (HTTP trigger, anon)     │────────►│  state/premarket.json    │
   └───────────────────────────┘         │  state/main.json         │
                                         └──────────────────────────┘
   ┌───────────────────────────┐  read           ▲
   │  FC function: check       │─────────────────┘
   │  (timer trigger, hourly)  │  if overdue & not alerted ─► Bark push ─► owner's phone
   └───────────────────────────┘
```

Two single-purpose functions sharing one OSS bucket. The daemon never judges "am I dead"; that judgment lives entirely in `check`, outside the node.

---

## 3. Repository layout — `deploy/deadman-fc/` (self-contained)

Kept **out of** the `marketwind` package: FC zips and deploys this directory independently, and it must not import the app. Files that change together live together, including its own tests.

| File | Responsibility |
|---|---|
| `s.yaml` | Serverless Devs manifest: FC service, `ping` (HTTP trigger, `authType: anonymous`), `check` (timer trigger, hourly cron), env vars, RAM-role reference. |
| `watcher/config.py` | Pure config from env: bucket, endpoint, `JOBS` list, `PERIOD_SECONDS`, `GRACE_SECONDS`, `BARK_BASE_URL`, `BARK_KEY`. One `load()` returning a frozen dataclass. |
| `watcher/state.py` | OSS state I/O: `read_state(client, bucket, job) -> State | None`, `put_ping(client, bucket, job, now)`, `mark_alerted(client, bucket, job)`. OSS client injected (real `oss2` in prod, dict-backed fake in tests). |
| `watcher/bark.py` | `send_bark(cfg, title, body, *, post=<default http post>)` — builds the Bark URL/payload, best-effort POST, injectable poster. |
| `watcher/ping_handler.py` | FC HTTP entrypoint `handler(event, context)`: parse `job` from query, validate against `JOBS`, `put_ping`, return 200; unknown/missing job → 400. |
| `watcher/check_handler.py` | FC timer entrypoint `handler(event, context)`: for each job run the deadline logic (§5); alert via `bark`. |
| `tests/` | Offline unit tests (dict-backed fake OSS, injected Bark poster). |
| `README.md` | Owner deploy + verify runbook (§8). |

Each unit is independently testable: given its inputs and injected clients, its behavior is fully determined without touching Aliyun.

---

## 4. Data model — OSS state object

One object per job at key `state/<job>.json`:

```json
{"last_ping": "2026-07-07T05:24:15+00:00", "alerted": false}
```

- `last_ping` — ISO-8601 UTC timestamp of the most recent check-in.
- `alerted` — `true` once a missed-deadline Bark has fired for the *current* silence; reset to `false` by the next successful ping. Prevents hourly re-paging.
- **Missing object ⇒ "not yet armed"** — the job has never checked in; `check` must **not** alert (mirrors Healthchecks' `new` status; prevents a fresh-deploy false page before the node has ever pinged).

`State` is a small frozen dataclass `{last_ping: datetime, alerted: bool}`; `read_state` returns `None` when the object is absent.

---

## 5. Behavior

### 5.1 `ping` handler
1. Read `job` from the HTTP event's query string.
2. If `job` not in `JOBS` → return **400** (loud fail; no silent accept of a typo'd job).
3. `put_ping(job, now_utc)` → writes `{last_ping: now, alerted: false}` (a new ping always clears a stale `alerted`).
4. Return **200**.
5. On OSS write error → return **500** and log loudly. (The daemon's `check_in` swallows the non-200, so a failed write just means the deadline isn't refreshed → the safe direction: it trends toward a page, never toward false silence.)

### 5.2 `check` handler (hourly, no input from node)
For **each** job in `JOBS`, independently (one job's error never blocks another):
```
state = read_state(job)
if state is None:            # not armed → never checked in
    continue                 # no alert
deadline = state.last_ping + PERIOD_SECONDS + GRACE_SECONDS
if now_utc <= deadline:      # healthy
    continue
if state.alerted:            # already paged for this silence
    continue
send_bark(f"MarketWind watchdog: {job} missed check-in",
          f"No '{job}' check-in since {state.last_ping:%Y-%m-%d %H:%M UTC}. "
          f"The morning report may not have been delivered — check the node.")
mark_alerted(job)            # set alerted=true so the next hours don't re-page
```
If `send_bark` fails, `alerted` is **not** set → next hour retries (loud, self-healing). Each job's exception is caught and logged; the loop continues.

---

## 6. Config & secrets

`check` function env (set at deploy via `s.yaml` variables / FC console):

| Var | Default | Notes |
|---|---|---|
| `OSS_BUCKET` | — | owner-created bucket name |
| `OSS_ENDPOINT` | — | e.g. `oss-cn-hangzhou-internal.aliyuncs.com` |
| `JOBS` | `premarket,main` | comma-separated |
| `PERIOD_SECONDS` | `86400` | 1 day |
| `GRACE_SECONDS` | `10800` | 3 h |
| `BARK_BASE_URL` | — | e.g. `https://api.day.app` or self-hosted |
| `BARK_KEY` | — | **secret** — owner supplies at deploy |

`ping` needs `OSS_BUCKET`, `OSS_ENDPOINT`, `JOBS`. OSS access uses the **FC service RAM role** (owner grants it read/write on the bucket) — no static keys in code. Timer cron: hourly (`0 0 * * * *`), configurable; ≤ 1 h page delay after grace is acceptable.

---

## 7. Testing strategy

All offline, no live Aliyun. Run: `PYTHONPATH=deploy/deadman-fc .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q deploy/deadman-fc/tests`. RED discipline per CLAUDE.md §8 — assertion-level RED (exact call / value), never a bare import error (except the pure-construction `State` dataclass, where import *is* the exercise).

- **`state`:** `put_ping` then `read_state` round-trips the timestamp + `alerted:false`; `read_state` on a missing key → `None`; `mark_alerted` flips only `alerted`, preserving `last_ping`.
- **`ping_handler`:** valid `job` → state written + 200; unknown/missing `job` → 400 **and no write** (RED asserts both the status and the absent write).
- **`check_handler` (the crux):**
  - overdue + `alerted:false` → `send_bark` called **once** + `alerted` set true.
  - overdue + `alerted:true` → `send_bark` **not** called.
  - within deadline → `send_bark` not called.
  - not armed (state `None`) → `send_bark` not called.
  - two jobs, one overdue / one healthy → only the overdue job pages (RED asserts the *which*).
  - `send_bark` raises → exception swallowed, `alerted` **not** set, loop continues to the other job.
- **`bark`:** builds the exact expected URL/payload from `cfg`; injectable poster records the call; a raising poster does not propagate.
- **`config`:** `load()` reads env into the dataclass with the documented defaults.

---

## 8. Owner deploy runbook (I write `README.md`; owner executes — secrets/infra only)

1. **Create an OSS bucket** (private) in the chosen domestic region.
2. **Create/assign an FC service RAM role** with read/write on that bucket.
3. **Set secrets** in `s.yaml` / FC env: `BARK_KEY`, `BARK_BASE_URL`, `OSS_BUCKET`, `OSS_ENDPOINT`.
4. **`s deploy`** with the owner's Aliyun credentials.
5. **Copy the two `ping` HTTP-trigger URLs** into the report node `.env` as `HEALTHCHECK_URL_PREMARKET` / `HEALTHCHECK_URL_MAIN` (`…/ping?job=premarket` / `…?job=main`); restart the daemon.
6. **Verify both directions:** trigger one delivered dispatch → confirm `state/<job>.json` appears with a fresh `last_ping`; then leave a job silent past `period+grace` (or temporarily shrink `GRACE_SECONDS`) → confirm a **Bark push** fires exactly once.

The code (§3–§7) is buildable and fully testable **now**, offline, without any Aliyun account. The runbook is executed later when the owner deploys; it does not block the code.

---

## 9. What this closes / does not close

**Closes:** W1 (node down & staying down) and W2 (push channel down) — after deploy, a missing morning report reliably produces a Bark push that does not depend on the node or its WeChat channel being alive.

**Does not close (accepted):** a provider-wide Aliyun outage taking down FC at deadline → no page (bounded watch-the-watcher regress; a personal system stops at one independent, more-reliable layer). A check-in ping lost to a transient blip while delivery *did* succeed → a spurious Bark push (safe direction; self-corrects at the next ping). Neither is a silent miss of the report itself.
