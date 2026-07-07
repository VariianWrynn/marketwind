# Dead-man's switch — out-of-process liveness watchdog (P2b item E / G1.3)

> **Superseded (watcher only, 2026-07-07):** the watcher-implementation decisions in this spec (self-hosted Healthchecks on a second host; email+Bark fan-out) are superseded by `2026-07-07-deadman-fc-watcher-design.md` (Aliyun FC serverless watcher, Bark-only). The §2 check-in contract and §3 daemon code in this spec remain in force and unchanged.

> **Read when:** building or changing the check-in / dead-man's-switch path, or standing up the second-host Healthchecks watcher.

**Status:** design approved (2026-07-07 brainstorm). Scope: **item E only** (the deferred P2b residual-closer). Cloud cutover (Track 1) is a separate owner-run ops track, out of scope here.

**Goal:** close the two residual silent-miss windows that an in-process push design *fundamentally cannot* self-report, by having the daemon **check in to an external watchdog only after it has delivered its morning outcome to the owner** — so the absence of a report becomes a loud, owner-visible page that originates *outside* the node.

**Through-line — "Obvious fail welcomed, silent fail strongly un-welcomed."** The switch exists solely to convert a silence (no report, no page) into a loud external alert. Every choice below favors a loud false-positive over a silent miss.

---

## 1. Problem & scope

P2b (durable, unattended operation) narrowed but did **not** eliminate the silent-miss class. Two residual windows remain, both named in the P2b design (§1, §6):

- **W1 — "down and staying down."** A node dead across a fire window that *never reboots* never runs boot `catch_up`, so it emits zero signal for those days. Every P2b notice is push-based *from the node*; a dead node pushes nothing.
- **W2 — "push channel itself down."** The node is alive and correctly writes a `failed_infra` ledger row, but the owner-facing page rides the very WeChat/WeCom channel that is down, so the page cannot escape. Only the ledger row + non-zero exit + logs remain — invisible until someone looks.

Closing both requires an **out-of-process, externally-originating** watcher — the only design that can report on a dead node or a dead channel. This is P2b §8.1 item E, flagged there as "the highest-value next item, not a nice-to-have."

**In scope:** the daemon-side **conditional check-in** (one HTTP ping after a delivered outcome), its config gating and per-job routing, the wiring through `dispatch_job`/`catch_up`, and an owner-run ops runbook for the second-host Healthchecks watcher.

**Out of scope:** the cloud cutover / provisioning of the report node (separate Track 1); provisioning the second host and configuring Healthchecks itself (owner-run ops — the runbook guides it, but it is not code); any change to the Law-5 gate, the ledger, or the retry/escalation logic.

**Decisions locked in the brainstorm:**
- Watcher = **self-hosted Healthchecks** on a **second host** (different box from the report node). No foreign SaaS (China-reachability + third-party-trust concerns).
- Alert fan-out = **email (`chishencsz@icloud.com`) + Bark** (iOS push). Both, for redundancy. **Never WeChat** — W2 is literally "the WeChat channel is down."
- Granularity = **per-job** (two checks: `premarket`, `main`), each independently guaranteed.
- Deadline = Healthchecks "simple" **period = 1 day, grace ≈ 2–3 h** (absorbs the premarket anchor drift + freshness tolerance + retry budget; a late-but-fine run never false-pages).

---

## 2. The check-in contract (the crux)

> At the end of a dispatch, ping that job's check-in URL **if and only if a message actually reached the owner** — a `published` report (the report send itself succeeded), *or* a status page / heartbeat that `send_with_fallback` delivered without raising.

This single rule closes both windows and nothing else:

| Situation | Message reached owner? | Ping? | Result |
|---|---|---|---|
| Node dead (W1) | no dispatch runs | — | no ping → Healthchecks pages after grace ✅ |
| Node alive, WeChat + WeCom both down (W2) | no (send raised) | **no** | `failed_infra` row written, no ping → Healthchecks pages ✅ |
| `published` (report send succeeded) | yes | yes | no page ✅ |
| Correct skip / sub-floor / verify-fail, page **delivered** | yes | yes | no page ✅ (owner already got the loud message the normal way) |
| `failed_infra` from an upstream transient, page **delivered** | yes | yes | no page ✅ (node alive + channel works + owner told loudly) |

The **only** two things that suppress a check-in are exactly W1 (nothing ran) and W2 (nothing delivered). A *delivered* `failed_infra` counts as a check-in: it proves the node is alive and the channel works, and the owner already received the loud message through the normal path — the dead-man's switch must not *also* fire.

Rationale for keying off *delivery* rather than *publication*: the dead-man's switch protects "did the owner get proof-of-life today," not "was a report published." Days with a correct non-publish (verify-fail, sub-floor, holiday heartbeat) are healthy days on which the owner *was* informed — they must satisfy the deadline.

---

## 3. Components

Each unit small, single-purpose, testable in isolation.

### 3.1 `scheduling/deadman.py` (new)

```
def check_in(url: str | None, *, post: Callable[[str], None] = <default http post>) -> None
```

- `url` empty/`None` → **no-op** (the disable gate; empty in tests / `--dry-run` / local dev).
- otherwise → best-effort `post(url)` (short timeout). **Swallows and logs every exception**; never raises into the caller. The default `post` does the real HTTP call (Healthchecks accepts a bare `GET`/`POST` to the ping URL); `post` is injectable so tests assert on calls without hitting the wire.

Responsibility: *fire one liveness ping, safely.* It knows nothing about jobs, outcomes, or the ledger.

### 3.2 `config.py`

Two new optional settings, default empty (⇒ disabled):
- `healthcheck_url_premarket: str = ""`
- `healthcheck_url_main: str = ""`

Empty defaults keep every existing test/local/dry-run path ping-free.

### 3.3 `scheduling/dispatch.py`

`dispatch_job` is already the single sender and already computes the outcome + the `inserted` delivery signal. Add, at the existing send seam:
- resolve this job's URL (`premarket` → premarket URL, `main` → main URL);
- call `check_in(url)` **guarded by `if inserted:`, placed immediately after the existing status-send line** (`if inserted and text is not None: send_with_fallback(...)`).

This exact placement realizes the §2 contract for free, because of how the existing code already behaves:
- **`published`** → `inserted` True, `text` is `None` (published is silent), no dispatch-level send → control reaches `check_in` → **pings**. (`inserted` True for `published` means *this* dispatcher won the insert and thus actually sent the report in `run_pipeline`; the idempotent already-published path returns `PUBLISHED` with `inserted` False and does not ping.)
- **Delivered loud status** (verify-fail / sub-floor / skip / a *reachable* `failed_infra`) → `send_with_fallback` returns → reaches `check_in` → **pings**.
- **W2 (both channels down)** → `send_with_fallback` **raises** (its existing contract on total failure), which propagates before `check_in` is reached → **no ping**. The raise-before-ping is what suppresses the check-in on a dead channel — no extra branch needed.
- **Lost-the-race duplicate** → `inserted` False → `check_in` skipped.

No new control flow, no change to ledger/retry/escalation — a single `if inserted: check_in(url)` after the existing send. The two URLs thread in as parameters (default `""`), mirroring how `label_prefix` is threaded.

`catch_up`'s **past-date `missed`** reconciliation writes rows but does **not** ping — those are reconciliation records, not today's live delivery, and a missed past day must not satisfy today's deadline. (Today's delegated run goes through `dispatch_job` and pings normally if it delivers.)

### 3.4 `scheduling/__main__.py` `run_scheduler`

Resolve the two URLs from `settings` and pass them into the `catch_up` and per-fire `dispatch_job` wiring — same threading pattern as `label_prefix`. (The manual `main()` entrypoint may leave them unset/`""`; the dead-man's switch is a daemon concern.)

### 3.5 Deploy config

`docker-compose.yml` (scheduler service) + `.env.example`: two new env passthroughs, `HEALTHCHECK_URL_PREMARKET` / `HEALTHCHECK_URL_MAIN`, default empty.

---

## 4. Data flow

```
cron fire ─► dispatch_job(job_id, …) ─► run_once ─► (outcome + send)
                    │
                    ├─ record_run (ledger row, unchanged)
                    ├─ send status page if applicable (unchanged)
                    └─ [iff a message was delivered] check_in(job_url)   ← new, strictly last

        Healthchecks (second host, independent) ── pages email + Bark
        if a job's ping is absent past period(1d)+grace(2–3h)
```

The daemon never judges "am I dead." That judgment lives entirely **outside** the node — the only place it can be made when the node or its channel is down.

---

## 5. Error handling & edge cases

- **Best-effort ping, biased to false-page over silent-miss.** `check_in` never raises into `dispatch_job` (the report already delivered; a crash here would be self-inflicted). **Accepted tradeoff:** a ping silently lost while delivery *did* succeed causes a Healthchecks false-page — the *safe* direction (loud, self-corrects next day). **No** ping-retries / jitter / circuit-breaker (YAGNI; "cut watchdog complexity"): a rare false page is cheaper than the machinery to prevent it.
- **Ping is strictly last and side-effect-only.** It fires after the ledger write and the send; its result never affects the returned outcome. The ledger row stays the durable record of truth.
- **Single check-in per delivery (no double-ping).** The ping keys off the **same** delivery signal (`inserted` + send-success) that already gates the P2b status send. A dispatcher that lost the cron-vs-catch-up race (didn't send) doesn't ping either — one logical delivery ⇒ one check-in.
- **Disable gate.** Empty URL ⇒ no-op, so offline tests / `--dry-run` / local never ping.
- **Second host must be independent.** A watcher co-located on the report node dies with it — defeating the purpose. The runbook (§7) requires a *different* box (ideally different provider/region).

---

## 6. Testing strategy

All offline, no live network. `check_in` takes an injectable `post`; `dispatch_job`'s send path is already stub-driven in the P2b tests. RED discipline per CLAUDE.md §8: assertion-level RED (the exact URL string / the call presence-or-absence), never a bare import error.

- **`deadman.check_in`:**
  - URL set + delivery → `post` called once with **that exact URL** (RED asserts the URL).
  - URL `""`/`None` → `post` **not** called.
  - `post` raises → `check_in` swallows it, returns normally, no exception propagates (RED: the call does not raise).
- **`dispatch_job` contract (the crux):**
  - `published` → pings the job's URL.
  - delivered loud status (e.g. `verify_fail` whose page sent) → pings.
  - **both channels down** (`failed_infra`, send raised) → **no ping** ← the W2 assertion, the one that matters most.
  - lost-the-race duplicate (`inserted` False) → no ping.
  - per-job routing: `premarket` dispatch pings the premarket URL, `main` pings the main URL (RED: wrong-URL asserts).
- **`catch_up`:** past-date `missed` reconciliation → no ping.
- **Config / regression:** empty defaults ⇒ disabled; `tests/scheduling` (and `tests/orchestration` where the send seam is touched) stay green with the new threading.

---

## 7. Ops runbook (owner-run — I write the doc, owner executes)

A short `docs/runbooks/deadman-switch.md`, mirroring `go-live-smoke.md`:

1. **Provision the second host** — a *different* box from the report node (different provider/region preferred; a cheap VPS or a home box suffices).
2. **Deploy Healthchecks** on it (its own docker-compose stack).
3. **Create two checks** (`premarket`, `main`), each period = 1 day, grace = 2–3 h; copy the two ping URLs.
4. **Wire integrations:** email → `chishencsz@icloud.com`; Bark → the owner's Bark server/key (Healthchecks webhook integration).
5. **Set the URLs** on the report node (`HEALTHCHECK_URL_PREMARKET` / `HEALTHCHECK_URL_MAIN` in `.env`), restart the daemon.
6. **Verify both directions:** one delivered dispatch → check goes green; then stop the daemon (or break the channel) past grace → confirm **email + Bark both fire**.

**Scope boundary:** the code (§3–§5) is buildable and fully testable **now**, offline, without the second host. The runbook is executed later when the host is provisioned; it does **not** block the code.

---

## 8. What this does and does NOT close

**Closes:** W1 (node down & staying down) and W2 (push channel down) — the two residual windows P2b explicitly left open. After this, a missing morning report reliably produces an external email + Bark page that does not depend on the node or its WeChat channel being alive.

**Does not close (accepted):** if the **second host** is also down at deadline, no page fires (the "watch the watcher" regress — bounded by choosing an independent, more-reliable host; a personal system does not chase infinite regress). A ping lost to a transient network blip while delivery succeeded false-pages (safe direction). Neither is a silent miss of the report itself.
