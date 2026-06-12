# Deployment & Live Smoke Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the small deploy-code units (floor-probe, scheduler entrypoint + compose service, channel + DEV-label flips) and the gated smoke runbook that take MarketWind from "wired but never run" to a persistent self-firing local daemon pushing real verified reports to WeChat.

**Architecture:** Three tiny code units in the scheduling entrypoint + config/label/compose, then a runbook doc. The live wiring (gather/enrich/draft/send/APScheduler) is already built and is exercised by the runbook, not the unit suite — so each task TDD's only its *pure* helpers (parser flags, formatters, the label prefix), and the live glue is `# pragma: no cover` verified by the smoke runbook. This follows P2a/P2b: live Bocha/DeepSeek/WeChat is smoke-only.

**Tech Stack:** Python 3.11, argparse, pydantic-settings, APScheduler, asyncpg, Docker Compose. Tests via pytest (`asyncio_mode=auto`), run with `.venv/Scripts/python.exe -m pytest`.

**Spec:** `docs/superpowers/specs/2026-06-13-deployment-live-smoke-design.md`. Channel order: ADR-0002 (WeChat primary, WeCom backup). Floor: `evaluate_floor` `8/1/2`.

**RED discipline (CLAUDE.md §8):** every behavioral test must fail on an **assertion** (or domain error) for the right reason — never a bare `ImportError`/`SystemExit`/`TypeError`. For a new helper, first scaffold the symbol returning a *wrong sentinel* so the test runs and the assertion fails; for a modified function, add the new parameter but with the *old* behavior so the new assertion fails. Watch it fail, then implement.

---

### Task 1: Floor-probe — `--floor-only` mode

Prints the live `FloorResult` and exits non-zero on sub-floor, **without drafting** (zero DeepSeek tokens). TDD the parser flag + the two pure helpers; the live `floor_probe()` coroutine is `# pragma: no cover - live` (smoke Stage 1).

**Files:**
- Modify: `marketwind/scheduling/__main__.py` (add `--floor-only` to `build_parser`; add `floor_line` + `floor_exit_code`; add live `floor_probe()` + dispatch)
- Test: `tests/scheduling/test_entrypoint.py`

**Contract (fix exactly):**
- `floor_line(result: FloorResult) -> str` — one human line containing `grounded=<g> primary=<p> outlets=<o> passed=<bool>`.
- `floor_exit_code(result: FloorResult) -> int` — `0` if `result.passed` else `1`.
- `build_parser` gains `--floor-only` (`action="store_true"`). `FloorResult` fields are `grounded_quotes`, `primary_traced_quotes`, `independent_outlets`, `passed` (see `marketwind/scout/domain.py`).

- [ ] **Step 1: Write failing tests**

```python
from marketwind.scout.domain import FloorResult
from marketwind.scheduling.__main__ import build_parser, floor_line, floor_exit_code

def _parse(argv):
    return build_parser().parse_args(argv)

def test_floor_only_flag_parses():
    assert _parse(["--floor-only"]).floor_only is True

def test_floor_line_reports_all_three_metrics():
    line = floor_line(FloorResult(grounded_quotes=9, primary_traced_quotes=2,
                                  independent_outlets=3, passed=True))
    assert "grounded=9" in line and "primary=2" in line
    assert "outlets=3" in line and "passed=True" in line

def test_exit_code_zero_on_pass_nonzero_on_subfloor():
    ok = FloorResult(grounded_quotes=9, primary_traced_quotes=2, independent_outlets=3, passed=True)
    bad = FloorResult(grounded_quotes=3, primary_traced_quotes=0, independent_outlets=1, passed=False)
    assert floor_exit_code(ok) == 0
    assert floor_exit_code(bad) != 0
```

- [ ] **Step 2: Watch RED (assertion-level).** Scaffold `--floor-only` in the parser, and stub `floor_line` to return `""` and `floor_exit_code` to return `0`. Run `… -m pytest tests/scheduling/test_entrypoint.py -v`. Expect the line-content and sub-floor-exit assertions to **fail on the assert** (not import/parse).
- [ ] **Step 3: Implement** the two helpers per contract. Then add `async def floor_probe() -> int` (`# pragma: no cover - live`): connect via `asyncpg`, run `gather_live` + `enrich_primary_live` exactly as `run_scheduler` wires them (real `now`/`prev` via `live_prev_trading_session`), call `evaluate_floor`, print `floor_line`, `return floor_exit_code`; close the conn in `finally`. Route argv: `--floor-only` ⇒ `raise SystemExit(asyncio.run(floor_probe()))`.
- [ ] **Step 4: GREEN.** Run the test file; expect PASS.
- [ ] **Step 5: Commit** (`feat: add --floor-only floor-probe entrypoint mode`).

---

### Task 2: Scheduler entrypoint (`--scheduler`) + channel flip (ADR-0002)

Make the persistent daemon reachable, and select WeChat as primary.

**Files:**
- Modify: `marketwind/scheduling/__main__.py` (add `--scheduler` + `want_scheduler`; dispatch in `__main__` block)
- Modify: `marketwind/scheduling/__main__.py` `run_scheduler` line ~107 (`im_channel` flip)
- Test: `tests/scheduling/test_entrypoint.py`

**Contract:** `want_scheduler(args) -> bool` returns `args.scheduler`. `build_parser` gains `--scheduler` (`store_true`).

- [ ] **Step 1: Write failing tests**

```python
def test_scheduler_flag_routes_to_daemon():
    assert want_scheduler(_parse(["--scheduler"])) is True

def test_absent_scheduler_flag_is_false():
    assert want_scheduler(_parse([])) is False
```

(add `want_scheduler` to the existing import line.)

- [ ] **Step 2: Watch RED.** Add `--scheduler` to the parser, stub `want_scheduler` to `return False`. Run the test file; the `["--scheduler"]` case **fails on the assert**.
- [ ] **Step 3: Implement** `want_scheduler` per contract. In the `if __name__ == "__main__"` block, parse argv and dispatch: `--scheduler` ⇒ `asyncio.run(run_scheduler())`, else the existing `asyncio.run(main())`. In `run_scheduler`, change the channel select from `"wecom_webhook"` to `"hermes_weixin"` (ADR-0002 — the factory's `hermes_weixin` branch already yields HermesWeixin primary + WeCom/Stub fallback, covered by `tests/im/test_factory.py`). Update the adjacent comment to cite ADR-0002.
- [ ] **Step 4: GREEN.** Run the test file; PASS. Also run `… -m pytest tests/im/test_factory.py -v` to confirm the channel pairing is still asserted.
- [ ] **Step 5: Commit** (`feat: add --scheduler entrypoint; flip live channel to WeChat primary (ADR-0002)`).

---

### Task 3: DEV-label flip behind a default-DEV config flag (G0.4)

Make the `【DEV / UNVERIFIED】` prefix removable by an explicit, reversible config flip — defaulting to ON so nothing changes silently.

**Files:**
- Modify: `marketwind/gateway/im/label.py` (`apply_label` gains a `prefix` param)
- Modify: `marketwind/config.py` (add `report_dev_label: bool = True`)
- Modify: `marketwind/orchestration/runner.py` (`run_pipeline` forwards a `label_prefix`) and `marketwind/scheduling/run_once.py` (forward the param) — default `DEV_PREFIX`, non-breaking
- Test: `tests/im/test_label.py`

**Contract (fix exactly):**
- `apply_label(body: str, *, prefix: str = DEV_PREFIX) -> str` — prepends `prefix`; the length guard becomes `len(prefix + body) > MAX_TOTAL → raise ValueError("exceeds")`. `MAX_TOTAL` stays `500`. With `prefix=""`, a 500-char body fits.
- `Settings.report_dev_label: bool = True`.
- `run_pipeline(..., label_prefix: str = DEV_PREFIX)` passes `label_prefix` into `apply_label`; `run_once` forwards `label_prefix` with the same default. Live entrypoints resolve `DEV_PREFIX if settings.report_dev_label else ""` and pass it down. Defaults keep every existing caller/test unchanged.

- [ ] **Step 1: Write failing tests** (append to `tests/im/test_label.py`)

```python
def test_empty_prefix_drops_dev_label():
    out = apply_label("正文。[1]", prefix="")
    assert not out.startswith(DEV_PREFIX)
    assert out == "正文。[1]"

def test_empty_prefix_allows_full_500_body():
    out = apply_label("字" * MAX_TOTAL, prefix="")
    assert len(out) == MAX_TOTAL

def test_default_prefix_unchanged():
    assert apply_label("正文").startswith(DEV_PREFIX)
```

- [ ] **Step 2: Watch RED.** Add the `prefix` parameter to `apply_label` **but ignore it** (keep prepending `DEV_PREFIX`). Run `… -m pytest tests/im/test_label.py -v`. `test_empty_prefix_drops_dev_label` and `_allows_full_500_body` **fail on the assert** (stub still prepends DEV); the existing four tests + `test_default_prefix_unchanged` stay green.
- [ ] **Step 3: Implement** `apply_label` to honor `prefix` (prepend `prefix`, guard on `len(prefix)+len(body)`). Add `report_dev_label` to `Settings`. Thread `label_prefix` (default `DEV_PREFIX`) through `run_pipeline` → `apply_label`, and through `run_once` → `run_pipeline`; in the live entrypoints (`main`, `run_scheduler`) resolve the prefix from `settings.report_dev_label` and pass it.
- [ ] **Step 4: GREEN.** Run `… -m pytest tests/im/ tests/orchestration tests/scheduling -v`; expect all PASS (threading is non-breaking via defaults).
- [ ] **Step 5: Commit** (`feat: gate DEV/UNVERIFIED label behind report_dev_label flag (G0.4)`).

---

### Task 4: `scheduler` Docker Compose service

Run the daemon as a restart-durable container alongside Postgres.

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example` (document `IM_CHANNEL=hermes_weixin` for the daemon + `REPORT_DEV_LABEL`)

- [ ] **Step 1: Add the service.** A `scheduler` service: `build: .`, `command: ["python", "-m", "marketwind.scheduling", "--scheduler"]`, `depends_on: postgres (condition: service_healthy)`, `restart: unless-stopped`, env `DATABASE_URL` (the in-network `postgres:5432` URL), `IM_CHANNEL=hermes_weixin`, plus pass-through of `HERMES_BIN`, `WEIXIN_TARGET`, `OPENAI_API_KEY`/`OPENAI_BASE_URL`, `BOCHA_API_KEY`, `REPORT_DEV_LABEL` from the host env. Leave the existing `app` (uvicorn) service unchanged.
- [ ] **Step 2: Hermes-access spike (≤5 min).** Decide how the container reaches the `hermes` CLI + `~/.hermes/.env`. **Default:** mount `~/.hermes:/root/.hermes:ro` and ensure `hermes` is installed/on PATH in the image. **Fallback if hermes won't containerize cleanly:** drop the in-container send — document running the scheduler as a host process (`… -m marketwind.scheduling --scheduler`) against the dockerized Postgres instead. Record the choice + reason inline in `docker-compose.yml` as a comment.
- [ ] **Step 3: Validate.** Run `docker compose config` (must parse with no error and show the `scheduler` service). Do **not** `up` here — that is smoke Stage 3.
- [ ] **Step 4: Commit** (`feat: add restart-durable scheduler compose service`).

---

### Task 5: Go-live smoke runbook + progress note

Capture the gated Stage 1–3 sequence as an executable runbook and record the phase.

**Files:**
- Create: `docs/runbooks/go-live-smoke.md`
- Create: `docs/progress/deployment-live-smoke.md`

- [ ] **Step 1: Write the runbook.** Transcribe spec Section B as a checklist with exact commands and pass/fail gates:
  - **Stage 1:** `PYTHONPATH=. .venv/Scripts/python.exe -m marketwind.scheduling --floor-only`. PASS = `passed=True`; FAIL ⇒ STOP, read which of grounded/primary/outlets fell short and map to the gap (primary→G1.1/G1.2/G1.4, outlets→crawler, grounded→gather). Re-tuning `8/1/2` is an explicit owner decision, never silent.
  - **Stage 2:** `… -m marketwind.scheduling --send-real` (DEV label ON) → owner eyeballs the WeChat report → if trustworthy, set `REPORT_DEV_LABEL=false`, re-run, confirm the clean label lands; if `verify_fail`, fix before flip.
  - **Stage 3:** `docker compose up -d scheduler` → confirm boot/`catch_up` in logs → temporarily set one cron ~2 min ahead to watch an in-container self-fire + push + ledger row → `docker restart` the container → confirm recovery + `catch_up` + **no duplicate publish**.
  - State the accepted costs (real tokens, real push) and the G1.5 cold-fail caveat (must fail loud).
- [ ] **Step 2: Write the progress note** (`docs/progress/deployment-live-smoke.md`): a short table of the modules added (floor-probe, `--scheduler`, label flag, compose service) + the invariants (floor-probe is draft-free & exits non-zero on sub-floor; channel = WeChat primary per ADR-0002; label flip default-DEV/reversible; restart durability via `unless-stopped` + `catch_up` idempotency) + the deferred items (cloud cutover, WeCom backup, G1.3 dead-man's switch, G1.5 cold-fail handling).
- [ ] **Step 3: Commit** (`docs: go-live smoke runbook + deployment progress note`).

---

## Final verification (after all tasks)

- [ ] Run the **full offline suite**: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q`. Expect all green (no regressions; new behavior covered by the entrypoint + label tests).
- [ ] Confirm `docker compose config` still parses.
- [ ] Hand off to the owner to execute the live runbook (Stages 1–3) — the live smoke is owner-run by design.
