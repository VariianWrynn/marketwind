# Verifier — Law-5 Publication Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert a fresh, independent, fail-closed Verifier pass between the Writer draft and IM publication so no brief is ever published without passing it (Iron Law 5).

**Architecture:** A new pure-core `marketwind/verifier/` package (deterministic Tier-1 checks + DeepSeek-judge Tier-2 checks behind an injected async seam) exposes `verify(output, pool, *, judge) -> VerifyResult`. `run_pipeline` calls `verify` **directly** (hardcoded, mirroring the existing `evaluate_floor` gate) between a `draft()` step and publication; on any violation it records to `claim_failures`, emits a dev-channel status with `trace_id`, and does not publish. Quote re-resolution requires plumbing `raw_content` + spans (already in the DB) into the pool.

**Tech Stack:** Python 3.11+, asyncpg, pytest (`asyncio_mode="auto"` — async tests need no decorator), regex, DeepSeek V4 Pro (judge, live only). Run tests with `.venv/Scripts/python.exe -m pytest`.

**Spec:** `docs/superpowers/specs/2026-06-09-verifier-law5-gate-design.md`. Read it before Task 1.

---

## How to read this plan (controller's altitude)

This plan is written for **subagent-driven execution with the harness present at every gate**. It deliberately does **not** pre-write implementation bodies. For each task it fixes three things and leaves the rest to the implementer:

1. **The contract** — exact module paths, signatures, types, field names, return shapes. These are binding; cross-task consistency depends on them. Do not rename or re-shape them.
2. **The RED assertion** — the specific behavior each test must pin, and that it must fail on an *assertion* (or domain error) for the right reason before implementation. Test intent is given explicitly; the implementer writes the test to that intent and may add cases, but must not weaken the named assertion.
3. **The spec-critical literals** — regex token lists, the span-equality rule, table DDL. Where the spec *is* the value, it is given verbatim.

Everything else — how the function body is structured — is the implementer's job, done against the real files. If you (the implementer) find the contract impossible or wrong, **stop and report**, do not silently re-shape it.

**RED discipline (project Iron Law):** every *behavioral* test must first fail on an **assertion** (or a domain error) for the expected reason — a bare `ImportError`/collection error is NOT a valid RED. For brand-new modules, scaffold a minimal stub (module + signature returning a wrong sentinel) so the test runs and the assertion fails, *then* implement. Pure construction/smoke-import tests (Task 1's dataclasses) are the one exception where an import-driven RED is legitimate.

---

## File Structure

| File | Responsibility |
|---|---|
| `marketwind/verifier/__init__.py` | package marker (empty) |
| `marketwind/verifier/domain.py` | `Violation`, `VerifyResult` value objects |
| `marketwind/verifier/checks.py` | Tier-1 deterministic checks + `index_quotes` helper |
| `marketwind/verifier/judge.py` | Tier-2 judge checks (synthesis, contradiction), fail-closed |
| `marketwind/verifier/verifier.py` | `verify(output, pool, *, judge)` aggregator |
| `marketwind/verifier/runner.py` | live DeepSeek judge seam (`# pragma: no cover`) |
| `marketwind/writer/domain.py` | **modify:** span fields on `PooledQuote`, `raw_content` on `PooledSource`, add `DraftBundle` |
| `marketwind/storage/repo.py` | **modify:** widen `load_pool` SELECTs; add `record_verifier_failures` |
| `migrations/0003_verifier_failures.sql` | `claim_failures` table |
| `marketwind/writer/runner.py` | **modify:** add `draft_report` returning `DraftBundle`; `run_writer` delegates |
| `marketwind/orchestration/runner.py` | **modify:** hardcoded verify gate + `draft`/`judge`/`record_fail` seams |
| `marketwind/scheduling/run_once.py` | **modify:** forward `draft`/`judge`/`record_fail` |
| `marketwind/scheduling/__main__.py` | **modify:** build live `draft`/`judge`/`record_fail` closures |

Tests created/modified: `tests/verifier/test_domain.py`, `test_checks.py`, `test_judge.py`, `test_verifier.py`; `tests/storage/test_pool_fields.py`, `test_record_failures.py`; `tests/writer/test_draft_bundle.py`; and edits to `tests/orchestration/test_floor_and_pipeline.py`, `tests/scheduling/test_run_once.py`, `tests/scheduling/test_integration_pipeline.py`.

**Execute tasks in numeric order.** Tasks are numbered in dependency order: Task 2 (pool plumbing) adds the `PooledQuote`/`PooledSource` fields the Tier-1 checks (Task 3) construct, so it must run first. (Tasks below appear in numeric order.)

---

## Task 1: Verifier value objects (`domain.py`)

**Files:** Create `marketwind/verifier/__init__.py` (empty), `marketwind/verifier/domain.py`; Test `tests/verifier/__init__.py` (empty), `tests/verifier/test_domain.py`.

**Contract:**
- `Violation` — frozen dataclass, fields `check: str`, `locus: str`, `detail: str` (in that order).
- `VerifyResult` — frozen dataclass, fields `passed: bool`, `violations: list[Violation]`.
- Invariant the rest of the system relies on: a result is passing **iff** it carries zero violations. (The aggregator in Task 5 constructs `passed`; `domain.py` itself only holds the value objects.)

- [ ] **Step 1 — Write the construction/smoke test.** In `test_domain.py`, assert a `Violation` round-trips its three fields and a `VerifyResult(passed=False, violations=[v])` exposes `.passed` and `.violations`. This is a pure construction test (the one legitimate import-RED exception).

- [ ] **Step 2 — Run it, watch it fail.** `.venv/Scripts/python.exe -m pytest tests/verifier/test_domain.py -v` → FAIL with `ModuleNotFoundError: No module named 'marketwind.verifier'`.

- [ ] **Step 3 — Implement** the two frozen dataclasses to the contract above. Create the empty package `__init__.py`.

- [ ] **Step 4 — Run it, watch it pass.** Same command → PASS.

- [ ] **Step 5 — Commit.** `feat(verifier): add Violation + VerifyResult value objects`.

---

## Task 2: Plumb `raw_content` + spans into the pool

**Why first:** Task 3's quote-resolution check re-resolves `raw_content[span_start:span_end] == text`, so the pool dataclasses must carry those columns (the DB already stores them; `load_pool` currently drops them). No schema migration.

**Files:** Modify `marketwind/writer/domain.py` (the `PooledQuote` / `PooledSource` dataclasses), `marketwind/storage/repo.py` (`load_pool`); Test `tests/storage/test_pool_fields.py`.

**Contract (additive, frozen dataclasses):**
- `PooledQuote` gains `span_start: int` and `span_end: int`.
- `PooledSource` gains `raw_content: str`.
- `load_pool`'s two SELECTs widen to fetch `span_start, span_end` from `quotes` and `raw_content` from `sources`, and pass them into the constructors.
- Every existing construction site (tests + live wiring) that builds a `PooledQuote`/`PooledSource` must be updated to pass the new fields. Find them before implementing; the writer + storage suites must stay green.

- [ ] **Step 1 — Write the failing test.** In `test_pool_fields.py`, build a `PooledQuote` with known spans and a `PooledSource` with known `raw_content`, and assert the fields are present and carry the values. (Behavioral-enough: it fails on an `AttributeError`/`TypeError` from the missing field, which is acceptable here since it is a field-presence construction test; prefer asserting the field value so the failure is on the assertion, not collection.)

- [ ] **Step 2 — Run it, watch it fail** on the missing field. `.venv/Scripts/python.exe -m pytest tests/storage/test_pool_fields.py -v`.

- [ ] **Step 3 — Add the fields** to the two dataclasses.

- [ ] **Step 4 — Run it, watch it pass.**

- [ ] **Step 5 — Widen `load_pool`** to SELECT and pass the new columns. Match the existing query/row-mapping style in `repo.py` exactly.

- [ ] **Step 6 — Update every other construction site** the field change broke, then run the full writer + storage suites: `.venv/Scripts/python.exe -m pytest tests/writer tests/storage -v` → all green. (If a live-DB test is skipped in this environment, note it; the field-construction test must pass.)

- [ ] **Step 7 — Commit.** `feat(storage): carry raw_content + quote spans into the pool for verifier re-resolution`.

---

## Task 3: Tier-1 deterministic checks (`checks.py`)

**Prerequisite:** Task 2 complete (the checks construct `PooledQuote`/`PooledSource` with the new fields).

**Files:** Create `marketwind/verifier/checks.py`; Test `tests/verifier/test_checks.py`.

**Contract:**
- `index_quotes(pool: list[PooledSource]) -> dict[str, tuple[PooledQuote, PooledSource]]` — maps each `quote_id` to its `(quote, owning source)`.
- Four pure check functions, each `(output: WriterOutput, pool_index) -> list[Violation]`, no I/O, no LLM:
  - `check_quotes_resolve` → for every `quote_id` a claim references: if it is **absent** from the index, emit `Violation("RF-3", claim.local_id, …)`; if present but `source.raw_content[quote.span_start:quote.span_end] != quote.text`, emit `Violation("RF-3", claim.local_id, …)`. **The span-equality rule is the spec — implement it literally, no normalization/strip/fuzzy match.**
  - `check_quant_has_primary` → for each claim, gather its referenced quotes; if **any** is `is_quantitative` and **none** of the referenced quotes has a primary (`attached_primary_url` set **or** owning source `is_primary` True), emit `Violation("I3", claim.local_id, …)`. (Law-3 keystone.)
  - `check_no_filler_attribution` → scan each sentence text **and** each claim statement against `_FILLER`; on a hit emit `Violation("RF-4", locus, …)` where `locus` identifies the sentence index or claim `local_id`.
  - `check_no_first_person_inference` → same scan shape against `_FIRST_PERSON`, emitting `Violation("RF-10", locus, …)`.

**Spec-critical literals (verbatim):**
```python
_FILLER = re.compile(r"据报道|业内人士|市场认为|普遍预期|通常来说|分析人士|知情人士|接近.{0,8}的人士|有消息称")
_FIRST_PERSON = re.compile(r"系统认为|分析显示|综合判断|经测算|研究表明")
```

- [ ] **Step 1 — Write the failing tests.** For each check, one **clean** output (asserts `== []`) and one **tripping** output (asserts a single `Violation` with the exact `check` code and the right `locus`). Specifically:
  - quotes_resolve: a quote whose `raw_content[span:]` ≠ its text → one `RF-3`; a byte-exact matching quote → `[]`. Also: a referenced `quote_id` missing from the pool → one `RF-3`.
  - quant_has_primary: a quantitative quote with no primary anywhere on the claim → one `I3`; the same claim with `attached_primary_url` set (or source `is_primary`) → `[]`.
  - filler / first-person: a sentence containing one token from each list → the matching `RF-4` / `RF-10`; neutral text → `[]`.
  Assert on `v.check` and `v.locus`, not just length, so the RED is on the assertion.

- [ ] **Step 2 — Run them, watch them fail** for the right reason (scaffold `checks.py` with stubs returning a wrong sentinel — e.g. always `[]` for the tripping cases and a bogus violation for the clean cases — so the assertions, not an ImportError, fail). `.venv/Scripts/python.exe -m pytest tests/verifier/test_checks.py -v`.

- [ ] **Step 3 — Implement** `index_quotes` and the four checks to the contract. Regex via the literals above.

- [ ] **Step 4 — Run them, watch them pass.**

- [ ] **Step 5 — Commit.** `feat(verifier): Tier-1 deterministic checks (RF-3, I3, RF-4, RF-10)`.

---

## Task 4: Tier-2 judge checks (`judge.py`)

**Files:** Create `marketwind/verifier/judge.py`; Test `tests/verifier/test_judge.py`.

**Contract:**
- `JudgeFn = Callable[[str], Awaitable[str]]` — the injected async seam (same shape as the Writer's `call`).
- `check_no_synthesis(output, *, judge: JudgeFn) -> list[Violation]` — emits violations with `check="I1"`.
- `check_no_contradiction(output, *, judge: JudgeFn) -> list[Violation]` — emits violations with `check="I10"`.
- Each builds a **strict-JSON Chinese prompt** describing the claim statements to inspect, calls `await judge(prompt)`, and parses the reply as JSON of shape `{"violations": [{"locus": str, "detail": str}, …]}`, mapping each entry to a `Violation(check, locus, detail)`.
- **Fail closed (the heart of this task):** any failure of the judge call or parse — exception raised, non-JSON reply, missing `violations` key, wrong shape — yields exactly `[Violation("judge_unavailable", <check>, "<reason>")]`. Never return `[]` on a judge error (that would be "pass on doubt").

- [ ] **Step 1 — Write the failing tests** with a **fake judge** (a plain async function returning canned strings — no network):
  - synthesis: fake returns JSON with one violation → assert one `Violation(check="I1", …)`; fake returns `{"violations": []}` → assert `[]`.
  - contradiction: analogous, `check="I10"`.
  - **fail-closed, both checks:** fake **raises** → assert one `Violation("judge_unavailable", …)`; fake returns garbage (`"not json"`) → assert one `Violation("judge_unavailable", …)`. Assert on `v.check`.

- [ ] **Step 2 — Run them, watch them fail** (scaffold the two functions returning `[]` so the tripping/fail-closed assertions fail on the assertion). `.venv/Scripts/python.exe -m pytest tests/verifier/test_judge.py -v`.

- [ ] **Step 3 — Implement** both checks: prompt build → `await judge(...)` → parse → map, with one `try/except` that converts any failure into the `judge_unavailable` violation. The prompt only asks the judge to **flag** synthesis/contradiction (Law 4: never rewrite, never generate a fact).

- [ ] **Step 4 — Run them, watch them pass.**

- [ ] **Step 5 — Commit.** `feat(verifier): Tier-2 judge checks (I1 synthesis, I10 contradiction), fail-closed`.

---

## Task 5: The `verify` aggregator (`verifier.py`)

**Files:** Create `marketwind/verifier/verifier.py`; Test `tests/verifier/test_verifier.py`.

**Contract:**
- `async def verify(output: WriterOutput, pool: list[PooledSource], *, judge: JudgeFn) -> VerifyResult`.
- Build the index once via `index_quotes(pool)`, run all four Tier-1 checks, then `await` both Tier-2 checks, concatenate every returned `Violation` in order, and return `VerifyResult(passed=(violations == []), violations=violations)`.
- `passed` is `True` **iff** zero violations across all tiers.

- [ ] **Step 1 — Write the failing tests:**
  - A fully clean output with a fake judge returning `{"violations": []}` → `result.passed is True`, `result.violations == []`.
  - An output that trips **one Tier-1** check (e.g. a quant claim with no primary) **and** a judge that flags **one** synthesis → `result.passed is False` and `result.violations` contains both the `I3` and the `I1` (assert both `check` codes are present). This proves cross-tier aggregation.

- [ ] **Step 2 — Run them, watch them fail** (scaffold `verify` returning `VerifyResult(True, [])` so the failing-case assertion fails). `.venv/Scripts/python.exe -m pytest tests/verifier/test_verifier.py -v`.

- [ ] **Step 3 — Implement** the aggregator to the contract.

- [ ] **Step 4 — Run them, watch them pass.**

- [ ] **Step 5 — Commit.** `feat(verifier): verify() aggregates Tier-1 + Tier-2 into a fail-closed VerifyResult`.

---

## Task 6: `claim_failures` table + `record_verifier_failures`

**Files:** Create `migrations/0003_verifier_failures.sql`; Modify `marketwind/storage/repo.py`; Test `tests/storage/test_record_failures.py`.

**Contract:**
- Migration DDL (verbatim — matches the spec §6):
```sql
create table if not exists claim_failures (
    failure_id   uuid primary key default gen_random_uuid(),
    trace_id     text not null,
    check_name   text not null,
    locus        text not null,
    detail       text not null,
    created_at   timestamptz not null default now()
);
create index if not exists claim_failures_trace_idx on claim_failures (trace_id);
```
- `async def record_verifier_failures(conn, trace_id: str, violations: list[Violation]) -> None` — inserts **one row per Violation** (mapping `Violation.check → check_name`) via a single `executemany`. **Early-return on empty `violations`** (no query). Match the existing repo function style (`async`, parameterized SQL).

- [ ] **Step 1 — Create the migration** file with the DDL above.

- [ ] **Step 2 — Write the failing test.** Follow the existing live-DB repo-test pattern in `tests/storage/` (same fixture/skip-marker as the current `repo` tests). Insert two violations under a `trace_id`, then read back and assert two rows with the expected `check_name`/`locus`/`detail`. Add a case: empty `violations` writes **zero** rows. If this environment has no DB, the test is skipped like its siblings — but write it.

- [ ] **Step 3 — Run it, watch it fail** on the missing function / assertion.

- [ ] **Step 4 — Implement** `record_verifier_failures`.

- [ ] **Step 5 — Run it, watch it pass** (or skip cleanly without DB).

- [ ] **Step 6 — Commit.** `feat(storage): claim_failures table + record_verifier_failures`.

---

## Task 7: `DraftBundle` + `draft_report` (Writer side)

**Files:** Modify `marketwind/writer/domain.py` (add `DraftBundle`), `marketwind/writer/runner.py`; Test `tests/writer/test_draft_bundle.py`.

**Contract:**
- `DraftBundle` — frozen dataclass: `output: WriterOutput`, `pool: list[PooledSource]`, `body: str`, `commit: Callable[[], Awaitable[str]]`. `commit` is a thunk that persists the report and returns its `report_id`; it is called by the pipeline **only after** verify passes.
- `async def draft_report(conn, *, call, max_chars=500) -> DraftBundle` — load the pool, assemble the `WriterOutput`, render the brief, and build a `_commit` thunk that calls `persist_report(conn, output.claims, brief.sentences)`. **No persistence happens inside `draft_report` itself** — only inside the returned thunk. Rendering the body before the gate is a cheap pure string op; the lazy thunk defers the only DB write until after verification.
- `run_writer` is refactored to **delegate**: `bundle = await draft_report(...)`, `report_id = await bundle.commit()`, `return report_id, bundle.body`. Its external signature/return stays unchanged so existing callers and tests keep working.

- [ ] **Step 1 — Add `DraftBundle`** to `writer/domain.py` (frozen dataclass, contract above).

- [ ] **Step 2 — Write the failing test.** With fakes (a fake `call`, a fake pool, a spy `commit`), assert that `draft_report` returns a `DraftBundle` whose `body` is the rendered brief and whose `commit` has **not** yet persisted (the spy records zero calls until invoked) — then `await bundle.commit()` triggers exactly one persist and returns the `report_id`. The key assertion: **persistence is deferred to `commit`**, proving the ordering Law 5 needs.

- [ ] **Step 3 — Run it, watch it fail** (scaffold `draft_report` so the deferral/return assertion fails for the right reason).

- [ ] **Step 4 — Implement** `draft_report` and the `run_writer` delegation.

- [ ] **Step 5 — Run the writer suite** → green: `.venv/Scripts/python.exe -m pytest tests/writer -v`.

- [ ] **Step 6 — Commit.** `feat(writer): DraftBundle + draft_report defer persistence to a post-verify commit thunk`.

---

## Task 8: Hardcoded verify gate in `run_pipeline`

**Files:** Modify `marketwind/orchestration/runner.py`; Test `tests/orchestration/test_floor_and_pipeline.py`.

**Contract (new `run_pipeline` signature):**
`async def run_pipeline(*, sources, draft, judge, record_fail, primary, fallback, dev_channel, trace_id)`
- `draft: () -> Awaitable[DraftBundle]` **replaces** `make_body`. It stays **lazy** — a sub-floor shortfall must cost no `draft()` call (no Writer/DeepSeek spend).
- `judge: Callable[[str], Awaitable[str]]` and `record_fail: Callable[[str, list[Violation]], Awaitable[None]]` are the only new injected seams.
- `verify` is **imported and called directly** (NOT injected) — mirroring the hardcoded `evaluate_floor` call, so no caller can wire a pipeline that skips it. This is what makes Law 5 structural.

**Control flow (the gate):**
1. `floor = evaluate_floor(sources)`; if not passed → `dev_channel.send(_status_message(floor, trace_id))`; return. (unchanged)
2. `bundle = await draft()`.
3. `result = await verify(bundle.output, bundle.pool, judge=judge)`.
4. if not `result.passed`: `await record_fail(trace_id, result.violations)`; `dev_channel.send(_verify_status(result, trace_id))`; return — **no publish, no commit**.
5. `await bundle.commit()`; then label + `send_with_fallback(...)` as today.
- `_verify_status(result, trace_id)` — mirror `_status_message`; include `trace_id`, the sorted-unique tripped `check` codes, and the violation count, ending `— brief NOT published`. Example shape: `[MarketWind] verifier gate failed trace_id=… checks=I3,RF-4 (3 violations) — brief NOT published`.

- [ ] **Step 1 — Update the existing pipeline tests to the new contract** (they define it). Rewrite the two `run_pipeline` tests to pass `draft`/`judge`/`record_fail` instead of `make_body`, and add:
  - **verify-fail path:** a `draft` returning a bundle whose output trips a check (or a `judge` that flags one) → assert **nothing published** (sink empty / `send_with_fallback` not called), `dev_channel` got the `_verify_status` message, `record_fail` was awaited with the violations, and `bundle.commit` was **not** called.
  - **verify-pass path:** clean bundle + clean judge → assert the labeled body **is** published and `bundle.commit` **was** called.
  - **sub-floor short-circuit:** below-floor sources → assert `draft` was **never awaited** (lazy).
  Use spies for `commit`/`record_fail`/`draft` so these assertions are exact.

- [ ] **Step 2 — Run them, watch them fail** for the right reason (the old `run_pipeline` doesn't accept the new kwargs / doesn't gate).

- [ ] **Step 3 — Implement the gate** to the control flow above. Import `verify` directly. Add `_verify_status`.

- [ ] **Step 4 — Run them, watch them pass.** `.venv/Scripts/python.exe -m pytest tests/orchestration/test_floor_and_pipeline.py -v`.

- [ ] **Step 5 — Commit.** `feat(orchestration): hardcoded fail-closed verifier gate in run_pipeline (Law 5)`.

---

## Task 9: Thread the seams through `run_once` + live `__main__`

**Files:** Modify `marketwind/scheduling/run_once.py`, `marketwind/scheduling/__main__.py`; Create `marketwind/verifier/runner.py`; Test `tests/scheduling/test_run_once.py`, `tests/scheduling/test_integration_pipeline.py`.

**Contract:**
- `run_once` replaces its `make_body` parameter with `draft`, `judge`, `record_fail` and forwards all three to `run_pipeline`. All other behavior (calendar/freshness gates, single-flight lock, gather) is untouched. Keep the parameter ordering consistent with the existing keyword-only style.
- `marketwind/verifier/runner.py` exposes the live judge seam: `async def call_judge(prompt: str) -> str` wrapping the real DeepSeek V4 Pro call (`# pragma: no cover`). Reuse the existing DeepSeek client used by the Writer (`call_deepseek` or equivalent) — do not introduce a second client.
- `__main__.main()` (live, `# pragma: no cover`) builds three closures: `_draft` (wraps `draft_report` with the live `call_deepseek`), `call_judge` (from `verifier/runner.py`), and `_record_fail` (calls `record_verifier_failures(conn, trace_id, violations)`), and passes them to `run_once`.

- [ ] **Step 1 — Update `run_once` tests** to pass `draft`/`judge`/`record_fail` (fakes) instead of `make_body`. Assert the three seams are forwarded into the pipeline and the verify-fail path short-circuits publication (reuse the spy pattern from Task 8). The calendar/freshness/lock tests stay as-is except for the seam swap in the `_run` helper.

- [ ] **Step 2 — Update the integration test** (`test_integration_pipeline.py`) to the new seam: a full clean chain publishes; a chain whose draft trips a check does not publish and records the failure.

- [ ] **Step 3 — Run both scheduling test files, watch them fail** for the right reason (signature mismatch). `.venv/Scripts/python.exe -m pytest tests/scheduling -v`.

- [ ] **Step 4 — Update `run_once`** to forward the new seams.

- [ ] **Step 5 — Run the scheduling tests, watch them pass.**

- [ ] **Step 6 — Create `verifier/runner.py`** with the live `call_judge` (`# pragma: no cover`).

- [ ] **Step 7 — Wire the live `__main__` closures** (`_draft`, `call_judge`, `_record_fail`) into the `run_once` call.

- [ ] **Step 8 — Run the full offline suite** → all green: `.venv/Scripts/python.exe -m pytest`.

- [ ] **Step 9 — Commit.** `feat(scheduling): thread draft/judge/record_fail seams through run_once and live entrypoint`.

---

## Task 10: Progress note

**Files:** Create `docs/progress/verifier-law5-gate.md`.

- [ ] **Step 1 — Write the progress note** following the lightweight template in `docs/progress/P1a-scout.md` (a `> Read when:` line, a module table, an "invariants proved" bullet list, and a "how to test" line). Capture: the six checks and their RF/I codes, the hardcoded-gate design (verify called directly like `evaluate_floor`), the `DraftBundle.commit` post-verify persistence ordering, the pool plumbing, the `claim_failures` table, and the recorded Tier-3 gaps from the spec §2. Note each task's commit SHA.

- [ ] **Step 2 — Commit.** `docs(progress): verifier Law-5 gate phase note`.

---

## Branch-end checklist (after Task 10)

- [ ] Full offline suite green: `.venv/Scripts/python.exe -m pytest`.
- [ ] Apply migration `0003_verifier_failures.sql` to the Docker DB; confirm `claim_failures` exists.
- [ ] Run the ground-truth regression (`make test-gt`) — any Writer/Verifier change must pass the sample set.
- [ ] Independent whole-branch code review (fresh reviewer subagent).
- [ ] `superpowers:finishing-a-development-branch`.
