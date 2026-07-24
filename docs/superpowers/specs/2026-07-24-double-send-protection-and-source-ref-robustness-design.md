# Double-Send Protection & Source-Reference Robustness: design

> **Read when:** before changing the dispatch double-publish guard, or before touching the message-2 (source-reference tail) send path.

**Status:** design approved (2026-07-24 brainstorm). Three decisions: **A2** (implement), **B1** + **C1** (accepted-decision records, no code).

**Goal:** close the residual double-*delivery* race in the dispatch layer that the P2b `UNIQUE (job_id, trading_date)` constraint does *not* cover, and record the two owner-decided assumptions behind PR #10's source-reference second message so a future reader does not re-litigate them.

**Through-line — "Obvious fail welcomed, silent fail strongly un-welcomed."** A duplicate report is an *obvious* fail; a phantom-published row or a silently-swallowed message-2 failure is a *silent* one. Every choice below keeps failures loud and owner-visible.

---

## 1. Origin & scope

These three decisions fell out of the PR #10 review ("Source-reference second message (G4.6): clickable —— 来源 —— list"). The review surfaced three owner-decision items; this doc records all three, but only **A** requires code.

- **A — double-send protection.** The message-2 review re-exposed a pre-existing TOCTOU race in the dispatch layer's check-before-send guard. It affects **message 1 (the report) too**, so it is a *separate* concern from the source-reference feature and ships as its **own spec → plan → PR**.
- **B — source-reference URL privacy.** Whether to scrub/normalize URLs rendered into message 2. Decision: **B1 — verbatim, no code.**
- **C — source-reference failure observability.** How loudly a both-channels message-2 failure is recorded. Decision: **C1 — keep PR #13's ledger.detail + WARNING log, no new infra.**

**In scope (code):** A2 — a Postgres advisory lock around the dispatch critical section.
**In scope (docs):** B1 + C1 accepted-decision records (this doc *is* the record).
**Out of scope:** any change to `render_source_tail`, the Verifier gate, the Writer schema, or verified sentence text (Law-5-neutral). No metrics stack, no URL scrubbing, no message-2 retry.

---

## 2. Decision A2 — claim-then-send double-send protection

### 2.1 The race (what P2b left open)

P2b's ledger uses `record_run` = `INSERT ... ON CONFLICT (job_id, trading_date) DO NOTHING RETURNING`, and a check-before-send `SELECT` (`already_published()`) immediately before the report send. The `UNIQUE` constraint makes a double **row** structurally impossible, and the check-before-send *shrinks* the duplicate-delivery window to "crash between the SELECT and the row write."

It does **not** close a concurrent race. Two dispatchers for the same `(job_id, trading_date)` — the cron job firing on boot, and the boot `catch_up(trigger="boot")` path that calls `dispatch_job(...)` — can **both** pass the check-before-send `SELECT` before either calls `record_run`. Both then send. The `UNIQUE` constraint rejects the *second row*, but the *second report* has already been delivered.

APScheduler's `max_instances=1, coalesce=True` only prevents a cron job from overlapping **itself**; it does nothing for the cron-vs-boot cross-path race. P2b §7 explicitly named this residual and deferred it: *"eliminating it would need a DB-level advisory lock claimed before the run, which is out of scope here."* This doc picks up exactly that deferred item.

### 2.2 Mechanism — Postgres advisory lock (blocking, re-read under lock)

Serialize the check-before-send → run/send → `record_run` critical section with a session-scoped Postgres advisory lock, keyed by a stable hash of `(job_id, trading_date)`. Shape:

```
acquire pg_advisory_lock(key)        # BLOCKS until the current holder releases
try:
    existing = get_run_status(...)   # authoritative re-read, now under the lock
    if existing is not None:
        return RunOutcome(existing)  # loser path: winner already recorded — no run, no send
    outcome = run_once(...)          # winner path: the gated pipeline (sends message 1[+2])
    ... boot/stale relabel ...
    record_run(...)                  # winner writes the terminal row
    return outcome
finally:
    pg_advisory_unlock(key)
```

- **Blocking, not `try_`.** The loser waits for the winner to finish and release, then acquires the lock and re-reads the ledger — which the winner has now written — so it returns the winner's outcome **correct-by-construction** and sends nothing. A non-blocking `pg_try_advisory_lock` was rejected: the loser would give up *immediately*, before the winner records, so it could not return an accurate status without inventing a new "concurrent-owner" outcome.
- **Loser does zero work.** Because the re-read happens *under* the lock (after the winner's `record_run`), the loser skips `run_once` entirely — no duplicate gather→draft→verify LLM spend. This also eliminates, for the concurrent-on-one-node case, the double-*work* that P2b §7 explicitly accepted. (It does not eliminate double-work across a crash-restart loop, which is not a concurrent case — see §2.4.)
- **Auto-release on connection close** makes it crash-safe: a dispatcher that dies mid-run drops the lock when its connection closes, so the slot is never permanently wedged — no stale-claim recovery code needed.
- **Named residual — a hung (not crashed) winner.** If the winner's connection stays alive but the run hangs, the loser blocks indefinitely. Accepted for a single-node personal system (a crash, the common case, auto-releases); the supervisor / freshness window is the out-of-band signal. A `lock_timeout` guard is deliberately not added (speculative complexity).

**Key derivation.** `pg_advisory_lock` takes a `bigint` (or two `int4`s). Derive it from a stable hash of `f"{job_id}:{trading_date.isoformat()}"` reduced into the signed 64-bit range. The hash must be **stable across processes** — Python's built-in `hash()` is salted per-process (`PYTHONHASHSEED`), so use `hashlib` (e.g. first 8 bytes of a `blake2b`/`sha1` digest, interpreted as a signed 64-bit int), **not** `hash()`.

**Why advisory lock over the A1 alternative (a two-phase claim row).** A claim row means a new non-terminal `SENDING` ledger status plus stale-claim / crash-recovery logic to reclaim a slot whose owner died mid-send. That is strictly more schema and more failure modes for the same guarantee. The advisory lock needs no migration, no new status, and self-heals on connection close.

### 2.3 Where it lives

Each dispatcher already opens its **own** `asyncpg.connect(settings.database_url)` (`scheduling/__main__.py` — one connection per dispatcher). Separate sessions are exactly what advisory locks serialize. The lock wraps the critical section inside `dispatch_job` (`scheduling/dispatch.py`): acquire before the run/record region, release in a `finally`. The **existing top-of-function no-op guard stays** as a cheap fast path (returns early when a terminal row already exists from a prior completed run, without ever acquiring the lock); the re-read *under* the lock is the authoritative one that closes the concurrent race.

This is a **superset** guard: it protects message 1 and message 2 alike, because it serializes the entire send+record region, not just the source tail. That is why it is scoped as its own change rather than folded into the message-2 PR.

### 2.4 What it does and does NOT close

It closes the **concurrent** double-delivery race (cron-vs-boot, or any two same-key dispatchers on one node). It does **not** change P2b's deliberate at-least-once seam: a crash *between* a successful send and the `record_run` write still re-delivers on next boot — that residual is unchanged and still accepted (an obvious duplicate beats a silent phantom-publish). The advisory lock narrows the *concurrent* window; it is not a distributed-exactly-once claim, and this system is single-node by design so cross-node locking is out of scope.

---

## 3. Decision B1 — source-reference URLs stay verbatim

Message 2 renders each source as a bare URL (`[{n}] {domain} — {url}`). Decision: **render URLs verbatim; no scrubbing, no normalization, no truncation code.**

- **Why not scrub query tokens.** WeCom auto-linkifies a **bare** URL; escaping, truncating, or rewriting it breaks the clickable link — which is the entire point of the source-reference message (a reader must be able to reach the primary source). A "privacy scrub" that strips query params would silently break links to sources that legitimately need them.
- **Accepted assumption.** Sources are public financial news / primary-source pages. A rare long or token-bearing URL is tolerated. This is not a system that handles user-private URLs, so there is no sensitive-token exposure to defend against.
- **Length interaction.** If a pathological URL pushes message 2 past WeCom's ~2048-byte text limit, that is caught by the **Option-A** path already in PR #13 (message 2's send failure is non-fatal: the report stays `published` and the failure is logged loudly). Note "Option A" (PR #13's non-fatal message-2 handling) is a *different* thing from "Decision A" (the double-send protection of §2). There is no separate length-guard code for message 2.

No code. This section is the record that verbatim URLs are an intentional choice, not an oversight.

---

## 4. Decision C1 — lean failure observability

When message 2 fails on **both** channels, the behavior stays exactly as PR #13 already implements it:

- **`ledger.detail`** records both channel errors — `_send_soft` combines primary + fallback causes (`primary={...}; fallback={...}`) so the durable row is self-explanatory.
- **A `logger.warning`** is emitted at the failure site (loud, non-fatal — matching the `deadman.py` precedent).
- The outcome **stays `PUBLISHED`** (Option A): the report itself succeeded; the missing source tail is a degraded-but-published state, never a raise and never a silent swallow.

**Deliberately omitted (simplicity — this is a demo/personal project per DECISIONS.md):**
- **No metrics stack / counter** (`send_message2.failure` with labels). Failure frequency is answerable by a one-off SQL query over the ledger's `detail` column; standing up Prometheus-style counters for a single-node personal system is speculative infrastructure.
- **No retry-count field.** Message 2 does **not** retry by design (it is the non-critical tail; the report already published). A retry counter would always be zero.

No code beyond what PR #13 already contains. This section records that the lean approach is intentional.

---

## 5. Testing strategy

Only A2 introduces code, so only A2 needs new tests. B1 and C1 are covered by PR #13's existing tests (source-tail render; `_send_soft` combining both channel errors; Option-A stays-published-on-message-2-failure).

**A2 (advisory-lock double-send guard) — offline, against the existing test Postgres:**
- **Concurrent same-key dispatchers → exactly one delivery.** Two `dispatch_job` calls for the same `(job_id, trading_date)` racing the critical section: assert the report send happens **once** and one ledger row exists. (RED: without the lock, both pass the check-before-send `SELECT` and both send — assert the send-count is 1, watch it fail at 2.)
- **Lock loser returns the winner's outcome, silently.** The dispatcher that acquires the lock *second* re-reads the ledger under the lock (winner has recorded), returns that `PUBLISHED` outcome, and sends **no** report and **no** status page (consistent with P2b single-sender). Also assert the loser never enters `run_once` (no duplicate work).
- **Stable cross-process key.** The lock key derives from `hashlib`, not `hash()` — a test pins the key for a known `(job_id, trading_date)` so a per-process-salted hash regression is caught. (RED: swapping in `hash()` changes the value → assertion fails.)
- **Crash-safety / auto-release** is a Postgres guarantee (lock drops on connection close); assert the lock is released after a normal `dispatch_job` completes so a subsequent same-key dispatch can acquire it.
- **No regression:** the existing dispatch / catch-up / no-op-guard tests stay green — the lock wraps the critical section without changing gate semantics or outcome mapping.

RED discipline per CLAUDE.md §8: assertion-level RED required (send-count == 1 failing at 2 is the load-bearing RED); the key-stability test uses a pinned expected value so a `hash()` regression goes red.
