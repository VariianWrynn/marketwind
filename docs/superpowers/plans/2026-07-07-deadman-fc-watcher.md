# Dead-man's Switch FC Watcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the external liveness watchdog as two small Aliyun Function Compute (FC) functions plus one OSS state bucket, so the *absence* of the daemon's daily check-in becomes a Bark push originating outside the report node.

**Architecture:** A `ping` HTTP function records each job's last check-in to an OSS object; a `check` timer function (hourly) reads those objects and, when a job is overdue past `period+grace` and not yet alerted, POSTs a Bark push. All business logic is pure and injected with fake OSS/Bark clients for offline tests; the FC-runtime entrypoints and the real OSS/HTTP clients are thin `# pragma: no cover` seams. The daemon side is unchanged — it already GETs a URL via `deadman.check_in`; the `ping` URL just becomes that URL.

**Tech Stack:** Python 3.11+, Aliyun FC (event-style handlers), Aliyun OSS (`oss2`), Serverless Devs (`s.yaml`), Bark (HTTP push), pytest.

**Spec:** `docs/superpowers/specs/2026-07-07-deadman-fc-watcher-design.md`. **Daemon contract (unchanged):** `docs/superpowers/specs/2026-07-07-deadman-switch-design.md` §2.

---

## Conventions (read once, apply to every task)

- **Everything lives in the self-contained deploy dir** `deploy/deadman-fc/`. It must **not** import the `marketwind` package (FC zips this dir independently).
- **Test run command** (Windows venv, from repo root):
  ```
  PYTHONPATH=deploy/deadman-fc .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q deploy/deadman-fc/tests
  ```
  Single file: append the file path.
- **RED discipline (CLAUDE.md §8):** every behavioral test must fail on an **assertion**, not a bare `ImportError`. For a brand-new module, first scaffold a minimal stub (module + signature returning a wrong sentinel) so the test *runs*, then watch the assertion fail, then implement. The one allowed exception is the pure-construction import of the `State`/`Config` dataclasses.
- **Spec-critical literals (do not paraphrase):** OSS key = `state/{job}.json`; JSON fields `last_ping` (ISO-8601) and `alerted` (bool); defaults `PERIOD_SECONDS=86400`, `GRACE_SECONDS=10800`, `JOBS=premarket,main`; deadline = `last_ping + period + grace`; ping query param name = `job`; HTTP statuses `200`/`400`; Bark URL = `{base}/{key}/{quote(title)}/{quote(body)}`.
- **`FakeStore`** (used in several test files — define it inline in each, it is 4 lines, keep tests self-contained):
  ```python
  class FakeStore:
      def __init__(self):
          self.objects = {}
      def get(self, key):
          return self.objects.get(key)
      def put(self, key, data):
          self.objects[key] = data
  ```

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `deploy/deadman-fc/watcher/__init__.py` | package marker (empty) | 1 |
| `deploy/deadman-fc/watcher/config.py` | `Config` frozen dataclass + `load(env)` | 1 |
| `deploy/deadman-fc/watcher/state.py` | `ObjectStore` protocol, `State` dataclass, `read_state`/`put_ping`/`mark_alerted` | 2 |
| `deploy/deadman-fc/watcher/oss_store.py` | real `oss2` adapter implementing `ObjectStore` (`# pragma: no cover`) | 2 |
| `deploy/deadman-fc/watcher/bark.py` | `send_bark(cfg, title, body, *, post) -> bool` | 3 |
| `deploy/deadman-fc/watcher/ping_handler.py` | `process_ping(...)` (pure) + `handler(event, context)` (pragma) | 4 |
| `deploy/deadman-fc/watcher/check_handler.py` | `run_check(...)` (pure) + `handler(event, context)` (pragma) | 5 |
| `deploy/deadman-fc/s.yaml` · `requirements.txt` · `README.md` | deploy manifest, deps, owner runbook | 6 |
| old spec/runbook banners · `docs/GAPS.md` · `docs/progress/deadman-switch.md` | supersession reconciliation | 7 |

---

## Task 1: Config loader

**Files:**
- Create: `deploy/deadman-fc/watcher/__init__.py` (empty)
- Create: `deploy/deadman-fc/watcher/config.py`
- Test: `deploy/deadman-fc/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# deploy/deadman-fc/tests/test_config.py
from watcher.config import Config, load


def test_load_reads_full_env():
    cfg = load({
        "OSS_BUCKET": "mw-deadman",
        "OSS_ENDPOINT": "oss-cn-hangzhou-internal.aliyuncs.com",
        "JOBS": "premarket,main",
        "PERIOD_SECONDS": "3600",
        "GRACE_SECONDS": "600",
        "BARK_BASE_URL": "https://api.day.app",
        "BARK_KEY": "abc123",
    })
    assert cfg == Config(
        oss_bucket="mw-deadman",
        oss_endpoint="oss-cn-hangzhou-internal.aliyuncs.com",
        jobs=("premarket", "main"),
        period_seconds=3600,
        grace_seconds=600,
        bark_base_url="https://api.day.app",
        bark_key="abc123",
    )


def test_load_applies_defaults():
    cfg = load({})
    assert cfg.jobs == ("premarket", "main")
    assert cfg.period_seconds == 86400
    assert cfg.grace_seconds == 10800
    assert cfg.oss_bucket == ""
    assert cfg.bark_key == ""
```

- [ ] **Step 2: Scaffold a stub, then verify the test fails on an assertion**

Create `config.py` with the real `Config` dataclass (so construction/equality works) but a **stub** `load` that returns defaults ignoring `env` — e.g. `return Config(oss_bucket="", oss_endpoint="", jobs=("premarket", "main"), period_seconds=86400, grace_seconds=10800, bark_base_url="", bark_key="")`.
Run: `PYTHONPATH=deploy/deadman-fc .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q deploy/deadman-fc/tests/test_config.py`
Expected: `test_load_reads_full_env` FAILS on the equality assertion (stub returns defaults, not the env values). `test_load_applies_defaults` passes — that is fine; the RED we care about is the full-env assertion failing for the right reason (values, not import).

- [ ] **Step 3: Implement `load`**

`Config` is a `@dataclass(frozen=True)` with fields exactly: `oss_bucket: str`, `oss_endpoint: str`, `jobs: tuple[str, ...]`, `period_seconds: int`, `grace_seconds: int`, `bark_base_url: str`, `bark_key: str`.
`load(env: Mapping[str, str] | None = None) -> Config`: default `env` to `os.environ`. Read strings with `env.get(KEY, "")` for `OSS_BUCKET`/`OSS_ENDPOINT`/`BARK_BASE_URL`/`BARK_KEY`. Parse `JOBS` = `tuple(j.strip() for j in env.get("JOBS", "premarket,main").split(",") if j.strip())`. Parse `PERIOD_SECONDS`/`GRACE_SECONDS` with `int(env.get(KEY, "<default>"))` using defaults `86400`/`10800`.

- [ ] **Step 4: Run test to verify it passes**

Run the Step-2 command. Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add deploy/deadman-fc/watcher/__init__.py deploy/deadman-fc/watcher/config.py deploy/deadman-fc/tests/test_config.py
git commit -m "feat(deadman-fc): config loader from env"
```

---

## Task 2: OSS state layer

**Files:**
- Create: `deploy/deadman-fc/watcher/state.py`
- Create: `deploy/deadman-fc/watcher/oss_store.py` (`# pragma: no cover`, no unit test — real-wire integration seam)
- Test: `deploy/deadman-fc/tests/test_state.py`

- [ ] **Step 1: Write the failing test**

```python
# deploy/deadman-fc/tests/test_state.py
from datetime import datetime, timezone

from watcher.state import State, read_state, put_ping, mark_alerted


class FakeStore:
    def __init__(self):
        self.objects = {}
    def get(self, key):
        return self.objects.get(key)
    def put(self, key, data):
        self.objects[key] = data


NOW = datetime(2026, 7, 7, 5, 0, tzinfo=timezone.utc)


def test_put_ping_then_read_round_trips():
    s = FakeStore()
    put_ping(s, "premarket", NOW)
    assert "state/premarket.json" in s.objects
    assert read_state(s, "premarket") == State(last_ping=NOW, alerted=False)


def test_read_state_missing_returns_none():
    assert read_state(FakeStore(), "premarket") is None


def test_mark_alerted_sets_flag_preserving_last_ping():
    s = FakeStore()
    put_ping(s, "main", NOW)
    mark_alerted(s, "main")
    assert read_state(s, "main") == State(last_ping=NOW, alerted=True)
```

- [ ] **Step 2: Scaffold a stub, then verify the test fails on an assertion**

Create `state.py` with the real `State` dataclass and stub functions that run but return wrong values: `read_state` returns `None` always; `put_ping`/`mark_alerted` do nothing.
Run: `PYTHONPATH=deploy/deadman-fc .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q deploy/deadman-fc/tests/test_state.py`
Expected: `test_put_ping_then_read_round_trips` FAILS on `"state/premarket.json" in s.objects` (nothing written) — an assertion failure, not an import error. (`test_read_state_missing_returns_none` passes with the stub — acceptable.)

- [ ] **Step 3: Implement the state layer**

Define `ObjectStore` as a `typing.Protocol` with `get(self, key: str) -> bytes | None` and `put(self, key: str, data: bytes) -> None`.
`State` = `@dataclass(frozen=True)` with `last_ping: datetime`, `alerted: bool`.
Key helper: `_key(job) -> f"state/{job}.json"`.
- `put_ping(store, job, now)`: `store.put(_key(job), json.dumps({"last_ping": now.isoformat(), "alerted": False}).encode())`.
- `read_state(store, job)`: `raw = store.get(_key(job))`; if `raw is None` return `None`; `d = json.loads(raw)`; return `State(datetime.fromisoformat(d["last_ping"]), d["alerted"])`.
- `mark_alerted(store, job)`: `st = read_state(store, job)`; if `st is None` return; `store.put(_key(job), json.dumps({"last_ping": st.last_ping.isoformat(), "alerted": True}).encode())`.

- [ ] **Step 4: Create the real OSS adapter (no test — pragma seam)**

Create `oss_store.py` with `# pragma: no cover` on the class body. It implements `ObjectStore` over `oss2`. `import oss2` at module top is safe because nothing imported by tests imports this module (handlers import it lazily inside their pragma entrypoints).
Prose: `class OssObjectStore` constructed from `(endpoint: str, bucket: str, credentials)` where `credentials` carries `access_key_id`, `access_key_secret`, `security_token` (supplied by the FC runtime `context.credentials` — confirm exact attribute names against the FC Python runtime at deploy time; this is an integration seam, do not trust this plan's guess). Build `auth = oss2.StsAuth(id, secret, token)` and `bucket_obj = oss2.Bucket(auth, "https://"+endpoint, bucket)`. `get(key)`: `try: return bucket_obj.get_object(key).read()` `except oss2.exceptions.NoSuchKey: return None`. `put(key, data)`: `bucket_obj.put_object(key, data)`.

- [ ] **Step 5: Run test to verify it passes**

Run the Step-2 command. Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add deploy/deadman-fc/watcher/state.py deploy/deadman-fc/watcher/oss_store.py deploy/deadman-fc/tests/test_state.py
git commit -m "feat(deadman-fc): OSS state layer (protocol + oss2 adapter)"
```

---

## Task 3: Bark sender

**Files:**
- Create: `deploy/deadman-fc/watcher/bark.py`
- Test: `deploy/deadman-fc/tests/test_bark.py`

- [ ] **Step 1: Write the failing test**

```python
# deploy/deadman-fc/tests/test_bark.py
from urllib.parse import quote

from watcher.config import Config
from watcher.bark import send_bark


def _cfg():
    return Config(
        oss_bucket="b", oss_endpoint="e", jobs=("premarket", "main"),
        period_seconds=86400, grace_seconds=10800,
        bark_base_url="https://api.day.app", bark_key="KEY",
    )


def test_send_bark_builds_expected_url_and_returns_true():
    calls = []
    ok = send_bark(_cfg(), "Title X", "Body Y", post=calls.append)
    assert ok is True
    assert calls == [f"https://api.day.app/KEY/{quote('Title X')}/{quote('Body Y')}"]


def test_send_bark_swallows_poster_error_and_returns_false():
    def boom(url):
        raise RuntimeError("network down")
    ok = send_bark(_cfg(), "t", "b", post=boom)
    assert ok is False
```

- [ ] **Step 2: Scaffold a stub, then verify the test fails on an assertion**

Create `bark.py` with `send_bark(cfg, title, body, *, post=_http_post) -> bool` stubbed to `return False` without calling `post`.
Run: `PYTHONPATH=deploy/deadman-fc .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q deploy/deadman-fc/tests/test_bark.py`
Expected: `test_send_bark_builds_expected_url_and_returns_true` FAILS on `ok is True` / `calls == [...]` (stub returns False, never calls post). Assertion failure, not import.

- [ ] **Step 3: Implement `send_bark`**

`_http_post(url: str) -> None` (`# pragma: no cover`): `urllib.request.urlopen(url, timeout=5)`.
`send_bark(cfg, title, body, *, post=_http_post) -> bool`: build `url = f"{cfg.bark_base_url.rstrip('/')}/{cfg.bark_key}/{quote(title)}/{quote(body)}"` (`from urllib.parse import quote`). `try: post(url); return True` `except Exception: logger.warning("bark push failed: %s", ...); return False`. Returning a bool (not raising) is the contract the `check` handler relies on to decide whether to set `alerted`.

- [ ] **Step 4: Run test to verify it passes**

Run the Step-2 command. Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add deploy/deadman-fc/watcher/bark.py deploy/deadman-fc/tests/test_bark.py
git commit -m "feat(deadman-fc): bark sender (bool-returning, best-effort)"
```

---

## Task 4: Ping handler

**Files:**
- Create: `deploy/deadman-fc/watcher/ping_handler.py`
- Test: `deploy/deadman-fc/tests/test_ping_handler.py`

- [ ] **Step 1: Write the failing test**

```python
# deploy/deadman-fc/tests/test_ping_handler.py
from datetime import datetime, timezone

from watcher.config import Config
from watcher.state import read_state, State
from watcher.ping_handler import process_ping


class FakeStore:
    def __init__(self):
        self.objects = {}
    def get(self, key):
        return self.objects.get(key)
    def put(self, key, data):
        self.objects[key] = data


def _cfg():
    return Config(
        oss_bucket="b", oss_endpoint="e", jobs=("premarket", "main"),
        period_seconds=86400, grace_seconds=10800,
        bark_base_url="https://api.day.app", bark_key="KEY",
    )


NOW = datetime(2026, 7, 7, 5, 0, tzinfo=timezone.utc)


def test_valid_job_writes_and_returns_200():
    s = FakeStore()
    code = process_ping(s, _cfg(), "premarket", NOW)
    assert code == 200
    assert read_state(s, "premarket") == State(last_ping=NOW, alerted=False)


def test_unknown_job_returns_400_and_writes_nothing():
    s = FakeStore()
    code = process_ping(s, _cfg(), "bogus", NOW)
    assert code == 400
    assert s.objects == {}


def test_missing_job_returns_400_and_writes_nothing():
    s = FakeStore()
    code = process_ping(s, _cfg(), None, NOW)
    assert code == 400
    assert s.objects == {}
```

- [ ] **Step 2: Scaffold a stub, then verify the test fails on an assertion**

Create `ping_handler.py` with `process_ping(store, cfg, job, now) -> int` stubbed to `return 400` and never writing.
Run: `PYTHONPATH=deploy/deadman-fc .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q deploy/deadman-fc/tests/test_ping_handler.py`
Expected: `test_valid_job_writes_and_returns_200` FAILS on `code == 200` (stub returns 400) — assertion failure, not import. (The two 400 tests pass with the stub — acceptable; the discriminating RED is the 200 path.)

- [ ] **Step 3: Implement `process_ping` + the FC entrypoint**

`process_ping(store, cfg, job, now) -> int`: `if job not in cfg.jobs: return 400`; `put_ping(store, job, now)`; `return 200`.
`handler(event, context)` (`# pragma: no cover`): parse `job` from the HTTP event's query string (FC event-style HTTP function — confirm the exact event shape for query params against the FC Python runtime at deploy; e.g. `event["queryParameters"]["job"]` after `json.loads` if `event` is a JSON string). Build the real store lazily: `from .oss_store import OssObjectStore`; `cfg = load()`; `store = OssObjectStore(cfg.oss_endpoint, cfg.oss_bucket, context.credentials)`; `code = process_ping(store, cfg, job, datetime.now(timezone.utc))`; return an FC HTTP response `{"statusCode": code, "body": "ok" if code == 200 else "unknown job"}`.

- [ ] **Step 4: Run test to verify it passes**

Run the Step-2 command. Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add deploy/deadman-fc/watcher/ping_handler.py deploy/deadman-fc/tests/test_ping_handler.py
git commit -m "feat(deadman-fc): ping handler records check-in, rejects unknown job"
```

---

## Task 5: Check handler (the crux)

**Files:**
- Create: `deploy/deadman-fc/watcher/check_handler.py`
- Test: `deploy/deadman-fc/tests/test_check_handler.py`

- [ ] **Step 1: Write the failing test**

```python
# deploy/deadman-fc/tests/test_check_handler.py
from datetime import datetime, timedelta, timezone

from watcher.config import Config
from watcher.state import put_ping, mark_alerted, read_state
from watcher.check_handler import run_check


class FakeStore:
    def __init__(self):
        self.objects = {}
    def get(self, key):
        return self.objects.get(key)
    def put(self, key, data):
        self.objects[key] = data


def _cfg(jobs=("premarket", "main")):
    return Config(
        oss_bucket="b", oss_endpoint="e", jobs=jobs,
        period_seconds=86400, grace_seconds=10800,
        bark_base_url="https://api.day.app", bark_key="KEY",
    )


NOW = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)
OVERDUE = NOW - timedelta(days=1, hours=4)   # past period(1d)+grace(3h)
FRESH = NOW - timedelta(hours=2)             # well inside the deadline


def _recorder(result=True):
    calls = []
    def bark(cfg, title, body):
        calls.append((title, body))
        return result
    return bark, calls


def test_overdue_not_alerted_pages_once_and_marks():
    s = FakeStore()
    put_ping(s, "premarket", OVERDUE)
    bark, calls = _recorder(True)
    paged = run_check(s, _cfg(("premarket",)), NOW, bark=bark)
    assert paged == ["premarket"]
    assert len(calls) == 1
    assert read_state(s, "premarket").alerted is True


def test_overdue_already_alerted_does_not_page():
    s = FakeStore()
    put_ping(s, "premarket", OVERDUE)
    mark_alerted(s, "premarket")
    bark, calls = _recorder(True)
    paged = run_check(s, _cfg(("premarket",)), NOW, bark=bark)
    assert paged == []
    assert calls == []


def test_within_deadline_does_not_page():
    s = FakeStore()
    put_ping(s, "premarket", FRESH)
    bark, calls = _recorder(True)
    paged = run_check(s, _cfg(("premarket",)), NOW, bark=bark)
    assert paged == []
    assert calls == []


def test_not_armed_does_not_page():
    s = FakeStore()  # never pinged
    bark, calls = _recorder(True)
    paged = run_check(s, _cfg(("premarket",)), NOW, bark=bark)
    assert paged == []
    assert calls == []


def test_only_overdue_job_pages_when_other_is_healthy():
    s = FakeStore()
    put_ping(s, "premarket", OVERDUE)
    put_ping(s, "main", FRESH)
    bark, calls = _recorder(True)
    paged = run_check(s, _cfg(("premarket", "main")), NOW, bark=bark)
    assert paged == ["premarket"]


def test_bark_failure_leaves_unalerted_for_retry():
    s = FakeStore()
    put_ping(s, "premarket", OVERDUE)
    bark, calls = _recorder(False)   # delivery failed
    paged = run_check(s, _cfg(("premarket",)), NOW, bark=bark)
    assert paged == []
    assert read_state(s, "premarket").alerted is False


def test_one_job_exception_does_not_block_the_other():
    s = FakeStore()
    put_ping(s, "premarket", OVERDUE)
    put_ping(s, "main", OVERDUE)
    def bark(cfg, title, body):
        if "premarket" in title:
            raise RuntimeError("boom")
        return True
    paged = run_check(s, _cfg(("premarket", "main")), NOW, bark=bark)
    assert paged == ["main"]
```

- [ ] **Step 2: Scaffold a stub, then verify the test fails on an assertion**

Create `check_handler.py` with `run_check(store, cfg, now, *, bark=send_bark) -> list[str]` stubbed to `return []` without calling `bark`.
Run: `PYTHONPATH=deploy/deadman-fc .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q deploy/deadman-fc/tests/test_check_handler.py`
Expected: `test_overdue_not_alerted_pages_once_and_marks` FAILS on `paged == ["premarket"]` (stub returns `[]`) — assertion failure, not import. (The "does not page" tests pass with the stub — acceptable; the discriminating REDs are the paging cases.)

- [ ] **Step 3: Implement `run_check` + the FC entrypoint**

`run_check(store, cfg, now, *, bark=send_bark) -> list[str]`:
```
paged = []
for job in cfg.jobs:
    try:
        st = read_state(store, job)
        if st is None:                      # not armed
            continue
        deadline = st.last_ping + timedelta(seconds=cfg.period_seconds + cfg.grace_seconds)
        if now <= deadline:                 # healthy
            continue
        if st.alerted:                      # already paged this silence
            continue
        title = f"MarketWind watchdog: {job} missed check-in"
        body = (f"No '{job}' check-in since {st.last_ping:%Y-%m-%d %H:%M UTC}. "
                f"The morning report may not have been delivered — check the node.")
        if bark(cfg, title, body):
            mark_alerted(store, job)
            paged.append(job)
    except Exception:
        logger.exception("check failed for job %s", job)
        continue
return paged
```
`handler(event, context)` (`# pragma: no cover`): `from .oss_store import OssObjectStore`; `cfg = load()`; `store = OssObjectStore(cfg.oss_endpoint, cfg.oss_bucket, context.credentials)`; `run_check(store, cfg, datetime.now(timezone.utc))`; return `{"paged": ...}` for the FC log.

- [ ] **Step 4: Run test to verify it passes**

Run the Step-2 command. Expected: 7 passed.

- [ ] **Step 5: Run the whole suite**

Run: `PYTHONPATH=deploy/deadman-fc .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q deploy/deadman-fc/tests`
Expected: 17 passed (2 config + 3 state + 2 bark + 3 ping + 7 check).

- [ ] **Step 6: Commit**

```bash
git add deploy/deadman-fc/watcher/check_handler.py deploy/deadman-fc/tests/test_check_handler.py
git commit -m "feat(deadman-fc): check handler pages overdue jobs (the crux)"
```

---

## Task 6: Deploy manifest, deps, owner runbook

**Files:**
- Create: `deploy/deadman-fc/requirements.txt`
- Create: `deploy/deadman-fc/s.yaml`
- Create: `deploy/deadman-fc/README.md`

No unit tests (config + docs). Verification is a YAML parse + a content check.

- [ ] **Step 1: Write `requirements.txt`**

```
oss2>=2.18
```

- [ ] **Step 2: Write `s.yaml`**

A Serverless Devs manifest declaring one FC service with two functions:
- `ping` — runtime `python3.10` (or the current FC Python runtime), handler `watcher.ping_handler.handler`, an **HTTP trigger** with `authType: anonymous` and methods `["GET"]`, code dir `./`.
- `check` — same runtime, handler `watcher.check_handler.handler`, a **timer trigger** with cron `0 0 * * * *` (hourly; FC cron is 6-field seconds-first) and `enable: true`.
- Both functions' `environmentVariables`: `OSS_BUCKET`, `OSS_ENDPOINT`, `JOBS: premarket,main`, `PERIOD_SECONDS: "86400"`, `GRACE_SECONDS: "10800"`; `check` additionally `BARK_BASE_URL`, `BARK_KEY`. Use `${env(...)}` / Serverless Devs variables so secrets are supplied at deploy, never committed.
- Reference the FC service **role** (`role: ${env(FC_SERVICE_ROLE_ARN)}`) that grants OSS read/write, so the runtime `context.credentials` can reach the bucket.

Confirm the exact `s.yaml` schema keys against the installed Serverless Devs / `fc3` component version at author time (this is an external-tool schema — verify, do not guess field names blindly).

- [ ] **Step 3: Write `README.md` (owner deploy + verify runbook)**

Six steps mirroring the spec §8: (1) create a private OSS bucket in a domestic region; (2) create/assign an FC service RAM role with read/write on that bucket, export its ARN as `FC_SERVICE_ROLE_ARN`; (3) export `BARK_KEY`, `BARK_BASE_URL`, `OSS_BUCKET`, `OSS_ENDPOINT`; (4) `s deploy`; (5) copy the two `ping` HTTP-trigger URLs into the report node `.env` as `HEALTHCHECK_URL_PREMARKET=<url>?job=premarket` and `HEALTHCHECK_URL_MAIN=<url>?job=main`, restart the daemon; (6) verify both directions — trigger a delivered dispatch and confirm `state/<job>.json` gains a fresh `last_ping`; then leave a job silent past `period+grace` (or temporarily set `GRACE_SECONDS` small) and confirm a single Bark push fires. Include a PASS/FAIL line per step, matching the tone of `docs/runbooks/deadman-switch.md`.

- [ ] **Step 4: Verify the manifest parses**

Run: `.venv/Scripts/python.exe -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('deploy/deadman-fc/s.yaml').read_text(encoding='utf-8')); print('s.yaml parses')"`
Expected: `s.yaml parses`

- [ ] **Step 5: Commit**

```bash
git add deploy/deadman-fc/requirements.txt deploy/deadman-fc/s.yaml deploy/deadman-fc/README.md
git commit -m "feat(deadman-fc): serverless devs manifest, deps, owner deploy runbook"
```

---

## Task 7: Documentation reconciliation (supersession)

**Files:**
- Modify: `docs/superpowers/specs/2026-07-07-deadman-switch-design.md` (banner near the top)
- Modify: `docs/runbooks/deadman-switch.md` (banner near the top)
- Modify: `docs/GAPS.md` (G1.3 remaining-work line)
- Modify: `docs/progress/deadman-switch.md` (production-watcher pointer)

No code tests. Verification is a grep for the banner text.

- [ ] **Step 1: Add a supersession banner to the old spec**

Immediately under the title of `docs/superpowers/specs/2026-07-07-deadman-switch-design.md`, insert:
```
> **Superseded (watcher only, 2026-07-07):** the watcher-implementation decisions in §1 "Decisions locked" / §7 ops runbook (self-hosted Healthchecks on a second host; email+Bark) are superseded by `2026-07-07-deadman-fc-watcher-design.md` (Aliyun FC serverless watcher, Bark-only). The §2 check-in contract and §3 daemon code in this spec remain in force and unchanged.
```

- [ ] **Step 2: Add a supersession banner to the old runbook**

Immediately under the title of `docs/runbooks/deadman-switch.md`, insert:
```
> **Superseded (2026-07-07):** the production watcher is now the Aliyun FC serverless watchdog — deploy via `deploy/deadman-fc/README.md`. This Healthchecks/second-host procedure is retained only as the historical rehearsal reference; the daemon-side check-in path it describes is unchanged.
```

- [ ] **Step 3: Update GAPS.md G1.3**

In `docs/GAPS.md`, update the G1.3 remaining-work description so the outstanding item reads as: owner-run **Aliyun FC watcher** deploy (`deploy/deadman-fc/README.md`) — OSS bucket + RAM role + Bark key + `s deploy` + wire the two `ping` URLs — replacing the prior "second-host Healthchecks" phrasing. Preserve the surrounding table/format; change only the G1.3 line(s).

- [ ] **Step 4: Update the progress doc pointer**

In `docs/progress/deadman-switch.md`, update the status/"Out of scope" lines so the **production watcher** is named as the FC serverless watchdog (spec `2026-07-07-deadman-fc-watcher-design.md`, deploy `deploy/deadman-fc/`), and note the local Healthchecks run was a rehearsal, not the deployed watcher. Keep it lightweight — a couple of edited lines, no rewrite.

- [ ] **Step 5: Verify the banners landed**

Run: `.venv/Scripts/python.exe -c "import pathlib; assert 'Superseded' in pathlib.Path('docs/superpowers/specs/2026-07-07-deadman-switch-design.md').read_text(encoding='utf-8'); assert 'Superseded' in pathlib.Path('docs/runbooks/deadman-switch.md').read_text(encoding='utf-8'); print('banners present')"`
Expected: `banners present`

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-07-07-deadman-switch-design.md docs/runbooks/deadman-switch.md docs/GAPS.md docs/progress/deadman-switch.md
git commit -m "docs(deadman): supersede Healthchecks watcher with FC watcher (banners + GAPS + progress)"
```

---

## Self-Review (author's checklist — completed)

**1. Spec coverage:**
- §2 architecture (2 functions + OSS) → Tasks 2–5 (logic) + Task 6 (`s.yaml` wiring). ✅
- §3 file layout → Tasks 1–6 create every listed file (+ `oss_store.py`, `requirements.txt`, noted refinements). ✅
- §4 data model (`state/<job>.json`, `not-armed = None`) → Task 2 (`read_state` None) + Task 5 (`test_not_armed_does_not_page`). ✅
- §5.1 ping behavior (400 unknown, 200 + write) → Task 4. ✅
- §5.2 check behavior (deadline, alerted dedup, per-job isolation, bark-fail retry) → Task 5's seven tests. ✅
- §6 config/secrets → Task 1 (`load`) + Task 6 (`s.yaml` env + role). ✅
- §7 test strategy → each task's verbatim tests; run command in Conventions. ✅
- §8 owner runbook → Task 6 Step 3. ✅
- §0 supersession → Task 7. ✅

**2. Placeholder scan:** No "TBD/TODO/handle edge cases". The two "confirm against the runtime/tool" notes (FC event shape, FC credentials attrs, `s.yaml`/cron schema) are deliberate integration-seam callouts inside `# pragma: no cover` code, per CLAUDE.md §8.7 (verify external behavior; don't guess) — not deferred logic.

**3. Type consistency:** `Config` fields identical across Tasks 1/3/4/5. `ObjectStore.get/put` and `State(last_ping, alerted)` identical across Tasks 2/4/5. `send_bark(cfg, title, body, *, post) -> bool` (Task 3) matches the `bark(cfg, title, body) -> bool` injection point in `run_check` (Task 5). `process_ping(store, cfg, job, now) -> int` and `run_check(store, cfg, now, *, bark) -> list[str]` are used consistently in their tests. `put_ping(store, job, now)` / `read_state(store, job)` / `mark_alerted(store, job)` — no `bucket` param (the store is bucket-scoped) — consistent across all call sites. ✅
