# Verifier — the Law-5 publication gate (Tier 1 + Tier 2)

> **Read when:** building or picking up the Verifier phase, or before wiring anything between the Writer draft and IM publication.

**Status:** design approved (brainstorming, 2026-06-09). Scope locked by owner: Tier 1 (deterministic) + Tier 2 (DeepSeek-judge) only; Tier 3 recorded as a gap. Disposition: binary fail-closed whole-report gate (option A).

---

## 1. Why

`run_pipeline` today is `evaluate_floor → make_body (Writer) → label → push`. **Nothing verifies the draft between the Writer and publication.** That is a direct hole in Iron Law 5 ("no publication without a fresh Verifier pass"). This phase closes the hole: a fresh, independent pass over the structured Writer output that **fails closed** — any check fires → the brief is not published; a dev-channel status message (with `trace_id` and the tripped checks) goes out instead, and the violations are recorded.

This is a financial system. The gate's job is to refuse to publish on doubt, never to "pass with a warning."

## 2. Scope

**In scope — six checks.**

**Tier 1 — deterministic (pure functions, no LLM):**
| Check | Invariant / RF | What it verifies |
|---|---|---|
| `check_quotes_resolve` | RF-3, RF-9 | Every quote a claim references **re-resolves independently** against its source's `raw_content` at the recorded span (`raw_content[span_start:span_end] == text`). A quote that does not resolve = the claim's grounding cannot be re-assembled. |
| `check_quant_has_primary` | I3, RF-6 | Any claim referencing a **quantitative** quote must reference at least one quote with a primary (`attached_primary_url` set, or from an `is_primary` source). The Law-3 keystone the cninfo-PDF limb feeds. |
| `check_no_filler_attribution` | RF-4 | No anonymous-filler attribution in any sentence/statement (据报道 / 业内人士 / 市场认为 / 普遍预期 / 通常来说 / 分析人士 / 知情人士 / 接近…的人士 / 有消息称). |
| `check_no_first_person_inference` | RF-10, Law 4 | No first-person model inference (系统认为 / 分析显示 / 综合判断 / 经测算 / 研究表明). |

**Tier 2 — DeepSeek judge (injected async seam):**
| Check | Invariant / RF | What it verifies |
|---|---|---|
| `check_no_synthesis` | I1, RF-2 | No single sentence fuses two distinct claims into a combined assertion neither claim states alone. |
| `check_no_contradiction` | I10, RF-7 | No two claim statements assert internally contradictory facts. **Coarse — no time-window precision** (the Writer emits no `time_window`; precision is a Tier-3 gap). |

**Out of scope — recorded Tier-3 gaps (deferred, not silently dropped).** Each needs Claim metadata the Writer does not emit, network/history, or the claim state machine:
- **I12** (derived_metric methodology) — Writer emits no `category`/`methodology`.
- **I3b** (corroboration ≥ 2 or attributed_single) and **I2** (corroboration dedup) — Writer emits no `corroboration_status`.
- **I10 time-window precision** — Writer emits no `time_window`.
- **I6** (90-day freshness search) and **I11** (cross-report consistency) — need network / report history.
- **Claim state machine** (drafted→verified/failed→rewritten, retry ≤ 1), **failure-rate thresholds**, **re-run loops**, **800-char digest** — Tier 3.

## 3. Inputs and the independence principle

`verify` takes the **structured** `WriterOutput` (claims + sentences) **and the `pool`** (`list[PooledSource]`) — not the rendered body string. It rebuilds its own quote/source index from the pool and re-checks the Writer's references from scratch. It trusts no Writer internal state. This is what makes the pass "fresh and independent" (Law 5) rather than the Writer marking its own homework.

**Pool plumbing (required, no DB migration).** The DB already stores `sources.raw_content` and `quotes.span_start/span_end`, but `load_pool` drops them. To re-resolve quotes the pool must carry them:
- `PooledQuote` gains `span_start: int`, `span_end: int`.
- `PooledSource` gains `raw_content: str`.
- `load_pool`'s two SELECTs widen to fetch those columns.

These are additive fields on frozen dataclasses; existing construction sites (tests, the live wiring) update to pass them. No schema change.

## 4. Module layout — `marketwind/verifier/`

Mirrors the proven Writer package shape (pure core + injected LLM seam + thin live runner).

| Module | Responsibility |
|---|---|
| `verifier/domain.py` | `Violation(check, locus, detail)` and `VerifyResult(passed, violations)` — frozen value objects, no I/O. `passed == (violations == [])`. |
| `verifier/checks.py` | The four **Tier-1** pure functions. Each takes `(output, pool_index)` and returns `list[Violation]`. No LLM, no I/O. |
| `verifier/judge.py` | The two **Tier-2** checks: build a strict-JSON prompt, call the injected `judge` seam, parse the verdict into `list[Violation]`. **Fails closed:** a judge error or unparseable verdict yields a `judge_unavailable` violation (cannot certify → no publish). |
| `verifier/verifier.py` | `verify(output, pool, *, judge) -> VerifyResult`. Builds the quote/source index, runs all Tier-1 checks, then Tier-2, aggregates every violation. |
| `verifier/runner.py` | Live wiring: real DeepSeek judge seam (`# pragma: no cover`). |

**The judge seam:** `judge: Callable[[str], Awaitable[str]]` — same injected-async-seam pattern as the Writer's `call`. Offline tests pass a fake judge returning canned JSON; the live runner wires DeepSeek V4 Pro (D-26).

## 5. The gate — `run_pipeline` integration

The pipeline already owns the **floor** gate (calls `evaluate_floor`, decides publish/no-publish, sends a status message). The Verifier gate is **symmetric**:

```
floor = evaluate_floor(sources)
if not floor.passed:
    dev_channel.send(_floor_status(floor, trace_id)); return      # existing
bundle = await draft()                  # Writer runs here (DeepSeek); returns (output, pool, body)
result = await verify(bundle.output, bundle.pool)   # fresh Verifier pass — Law 5
if not result.passed:
    await record_fail(result)           # persist violations to claim_failures
    dev_channel.send(_verify_status(result, trace_id)); return    # NO publish
labeled = apply_label(bundle.body)
send_with_fallback(labeled, primary=..., fallback=..., trace_id=trace_id)
```

**Seam changes (surgical):**
- `make_body: () -> Awaitable[str]` becomes `draft: () -> Awaitable[DraftBundle]`, where `DraftBundle = (output: WriterOutput, pool: list[PooledSource], body: str)`. `draft` stays **lazy** — a sub-floor shortfall still costs no Writer/DeepSeek call. Rendering the body is a pure string op; rendering before the gate (and discarding it on failure) is cheap and keeps the seam minimal (no separate `render` seam).
- Two new injected seams: `verify: (WriterOutput, list[PooledSource]) -> Awaitable[VerifyResult]` and `record_fail: (VerifyResult) -> Awaitable[None]`.

**Persistence timing (Law 5).** `persist_report` (writing claims + sentences) moves to **after** the Verifier passes. A report that fails verification is **never persisted or published** — only its violations land in `claim_failures`. The live `draft` wiring assembles + renders without persisting; persistence happens on the publish path.

**Status message** (mirrors `_status_message`): `[MarketWind] verifier gate failed trace_id=… checks=RF-4,I3 (3 violations) — brief NOT published`.

## 6. Failure recording — `claim_failures`

`claim_failures` is named throughout the contract/docs but no table exists. Add one (migration `0003_verifier_failures.sql`) and a repo function:

```sql
create table if not exists claim_failures (
    failure_id   uuid primary key default gen_random_uuid(),
    trace_id     text not null,
    check_name   text not null,   -- "RF-4", "I3", "I1", "judge_unavailable", …
    locus        text not null,   -- claim local_id / sentence index / quote_id
    detail       text not null,
    created_at   timestamptz not null default now()
);
```

`record_verifier_failures(conn, trace_id, violations)` inserts one row per `Violation`. This is the minimal persistence the disposition requires; the weekly-review feedback loop and the full claim state machine remain Tier-3.

## 7. Testing (all offline, TDD)

- **`tests/verifier/test_checks.py`** — each Tier-1 check: a clean output (no violation) and a tripping output (exact violation). `check_quotes_resolve`: a quote whose `raw_content[span:]` no longer equals its text fires; a matching one passes. `check_quant_has_primary`: a quantitative claim with no primary fires; one with `attached_primary_url` passes. Filler/first-person: each regex token fires; neutral text passes.
- **`tests/verifier/test_judge.py`** — fake judge returning canned JSON: synthesis verdict → violation; clean → none; contradiction → violation; **judge raises / returns garbage → `judge_unavailable` violation (fail-closed).**
- **`tests/verifier/test_verifier.py`** — `verify` aggregates across tiers; `passed` iff zero violations.
- **`tests/orchestration/test_runner.py`** (extend) — verify-fail path: no publish, status to dev_channel, `record_fail` called; verify-pass path: publishes; sub-floor still short-circuits before `draft`.
- **`tests/storage/`** — `load_pool` returns the new fields; `record_verifier_failures` writes rows (live-DB test marked as existing repo tests are).

**RED discipline (project Iron Law):** every behavioral test must fail on an *assertion* (or a domain error) for the right reason before implementation — a bare `ImportError` is not a valid RED except for pure construction/smoke-import tests. For brand-new modules, scaffold a minimal stub returning a wrong sentinel, watch the assertion fail, then implement.

## 8. Non-goals / invariants honored

- **Fail closed, always.** Judge unavailable, a quote that won't resolve, a quantitative claim with no primary → no publish. Never "publish with a warning."
- **Surgical.** New `verifier/` package; three additive pool fields; one new migration + repo function; a symmetric gate in `run_pipeline`. No refactor of the Writer or floor logic.
- **No model laundering (Law 4).** The judge only *flags* synthesis/contradiction; it never rewrites the report or generates a fact. Deterministic checks are regex/equality only.
- **Tier 3 is recorded, not silently skipped** (§2).
