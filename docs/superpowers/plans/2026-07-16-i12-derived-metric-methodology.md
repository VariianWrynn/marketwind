# I12 Derived-Metric Methodology Enforcement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce I12 (CITATION_CONTRACT §4) end-to-end — a `derived_metric` claim (a source's own computation over base data, e.g. 日赚 3.6 亿) must carry a `methodology` label, or the Verifier flags it and the report fails the Law-5 gate.

**Architecture:** Full vertical. The claim schema gains two fields (`category`, `methodology`); the Writer prompt teaches the model to classify derived metrics and label their basis; the I8 schema parses + enum-validates the fields but does **not** reject (per `failure-handling.md:25`, I12 is a graded claim-level failure, not a whole-report reject — RF-1); a new deterministic Tier-1 Verifier check `check_derived_methodology` produces the `I12` `Violation`; the DB gains `category`/`methodology` columns with a CHECK constraint as an integrity backstop.

**Locked interpretations (agreed with owner 2026-07-16):**
- **Q1 — category is optional, defaults to `quantitative`.** The Writer is NOT forced into 9-way classification of every claim; only claims it explicitly marks `derived_metric` are subject to I12. Keeps the change surgical.
- **Q2 — enforcement lives in the Verifier**, not the I8 schema. Schema parses + enum-validates only. DB CHECK is a last-resort backstop.
- **Q3 — the deterministic check is: `category == 'derived_metric'` ⟹ `methodology` is non-empty** (matches the DB CHECK `CITATION_CONTRACT.md:123` verbatim). "State the basis in the body" is satisfied by the Writer also populating `methodology`.

**Tech Stack:** Python 3.11+, frozen dataclasses, asyncpg + Postgres, pytest (async). DeepSeek prompt is a plain string builder.

**Spec-critical literals (verbatim — do not paraphrase tokens):**
- Category enum (9 values): `quantitative`, `temporal`, `comparative`, `attribution`, `causal`, `quoted_inference`, `freshness`, `derived_metric`, `correction` (`CITATION_CONTRACT.md:110`)
- Check code string: `I12`
- DB CHECK implication: `(category = 'derived_metric') ⟹ (methodology IS NOT NULL)` (`CITATION_CONTRACT.md:123`)
- Methodology example value: `按净利润计` (`CITATION_CONTRACT.md:116`)

---

## File Structure

| File | Change |
|---|---|
| `marketwind/writer/domain.py` | `DraftClaim` gains `category: str = "quantitative"`, `methodology: str \| None = None` (trailing, defaulted) |
| `marketwind/writer/schema.py` | `parse_and_validate` reads `category`/`methodology`, enum-validates `category`, passes them to `DraftClaim` |
| `marketwind/writer/writer.py` | `assemble` remap copies `category`/`methodology` through the alias→uuid remap |
| `marketwind/writer/prompt.py` | `_OUTPUT_SPEC` adds `category`/`methodology` to the JSON shape + the derived-metric rule |
| `marketwind/verifier/checks.py` | new `check_derived_methodology(output, pool_index)` |
| `marketwind/verifier/verifier.py` | wire the 7th check into `verify()` |
| `migrations/0006_i12_derived_metric.sql` | ALTER `claims` add columns + CHECK constraints |
| `marketwind/storage/repo.py` | `persist_report` inserts `category`/`methodology` |
| `docs/progress/i12-derived-methodology.md` | short progress note (final task) |

Test files: `tests/writer/test_domain.py`, `tests/writer/test_schema.py` (create if absent), `tests/writer/test_writer_remap.py` (create), `tests/verifier/test_checks.py`, `tests/verifier/test_verifier.py`, `tests/writer/test_prompt.py`, `tests/writer/test_repo_writer.py`.

**RED discipline (Iron Law):** Every behavioral task below must watch its assertion fail *for the stated reason* — never a bare `ImportError`/collection error. Task 1 (frozen-dataclass construction) is the one legitimate construction-smoke exception. Report the actual RED assertion text and the GREEN output back to the controller for each task.

---

### Task 1: Domain — add `category` / `methodology` to `DraftClaim`

**Files:**
- Modify: `marketwind/writer/domain.py` (the `DraftClaim` dataclass, currently lines 34-38)
- Test: `tests/writer/test_domain.py`

- [ ] **Step 1: Write the failing test**

```python
def test_draftclaim_carries_category_and_methodology():
    from marketwind.writer.domain import DraftClaim
    c = DraftClaim(
        local_id="c-001",
        statement="长鑫存储去年日赚3.6亿元。",
        quote_ids=["q-1"],
        category="derived_metric",
        methodology="按净利润计",
    )
    assert c.category == "derived_metric"
    assert c.methodology == "按净利润计"


def test_draftclaim_defaults_are_non_derived():
    from marketwind.writer.domain import DraftClaim
    c = DraftClaim(local_id="c-002", statement="营收508亿元。", quote_ids=["q-2"])
    assert c.category == "quantitative"
    assert c.methodology is None
```

- [ ] **Step 2: Run to verify RED**

Run: `pytest tests/writer/test_domain.py -k "category or defaults" -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'category'` (construction-smoke RED; legitimate for a behavior-free frozen dataclass).

- [ ] **Step 3: Implement**

Add two trailing, defaulted fields to `DraftClaim`: `category: str = "quantitative"` and `methodology: str | None = None`. They MUST come after `quote_ids` so existing positional constructions (`DraftClaim("c-001", "...", [qid])`) keep working.

- [ ] **Step 4: Run to verify GREEN** — `pytest tests/writer/test_domain.py -v` → PASS.

- [ ] **Step 5: Commit** — `feat(writer): add category/methodology fields to DraftClaim (I12)`

---

### Task 2: Schema — parse + enum-validate `category` / `methodology`

**Files:**
- Modify: `marketwind/writer/schema.py` (`parse_and_validate`, claim loop lines 33-45)
- Test: `tests/writer/test_schema.py` (create if it does not exist)

**Contract:** For each claim JSON, read `category` (default `"quantitative"` when absent) and `methodology` (default `None`). Validate `category` is in the 9-value enum set; on failure raise `SchemaViolation`. Do **NOT** reject a `derived_metric` claim that lacks `methodology` — that is the Verifier's graded call (Q2). Pass both fields into `DraftClaim(...)`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from marketwind.writer.schema import parse_and_validate, SchemaViolation

_QIDS = {"q1"}
_SIDS = {"s1"}

def _raw(category=None, methodology=None):
    import json
    claim = {"id": "c-001", "statement": "陈述", "quote_ids": ["q1"]}
    if category is not None:
        claim["category"] = category
    if methodology is not None:
        claim["methodology"] = methodology
    return json.dumps({
        "claims": [claim],
        "sentences": [{"sentence": "陈述。", "claim_ids": ["c-001"],
                       "source_ids": ["s1"], "sentence_type": "factual"}],
    })

def test_schema_parses_category_and_methodology():
    out = parse_and_validate(_raw("derived_metric", "按净利润计"), _QIDS, _SIDS)
    assert out.claims[0].category == "derived_metric"
    assert out.claims[0].methodology == "按净利润计"

def test_schema_defaults_category_when_absent():
    out = parse_and_validate(_raw(), _QIDS, _SIDS)
    assert out.claims[0].category == "quantitative"
    assert out.claims[0].methodology is None

def test_schema_rejects_unknown_category():
    with pytest.raises(SchemaViolation):
        parse_and_validate(_raw("bogus_category"), _QIDS, _SIDS)

def test_schema_does_not_reject_derived_without_methodology():
    # Q2: I8 schema is not the enforcer; a derived_metric with no methodology parses.
    out = parse_and_validate(_raw("derived_metric"), _QIDS, _SIDS)
    assert out.claims[0].category == "derived_metric"
    assert out.claims[0].methodology is None
```

- [ ] **Step 2: Run to verify RED**

Run: `pytest tests/writer/test_schema.py -v`
Expected: FAIL — `test_schema_parses_category_and_methodology` asserts `category == "derived_metric"` but the current schema builds `DraftClaim` without the field, so it defaults to `"quantitative"` → **AssertionError on the value** (proper behavioral RED, not an import error); `test_schema_rejects_unknown_category` fails because no enum check raises yet.

- [ ] **Step 3: Implement**

In the claim loop: define a module-level frozenset `_VALID_CATEGORIES` with the 9 spec values (verbatim). Read `cat = c.get("category", "quantitative")` and `meth = c.get("methodology")`. If `cat not in _VALID_CATEGORIES`, raise `SchemaViolation(f"unknown claim category: {cat!r}")`. Pass `category=cat, methodology=meth` into the `DraftClaim(...)` construction. No derived-without-methodology rejection here.

- [ ] **Step 4: Run to verify GREEN** — `pytest tests/writer/test_schema.py -v` → PASS.

- [ ] **Step 5: Commit** — `feat(writer): parse+enum-validate claim category/methodology in I8 schema`

---

### Task 3: Writer — carry `category` / `methodology` through the alias→uuid remap

**Files:**
- Modify: `marketwind/writer/writer.py` (`assemble`, remap of `validated.claims`, lines 27-34)
- Test: `tests/writer/test_writer_remap.py` (create)

**Contract:** The remap that rebuilds `DraftClaim` with real uuids must preserve `category` and `methodology`. Without this, the fields survive parsing (Task 2) but get dropped at remap → default back to `quantitative`/`None`, silently defeating the guard.

- [ ] **Step 1: Write the failing test**

```python
import json
from marketwind.writer.domain import PooledQuote, PooledSource
from marketwind.writer.writer import assemble

def _pool():
    q = PooledQuote(quote_id="uuid-q", text="日赚3.6亿", is_quantitative=True,
                    quote_type="data", attached_primary_url="https://cninfo.com.cn/x",
                    span_start=0, span_end=5)
    return [PooledSource(source_id="uuid-s", url="https://cninfo.com.cn/x",
                         domain="cninfo.com.cn", is_primary=True, quotes=[q],
                         raw_content="日赚3.6亿")]

async def test_assemble_preserves_category_and_methodology():
    # Stub returns alias ids (q1/s1) with a derived_metric claim.
    content = json.dumps({
        "claims": [{"id": "c-001", "statement": "长鑫日赚3.6亿元。",
                    "quote_ids": ["q1"], "category": "derived_metric",
                    "methodology": "按净利润计"}],
        "sentences": [{"sentence": "长鑫日赚3.6亿元。", "claim_ids": ["c-001"],
                       "source_ids": ["s1"], "sentence_type": "factual"}],
    })
    async def stub_call(_messages):
        return content
    out = await assemble(_pool(), call=stub_call)
    assert out.claims[0].category == "derived_metric"
    assert out.claims[0].methodology == "按净利润计"
    assert out.claims[0].quote_ids == ["uuid-q"]  # alias remapped to real uuid
```

- [ ] **Step 2: Run to verify RED**

Run: `pytest tests/writer/test_writer_remap.py -v`
Expected: FAIL — remap constructs `DraftClaim(local_id=…, statement=…, quote_ids=…)` without `category`, so `out.claims[0].category` defaults to `"quantitative"` → **AssertionError: 'quantitative' != 'derived_metric'** (proper behavioral RED).

- [ ] **Step 3: Implement** — in the `remapped_claims` comprehension add `category=c.category, methodology=c.methodology`.

- [ ] **Step 4: Run to verify GREEN** — `pytest tests/writer/test_writer_remap.py -v` → PASS.

- [ ] **Step 5: Commit** — `fix(writer): preserve category/methodology across alias→uuid remap`

---

### Task 4: Verifier — `check_derived_methodology` (the I12 guard)

**Files:**
- Modify: `marketwind/verifier/checks.py` (add the function)
- Test: `tests/verifier/test_checks.py`

**Contract (signature must match the other Tier-1 checks for uniform wiring):**
```python
def check_derived_methodology(
    output: WriterOutput,
    pool_index: dict[str, tuple[PooledQuote, PooledSource]],
) -> list[Violation]:
```
Rule (Q3): for each claim, if `claim.category == "derived_metric"` and `methodology` is `None` or blank after `.strip()`, append `Violation(check="I12", locus=claim.local_id, detail=...)`. Claims of any other category are never flagged. `pool_index` is unused (kept for signature uniformity — mirror `check_no_filler_attribution`).

- [ ] **Step 1: Write the failing tests**

```python
from marketwind.verifier.checks import check_derived_methodology
from marketwind.writer.domain import DraftClaim, WriterOutput

def _out(*claims):
    return WriterOutput(claims=list(claims), sentences=[])

def test_i12_flags_derived_metric_without_methodology():
    out = _out(DraftClaim("c-001", "长鑫日赚3.6亿元。", ["q1"], category="derived_metric"))
    vs = check_derived_methodology(out, {})
    assert len(vs) == 1
    assert vs[0].check == "I12"
    assert vs[0].locus == "c-001"

def test_i12_passes_derived_metric_with_methodology():
    out = _out(DraftClaim("c-001", "长鑫日赚3.6亿元。", ["q1"],
                          category="derived_metric", methodology="按净利润计"))
    assert check_derived_methodology(out, {}) == []

def test_i12_ignores_non_derived_claims():
    out = _out(DraftClaim("c-001", "营收508亿元。", ["q1"], category="quantitative"))
    assert check_derived_methodology(out, {}) == []

def test_i12_flags_blank_methodology():
    out = _out(DraftClaim("c-001", "长鑫日赚3.6亿元。", ["q1"],
                          category="derived_metric", methodology="   "))
    assert len(check_derived_methodology(out, {})) == 1
```

- [ ] **Step 2: Run to verify RED**

First add a minimal stub `def check_derived_methodology(output, pool_index): return []` so the test *runs* (avoids a bare ImportError). Run: `pytest tests/verifier/test_checks.py -k i12 -v`
Expected: FAIL — `test_i12_flags_derived_metric_without_methodology` asserts `len(vs) == 1` but the stub returns `[]` → **AssertionError: 0 != 1** (proper behavioral RED against the stub sentinel).

- [ ] **Step 3: Implement** — replace the stub body with the rule above.

- [ ] **Step 4: Run to verify GREEN** — `pytest tests/verifier/test_checks.py -k i12 -v` → PASS (4 tests).

- [ ] **Step 5: Commit** — `feat(verifier): add check_derived_methodology (I12)`

---

### Task 5: Verifier — wire I12 into the `verify()` aggregator

**Files:**
- Modify: `marketwind/verifier/verifier.py` (import + `violations.extend(...)`)
- Test: `tests/verifier/test_verifier.py`

**Contract:** Add `check_derived_methodology` to the imports and call it in `verify()` alongside the other Tier-1 checks (before the async judge checks). A derived-metric-without-methodology claim must make `result.passed is False` with an `I12` violation.

- [ ] **Step 1: Write the failing test** (append to `tests/verifier/test_verifier.py`; reuses the `_judge_clean` fake already in that file)

```python
async def test_verify_flags_i12_derived_without_methodology():
    from marketwind.writer.domain import (
        DraftClaim, DraftSentence, PooledQuote, PooledSource, WriterOutput,
    )
    text = "长鑫日赚3.6亿元"
    quote = PooledQuote(quote_id="q-001", text=text, is_quantitative=True,
                        quote_type="data", attached_primary_url="https://cninfo.com.cn/x",
                        span_start=0, span_end=len(text))
    source = PooledSource(source_id="s-001", url="https://cninfo.com.cn/x",
                          domain="cninfo.com.cn", is_primary=True, quotes=[quote],
                          raw_content=text)
    claim = DraftClaim("c-001", "长鑫存储去年日赚3.6亿元。", ["q-001"],
                       category="derived_metric")  # methodology missing
    sentence = DraftSentence("长鑫存储去年日赚3.6亿元。", ["c-001"], ["s-001"], "factual")
    out = WriterOutput(claims=[claim], sentences=[sentence])
    result = await verify(out, [source], judge=_judge_clean)
    assert result.passed is False
    assert "I12" in {v.check for v in result.violations}
```

- [ ] **Step 2: Run to verify RED**

Run: `pytest tests/verifier/test_verifier.py -k i12 -v`
Expected: FAIL — I12 not yet wired, so `verify()` returns no I12 violation and (with a clean primary-backed quote) `result.passed is True` → **AssertionError: True is not False** (proper behavioral RED). Confirm the existing `test_verify_clean_passes` still passes (its clean claim defaults to `category="quantitative"`, so I12 must not touch it).

- [ ] **Step 3: Implement** — import `check_derived_methodology` and add `violations.extend(check_derived_methodology(output, pool_index))` with the other Tier-1 checks. Update the docstring's check list from "six" to "seven".

- [ ] **Step 4: Run to verify GREEN** — `pytest tests/verifier/test_verifier.py -v` → PASS (all, including the pre-existing clean/cross-tier tests).

- [ ] **Step 5: Commit** — `feat(verifier): enforce I12 in the Law-5 publication gate`

---

### Task 6: Writer prompt — teach derived-metric classification + methodology

**Files:**
- Modify: `marketwind/writer/prompt.py` (`_OUTPUT_SPEC`)
- Test: `tests/writer/test_prompt.py`

**Contract:** The JSON claim shape in `_OUTPUT_SPEC` gains `"category"` and `"methodology"` keys, and a rule instructs: default `category` is `"quantitative"`; mark a claim `"derived_metric"` when its number is the source's own computation over base figures (examples 日赚 / 合计减持额); such a claim MUST include a `methodology` label (e.g. `按净利润计`) stating the basis, or use only the base figures instead. Number-fidelity and self-contained-claim rules are untouched (surgical — do not reword adjacent lines).

- [ ] **Step 1: Write the failing test**

```python
from marketwind.writer.prompt import build_writer_prompt

def test_prompt_teaches_derived_metric_methodology():
    msgs = build_writer_prompt([])
    system = msgs[0]["content"]
    assert "derived_metric" in system
    assert "methodology" in system
```

- [ ] **Step 2: Run to verify RED**

Run: `pytest tests/writer/test_prompt.py -k derived -v`
Expected: FAIL — current `_OUTPUT_SPEC` mentions neither token → **AssertionError** on `"derived_metric" in system` (proper: asserts presence, fails because guidance absent). `build_writer_prompt([])` runs fine (it reads the rationalization table and serializes an empty pool), so this is not an import/collection error.

- [ ] **Step 3: Implement** — extend the `_OUTPUT_SPEC` JSON example and add the derived-metric rule bullet as described in the contract above.

- [ ] **Step 4: Run to verify GREEN** — `pytest tests/writer/test_prompt.py -v` → PASS.

- [ ] **Step 5: Prompt regression** — if `tests/prompt_regression/` exists, run `make eval-prompt` (or the pytest path it uses) and confirm the score does not drop below the prior baseline (CLAUDE.md §8.3). If the harness is not present, record that in the commit body and proceed.

- [ ] **Step 6: Commit** — `feat(writer): prompt guidance for derived_metric category + methodology (I12)`

---

### Task 7: DB — migration 0006 + `persist_report` writes the fields

**Files:**
- Create: `migrations/0006_i12_derived_metric.sql`
- Modify: `marketwind/storage/repo.py` (`persist_report`, the claims INSERT lines 109-115)
- Test: `tests/writer/test_repo_writer.py` (append; real Postgres via the existing `conn` fixture)

**Migration content (spec-critical — the CHECK is the integrity backstop):**
```sql
-- I12: derived_metric claims must carry a methodology (CITATION_CONTRACT §4 I12, D-12).
-- Migrations are versioned (schema_migrations); 0006 runs exactly once.
alter table claims add column category text not null default 'quantitative';
alter table claims add column methodology text;
alter table claims add constraint claims_category_enum check (
    category in ('quantitative', 'temporal', 'comparative', 'attribution',
                 'causal', 'quoted_inference', 'freshness', 'derived_metric', 'correction')
);
alter table claims add constraint claims_derived_needs_methodology check (
    category <> 'derived_metric' or methodology is not null
);
```

**persist_report change:** the claims INSERT must include `category` and `methodology`:
```
insert into claims (statement, quote_ids, category, methodology)
values ($1, $2::uuid[], $3, $4) returning claim_id;
```
passing `c.statement, c.quote_ids, c.category, c.methodology`.

- [ ] **Step 1: Write the failing tests** (append to `tests/writer/test_repo_writer.py`; follow its existing `conn` fixture + delete-first pattern)

```python
async def test_persist_report_writes_category_and_methodology(conn):
    import asyncpg
    from marketwind.writer.domain import DraftClaim, DraftSentence, WriterOutput
    from marketwind.writer.render import render_brief
    await conn.execute("delete from sources;")
    await conn.execute("delete from claims;")
    await conn.execute("delete from sentences;")
    sid = await upsert_source(conn, _sample_source())
    pool = await load_pool(conn)
    qid = pool[0].quotes[0].quote_id
    out = WriterOutput(
        claims=[DraftClaim("c-001", "长鑫日赚3.6亿元。", [qid],
                           category="derived_metric", methodology="按净利润计")],
        sentences=[DraftSentence("长鑫日赚3.6亿元。", ["c-001"], [sid], "factual")],
    )
    brief = render_brief(out)
    await persist_report(conn, out.claims, brief.sentences)
    row = await conn.fetchrow("select category, methodology from claims;")
    assert row["category"] == "derived_metric"
    assert row["methodology"] == "按净利润计"


async def test_db_check_rejects_derived_without_methodology(conn):
    import asyncpg
    import pytest
    await conn.execute("delete from claims;")
    with pytest.raises(asyncpg.IntegrityConstraintViolationError):
        await conn.execute(
            "insert into claims (statement, quote_ids, category, methodology)"
            " values ('x', '{}'::uuid[], 'derived_metric', null);"
        )
```

- [ ] **Step 2: Run to verify RED**

Run: `pytest tests/writer/test_repo_writer.py -k "category or check_rejects" -v`
Expected: FAIL — before the migration/persist change, `select category from claims` errors (column absent) / the derived_metric insert is accepted (no CHECK) so `pytest.raises` is unsatisfied. If Postgres/`DATABASE_URL` is unavailable, STOP and report BLOCKED (do not skip — the DB layer is the point of this task).

- [ ] **Step 3: Implement** — write `migrations/0006_i12_derived_metric.sql` as above; update `persist_report`'s INSERT and params. (Migrations auto-apply via the `conn` fixture's `apply_migrations`.)

- [ ] **Step 4: Run to verify GREEN** — `pytest tests/writer/test_repo_writer.py -v` → PASS (existing repo tests + the two new ones).

- [ ] **Step 5: Commit** — `feat(storage): persist claim category/methodology + I12 CHECK constraint (migration 0006)`

---

### Task 8: Full-suite verification + ground-truth regression + progress note

**Files:**
- Create: `docs/progress/i12-derived-methodology.md`

- [ ] **Step 1: Run the full suite** — `pytest -q` (or `make test`). Expected: all green. Any DraftClaim construction site that broke (it should not, given trailing defaults) is fixed here — the fix must trace only to the new fields.

- [ ] **Step 2: Ground-truth regression** — `make test-gt` (the `tests/citation_ground_truth/` sample set, CLAUDE.md §8.2). Expected: no regression. If a sample now legitimately exercises I12, confirm the change is correct, not a softening.

- [ ] **Step 3: Progress note** — write `docs/progress/i12-derived-methodology.md` following the `docs/progress/P1a-scout.md` template: a small table (module → what it does → commit) plus a few bullets on the invariant proven (I12: `derived_metric ⟹ methodology`), the three locked interpretations, and the Verifier-enforced / DB-backstop split.

- [ ] **Step 4: Commit** — `docs(progress): I12 derived-metric methodology note`

---

## Self-Review

**Spec coverage** — I12 (`CITATION_CONTRACT.md:158`) → Tasks 4-5; category enum + methodology field (`:110/:116`) → Tasks 1-2; DB CHECK (`:123`) → Task 7; graded (not reject) handling (`failure-handling.md:25`, Q2) → schema does not reject (Task 2), Verifier flags (Task 4); D-12 → whole plan; Writer emission → Task 6; persistence → Task 7. No uncovered requirement.

**Placeholder scan** — no TBD/"handle edge cases"; every code step shows the code or the exact contract.

**Type consistency** — `check_derived_methodology(output, pool_index) -> list[Violation]` (Task 4) matches the wiring in Task 5; `DraftClaim(..., category, methodology)` field names identical across Tasks 1/2/3/4/7; check code string `"I12"` identical in Tasks 4/5; category token `"derived_metric"` identical in Tasks 2/4/6/7; methodology example `按净利润计` identical in Tasks 1/3/4/7.
