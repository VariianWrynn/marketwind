# Dead-man's switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two residual silent-miss windows (W1 "node down & staying down", W2 "push channel down") by having the daemon check in to an external Healthchecks watchdog **only after** it has delivered a message to the owner — so the absence of a check-in becomes a loud, owner-visible external page.

**Architecture:** A new single-purpose `deadman.check_in(url)` fires one best-effort HTTP ping. `dispatch_job` calls it as `if inserted: check_in(url)` placed immediately after the existing status-send line — realizing the "ping iff a message reached the owner" contract for free, because on W2 `send_with_fallback` raises before the ping is reached (no extra branch). Two per-job URLs (`premarket`, `main`) thread through from config → `run_scheduler` → `catch_up`/`dispatch_job`, mirroring the existing `label_prefix` threading. Empty URL ⇒ no-op (the disable gate for tests/dry-run/local).

**Tech Stack:** Python 3.11+, pytest (async), pydantic-settings, stdlib `urllib.request` for the ping, Docker Compose.

**Authority for RED assertions:** `docs/superpowers/specs/2026-07-07-deadman-switch-design.md` §2 (contract) and §6 (testing strategy). **Authority for fixture/monkeypatch patterns:** `tests/scheduling/test_dispatch_job.py`, `tests/scheduling/test_catch_up.py`, `tests/scheduling/test_config_p2a.py`.

**Run/test convention (this repo):**
```
PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q <path>
```
Async tests need no explicit decorator — the repo's existing `tests/scheduling/*` async tests run under the configured asyncio mode; match the existing files exactly (plain `async def test_...(monkeypatch)`).

---

### Task 1: `deadman.check_in` — the safe single-purpose ping

**Files:**
- Create: `marketwind/scheduling/deadman.py`
- Test: `tests/scheduling/test_deadman.py`

**Contract (fix exactly):**
```python
def check_in(url: str | None, *, post: Callable[[str], None] = _http_post) -> None
```
- `url` empty (`""`) or `None` → **no-op** (return without calling `post`). This is the disable gate.
- otherwise → call `post(url)` inside a `try/except Exception` that **swallows and logs** every exception; `check_in` never raises into its caller.
- `_http_post(url)` is the default real sender: a bare `urllib.request.urlopen(url, timeout=<short, e.g. 5s>)` (Healthchecks accepts a bare GET/POST to the ping URL). Mark `_http_post` with `# pragma: no cover` — it is the live-network seam and is never exercised offline. `post` is injectable precisely so tests assert on calls without hitting the wire.
- Use the stdlib `logging` module for the swallow-log (module-level `logger = logging.getLogger(__name__)`); the log message must make a lost ping visible ("obvious fail welcomed").

`check_in` knows nothing about jobs, outcomes, or the ledger — it only fires one liveness ping, safely.

- [ ] **Step 1: Write the failing tests**

Three behavioral tests in `tests/scheduling/test_deadman.py`. Each injects a recorder `post` so nothing hits the network.

```python
from marketwind.scheduling.deadman import check_in


def test_pings_exact_url_when_set():
    calls = []
    check_in("http://hc.example/ping/abc", post=calls.append)
    assert calls == ["http://hc.example/ping/abc"]


def test_no_op_when_url_empty():
    calls = []
    check_in("", post=calls.append)
    check_in(None, post=calls.append)
    assert calls == []


def test_swallows_post_error():
    def boom(url):
        raise RuntimeError("network down")
    # Must return normally — a ping failure must never propagate into the caller.
    check_in("http://hc.example/ping/abc", post=boom)
```

RED assertions that matter: the **exact URL string** passed through (test 1), the **absence** of any call for empty/None (test 2), and that a raising `post` **does not** propagate (test 3 — it has no `assert`; the RED is "the call raises" — see Step 2).

- [ ] **Step 2: Run tests to verify they fail correctly**

Scaffold a minimal stub FIRST so the tests run and fail on behavior, not on `ImportError` (CLAUDE.md §8): create `deadman.py` with `def check_in(url, *, post=lambda u: None): pass` (a no-op that ignores `post`).

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/scheduling/test_deadman.py`
Expected: `test_pings_exact_url_when_set` FAILS on `assert calls == [...]` (stub never calls post). `test_no_op_when_url_empty` PASSES against the stub (acceptable — it pins the no-op direction). `test_swallows_post_error` PASSES against the stub (it never calls post). The discriminating RED is test 1's assertion failure.

Note for the harness: test 3's guarantee (swallow) is only genuinely exercised once the implementation actually calls `post`. Confirm test 3 stays green after Step 3 (when `post` IS called and raises).

- [ ] **Step 3: Write minimal implementation**

Implement `check_in` per the contract above (guard empty/None; try/except around `post(url)`; log on exception) and `_http_post` (stdlib urlopen, short timeout, `# pragma: no cover`). Keep it under ~25 lines.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/scheduling/test_deadman.py`
Expected: 3 passed. In particular test 3 now actually calls the raising `post` and still returns normally.

- [ ] **Step 5: Commit**

```bash
git add marketwind/scheduling/deadman.py tests/scheduling/test_deadman.py
git commit -m "feat(scheduling): add deadman.check_in best-effort liveness ping"
```

---

### Task 2: Config — two optional per-job Healthcheck URLs

**Files:**
- Modify: `marketwind/config.py` (add two fields alongside the P2b scheduling block, ~line 35-36)
- Test: `tests/scheduling/test_config_p2a.py`

**Contract (fix exactly):**
```python
healthcheck_url_premarket: str = ""
healthcheck_url_main: str = ""
```
Default empty ⇒ disabled. Empty defaults keep every existing test/local/dry-run path ping-free.

- [ ] **Step 1: Write the failing test**

Add to `tests/scheduling/test_config_p2a.py` (uses `Settings(database_url="postgres://x", redis_url="redis://x")`):

```python
def test_healthcheck_urls_default_empty():
    s = Settings(database_url="postgres://x", redis_url="redis://x")
    assert s.healthcheck_url_premarket == ""
    assert s.healthcheck_url_main == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/scheduling/test_config_p2a.py::test_healthcheck_urls_default_empty`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'healthcheck_url_premarket'`. (This is a construction-adjacent field-presence test; the assertion on `== ""` is the discriminating check once the attribute exists.)

- [ ] **Step 3: Add the two fields**

Add the two lines to `Settings` in the P2b scheduling block (after `main_report_time_cst`).

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/scheduling/test_config_p2a.py`
Expected: all passed (new test + existing).

- [ ] **Step 5: Commit**

```bash
git add marketwind/config.py tests/scheduling/test_config_p2a.py
git commit -m "feat(config): add per-job healthcheck_url settings (default empty)"
```

---

### Task 3: `dispatch_job` — ping iff a message was delivered (the crux)

**Files:**
- Modify: `marketwind/scheduling/dispatch.py` (import `check_in`; add param; add one line after the send seam ~line 214-217)
- Test: `tests/scheduling/test_dispatch_job.py`

**Contract (fix exactly):**
- Add `from marketwind.scheduling.deadman import check_in` to the imports.
- Add a new keyword param to `dispatch_job`, **as the last parameter after `label_prefix`**, so `_COMMON_KWARGS` (which omits it) still works via the default:
  ```python
  healthcheck_url: str = "",
  ```
- At the send seam, immediately AFTER the existing block:
  ```python
  text = _status_text(outcome, plan, trace_id)
  if inserted and text is not None:
      send_with_fallback(text, primary=primary, fallback=fallback, trace_id=trace_id)
  ```
  add:
  ```python
  if inserted:
      check_in(healthcheck_url)
  ```
  placed BEFORE `return outcome`.

Why this exact placement realizes §2 (do not add branches):
- `published` → `inserted` True, `text` None (silent) → no send → reaches `check_in` → **pings**.
- delivered loud status (verify-fail / sub-floor / skip / reachable `failed_infra`) → `send_with_fallback` returns → reaches `check_in` → **pings**.
- W2 (both channels down) → `send_with_fallback` **raises** (its existing contract) → propagates before `check_in` → **no ping**.
- lost-the-race duplicate → `inserted` False → `check_in` skipped.

No change to ledger/retry/escalation. The ping is strictly last and side-effect-only.

- [ ] **Step 1: Write the failing tests**

Add to `tests/scheduling/test_dispatch_job.py`. Monkeypatch `marketwind.scheduling.dispatch.check_in` with a recorder. Follow the existing `_make_ledger` / `_COMMON_KWARGS` / `StubSink` pattern.

```python
async def test_published_pings_healthcheck(monkeypatch):
    pings = []
    async def stub_run_once(*a, **k):
        return RunOutcome(PUBLISHED)
    _, _, fake_get, fake_record = _make_ledger()
    monkeypatch.setattr("marketwind.scheduling.dispatch.run_once", stub_run_once)
    monkeypatch.setattr("marketwind.scheduling.dispatch.get_run_status", fake_get)
    monkeypatch.setattr("marketwind.scheduling.dispatch.record_run", fake_record)
    monkeypatch.setattr("marketwind.scheduling.dispatch.check_in", lambda url: pings.append(url))
    await dispatch_job("main", **{**_COMMON_KWARGS, "primary": StubSink(),
                                  "fallback": StubSink(), "healthcheck_url": "http://hc/main"})
    assert pings == ["http://hc/main"]


async def test_delivered_status_pings_healthcheck(monkeypatch):
    pings = []
    async def stub_run_once(*a, **k):
        return RunOutcome(SUB_FLOOR, "g=0 p=0 o=0")
    _, _, fake_get, fake_record = _make_ledger()
    monkeypatch.setattr("marketwind.scheduling.dispatch.run_once", stub_run_once)
    monkeypatch.setattr("marketwind.scheduling.dispatch.get_run_status", fake_get)
    monkeypatch.setattr("marketwind.scheduling.dispatch.record_run", fake_record)
    monkeypatch.setattr("marketwind.scheduling.dispatch.check_in", lambda url: pings.append(url))
    await dispatch_job("main", **{**_COMMON_KWARGS, "primary": StubSink(),
                                  "fallback": StubSink(), "healthcheck_url": "http://hc/main"})
    assert pings == ["http://hc/main"]


async def test_both_channels_down_does_not_ping(monkeypatch):
    # W2: node alive, wrote failed_infra row, but the page could not escape
    # (send_with_fallback raised). The dead-man's switch must NOT also ping —
    # its silence is what pages the owner externally. THE assertion that matters most.
    pings = []
    async def stub_run_once(*a, **k):
        return RunOutcome(FAILED_INFRA, "boom")
    _, _, fake_get, fake_record = _make_ledger()
    def raising_send(text, *, primary, fallback, trace_id):
        raise RuntimeError("both IM channels failed")
    monkeypatch.setattr("marketwind.scheduling.dispatch.run_once", stub_run_once)
    monkeypatch.setattr("marketwind.scheduling.dispatch.get_run_status", fake_get)
    monkeypatch.setattr("marketwind.scheduling.dispatch.record_run", fake_record)
    monkeypatch.setattr("marketwind.scheduling.dispatch.send_with_fallback", raising_send)
    monkeypatch.setattr("marketwind.scheduling.dispatch.check_in", lambda url: pings.append(url))
    with pytest.raises(RuntimeError):
        await dispatch_job("main", **{**_COMMON_KWARGS, "primary": StubSink(),
                                      "fallback": StubSink(), "healthcheck_url": "http://hc/main"})
    assert pings == [], f"W2 must not ping; got {pings!r}"


async def test_record_conflict_does_not_ping(monkeypatch):
    pings = []
    async def stub_run_once(*a, **k):
        return RunOutcome(SUB_FLOOR, "g=0 p=0 o=0")
    async def fake_get(conn, *, job_id, trading_date):
        return None
    async def conflict_record(conn, *, job_id, trading_date, status, trace_id, detail=None):
        return False
    monkeypatch.setattr("marketwind.scheduling.dispatch.run_once", stub_run_once)
    monkeypatch.setattr("marketwind.scheduling.dispatch.get_run_status", fake_get)
    monkeypatch.setattr("marketwind.scheduling.dispatch.record_run", conflict_record)
    monkeypatch.setattr("marketwind.scheduling.dispatch.check_in", lambda url: pings.append(url))
    await dispatch_job("main", **{**_COMMON_KWARGS, "primary": StubSink(),
                                  "fallback": StubSink(), "healthcheck_url": "http://hc/main"})
    assert pings == [], f"lost-race duplicate must not ping; got {pings!r}"
```

The critical RED is `test_both_channels_down_does_not_ping` — the W2 assertion. It also depends on `dispatch_job` still re-raising the transient `RuntimeError` at `retries=0` (existing behavior: `_TRANSIENT` includes `RuntimeError`, but with `retries=0` the escalation path turns it into a `FAILED_INFRA` outcome — WAIT, verify this). See Step 2 note.

- [ ] **Step 2: Run tests to verify they fail correctly**

First scaffold the param + import but NOT the `check_in` call: add `healthcheck_url: str = ""` to the signature and the import, but do NOT yet add the `if inserted: check_in(...)` line. This makes the ping tests fail on the assertion (recorder stays empty) rather than on a missing param.

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/scheduling/test_dispatch_job.py`
Expected: `test_published_pings_healthcheck` and `test_delivered_status_pings_healthcheck` FAIL on `assert pings == ["http://hc/main"]` (empty). `test_both_channels_down_does_not_ping` and `test_record_conflict_does_not_ping` PASS (no ping wired yet — they pin the suppression direction).

**IMPORTANT verification for the W2 test premise (harness must confirm before writing impl):** trace how `dispatch_job` behaves when `send_with_fallback` raises `RuntimeError`. The send is OUTSIDE the retry loop (the retry loop wraps only `run_once`). So a `RuntimeError` from `send_with_fallback` at the send seam propagates OUT of `dispatch_job` unhandled — the `with pytest.raises(RuntimeError)` is correct, and `check_in` (placed after the send) is never reached. Confirm this by reading the current control flow in `dispatch.py` (the retry loop ends at line ~192; the send is at ~215). If instead the send were inside a try/except, this test's premise would be wrong — it is not, but VERIFY before implementing.

- [ ] **Step 3: Add the `if inserted: check_in(healthcheck_url)` line**

Add the two-line block after the existing send block, before `return outcome`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/scheduling/test_dispatch_job.py`
Expected: all passed (4 new + 8 existing). The existing tests still pass because `check_in("")` (default) is a no-op — no existing test wires a URL.

- [ ] **Step 5: Commit**

```bash
git add marketwind/scheduling/dispatch.py tests/scheduling/test_dispatch_job.py
git commit -m "feat(scheduling): dispatch_job checks in to deadman switch iff delivered"
```

---

### Task 4: `catch_up` — route per-job URLs; past-missed does not ping

**Files:**
- Modify: `marketwind/scheduling/dispatch.py` (`catch_up` signature + the today-delegation call)
- Test: `tests/scheduling/test_catch_up.py`

**Contract (fix exactly):**
- Add a new keyword param to `catch_up`, **as the last parameter after `label_prefix`**:
  ```python
  healthcheck_urls: dict[str, str] | None = None,
  ```
- When delegating today's run to `dispatch_job`, pass:
  ```python
  healthcheck_url=(healthcheck_urls or {}).get(job_id, ""),
  ```
- The past-date `missed` branch (which writes rows directly and may page) must **NOT** ping — those are reconciliation records, not today's live delivery; a missed past day must not satisfy today's deadline. Do not add any `check_in` call there.

- [ ] **Step 1: Write the failing tests**

Add to `tests/scheduling/test_catch_up.py`. Because `catch_up` delegates today to the real `dispatch_job` (not stubbed here for the routing test), the cleanest RED is to stub `dispatch_job` and assert the `healthcheck_url` kwarg it receives for each job. Extend the existing `stub_dispatch_job` capture to record kwargs.

```python
async def test_today_delegation_routes_per_job_url(monkeypatch):
    """premarket-today delegates with the premarket URL; main-today with the main URL."""
    _, _, fake_get, fake_record = _make_ledger()
    seen = {}
    async def stub_dispatch_job(job_id, *, now, conn, sessions, trigger, **kwargs):
        seen[job_id] = kwargs.get("healthcheck_url")
        return RunOutcome(PUBLISHED)
    monkeypatch.setattr("marketwind.scheduling.dispatch.get_run_status", fake_get)
    monkeypatch.setattr("marketwind.scheduling.dispatch.record_run", fake_record)
    monkeypatch.setattr("marketwind.scheduling.dispatch.dispatch_job", stub_dispatch_job)
    await catch_up(
        sessions=_SESSIONS_5, primary=StubSink(), fallback=StubSink(),
        healthcheck_urls={"premarket": "http://hc/pre", "main": "http://hc/main"},
        **_COMMON_KWARGS,
    )
    assert seen == {"premarket": "http://hc/pre", "main": "http://hc/main"}
```

For "past-missed does not ping": the past-date branch never calls `check_in` (there is no `check_in` in `catch_up` at all), so a direct assertion is that `catch_up` imports/uses no ping on the reconciliation path. The meaningful, non-tautological guard is that the routing test above passes URLs ONLY through `dispatch_job` (today), never on a past `missed` write. A dedicated monkeypatch of `dispatch.check_in` to a recorder, run over an all-empty ledger (which produces past `missed` rows + today delegation), asserting the recorder is empty EXCEPT via the stubbed `dispatch_job` (which is stubbed and thus won't call the real check_in), documents intent:

```python
async def test_past_missed_does_not_ping(monkeypatch):
    pings = []
    _, recorded, fake_get, fake_record = _make_ledger()
    async def stub_dispatch_job(job_id, *, now, conn, sessions, trigger, **kwargs):
        return RunOutcome(PUBLISHED)  # today path stubbed; not under test here
    monkeypatch.setattr("marketwind.scheduling.dispatch.get_run_status", fake_get)
    monkeypatch.setattr("marketwind.scheduling.dispatch.record_run", fake_record)
    monkeypatch.setattr("marketwind.scheduling.dispatch.dispatch_job", stub_dispatch_job)
    monkeypatch.setattr("marketwind.scheduling.dispatch.check_in", lambda url: pings.append(url))
    await catch_up(
        sessions=_SESSIONS_5, primary=StubSink(), fallback=StubSink(),
        healthcheck_urls={"premarket": "http://hc/pre", "main": "http://hc/main"},
        **_COMMON_KWARGS,
    )
    # 4 past dates × 2 jobs = 8 missed rows written directly by catch_up — none pinged.
    assert [r for r in recorded if r[2] == "missed"], "sanity: past missed rows were written"
    assert pings == [], f"past missed reconciliation must not ping; got {pings!r}"
```

- [ ] **Step 2: Run tests to verify they fail correctly**

Scaffold: add the `healthcheck_urls` param to `catch_up` but do NOT yet thread it into the `dispatch_job` call. Then `test_today_delegation_routes_per_job_url` FAILS on `assert seen == {...}` (values are `None` — kwarg not passed). `test_past_missed_does_not_ping` PASSES (correctly — catch_up never pings; this test guards against a future regression).

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/scheduling/test_catch_up.py`
Expected: routing test FAILS on the `seen` assertion.

- [ ] **Step 3: Thread the URL into the today-delegation call**

Add `healthcheck_url=(healthcheck_urls or {}).get(job_id, "")` to the `dispatch_job(...)` call inside `catch_up`'s `d == today` branch.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/scheduling/test_catch_up.py`
Expected: all passed (2 new + 4 existing). Existing tests pass because `healthcheck_urls` defaults to `None` and their `stub_dispatch_job` ignores extra kwargs.

- [ ] **Step 5: Commit**

```bash
git add marketwind/scheduling/dispatch.py tests/scheduling/test_catch_up.py
git commit -m "feat(scheduling): catch_up routes per-job healthcheck URLs; past-missed never pings"
```

---

### Task 5: `run_scheduler` wiring (live entrypoint)

**Files:**
- Modify: `marketwind/scheduling/__main__.py` (`run_scheduler`, `# pragma: no cover - live`)

**Contract (fix exactly):**
- In `run_scheduler`, after `label_prefix` is resolved, build:
  ```python
  healthcheck_urls = {
      "premarket": settings.healthcheck_url_premarket,
      "main": settings.healthcheck_url_main,
  }
  ```
- Pass `healthcheck_urls=healthcheck_urls` into the `catch_up(...)` call.
- In the `_dispatch(job_id)` closure, pass `healthcheck_url=healthcheck_urls.get(job_id, "")` into the `dispatch_job(...)` call.
- The manual `main()` entrypoint is left unchanged — the dead-man's switch is a daemon concern; `main()` dispatches at `""` (disabled).

This mirrors exactly how `label_prefix` is already threaded through both call sites.

- [ ] **Step 1: Make the edits**

Add the dict build + thread it into `catch_up` and `_dispatch` as specified. This code is `# pragma: no cover - live` (no unit test — it wires live singletons).

- [ ] **Step 2: Verify import + full scheduling suite green**

Run:
```
PYTHONPATH=. .venv/Scripts/python.exe -c "import marketwind.scheduling.__main__"
PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/scheduling
```
Expected: import OK (no syntax/name errors); full `tests/scheduling` suite passes.

- [ ] **Step 3: Commit**

```bash
git add marketwind/scheduling/__main__.py
git commit -m "feat(scheduling): thread per-job healthcheck URLs through run_scheduler"
```

---

### Task 6: Deploy config passthroughs

**Files:**
- Modify: `docker-compose.yml` (scheduler service `environment:` block)
- Modify: `.env.example`

**Contract (fix exactly):**
- In `docker-compose.yml`, add to the `scheduler` service `environment:` block:
  ```yaml
      HEALTHCHECK_URL_PREMARKET: ${HEALTHCHECK_URL_PREMARKET:-}
      HEALTHCHECK_URL_MAIN: ${HEALTHCHECK_URL_MAIN:-}
  ```
  (default empty ⇒ disabled, matching the other optional passthroughs like `OPENAI_API_KEY`.)
- In `.env.example`, add under the "Scheduler daemon" block a documented pair, commented out:
  ```
  # Dead-man's switch — per-job Healthchecks ping URLs (see docs/runbooks/deadman-switch.md).
  # Empty/unset = disabled (no external check-in). Set only after the second host is provisioned.
  # HEALTHCHECK_URL_PREMARKET=https://<second-host>/ping/<premarket-uuid>
  # HEALTHCHECK_URL_MAIN=https://<second-host>/ping/<main-uuid>
  ```

- [ ] **Step 1: Make the edits**

- [ ] **Step 2: Verify compose config parses**

Run: `docker compose config` (from repo root)
Expected: renders without error; the two new env keys appear under the scheduler service with empty values.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "chore(deploy): pass HEALTHCHECK_URL_PREMARKET/MAIN to scheduler service"
```

---

### Task 7: Owner-run ops runbook

**Files:**
- Create: `docs/runbooks/deadman-switch.md`

**Contract:** Mirror the structure of `docs/runbooks/go-live-smoke.md`. A short numbered runbook the owner executes when provisioning the second host. The code is buildable/testable now, offline, without the host; the runbook does NOT block the code (state this as a scope boundary at the end). Six steps, per spec §7:

1. Provision a second host — a *different* box from the report node (different provider/region preferred; a cheap VPS or home box suffices). Rationale: a watcher co-located on the report node dies with it.
2. Deploy Healthchecks on it (its own docker-compose stack).
3. Create two checks (`premarket`, `main`), each **period = 1 day, grace = 2–3 h**; copy the two ping URLs.
4. Wire integrations: email → `chishencsz@icloud.com`; Bark → the owner's Bark server/key. **Never WeChat** (W2 is "the WeChat channel is down").
5. Set the URLs on the report node (`HEALTHCHECK_URL_PREMARKET` / `HEALTHCHECK_URL_MAIN` in `.env`), restart the daemon.
6. Verify both directions: one delivered dispatch → check goes green; then stop the daemon (or break the channel) past grace → confirm **email + Bark both fire**.

Include a one-line "what this closes" (W1 + W2) and the accepted non-closure (if the second host is also down at deadline, no page — bounded by choosing an independent, more-reliable host).

- [ ] **Step 1: Write the runbook** following `go-live-smoke.md`'s tone and the six steps above.

- [ ] **Step 2: Commit**

```bash
git add docs/runbooks/deadman-switch.md
git commit -m "docs(runbook): add owner-run dead-man's switch provisioning runbook"
```

---

### Task 8: Progress note + GAPS update

**Files:**
- Create: `docs/progress/deadman-switch.md`
- Modify: `docs/GAPS.md` (G1.3 status)

**Contract:** Per CLAUDE.md §8.6, a lightweight progress note (a table of modules + commits + invariants proven), NOT a full design doc. Update GAPS.md G1.3 to reflect that the daemon-side dead-man's switch is built + tested offline, with the second-host provisioning deferred to the owner-run runbook (link it).

- [ ] **Step 1: Write `docs/progress/deadman-switch.md`**

Cover: what each module does (`deadman.py`, the `dispatch_job`/`catch_up` threading, config, deploy), the commits, and the key invariants:
- Ping fires iff a message reached the owner (§2 contract); the only two suppressors are W1 (nothing ran) and W2 (send raised before ping).
- `check_in` never raises into `dispatch_job` (best-effort, biased to false-page over silent-miss).
- Empty URL ⇒ disabled (tests/dry-run/local never ping).
- past-date `missed` reconciliation never pings.

- [ ] **Step 2: Update GAPS.md G1.3**

Mark the code portion done (buildable/tested offline); note the second-host provisioning is owner-run per `docs/runbooks/deadman-switch.md`.

- [ ] **Step 3: Run the full scheduling suite one final time**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/scheduling tests/orchestration`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add docs/progress/deadman-switch.md docs/GAPS.md
git commit -m "docs: dead-man's switch progress note + G1.3 status update"
```

---

## Self-Review

**Spec coverage (against `2026-07-07-deadman-switch-design.md`):**
- §3.1 `deadman.py` → Task 1 ✓
- §3.2 config → Task 2 ✓
- §3.3 `dispatch.py` dispatch_job seam → Task 3 ✓; catch_up no-ping → Task 4 ✓
- §3.4 `run_scheduler` wiring → Task 5 ✓
- §3.5 deploy config → Task 6 ✓
- §6 testing strategy: `check_in` (Task 1), dispatch contract incl. W2 (Task 3), catch_up past-missed + per-job routing (Task 4), config defaults (Task 2) ✓
- §7 runbook → Task 7 ✓
- §8 close/not-close documented in runbook + progress note (Tasks 7, 8) ✓

**Type consistency:** `check_in(url: str | None, *, post=...) -> None` used identically in Tasks 1 & 3. `dispatch_job(..., healthcheck_url: str = "")` used in Task 3, called with that kwarg in Task 4 & 5. `catch_up(..., healthcheck_urls: dict[str, str] | None = None)` defined Task 4, called with dict in Task 5. `settings.healthcheck_url_premarket` / `healthcheck_url_main` defined Task 2, read in Tasks 5 & 6. Env keys `HEALTHCHECK_URL_PREMARKET` / `HEALTHCHECK_URL_MAIN` consistent Tasks 6. All consistent.

**Placeholder scan:** No TBD/TODO. Every code step shows exact contract; test bodies are given verbatim (RED assertions pinned); impl described in prose per controller altitude.

**Controller-altitude check:** implementation bodies of `check_in`, the `dispatch_job` line, and the `catch_up` threading are described, not pre-written in full — but signatures, the exact ping-placement, the RED assertions (esp. the W2 "no ping" assertion), and spec-critical literals (URL routing, empty-default disable gate) are fixed. Test code is closer to verbatim, deliberately, because the RED assertion is what the harness is on the hook for.
