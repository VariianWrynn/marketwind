# Agent-operable deploy — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Read when:** implementing, reviewing, or resuming the agent-operable deploy work. Spec: `docs/superpowers/specs/2026-08-01-agent-operable-deploy-design.md` — read it first; this plan does not restate its reasoning.

**Goal:** Make a fresh Aliyun ECS box reach a verified running MarketWind stack under a third-party (Hermes) agent's control, with the agent's own destructive Docker commands made survivable and its delivery path guarded.

**Architecture:** Six repo guardrails turn the wrong command harmless (named Postgres volume, `COMPOSE_FILE` in `.env`, a gating one-shot `migrate` service, `.dockerignore`, an `app` healthcheck, loopback DB binds). One root-level `DEPLOY.md` carries the procedure the guardrails cannot. A stdlib preflight (`check_hermes.py`) plus a `scheduler` healthcheck protect the hermes delivery path that the deploying agent itself could sever.

**Tech Stack:** Docker Compose v2 · Python 3.11 · pytest + pyyaml (structural assertions) · asyncpg · Markdown docs.

---

## Sequencing constraint — read before starting

**Task 1 must land before Task 4.** Task 4 makes `app` and `scheduler` gate on `migrate` exiting `0`. Today `migrate.py` exits `0` when it finds *no* migration files (spec §3.3.1) — so shipping the gate first would have the stack bless an empty database. Task 1 closes that path. Do not reorder.

Everything after Task 4 is independent and may be executed in any order, but the numbering below is the recommended one (guardrails → preflight → docs).

## File Structure

| File | Created / Modified | Responsibility |
|---|---|---|
| `marketwind/storage/migrate.py` | Modify | Gains `pending_migration_paths()` — the fail-loud guard that makes exit-0 mean "schema applied" |
| `tests/storage/test_migrate_guard.py` | Create | Pins the guard. DB-free (pure path logic) |
| `docker-compose.yml` | Modify | Named `pgdata` volume; `migrate` service; `app` healthcheck; `depends_on` gates |
| `deploy/report-node/docker-compose.prod.yml` | Modify | Loopback binds for postgres/redis; `scheduler` hermes healthcheck |
| `.env.example` | Modify | `COMPOSE_PROJECT_NAME` (active), `COMPOSE_FILE` (commented) |
| `.dockerignore` | Create | Trim the build context |
| `tests/deploy/__init__.py` | Create | Package marker (matches `tests/storage/`, `tests/scheduling/`) |
| `tests/deploy/test_compose_guardrails.py` | Create | Six structural assertions, each pinning a non-obvious constraint |
| `pyproject.toml` | Modify | `pyyaml` dev dependency |
| `deploy/report-node/check_hermes.py` | Create | Stdlib preflight for the hermes delivery path |
| `deploy/report-node/tests/test_check_hermes.py` | Create | Real-filesystem tests (stub-executable pattern) |
| `DEPLOY.md` | Create | The agent-facing deploy + operate procedure |
| `README.md` | Modify | Above-the-fold pointer + repository-map entry |
| `CLAUDE.md` | Modify | §9 document-map row |
| `docs/adr/0004-stack-applies-migrations.md` | Create | Overturn record for owner-run migrations |
| `DECISIONS.md` | Modify | D-32 row referencing ADR-0004 |
| `deploy/report-node/README.md` | Modify | HTTPS→SSH clone; `COMPOSE_FILE` note; §9 rewritten |
| `docs/progress/cloud-cutover-aliyun.md` | Modify | Lines 15 + 31 now describe behaviour this work replaces |
| `docs/progress/agent-operable-deploy.md` | Create | Phase progress note |
| `docs/GAPS.md` | Modify | G0.2 advanced, **not** closed |

## Standing rules for every task

- **The RED must be an assertion or a domain error, never `KeyError` / `ImportError`** (`CLAUDE.md` §8.2). Structural tests read through `.get(...)` with defaults so a missing key surfaces as `assert "migrate" in ...`, not a lookup crash. For new Python modules, scaffold a stub that *reproduces today's behaviour* first, watch the assertion fail, then implement.
- **Report RED assertion text and GREEN output verbatim.** A summary of what a test did is not evidence.
- **Surgical changes** (`CLAUDE.md` §4③). Do not reformat, reorder, or "improve" adjacent YAML, comments, or docs. Every changed line must trace to the task.
- **Test command needs DB env vars for anything importing `marketwind.*`** — `config.py` instantiates `Settings()` at import time and `redis_url` has no default. Prefix:
  ```
  DATABASE_URL=postgresql://marketwind:marketwind@localhost:5432/marketwind REDIS_URL=redis://localhost:6379/0
  ```
  Tests that only parse YAML/text need no prefix.
- **Docker is not available in this worktree.** No task may claim a `docker compose` result. Compose *merge* semantics are verified on the box by `DEPLOY.md` gate 0, by design (spec §7).

---

### Task 1: Close the migrate silent-success path

Spec §3.3.1. **Prerequisite of Task 4.**

**Files:**
- Modify: `marketwind/storage/migrate.py:14-44`
- Create: `tests/storage/test_migrate_guard.py`

**Contract to implement:**

```python
def pending_migration_paths() -> list[Path]:
    """Every migration on disk, in filename order."""
```

Returns `sorted(MIGRATIONS_DIR.glob("*.sql"))`, and **raises `RuntimeError` when that list is empty** — which covers both "directory missing" and "directory present but empty", since `Path.glob` on a nonexistent directory yields nothing. `apply_migrations` iterates this function instead of globbing inline. Nothing else in the file changes.

The error message must name `MIGRATIONS_DIR` and say why an empty result is fatal, e.g. `f"no *.sql migrations under {MIGRATIONS_DIR} — refusing to report success against an unmigrated database"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/storage/test_migrate_guard.py`:

```python
"""The migration runner must not report success when it found nothing to apply.

`MIGRATIONS_DIR` is resolved by walking up from __file__, which lands on
/app/migrations in-container only because `python -m` puts the working directory
first on sys.path. Any shift in resolution empties the glob — and an exit-0 there
would let the compose gate (docker-compose.yml `migrate`) bless an empty database.
"""

import pytest

from marketwind.storage import migrate


def test_pending_paths_raises_when_migrations_dir_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)
    with pytest.raises(RuntimeError):
        migrate.pending_migration_paths()


def test_pending_paths_raises_when_migrations_dir_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path / "nope")
    with pytest.raises(RuntimeError):
        migrate.pending_migration_paths()


def test_pending_paths_returns_the_real_migrations_in_filename_order():
    paths = migrate.pending_migration_paths()
    names = [p.name for p in paths]
    assert names, "the repo ships migrations; an empty result here is the bug above"
    assert names == sorted(names)
    assert all(n.endswith(".sql") for n in names)
```

- [ ] **Step 2: Scaffold today's behaviour so the RED is an assertion, not an ImportError**

Add to `marketwind/storage/migrate.py`, directly below `MIGRATIONS_DIR`, the **unguarded** version — this is exactly what the code does today, extracted:

```python
def pending_migration_paths() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))
```

Do not change `apply_migrations` yet.

- [ ] **Step 3: Run the tests to verify they fail for the right reason**

Run:
```
DATABASE_URL=postgresql://marketwind:marketwind@localhost:5432/marketwind REDIS_URL=redis://localhost:6379/0 python -m pytest tests/storage/test_migrate_guard.py -v
```
Expected: the two `pytest.raises` tests FAIL with `Failed: DID NOT RAISE <class 'RuntimeError'>`; the third PASSES.

That failure text *is* the production bug — capture it verbatim as the RED evidence.

- [ ] **Step 4: Add the guard**

Insert the empty-list check into `pending_migration_paths`, then change `apply_migrations` to iterate `pending_migration_paths()` in place of `sorted(MIGRATIONS_DIR.glob("*.sql"))`.

- [ ] **Step 5: Run the tests to verify they pass**

Run the same command. Expected: `3 passed`.

- [ ] **Step 6: Commit**

```bash
git add marketwind/storage/migrate.py tests/storage/test_migrate_guard.py
git commit -m "fix(migrate): refuse to exit 0 when no migration files were found"
```

---

### Task 2: Named volume for Postgres

Spec §3.1. Adds the first structural test file, so it also lands `pyyaml` and `tests/deploy/`.

**Files:**
- Modify: `docker-compose.yml:2-14`, plus a new top-level `volumes:` block
- Modify: `pyproject.toml:22-28`
- Create: `tests/deploy/__init__.py` (empty), `tests/deploy/test_compose_guardrails.py`

- [ ] **Step 1: Write the failing test**

Create `tests/deploy/__init__.py` (empty) and `tests/deploy/test_compose_guardrails.py`:

```python
"""Structural guards on the compose files.

Only constraints that are NOT obvious from reading the YAML belong here — a test
that restates the file it just parsed is tautological (CLAUDE.md §4②). Each test
below pins something a later editor would plausibly and wrongly simplify away.

Every lookup goes through .get(...) so a missing key fails as an assertion, not a
KeyError — a KeyError fires identically for a good test and a broken one and so
proves nothing (CLAUDE.md §8.2).
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "docker-compose.yml"
PROD = ROOT / "deploy" / "report-node" / "docker-compose.prod.yml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_postgres_data_lives_on_a_named_volume():
    compose = _load(BASE)
    mounts = compose.get("services", {}).get("postgres", {}).get("volumes", []) or []
    assert any(str(m).startswith("pgdata:") for m in mounts), (
        "postgres must mount the named volume pgdata; on an anonymous volume a plain "
        "`docker compose down` destroys the database"
    )
    assert "pgdata" in (compose.get("volumes") or {}), (
        "pgdata must be declared in the top-level volumes: block"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/deploy/test_compose_guardrails.py -v`
Expected: FAIL with `AssertionError: postgres must mount the named volume pgdata; ...`

(If it errors on `import yaml` instead, do Step 3 first, reinstall dev deps, and re-run to get a real RED.)

- [ ] **Step 3: Declare pyyaml as a dev dependency**

In `pyproject.toml`, add `"pyyaml>=6.0",` to the `dev` list in `[project.optional-dependencies]`. Keep the existing entries and their order.

- [ ] **Step 4: Add the volume**

In `docker-compose.yml`, give `postgres` a `volumes:` key and add a top-level `volumes:` block at the end of the file:

```yaml
    volumes:
      - pgdata:/var/lib/postgresql/data
```

```yaml
volumes:
  pgdata:
```

Redis deliberately gets **no** volume — adding one would imply a durability guarantee the system does not rely on (spec §3.1).

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/deploy/test_compose_guardrails.py -v`
Expected: `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml pyproject.toml tests/deploy/__init__.py tests/deploy/test_compose_guardrails.py
git commit -m "feat(compose): put Postgres data on a named volume so \`down\` is survivable"
```

---

### Task 3: `app` healthcheck

Spec §3.5. Sequenced before Task 4 only because Task 4 edits the same `app` block and a healthy `app` is the signal the gate is meant to produce.

**Files:**
- Modify: `docker-compose.yml:26-37` (`app` service)
- Modify: `tests/deploy/test_compose_guardrails.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/deploy/test_compose_guardrails.py`:

```python
def test_app_healthcheck_probes_with_stdlib_python_not_curl():
    app = _load(BASE).get("services", {}).get("app", {})
    probe = app.get("healthcheck", {}).get("test", []) or []
    assert "python" in probe, (
        "the image is python:3.11-slim, which ships neither curl nor wget — a curl "
        "probe would mark app unhealthy forever, the exact false signal this guards"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/deploy/test_compose_guardrails.py -v`
Expected: FAIL with `AssertionError: the image is python:3.11-slim, ...`

- [ ] **Step 3: Add the healthcheck**

Add to the `app` service in `docker-compose.yml`, verbatim:

```yaml
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
```

`GET /health` already returns 200 when Postgres and Redis are both reachable and 503 otherwise (`marketwind/gateway/app.py`), and `urlopen` raises on 503 — so the non-zero exit falls out with no extra logic. `start_period` keeps the container from being marked unhealthy while uvicorn is still binding.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/deploy/test_compose_guardrails.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml tests/deploy/test_compose_guardrails.py
git commit -m "feat(compose): health-gate the app on its own /health endpoint"
```

---

### Task 4: One-shot `migrate` service, gating `app` and `scheduler`

Spec §3.3. **Requires Task 1.** Confirm `pending_migration_paths` is on `master`/HEAD before starting — without it this task ships a gate that can bless an empty database.

**Files:**
- Modify: `docker-compose.yml` (new `migrate` service; `depends_on` on `app` and `scheduler`)
- Modify: `tests/deploy/test_compose_guardrails.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/deploy/test_compose_guardrails.py`:

```python
def test_migrate_service_sets_redis_url_even_though_it_never_uses_redis():
    services = _load(BASE).get("services", {})
    env = services.get("migrate", {}).get("environment", {}) or {}
    assert "REDIS_URL" in env, (
        "config.py declares redis_url with no default and instantiates Settings() at "
        "import time, and .env is not in the image — a migrate service given only "
        "DATABASE_URL dies in pydantic validation, never satisfies "
        "service_completed_successfully, and blocks app+scheduler from ever starting. "
        "This looks unnecessary. It is not. Do not remove it."
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/deploy/test_compose_guardrails.py -v`
Expected: FAIL with `AssertionError: config.py declares redis_url with no default ...`

Confirm it is an `AssertionError` and not a `KeyError` — that is the point of the `.get(...)` chain.

- [ ] **Step 3: Add the service and the gates**

New service in `docker-compose.yml`, verbatim:

```yaml
  migrate:
    build: .
    command: ["python", "-m", "marketwind.storage.migrate"]
    environment:
      DATABASE_URL: postgresql://marketwind:marketwind@postgres:5432/marketwind
      REDIS_URL: redis://redis:6379/0
    depends_on:
      postgres:
        condition: service_healthy
    restart: "no"
```

Then add to **both** `app` and `scheduler`, merged into their existing `depends_on` maps (keep their current `postgres` / `redis` health conditions):

```yaml
      migrate:
        condition: service_completed_successfully
```

Place `migrate` between `redis` and `app` in the file so it reads in dependency order. Add a short comment above it stating that it exits after applying `migrations/*.sql` and that `app`/`scheduler` will not start until it exits `0` — plus the `REDIS_URL` reason in one line, so the trap is visible in the file and not only in the test.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/deploy/test_compose_guardrails.py -v`
Expected: `3 passed`.

- [ ] **Step 5: Confirm the YAML is still well-formed and the gates merged as intended**

Run:
```
python -c "import yaml,sys; c=yaml.safe_load(open('docker-compose.yml',encoding='utf-8')); print(sorted(c['services'])); print(c['services']['app']['depends_on']); print(c['services']['scheduler']['depends_on'])"
```
Expected: services list includes `migrate`; both `depends_on` maps show `migrate: {condition: service_completed_successfully}` **alongside** their pre-existing entries (`app` keeps `postgres` and `redis`; `scheduler` keeps `postgres`).

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml tests/deploy/test_compose_guardrails.py
git commit -m "feat(compose): apply migrations at boot via a gating one-shot service"
```

---

### Task 5: Prod override — loopback DB binds and the hermes healthcheck

Spec §3.6 and §5. Both belong in the prod override, not the base file: the loopback binds would block the owner's host-run tests against published ports, and a hermes healthcheck in base would sit permanently red on a dev machine where `HERMES_BIN` defaults to the bare string `hermes` (`docker-compose.yml:52`).

**Files:**
- Modify: `deploy/report-node/docker-compose.prod.yml`
- Modify: `tests/deploy/test_compose_guardrails.py`

**Contract for the healthcheck.** Two predicates, both required:

```yaml
      test: ["CMD-SHELL", 'test -x "$$HERMES_BIN" && test -x "$$(dirname "$$HERMES_BIN")/python"']
```

- `$$` is Compose's escape for a literal `$` — without it Compose interpolates at parse time and the container gets an empty string.
- The **second** predicate is the load-bearing one. `test -x` follows symlinks, and `<venv>/bin/python` is a symlink into the uv standalone tree that lives *outside* `~/.hermes` (the reason `HERMES_UV_PYTHON_DIR` is mounted at all — see the comment already at `docker-compose.prod.yml:18-22`). If that mount is missing or the interpreter moves, the symlink dangles and the check goes red within a minute — which is precisely the ADR-0001 failure mode that `test -x "$HERMES_BIN"` alone cannot see.
- Task 6's `check_hermes.py` validates this healthcheck's premise (that the sibling `python` exists) **before** the stack comes up, so an unusual venv layout produces a named preflight failure rather than a mystery red row.

- [ ] **Step 1: Write the failing tests**

Append to `tests/deploy/test_compose_guardrails.py`:

```python
def test_prod_binds_postgres_and_redis_to_loopback():
    services = _load(PROD).get("services", {})
    for name in ("postgres", "redis"):
        published = services.get(name, {}).get("ports", []) or []
        assert published, f"{name} must republish on loopback in the prod override"
        assert all(str(p).startswith("127.0.0.1:") for p in published), (
            f"{name} is published on all interfaces by the base file with guessable "
            f"credentials; the prod override must narrow it to loopback (SSH tunnel "
            f"is already the documented access pattern)"
        )


def test_scheduler_healthcheck_also_exercises_the_venv_interpreter():
    sched = _load(PROD).get("services", {}).get("scheduler", {})
    probe = " ".join(str(p) for p in (sched.get("healthcheck", {}).get("test", []) or []))
    assert "HERMES_BIN" in probe, (
        "the scheduler must continuously prove its delivery path; the deploying agent "
        "is the same hermes install the scheduler invokes, and it has host root"
    )
    assert "python" in probe, (
        "testing HERMES_BIN alone cannot see a dangling uv interpreter — the actual "
        "ADR-0001 failure mode. Do not simplify this to `test -x $HERMES_BIN`."
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/deploy/test_compose_guardrails.py -v`
Expected: both new tests FAIL with `AssertionError` (`postgres must republish on loopback ...` and `the scheduler must continuously prove its delivery path ...`). The three earlier tests still pass.

- [ ] **Step 3: Add both to the prod override**

Add `ports:` to the existing `postgres` and `redis` service blocks in `deploy/report-node/docker-compose.prod.yml` (they currently carry only `restart: unless-stopped` — keep it):

```yaml
    ports:
      - "127.0.0.1:5432:5432"
```
```yaml
    ports:
      - "127.0.0.1:6379:6379"
```

Add the healthcheck to the existing `scheduler` block, below its `volumes:`, using the verbatim `test:` line from the contract above, with:

```yaml
      interval: 60s
      timeout: 5s
      retries: 3
      start_period: 20s
```

Precede it with a two-line comment naming ADR-0001 and stating why the interpreter half exists.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/deploy/test_compose_guardrails.py -v`
Expected: `5 passed`.

- [ ] **Step 5: Confirm the `$$` survived YAML parsing**

Run:
```
python -c "import yaml; print(yaml.safe_load(open('deploy/report-node/docker-compose.prod.yml',encoding='utf-8'))['services']['scheduler']['healthcheck']['test'])"
```
Expected output contains the literal `$$HERMES_BIN` (two dollar signs). If it shows one, the escape is wrong and Compose will interpolate it away.

- [ ] **Step 6: Commit**

```bash
git add deploy/report-node/docker-compose.prod.yml tests/deploy/test_compose_guardrails.py
git commit -m "feat(prod): bind DBs to loopback and health-gate the hermes delivery path"
```

---

### Task 6: `check_hermes.py` preflight

Spec §5. Stdlib-only, runnable on a bare host before anything is built, matching `check_keys.py`'s PASS/FAIL/exit contract.

**Files:**
- Create: `deploy/report-node/check_hermes.py`
- Create: `deploy/report-node/tests/test_check_hermes.py`

**Contract to implement:**

```python
DEFAULT_UV_PYTHON_DIR = "/root/.local/share/uv/python/cpython-3.11-linux-x86_64-gnu"

def venv_interpreter(hermes_bin):      # -> str, the sibling `python` of the entrypoint
def check_hermes_bin(env):             # -> ("HERMES_BIN", PASS|FAIL, detail)
def check_venv_interpreter(env):       # -> ("venv interpreter", PASS|FAIL, detail)
def check_interpreter_mounted(env):    # -> ("interpreter under mount", PASS|FAIL, detail)
def main(argv):                        # -> int
```

Reuse `check_keys.py` rather than duplicating its plumbing — it is a sibling file, so:

```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_keys import FAIL, PASS, load_env, summarize
```

Behaviour, in prose:

- `venv_interpreter` joins `dirname(hermes_bin)` with `"python"`. It does not check existence.
- `check_hermes_bin` FAILs if `HERMES_BIN` is unset, if the path is not a file, or if it is not `os.access(..., os.X_OK)`. Each FAIL detail names which of the three it was and echoes the path.
- `check_venv_interpreter` FAILs if the sibling `python` is not executable. `os.access` follows symlinks, so a dangling link into an unmounted uv tree FAILs here — the detail must say so, since that is the whole point. It does not re-check `HERMES_BIN`; when `HERMES_BIN` is unset it FAILs with "HERMES_BIN unset".
- `check_interpreter_mounted` resolves the interpreter with `os.path.realpath` and FAILs unless the result is under `env.get("HERMES_UV_PYTHON_DIR", DEFAULT_UV_PYTHON_DIR)`. Compare with a trailing `os.sep` appended to the directory so `/root/.local/share/uv/python/cpython-3.11-x` does not match a prefix of `/root/.local/share/uv/python/cpython-3.11-xyz`. The FAIL detail must print the **real** resolved directory, because that string is what the operator pastes into `HERMES_UV_PYTHON_DIR`.
- `main` reads the `.env` path from `argv[1]` or `./.env` (same as `check_keys.main`), prints a source line, runs the three checks, renders via `summarize`, returns its exit code.
- Module docstring states what it prevents: an ADR-0001 mid-report `hermes: not found` becoming a pre-deploy failure with a named cause; and that it validates the premise of the `scheduler` healthcheck added in Task 5.

- [ ] **Step 1: Write the failing tests**

Create `deploy/report-node/tests/test_check_hermes.py`. Build a real venv-shaped tree on disk (the stub-executable pattern from `test_backup_script.py:11-30`) rather than mocking `os.path`:

```python
"""Preflight for the hermes delivery path, tested against real files.

The failure this guards is a symlinked interpreter that resolves outside the
directory the prod compose mounts (ADR-0001), so the tests build actual files and
symlinks instead of mocking os.path — a mock cannot dangle.
"""

from __future__ import annotations

import importlib.util
import stat
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "check_hermes.py"
_spec = importlib.util.spec_from_file_location("check_hermes", _MODULE_PATH)
check_hermes = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(check_hermes)

PASS, FAIL = "PASS", "FAIL"


def _venv(tmp_path: Path, *, uv_dir_name="uv-python", interpreter=True):
    """A hermes-shaped venv: bin/hermes plus bin/python -> <uv_dir>/bin/python3.11."""
    bin_dir = tmp_path / "hermes-agent" / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    hermes = bin_dir / "hermes"
    hermes.write_text("#!/bin/sh\nexit 0\n")
    hermes.chmod(hermes.stat().st_mode | stat.S_IEXEC)
    uv_dir = tmp_path / uv_dir_name
    real = uv_dir / "bin" / "python3.11"
    if interpreter:
        real.parent.mkdir(parents=True)
        real.write_text("#!/bin/sh\nexit 0\n")
        real.chmod(real.stat().st_mode | stat.S_IEXEC)
    (bin_dir / "python").symlink_to(real)
    env = {"HERMES_BIN": str(hermes), "HERMES_UV_PYTHON_DIR": str(uv_dir)}
    return env, uv_dir


def test_all_three_pass_on_a_well_formed_venv(tmp_path):
    env, _ = _venv(tmp_path)
    for check in (check_hermes.check_hermes_bin,
                  check_hermes.check_venv_interpreter,
                  check_hermes.check_interpreter_mounted):
        _name, status, detail = check(env)
        assert status == PASS, detail


def test_unset_hermes_bin_fails(tmp_path):
    _name, status, _detail = check_hermes.check_hermes_bin({})
    assert status == FAIL


def test_dangling_interpreter_symlink_fails(tmp_path):
    # The ADR-0001 failure mode: HERMES_UV_PYTHON_DIR not mounted, so the venv's
    # python symlink points at nothing. HERMES_BIN itself is still fine.
    env, _ = _venv(tmp_path, interpreter=False)
    assert check_hermes.check_hermes_bin(env)[1] == PASS
    _name, status, _detail = check_hermes.check_venv_interpreter(env)
    assert status == FAIL


def test_interpreter_outside_the_mounted_dir_fails_and_names_the_real_dir(tmp_path):
    env, _ = _venv(tmp_path)
    env["HERMES_UV_PYTHON_DIR"] = str(tmp_path / "somewhere-else")
    _name, status, detail = check_hermes.check_interpreter_mounted(env)
    assert status == FAIL
    assert str(tmp_path / "uv-python") in detail, (
        "the detail must print the real resolved dir — that string is what the "
        "operator pastes into HERMES_UV_PYTHON_DIR"
    )


def test_main_exits_nonzero_when_hermes_is_missing(tmp_path, monkeypatch):
    # load_env merges the real process environment, so clear the key explicitly —
    # otherwise this test passes or fails depending on the runner's shell.
    monkeypatch.delenv("HERMES_BIN", raising=False)
    assert check_hermes.main(["check_hermes.py", str(tmp_path / "absent.env")]) != 0
```

- [ ] **Step 2: Scaffold a stub so the RED is an assertion**

Create `deploy/report-node/check_hermes.py` with the module docstring, the imports, `DEFAULT_UV_PYTHON_DIR`, and every function from the contract present but returning a wrong sentinel — each check returning `(name, FAIL, "not implemented")` and `main` returning `0`. This makes the module importable so the tests actually run.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest deploy/report-node/tests/test_check_hermes.py -v`

(`testpaths = ["tests"]` in `pyproject.toml` means bare `pytest` will not pick this directory up — pass the path explicitly, as `test_backup_script.py` and `test_check_keys.py` already require.)

Expected: `test_all_three_pass_on_a_well_formed_venv` FAILs with `AssertionError: not implemented`; `test_main_exits_nonzero_when_hermes_is_missing` FAILs with `assert 0 != 0`. The three FAIL-path tests pass against the stub — that is expected and is why the pass-path and `main` tests carry the RED.

- [ ] **Step 4: Implement the three checks and `main`**

Per the contract above. No new dependencies; stdlib only; no type hints (match `check_keys.py`'s style, which targets a bare host interpreter).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest deploy/report-node/tests/test_check_hermes.py -v`
Expected: `6 passed`.

- [ ] **Step 6: Confirm it runs as a script and fails loud**

Run from the repo root:
```
python deploy/report-node/check_hermes.py /nonexistent.env; echo "exit=$?"
```
Expected: a PASS/FAIL table with three FAIL rows, a `3 CHECK(S) FAILED` verdict line, and `exit=1`. (On Windows every path check fails — that is the correct output for this command, not a bug.)

- [ ] **Step 7: Commit**

```bash
git add deploy/report-node/check_hermes.py deploy/report-node/tests/test_check_hermes.py
git commit -m "feat(deploy): preflight the hermes delivery path before the stack builds"
```

---

### Task 7: `COMPOSE_FILE` and `COMPOSE_PROJECT_NAME` in `.env.example`

Spec §3.2.

**Files:**
- Modify: `.env.example`
- Modify: `tests/deploy/test_compose_guardrails.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/deploy/test_compose_guardrails.py`:

```python
def test_env_example_ships_compose_file_commented_and_correctly_ordered():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    hits = [ln for ln in lines if "COMPOSE_FILE=" in ln]
    assert hits, "COMPOSE_FILE must be present in .env.example for the node to uncomment"
    line = hits[0]
    assert line.lstrip().startswith("#"), (
        "must ship COMMENTED OUT — active it breaks the Windows dev box three ways "
        "(path separator, `make dev` launching the prod stack, ${OSS_BUCKET:?} "
        "hard-failing every compose command). DEPLOY.md makes uncommenting an explicit step."
    )
    assert line.split("COMPOSE_FILE=", 1)[1].strip() == (
        "docker-compose.yml:deploy/report-node/docker-compose.prod.yml"
    ), "base file first, prod override second — the override must win"
    assert any(ln.startswith("COMPOSE_PROJECT_NAME=marketwind") for ln in lines), (
        "pin the project name: the pgdata volume is <project>_pgdata, and the project "
        "otherwise derives from the directory — a re-clone into marketwind-1 would "
        "silently attach a different, empty volume"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/deploy/test_compose_guardrails.py -v`
Expected: FAIL with `AssertionError: COMPOSE_FILE must be present in .env.example ...`

- [ ] **Step 3: Add the lines**

Insert at the top of `.env.example`, above the existing `DATABASE_URL` block, verbatim:

```
# Compose wiring. COMPOSE_PROJECT_NAME is pinned because the Postgres volume is
# <project>_pgdata and the project name otherwise derives from the directory name.
COMPOSE_PROJECT_NAME=marketwind
# Report node ONLY — uncomment on the Linux box so bare `docker compose ...` resolves
# to the production stack. Leave commented on dev machines (see DEPLOY.md §3).
#COMPOSE_FILE=docker-compose.yml:deploy/report-node/docker-compose.prod.yml
```

Both keys are inert to the application: `Settings` sets `extra="ignore"` (`marketwind/config.py:44`).

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/deploy/test_compose_guardrails.py -v`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add .env.example tests/deploy/test_compose_guardrails.py
git commit -m "feat(env): make bare \`docker compose\` resolve the prod stack on the node"
```

---

### Task 8: `.dockerignore`

Spec §3.4. No test — a test here would restate the file it just read.

**Files:**
- Create: `.dockerignore`

- [ ] **Step 1: Create the file**

At repo root, verbatim:

```
.git
.env
.venv
**/__pycache__
**/*.pyc
.pytest_cache
marketwind.egg-info
docs/
tests/
deploy/
.claude/
```

The `**/` prefixes are load-bearing: `.dockerignore` patterns anchor at the context root, so a bare `__pycache__` would miss `marketwind/__pycache__/`, which exists in this repo today.

- [ ] **Step 2: Verify no exclusion can affect the image**

Run: `grep -n "^COPY" Dockerfile`
Expected: only `pyproject.toml`, `marketwind`, `migrations`, `citation` are copied — none of which is excluded above. Excluding `.git` is safe because `pyproject.toml:3` pins a static `version = "0.0.0"` with no `setuptools-scm`.

- [ ] **Step 3: Commit**

```bash
git add .dockerignore
git commit -m "chore(build): trim the Docker build context"
```

---

### Task 9: `DEPLOY.md`

Spec §4. Root placement is a deliberate exception to the keep-the-root-clean convention, because this file's entire job is to be found cold by a non-Claude agent.

**Files:**
- Create: `DEPLOY.md`

**Required shape.** Nine numbered sections in this order, plus the opening.

**Opening** — addressed directly to its reader: *if you are an agent operating this repository on the deployment box, this is your file.* State three things: it is complete and self-contained; the compose files are not to be improvised from; **any step whose output does not match what is written must stop and report rather than be worked around.** Add the standard `> **Read when:**` line.

1. **Preconditions** — Docker Engine + Compose v2, host timezone `Asia/Shanghai`, SSH git auth as the repo owner, hermes installed and WeChat-authenticated.
2. **Get the code** — `git clone git@github.com:VariianWrynn/marketwind.git`. State the reason inline: git over HTTPS is reset on this network (`CLAUDE.md` §10), so a future reader does not "fix" it back to `https://`.
3. **Configure** — `cp .env.example .env && chmod 600 .env`; **uncomment `COMPOSE_FILE`** as an explicit, called-out step; then a table of every variable with columns *variable / who supplies it / what breaks without it*. Mark `OPENAI_API_KEY`, `BOCHA_API_KEY`, `HERMES_BIN`, `HERMES_HOST_DIR`, `TZ`, `OSS_BUCKET` as required; `HERMES_UV_PYTHON_DIR`, `WEIXIN_TARGET`, `BACKUP_INTERVAL_SECONDS` as defaulted; `BARK_KEY`, `HEALTHCHECK_URL_*` as owner-supplied and optional. Note that `OSS_BUCKET` must be set even though bucket provisioning is out of scope, because `docker-compose.prod.yml:31` uses `${OSS_BUCKET:?…}` and an unset value hard-fails **every** compose command including `ps` and `config`.
   State once, explicitly, that **all commands run from the repository root** — Compose walks parent directories for `docker-compose.yml` but *not* for `.env`, so from a subdirectory the agent silently gets the dev stack.
4. **Bring the stack up** — the single `docker compose up -d --build`.
5. **Verify** — an ordered gate list, each with its expected output:
   - **Gate 0, before `up`:** `docker compose config`. This is the only cheap on-box check that mechanically proves `COMPOSE_FILE` resolved, that the merge produced `TZ: Asia/Shanghai` on `scheduler`, and that `OSS_BUCKET` interpolated. Say what to look for, by name.
   - **Gate 1:** `python3 deploy/report-node/check_keys.py` — green.
   - **Gate 2:** `python3 deploy/report-node/check_hermes.py` — green.
   - **Gate 3:** `docker compose ps -a` matches this table **exactly**:

     | Service | Expected state | Note |
     |---|---|---|
     | `postgres` | `Up (healthy)` | |
     | `redis` | `Up (healthy)` | |
     | `migrate` | `Exited (0)` | **Only visible with `-a`.** Its absence from plain `docker compose ps` is success, not a fault |
     | `app` | `Up (healthy)` | |
     | `scheduler` | `Up (healthy)` | healthy ⇒ the hermes entrypoint *and* its interpreter resolve |
     | `backup` | `Up` | no healthcheck; it will log failures until the OSS bucket exists — that is the documented intent |

     Say plainly that "all healthy" is **not** the criterion, because `backup` has no healthcheck and `migrate` is supposed to be gone.
   - **Gate 4:** tables present — `docker compose exec postgres psql -U marketwind -d marketwind -c '\dt'` shows `run_ledger` and `schema_migrations`.
   - **Gate 5:** `docker compose exec scheduler python -m marketwind.scheduling --run-once --dry-run --floor-only` passes.
     *(Verify the exact flag spelling against `marketwind/scheduling/__main__.py` before writing it — do not copy this line on trust.)*
6. **Routine operations** — update/redeploy (`git pull` then `up -d --build`), read logs (`docker compose logs -f scheduler`), restart one service, inspect the DB. Note that migrations now apply automatically on every `up`, so a deploy that adds `migrations/*.sql` needs no separate step.
7. **Prohibited operations** — a table of *command / consequence*, covering at minimum: `docker compose down -v` and `docker system prune` in any form (destroys `pgdata`); printing, echoing or committing `.env` (leaks live keys); writing anything under `/root/.hermes` (that is the live WeChat session); upgrading, reinstalling, or re-running `hermes gateway setup` while the scheduler is running (severs delivery — escalate first); `--send-real` without explicit owner instruction; and loosening the freshness ceiling to force an off-hours run (`--force-fresh` is the designed override and keeps the verifier gate).
8. **When something is wrong** — the four cutover failure signatures from `docs/progress/cloud-cutover-aliyun.md`, each as *symptom / diagnostic / fix*: missing tables (`relation "run_ledger" does not exist`); missing Chromium (`Executable doesn't exist at …/chrome-headless-shell`); missing `citation/` (`FileNotFoundError: '/app/citation/rationalization-table.md'`); hermes not resolvable. Add a fifth: **`scheduler` unhealthy but `check_hermes.py` green** ⇒ the venv layout differs from the assumed `<venv>/bin/python` and the Task 5 healthcheck predicate needs adjusting — report, do not delete the healthcheck.
   Add the one-time note for a node that *already had data* before the named-volume change: take a `pg_dump` first, or copy the old anonymous volume across with
   `docker run --rm -v <old-anon-volume>:/from -v marketwind_pgdata:/to alpine sh -c 'cp -a /from/. /to/'`.
9. **Escalate to the owner** — the human-only steps: secret values, the `hermes gateway setup` QR scan, Aliyun console work (RAM role, OSS bucket + 14-day lifecycle rule), the daily WeChat keepalive (ADR-0002), and any request to flip `REPORT_DEV_LABEL`.

Close with a **Relationship to other docs** line: `deploy/report-node/README.md` remains the owner-facing provisioning guide (ECS sizing, security groups, RAM roles, OSS lifecycle) and is linked, not duplicated.

- [ ] **Step 1: Verify the two commands this file asserts**

Run: `grep -rn "run-once\|floor-only\|force-fresh\|send-real" marketwind/scheduling/__main__.py`
Use the flag spellings that actually appear. If gate 5's invocation cannot be confirmed from the source, write the gate against what the source supports and say so — do not ship a command you did not verify (`CLAUDE.md` §8.4).

- [ ] **Step 2: Write `DEPLOY.md`**

Per the shape above. Prose over bullet-fragments where a reason is being given; tables where the reader is matching output.

- [ ] **Step 3: Check every path and file it references exists**

Run: `ls .env.example deploy/report-node/check_keys.py deploy/report-node/check_hermes.py deploy/report-node/README.md deploy/report-node/docker-compose.prod.yml docs/progress/cloud-cutover-aliyun.md`
Expected: all present, no errors. Then re-read `DEPLOY.md` and confirm no other path is named that this command did not cover.

- [ ] **Step 4: Commit**

```bash
git add DEPLOY.md
git commit -m "docs: add the agent-facing deploy and operate runbook at repo root"
```

---

### Task 10: Discoverability edits

Spec §4.1. A deploy document reachable only from `README.md` is invisible to agents following `CLAUDE.md`'s map.

**Files:**
- Modify: `README.md` (below the intro, above the fold; plus the Repository map block at `README.md:29-44`)
- Modify: `CLAUDE.md` §9 document map

- [ ] **Step 1: Add the `README.md` pointer**

Directly beneath the intro blockquote (`README.md:5`), a short block naming `DEPLOY.md` as authoritative for deploying and operating the report node, addressed so an agent recognises itself — *if you are an agent deploying this repository to the report node, read `DEPLOY.md`* — and naming `deploy/report-node/README.md` as the owner-facing provisioning guide.

- [ ] **Step 2: Add it to the Repository map**

In the code block at `README.md:29-44`, add a `DEPLOY.md` line in the top group alongside `CLAUDE.md` / `CITATION_CONTRACT.md` / `DECISIONS.md` / `ARCHITECTURE.md`, with a one-line comment. Keep the existing alignment style.

- [ ] **Step 3: Add the `CLAUDE.md` §9 row**

A `DEPLOY.md` row in the document-map table, `Read when: deploying or operating the ECS report node`. Place it after the `ARCHITECTURE.md` / `DECISIONS.md` rows.

- [ ] **Step 4: Verify the map is not lying**

Run: `ls DEPLOY.md ARCHITECTURE.md CITATION_CONTRACT.md DECISIONS.md`
Expected: all four present.

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: point README and the CLAUDE.md map at DEPLOY.md"
```

---

### Task 11: ADR-0004 and the `DECISIONS.md` row

Spec §6. "Migrations are owner-run" is a *documented* decision, not a numbered `DECISIONS.md` entry, so this ADR is more process than strictly required — but it is consistent with `CLAUDE.md` §3 and cheap.

**Files:**
- Create: `docs/adr/0004-stack-applies-migrations.md`
- Modify: `DECISIONS.md` (the *Resolved infrastructure choices* table, after `D-30`)

- [ ] **Step 1: Write the ADR**

Follow the structure of `docs/adr/0003-trusted-outlet-primary-grade-tier.md`: title, then **Status** (accepted) / **Grantor** (project owner) / **Date** (2026-08-01) / **Scope** (permanent) / **Expiry condition**, then the prose sections.

Content, in your own words:

- **Triggering situation.** Two things. The `0006` incident: a node pulled new code, rebuilt, and lost a morning run because nobody re-ran `migrate` (`docs/progress/cloud-cutover-aliyun.md` line 31 records the standing rule that was supposed to prevent it). And the shift to agent operation, which removes the human that rule assumed would remember.
- **Decision.** A one-shot `migrate` compose service applies `migrations/*.sql` at boot; `app` and `scheduler` gate on `service_completed_successfully`. The runner is already idempotent, so re-running on every `up` is a no-op.
- **What it costs.** Boot-time blast radius widens: a malformed migration now blocks `app` and `scheduler` from starting rather than surfacing at first query. That is the intended trade — loud and early over silent and mid-report — and it is consistent with the project's "obvious fail welcomed, silent fail strongly unwelcomed" rule.
- **Precondition.** The gate is only meaningful because `pending_migration_paths()` (Task 1) makes exit-0 mean "schema applied". State that dependency explicitly; without it the gate would bless an empty database, inverting the ADR's own purpose.
- **Expiry condition.** Revisit if a migration ever needs to run against live traffic in a way boot-time application cannot express (e.g. a long backfill), at which point split DDL from data migration via a new ADR.
- **Affected modules** table: `docker-compose.yml` (new `migrate` service + two gates), `marketwind/storage/migrate.py` (the guard), `deploy/report-node/README.md` §9 (rewritten), `docs/progress/cloud-cutover-aliyun.md` (lines 15, 31).

- [ ] **Step 2: Add the `DECISIONS.md` row**

In the *Resolved infrastructure choices* table (two columns, `| ID | Decision |`), after `D-30`:

```
| D-32 | **The stack applies DB migrations at boot.** A one-shot `migrate` compose service runs `python -m marketwind.storage.migrate` and `app`/`scheduler` gate on `service_completed_successfully`; the runner now fails loud when it finds no migration files. Overturns the previously-documented "migrations are owner-run" — see [ADR-0004](docs/adr/0004-stack-applies-migrations.md) |
```

`D-31` is already taken (citation table); `D-32` is the next free number. Confirm with `grep -n "D-31\|D-32" DECISIONS.md` before writing.

- [ ] **Step 3: Verify**

Run: `grep -n "D-32" DECISIONS.md && ls docs/adr/`
Expected: the row prints; `0004-stack-applies-migrations.md` is listed.

- [ ] **Step 4: Commit**

```bash
git add docs/adr/0004-stack-applies-migrations.md DECISIONS.md
git commit -m "docs(adr): record the overturn of owner-run migrations"
```

---

### Task 12: Correct the two documents this work invalidates

Spec §6. `CLAUDE.md` §8.6: a PR updates the note it invalidates. Leaving these is how the same work gets planned twice.

**Files:**
- Modify: `deploy/report-node/README.md` (lines 33, 36, §8, §9)
- Modify: `docs/progress/cloud-cutover-aliyun.md` (lines 15, 31)

- [ ] **Step 1: Fix the HTTPS clone**

`deploy/report-node/README.md:33` reads `git clone https://github.com/VariianWrynn/marketwind.git`. Change to the SSH remote and add a one-line reason (git over HTTPS is reset on this network — `CLAUDE.md` §10) so it is not reverted.

- [ ] **Step 2: Note `COMPOSE_FILE` at the two-`-f` commands**

Line 36 and §8 (line 69) both spell out `docker compose -f docker-compose.yml -f deploy/report-node/docker-compose.prod.yml …`. Leave the explicit form (it still works and is unambiguous) but add a one-line note that with `COMPOSE_FILE` uncommented in `.env` the bare `docker compose …` is equivalent, pointing at `DEPLOY.md` §3.

- [ ] **Step 3: Rewrite §9**

§9 (lines 72-77) currently reads "Apply DB migrations (once after first `up`…)" and "Nothing runs this automatically" — flatly wrong after Task 4. Replace with: migrations are applied automatically by the `migrate` service on every `up`, `app`/`scheduler` do not start until it exits `0`, and the manual `exec app python -m marketwind.storage.migrate` remains available for a targeted re-run. Reference ADR-0004.

- [ ] **Step 4: Update the cutover note**

In `docs/progress/cloud-cutover-aliyun.md`:
- Line 15 ("No container runs `migrate` automatically (by design — idempotent, owner-run)") — this is the decision being overturned. Mark it as superseded by ADR-0004 rather than deleting the history: the row records what the first cutover found, and it is still true of *that* deploy.
- Line 31's **Standing rule** ("a PR that adds a `migrations/*.sql` needs a migrate run on the node, not just an image rebuild") is now obsolete. Say so, and say what replaced it.

Keep both edits minimal — this is a historical record, not a document to rewrite.

- [ ] **Step 5: Verify nothing still claims migrations are manual**

Run: `grep -rn "owner-run\|Nothing runs this automatically\|Standing rule" deploy/report-node/README.md docs/progress/cloud-cutover-aliyun.md DEPLOY.md`
Expected: every remaining hit is explicitly marked as superseded or historical. No hit asserts current behaviour.

- [ ] **Step 6: Commit**

```bash
git add deploy/report-node/README.md docs/progress/cloud-cutover-aliyun.md
git commit -m "docs: correct the two notes that auto-migration invalidates"
```

---

### Task 13: Progress note and `GAPS.md`

Spec §6.

**Files:**
- Create: `docs/progress/agent-operable-deploy.md`
- Modify: `docs/GAPS.md:16` (G0.2)

- [ ] **Step 1: Write the progress note**

Follow `docs/progress/P1a-scout.md`'s template — lightweight, a table plus a few bullets, not a second design doc. Include:

- `> **Read when:**` header.
- A table: *change / file / commit / what it prevents*, one row per guardrail plus `DEPLOY.md` and `check_hermes.py`.
- **How to test**: the two pytest commands (`tests/deploy/`, `tests/storage/test_migrate_guard.py`, `deploy/report-node/tests/test_check_hermes.py`) and the fact that compose *merge* semantics are covered on the box by `DEPLOY.md` gate 0, not by unit tests.
- **Out of scope**, naming them: the FC dead-man watcher (G1.3), OSS bucket + RAM-role provisioning, the WeCom fallback (G1.5), CI (G2.7).
- **Known caveats**, at minimum: `COMPOSE_FILE` ships commented out so the agent must uncomment it (gate 0 catches the omission); `COMPOSE_FILE` is directory-sensitive; the named-volume switch orphans any pre-existing anonymous volume, with the recovery command; nothing enforces that the agent reads `DEPLOY.md`, which is why the guardrails do not depend on it.
- The spec link, so the *why* is one hop away.

- [ ] **Step 2: Update G0.2 — advanced, NOT closed**

`docs/GAPS.md:16` is G0.2 (*Deploy & run the daemon persistently*). Leave it in Tier 0 and open. Update its **Note** column to say what this work changed (a fresh box now reaches a verified stack under agent control, with the schema applied automatically and the delivery path guarded) and state plainly that **only an actual unattended live run closes it**. Add `DEPLOY.md` and this progress note to the *Source* column.

Do **not** move it to *Recently closed*.

- [ ] **Step 3: Verify**

Run: `grep -n "G0.2" docs/GAPS.md`
Expected: still in the Tier 0 table, not in *Recently closed*, Note mentions `DEPLOY.md`.

- [ ] **Step 4: Commit**

```bash
git add docs/progress/agent-operable-deploy.md docs/GAPS.md
git commit -m "docs: record the agent-operable deploy work and advance G0.2"
```

---

### Task 14: Full-suite verification

`CLAUDE.md` §8.4 — no command run means no claim.

- [ ] **Step 1: Run the whole suite**

Run:
```
DATABASE_URL=postgresql://marketwind:marketwind@localhost:5432/marketwind REDIS_URL=redis://localhost:6379/0 python -m pytest -q
```
Expected: no **new** failures relative to the pre-work baseline. Tests needing a live Postgres or Redis (`tests/test_migrate.py`, `tests/test_health.py`, `tests/storage/*repo*`) will error without a running stack — capture the baseline first with `git stash` if the distinction is unclear, and report the delta, not the raw count.

- [ ] **Step 2: Run the two out-of-testpaths suites**

Run:
```
python -m pytest deploy/report-node/tests -q
```
Expected: all pass, including the new `test_check_hermes.py`.

- [ ] **Step 3: Lint**

Run: `python -m ruff check marketwind deploy tests`
Expected: clean, or only pre-existing findings untouched by this work.

- [ ] **Step 4: Confirm both compose files still parse**

Run:
```
python -c "import yaml; [yaml.safe_load(open(p,encoding='utf-8')) for p in ('docker-compose.yml','deploy/report-node/docker-compose.prod.yml')]; print('both parse')"
```
Expected: `both parse`.

- [ ] **Step 5: State clearly what was NOT verified**

Docker is unavailable in this worktree. The report must say, in these terms: the compose **merge** result, the actual image build, and every gate in `DEPLOY.md` §5 are unverified here and are verified on the box by gate 0 onward. Do not imply otherwise.

---

## Self-review — spec coverage

| Spec section | Task |
|---|---|
| §3.1 named volume | 2 |
| §3.2 `COMPOSE_FILE` / `COMPOSE_PROJECT_NAME` | 7 |
| §3.3 `migrate` service + gates | 4 |
| §3.3.1 silent-success guard | 1 (sequenced first) |
| §3.4 `.dockerignore` | 8 |
| §3.5 `app` healthcheck | 3 |
| §3.6 loopback binds | 5 |
| §4 `DEPLOY.md` | 9 |
| §4.1 discoverability | 10 |
| §5 `check_hermes.py` + scheduler healthcheck | 6, 5 |
| §6 ADR-0004 + `DECISIONS.md` | 11 |
| §6 invalidated docs | 12 |
| §6 progress note + G0.2 | 13 |
| §7 testing | 1, 2, 3, 4, 5, 6, 14 |

**Deviation from the spec, declared.** §7 lists four structural tests; this plan adds a fifth (`test_scheduler_healthcheck_also_exercises_the_venv_interpreter`, Task 5) and a sixth (`test_prod_binds_postgres_and_redis_to_loopback`, Task 5). Both satisfy §7's stated criterion — they pin a constraint that is not obvious from reading the YAML and that a later editor would plausibly simplify away. §5 was written after §7's list was trimmed, and its healthcheck is described there as "the load-bearing half of requirement 3"; leaving it unpinned would be inconsistent with §7's own rule.

**Also resolved here, since the spec deferred it:** §5 says the plan must determine whether the installed hermes supports a side-effect-free `--version`/`--help` "by checking what the installed hermes supports on the box". The box is not reachable from this worktree, so assuming a flag would violate §5's own instruction. Task 5 instead exercises the interpreter through the venv's sibling `python`, which tests the exact ADR-0001 mechanism with no assumption about hermes's CLI surface — and Task 6's `check_hermes.py` validates that predicate's premise before the stack comes up.
