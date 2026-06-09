# Verifier — Law-5 Publication Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert a fresh, independent, fail-closed Verifier pass between the Writer draft and IM publication so no brief is ever published without passing it (Iron Law 5).

**Architecture:** A new pure-core `marketwind/verifier/` package (deterministic Tier-1 checks + DeepSeek-judge Tier-2 checks behind an injected async seam) exposes `verify(output, pool, *, judge) -> VerifyResult`. `run_pipeline` calls `verify` **directly** (hardcoded, mirroring the existing `evaluate_floor` gate) between a `draft()` step and publication; on any violation it records to `claim_failures`, emits a dev-channel status with `trace_id`, and does not publish. Quote re-resolution requires plumbing `raw_content` + spans (already in the DB) into the pool.

**Tech Stack:** Python 3.11+, asyncpg, pytest (`asyncio_mode="auto"` — async tests need no decorator), regex, DeepSeek V4 Pro (judge, live only). Run tests with `.venv/Scripts/python.exe -m pytest`.

**Spec:** `docs/superpowers/specs/2026-06-09-verifier-law5-gate-design.md`.

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
| `marketwind/writer/domain.py` | **modify:** add span fields to `PooledQuote`, `raw_content` to `PooledSource`, add `DraftBundle` |
| `marketwind/storage/repo.py` | **modify:** widen `load_pool` SELECTs; add `record_verifier_failures` |
| `migrations/0003_verifier_failures.sql` | `claim_failures` table |
| `marketwind/writer/runner.py` | **modify:** add `draft_report` returning `DraftBundle`; `run_writer` delegates |
| `marketwind/orchestration/runner.py` | **modify:** hardcoded verify gate + `draft`/`judge`/`record_fail` seams |
| `marketwind/scheduling/run_once.py` | **modify:** forward `draft`/`judge`/`record_fail` |
| `marketwind/scheduling/__main__.py` | **modify:** build live `draft`/`judge`/`record_fail` closures |

Tests created/modified: `tests/verifier/test_domain.py`, `tests/verifier/test_checks.py`, `tests/verifier/test_judge.py`, `tests/verifier/test_verifier.py`, `tests/storage/test_pool_fields.py`, `tests/storage/test_record_failures.py`, `tests/writer/test_draft_bundle.py`, and edits to `tests/orchestration/test_floor_and_pipeline.py`, `tests/scheduling/test_run_once.py`, `tests/scheduling/test_integration_pipeline.py`.

**Execute tasks in numeric order.** Tasks are numbered in dependency order: Task 2 (pool plumbing) adds the `PooledQuote`/`PooledSource` fields the Tier-1 checks (Task 3) construct, so it must run first.

---

## Task 1: Verifier value objects (`domain.py`)

**Files:**
- Create: `marketwind/verifier/__init__.py` (empty)
- Create: `marketwind/verifier/domain.py`
- Test: `tests/verifier/test_domain.py`

- [ ] **Step 1: Create the test directory marker and the failing test**

Create `tests/verifier/__init__.py` (empty) and `tests/verifier/test_domain.py`:

```python
from marketwind.verifier.domain import Violation, VerifyResult


def test_violation_is_frozen_value_object():
    v = Violation(check="RF-4", locus="sentence[0]", detail="anonymous filler")
    assert (v.check, v.locus, v.detail) == ("RF-4", "sentence[0]", "anonymous filler")


def test_verify_result_carries_passed_and_violations():
    v = Violation(check="I3", locus="c-001", detail="no primary")
    res = VerifyResult(passed=False, violations=[v])
    assert res.passed is False
    assert res.violations == [v]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/verifier/test_domain.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'marketwind.verifier'` (this is a pure construction/smoke-import test, so an import-driven RED is the legitimate exception per the RED-discipline note).

- [ ] **Step 3: Create the package and implement the value objects**

Create empty `marketwind/verifier/__init__.py`. Create `marketwind/verifier/domain.py`:

```python
"""Verifier value objects. No I/O, no LLM. passed == (violations == [])."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Violation:
    check: str    # "RF-3" | "I3" | "RF-4" | "RF-10" | "I1" | "I10" | "judge_unavailable"
    locus: str    # claim local_id / "sentence[i]" / quote_id
    detail: str


@dataclass(frozen=True)
class VerifyResult:
    passed: bool
    violations: list[Violation]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/verifier/test_domain.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add marketwind/verifier/__init__.py marketwind/verifier/domain.py tests/verifier/__init__.py tests/verifier/test_domain.py
git commit -m "feat(verifier): Violation + VerifyResult value objects"
```

---

## Task 3: Tier-1 deterministic checks (`checks.py`)

**Files:**
- Create: `marketwind/verifier/checks.py`
- Test: `tests/verifier/test_checks.py`

**Prerequisite:** Task 2 (pool plumbing) must be complete — this task's tests construct `PooledQuote(..., span_start=, span_end=)` and `PooledSource(..., raw_content=)`, which Task 2 adds.

Context: the checks consume a `WriterOutput` (`marketwind/writer/domain.py`: `WriterOutput(claims, sentences)`, `DraftClaim(local_id, statement, quote_ids)`, `DraftSentence(sentence, claim_ids, source_ids, sentence_type)`) plus a quote index built from the pool.

- [ ] **Step 1: Write the failing tests**

Create `tests/verifier/test_checks.py`:

```python
from marketwind.verifier.checks import (
    index_quotes,
    check_quotes_resolve,
    check_quant_has_primary,
    check_no_filler_attribution,
    check_no_first_person_inference,
)
from marketwind.writer.domain import (
    DraftClaim, DraftSentence, WriterOutput, PooledQuote, PooledSource,
)

RAW = "科创50昨日收涨0.36%，成交额约3.24万亿元。"


def _pool_one_quote(text, *, span, is_quant=False, primary=None, is_primary_src=False):
    start, end = span
    q = PooledQuote(quote_id="q1", text=text, is_quantitative=is_quant,
                    quote_type="factual", attached_primary_url=primary,
                    span_start=start, span_end=end)
    s = PooledSource(source_id="s1", url="http://x", domain="x", is_primary=is_primary_src,
                     raw_content=RAW, quotes=[q])
    return [s]


def test_quotes_resolve_passes_when_span_matches():
    text = RAW[5:11]  # the quote substring at its recorded span
    pool = _pool_one_quote(text, span=(5, 11))
    out = WriterOutput(claims=[DraftClaim("c-1", "stmt", ["q1"])], sentences=[])
    assert check_quotes_resolve(out, index_quotes(pool)) == []


def test_quotes_resolve_fires_when_span_does_not_match():
    pool = _pool_one_quote("收涨0.36%", span=(0, 4))  # span 0..4 of RAW is "科创50昨", not the text
    out = WriterOutput(claims=[DraftClaim("c-1", "stmt", ["q1"])], sentences=[])
    res = check_quotes_resolve(out, index_quotes(pool))
    assert len(res) == 1 and res[0].check == "RF-3" and res[0].locus == "c-1"


def test_quotes_resolve_fires_when_quote_missing_from_pool():
    out = WriterOutput(claims=[DraftClaim("c-1", "stmt", ["ghost"])], sentences=[])
    res = check_quotes_resolve(out, index_quotes(_pool_one_quote(RAW[5:11], span=(5, 11))))
    assert len(res) == 1 and res[0].check == "RF-3"


def test_quant_has_primary_passes_with_attached_url():
    pool = _pool_one_quote(RAW[5:11], span=(5, 11), is_quant=True, primary="http://p")
    out = WriterOutput(claims=[DraftClaim("c-1", "stmt", ["q1"])], sentences=[])
    assert check_quant_has_primary(out, index_quotes(pool)) == []


def test_quant_has_primary_passes_when_source_is_primary():
    pool = _pool_one_quote(RAW[5:11], span=(5, 11), is_quant=True, is_primary_src=True)
    out = WriterOutput(claims=[DraftClaim("c-1", "stmt", ["q1"])], sentences=[])
    assert check_quant_has_primary(out, index_quotes(pool)) == []


def test_quant_has_primary_fires_when_no_primary():
    pool = _pool_one_quote(RAW[5:11], span=(5, 11), is_quant=True)
    out = WriterOutput(claims=[DraftClaim("c-1", "stmt", ["q1"])], sentences=[])
    res = check_quant_has_primary(out, index_quotes(pool))
    assert len(res) == 1 and res[0].check == "I3" and res[0].locus == "c-1"


def test_quant_has_primary_ignores_non_quant_claim():
    pool = _pool_one_quote(RAW[5:11], span=(5, 11), is_quant=False)
    out = WriterOutput(claims=[DraftClaim("c-1", "stmt", ["q1"])], sentences=[])
    assert check_quant_has_primary(out, index_quotes(pool)) == []


def test_filler_attribution_fires_on_anonymous_source():
    out = WriterOutput(
        claims=[],
        sentences=[DraftSentence("据报道公司业绩大增。", ["c-1"], ["s1"], "factual")],
    )
    res = check_no_filler_attribution(out)
    assert len(res) == 1 and res[0].check == "RF-4"


def test_filler_attribution_passes_on_clean_sentence():
    out = WriterOutput(
        claims=[],
        sentences=[DraftSentence("公司公告净利润同比增长。", ["c-1"], ["s1"], "factual")],
    )
    assert check_no_filler_attribution(out) == []


def test_first_person_inference_fires():
    out = WriterOutput(
        claims=[],
        sentences=[DraftSentence("综合判断该股将上涨。", ["c-1"], ["s1"], "factual")],
    )
    res = check_no_first_person_inference(out)
    assert len(res) == 1 and res[0].check == "RF-10"


def test_first_person_inference_passes_on_clean_sentence():
    out = WriterOutput(
        claims=[],
        sentences=[DraftSentence("公司公告净利润同比增长。", ["c-1"], ["s1"], "factual")],
    )
    assert check_no_first_person_inference(out) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

First scaffold a stub so the assertions (not an ImportError) fail. Create `marketwind/verifier/checks.py`:

```python
def index_quotes(pool):
    return {}

def check_quotes_resolve(output, qindex):
    return []

def check_quant_has_primary(output, qindex):
    return []

def check_no_filler_attribution(output):
    return []

def check_no_first_person_inference(output):
    return []
```

Run: `.venv/Scripts/python.exe -m pytest tests/verifier/test_checks.py -v`
Expected: FAIL on assertions — the `_fires_` tests assert `len(res) == 1` but the stubs return `[]` (e.g. `test_quotes_resolve_fires_when_span_does_not_match` fails `assert len([]) == 1`). This is a real behavioral RED.

- [ ] **Step 3: Implement the checks**

Replace `marketwind/verifier/checks.py`:

```python
"""Tier-1 deterministic Verifier checks. Pure functions, no LLM, no I/O.

Each check returns a list of Violation; an empty list means the check passed.
`index_quotes` builds the quote_id -> (PooledQuote, PooledSource) map the
resolution/primary checks need."""

from __future__ import annotations

import re

from marketwind.verifier.domain import Violation
from marketwind.writer.domain import PooledQuote, PooledSource, WriterOutput

# RF-4: anonymous-filler attribution that can never be a real, citable source.
_FILLER = re.compile(
    r"据报道|业内人士|市场认为|普遍预期|通常来说|分析人士|知情人士|接近.{0,8}的人士|有消息称"
)
# RF-10 / Law 4: first-person model inference passed off as fact.
_FIRST_PERSON = re.compile(r"系统认为|分析显示|综合判断|经测算|研究表明")


def index_quotes(pool: list[PooledSource]) -> dict[str, tuple[PooledQuote, PooledSource]]:
    out: dict[str, tuple[PooledQuote, PooledSource]] = {}
    for s in pool:
        for q in s.quotes:
            out[q.quote_id] = (q, s)
    return out


def check_quotes_resolve(output: WriterOutput, qindex) -> list[Violation]:
    """RF-3 / RF-9: every quote a claim references must re-resolve against its
    source's raw_content at the recorded span. A quote that does not resolve
    means the claim's grounding cannot be independently re-assembled."""
    out: list[Violation] = []
    for c in output.claims:
        for qid in c.quote_ids:
            entry = qindex.get(qid)
            if entry is None:
                out.append(Violation("RF-3", c.local_id, f"quote {qid} not present in pool"))
                continue
            q, s = entry
            if s.raw_content[q.span_start:q.span_end] != q.text:
                out.append(Violation("RF-3", c.local_id,
                                     f"quote {qid} span does not resolve to its text"))
    return out


def check_quant_has_primary(output: WriterOutput, qindex) -> list[Violation]:
    """I3 / RF-6: a claim referencing any quantitative quote must reference at
    least one quote backed by a primary (attached_primary_url set, or from an
    is_primary source). The Law-3 keystone."""
    out: list[Violation] = []
    for c in output.claims:
        entries = [qindex[qid] for qid in c.quote_ids if qid in qindex]
        if not any(q.is_quantitative for q, _ in entries):
            continue
        has_primary = any((q.attached_primary_url is not None) or s.is_primary
                          for q, s in entries)
        if not has_primary:
            out.append(Violation("I3", c.local_id,
                                 "quantitative claim has no primary-sourced quote"))
    return out


def _scan(output: WriterOutput, pattern: re.Pattern, check: str, detail: str) -> list[Violation]:
    out: list[Violation] = []
    for i, s in enumerate(output.sentences):
        if pattern.search(s.sentence):
            out.append(Violation(check, f"sentence[{i}]", detail))
    for c in output.claims:
        if pattern.search(c.statement):
            out.append(Violation(check, c.local_id, detail))
    return out


def check_no_filler_attribution(output: WriterOutput) -> list[Violation]:
    """RF-4."""
    return _scan(output, _FILLER, "RF-4", "anonymous filler attribution")


def check_no_first_person_inference(output: WriterOutput) -> list[Violation]:
    """RF-10 / Law 4."""
    return _scan(output, _FIRST_PERSON, "RF-10", "first-person model inference")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/verifier/test_checks.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add marketwind/verifier/checks.py tests/verifier/test_checks.py
git commit -m "feat(verifier): Tier-1 deterministic checks (resolve, quant-primary, filler, first-person)"
```

---

## Task 4: Tier-2 judge checks (`judge.py`)

**Files:**
- Create: `marketwind/verifier/judge.py`
- Test: `tests/verifier/test_judge.py`

Context: the judge is an injected async seam `judge: Callable[[str], Awaitable[str]]` returning a JSON string (same injected-seam pattern as the Writer's `call`). The check builds a prompt, calls `judge`, parses `{"violations": [{"locus": "...", "detail": "..."}]}`. **Fail closed:** any exception from `judge` or any JSON-parse failure yields a single `judge_unavailable` violation (we cannot certify → no publish).

- [ ] **Step 1: Write the failing tests**

Create `tests/verifier/test_judge.py`:

```python
import json

from marketwind.verifier.judge import check_no_synthesis, check_no_contradiction
from marketwind.writer.domain import DraftClaim, DraftSentence, WriterOutput

_OUT = WriterOutput(
    claims=[DraftClaim("c-1", "甲公司净利润增长", ["q1"]),
            DraftClaim("c-2", "乙公司营收下降", ["q2"])],
    sentences=[DraftSentence("甲公司净利润增长且乙公司营收下降。", ["c-1", "c-2"], ["s1"], "factual")],
)


def _judge_returning(payload):
    async def _j(prompt):
        return payload
    return _j


async def test_synthesis_clean_returns_no_violation():
    judge = _judge_returning(json.dumps({"violations": []}))
    assert await check_no_synthesis(_OUT, judge=judge) == []


async def test_synthesis_flagged_returns_violation():
    judge = _judge_returning(json.dumps(
        {"violations": [{"locus": "sentence[0]", "detail": "fuses c-1 and c-2"}]}))
    res = await check_no_synthesis(_OUT, judge=judge)
    assert len(res) == 1 and res[0].check == "I1" and res[0].locus == "sentence[0]"


async def test_contradiction_flagged_returns_violation():
    judge = _judge_returning(json.dumps(
        {"violations": [{"locus": "c-1|c-2", "detail": "incompatible"}]}))
    res = await check_no_contradiction(_OUT, judge=judge)
    assert len(res) == 1 and res[0].check == "I10"


async def test_judge_exception_fails_closed():
    async def _boom(prompt):
        raise RuntimeError("network down")
    res = await check_no_synthesis(_OUT, judge=_boom)
    assert len(res) == 1 and res[0].check == "judge_unavailable"


async def test_judge_garbage_output_fails_closed():
    judge = _judge_returning("not json at all")
    res = await check_no_contradiction(_OUT, judge=judge)
    assert len(res) == 1 and res[0].check == "judge_unavailable"
```

- [ ] **Step 2: Run the tests to verify they fail**

Scaffold a stub first so assertions fail (not ImportError). Create `marketwind/verifier/judge.py`:

```python
async def check_no_synthesis(output, *, judge):
    return []

async def check_no_contradiction(output, *, judge):
    return []
```

Run: `.venv/Scripts/python.exe -m pytest tests/verifier/test_judge.py -v`
Expected: FAIL on assertions — `test_synthesis_flagged_returns_violation` asserts `len(res) == 1` but stub returns `[]`; `test_judge_exception_fails_closed` asserts a `judge_unavailable` violation but stub returns `[]`.

- [ ] **Step 3: Implement the judge checks**

Replace `marketwind/verifier/judge.py`:

```python
"""Tier-2 Verifier checks via the DeepSeek judge (injected async seam).

`judge(prompt) -> str` returns a JSON string {"violations": [{"locus","detail"}]}.
Fails CLOSED: any judge exception or unparseable verdict yields a single
'judge_unavailable' violation so the report cannot be certified."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from marketwind.verifier.domain import Violation
from marketwind.writer.domain import WriterOutput

JudgeFn = Callable[[str], Awaitable[str]]

_SYNTHESIS_INSTRUCTION = (
    "你是事实核查器。下面是若干句子及其引用的claim陈述。判断是否有任一句子把两个"
    "不同的claim融合成一个二者单独都未陈述的新论断（跨claim综合，违反不变量I1）。"
    "只返回JSON：{\"violations\":[{\"locus\":\"sentence[i]\",\"detail\":\"...\"}]}，"
    "无问题则violations为空数组。\n\n"
)
_CONTRADICTION_INSTRUCTION = (
    "你是事实核查器。下面是若干claim陈述。判断是否存在两个claim互相矛盾（违反不变量"
    "I10）。只返回JSON：{\"violations\":[{\"locus\":\"c-x|c-y\",\"detail\":\"...\"}]}，"
    "无矛盾则violations为空数组。\n\n"
)


def _render_sentences(output: WriterOutput) -> str:
    stmt = {c.local_id: c.statement for c in output.claims}
    lines = []
    for i, s in enumerate(output.sentences):
        cited = "；".join(stmt.get(cid, cid) for cid in s.claim_ids)
        lines.append(f"sentence[{i}]: {s.sentence}  (claims: {cited})")
    return "\n".join(lines)


def _render_claims(output: WriterOutput) -> str:
    return "\n".join(f"{c.local_id}: {c.statement}" for c in output.claims)


async def _ask(output: WriterOutput, *, judge: JudgeFn, check: str,
               instruction: str, body: str) -> list[Violation]:
    try:
        raw = await judge(instruction + body)
        parsed = json.loads(raw)
        items = parsed["violations"]
    except Exception:
        return [Violation("judge_unavailable", check,
                          f"{check} judge unavailable or unparseable verdict")]
    return [Violation(check, str(it.get("locus", "")), str(it.get("detail", "")))
            for it in items]


async def check_no_synthesis(output: WriterOutput, *, judge: JudgeFn) -> list[Violation]:
    """I1 / RF-2."""
    return await _ask(output, judge=judge, check="I1",
                      instruction=_SYNTHESIS_INSTRUCTION, body=_render_sentences(output))


async def check_no_contradiction(output: WriterOutput, *, judge: JudgeFn) -> list[Violation]:
    """I10 / RF-7 (coarse; no time-window precision — Tier-3 gap)."""
    return await _ask(output, judge=judge, check="I10",
                      instruction=_CONTRADICTION_INSTRUCTION, body=_render_claims(output))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/verifier/test_judge.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add marketwind/verifier/judge.py tests/verifier/test_judge.py
git commit -m "feat(verifier): Tier-2 judge checks (synthesis, contradiction) — fail closed"
```

---

## Task 5: The `verify` aggregator (`verifier.py`)

**Files:**
- Create: `marketwind/verifier/verifier.py`
- Test: `tests/verifier/test_verifier.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/verifier/test_verifier.py`:

```python
import json

from marketwind.verifier.verifier import verify
from marketwind.writer.domain import (
    DraftClaim, DraftSentence, WriterOutput, PooledQuote, PooledSource,
)

RAW = "科创50昨日收涨0.36%，成交额约3.24万亿元。公司公告净利润同比增长。"


def _clean_pool():
    q = PooledQuote(quote_id="q1", text=RAW[16:24], is_quantitative=False,
                    quote_type="factual", attached_primary_url=None,
                    span_start=16, span_end=24)
    s = PooledSource(source_id="s1", url="http://x", domain="x", is_primary=False,
                     raw_content=RAW, quotes=[q])
    return [s]


async def _judge_clean(prompt):
    return json.dumps({"violations": []})


async def test_clean_report_passes():
    out = WriterOutput(
        claims=[DraftClaim("c-1", RAW[16:24], ["q1"])],
        sentences=[DraftSentence(RAW[16:24] + "。", ["c-1"], ["s1"], "factual")],
    )
    res = await verify(out, _clean_pool(), judge=_judge_clean)
    assert res.passed is True and res.violations == []


async def test_tier1_violation_fails_and_aggregates():
    # quantitative quote with no primary -> I3 fires; passed must be False.
    q = PooledQuote(quote_id="q1", text=RAW[16:24], is_quantitative=True,
                    quote_type="data", attached_primary_url=None,
                    span_start=16, span_end=24)
    s = PooledSource(source_id="s1", url="http://x", domain="x", is_primary=False,
                     raw_content=RAW, quotes=[q])
    out = WriterOutput(claims=[DraftClaim("c-1", RAW[16:24], ["q1"])], sentences=[])
    res = await verify(out, [s], judge=_judge_clean)
    assert res.passed is False
    assert any(v.check == "I3" for v in res.violations)


async def test_tier2_judge_unavailable_fails_closed():
    async def _boom(prompt):
        raise RuntimeError("down")
    out = WriterOutput(
        claims=[DraftClaim("c-1", RAW[16:24], ["q1"])],
        sentences=[DraftSentence(RAW[16:24] + "。", ["c-1"], ["s1"], "factual")],
    )
    res = await verify(out, _clean_pool(), judge=_boom)
    assert res.passed is False
    assert any(v.check == "judge_unavailable" for v in res.violations)
```

- [ ] **Step 2: Run the tests to verify they fail**

Scaffold a stub so assertions fail. Create `marketwind/verifier/verifier.py`:

```python
from marketwind.verifier.domain import VerifyResult

async def verify(output, pool, *, judge):
    return VerifyResult(passed=True, violations=[])
```

Run: `.venv/Scripts/python.exe -m pytest tests/verifier/test_verifier.py -v`
Expected: FAIL on assertions — `test_tier1_violation_fails_and_aggregates` asserts `res.passed is False` but stub returns `passed=True`.

- [ ] **Step 3: Implement the aggregator**

Replace `marketwind/verifier/verifier.py`:

```python
"""verify(): the fresh, independent Law-5 pass. Runs all Tier-1 deterministic
checks then both Tier-2 judge checks, aggregates every Violation, and passes
only when none fired."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from marketwind.verifier.checks import (
    check_no_filler_attribution,
    check_no_first_person_inference,
    check_quant_has_primary,
    check_quotes_resolve,
    index_quotes,
)
from marketwind.verifier.domain import VerifyResult, Violation
from marketwind.verifier.judge import check_no_contradiction, check_no_synthesis
from marketwind.writer.domain import PooledSource, WriterOutput

JudgeFn = Callable[[str], Awaitable[str]]


async def verify(output: WriterOutput, pool: list[PooledSource], *,
                 judge: JudgeFn) -> VerifyResult:
    qindex = index_quotes(pool)
    violations: list[Violation] = []
    violations += check_quotes_resolve(output, qindex)
    violations += check_quant_has_primary(output, qindex)
    violations += check_no_filler_attribution(output)
    violations += check_no_first_person_inference(output)
    violations += await check_no_synthesis(output, judge=judge)
    violations += await check_no_contradiction(output, judge=judge)
    return VerifyResult(passed=(not violations), violations=violations)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/verifier/test_verifier.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add marketwind/verifier/verifier.py tests/verifier/test_verifier.py
git commit -m "feat(verifier): verify() aggregator over Tier-1 + Tier-2 checks"
```

---

## Task 2: Plumb `raw_content` + spans into the pool

**Files:**
- Modify: `marketwind/writer/domain.py` (PooledQuote, PooledSource)
- Modify: `marketwind/storage/repo.py:49-82` (`load_pool`)
- Test: `tests/storage/test_pool_fields.py`

Context: the DB already stores `sources.raw_content` and `quotes.span_start`/`span_end` (migration `0002_p1_core.sql`); `load_pool` just drops them. This task adds the fields to the two frozen dataclasses and widens the two SELECTs. The Tier-1 checks (Task 3) and the verify aggregator (Task 5) depend on these fields, which is why this runs before them.

- [ ] **Step 1: Write the failing test**

Create `tests/storage/test_pool_fields.py`:

```python
from marketwind.writer.domain import PooledQuote, PooledSource


def test_pooled_quote_carries_spans():
    q = PooledQuote(quote_id="q1", text="abc", is_quantitative=True,
                    quote_type="factual", attached_primary_url=None,
                    span_start=3, span_end=6)
    assert (q.span_start, q.span_end) == (3, 6)


def test_pooled_source_carries_raw_content():
    s = PooledSource(source_id="s1", url="http://x", domain="x", is_primary=False,
                     raw_content="abcdef", quotes=[])
    assert s.raw_content == "abcdef"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/storage/test_pool_fields.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'span_start'` (the frozen dataclass rejects the new kwarg). This is a construction RED on a real signature mismatch.

- [ ] **Step 3: Add the fields**

In `marketwind/writer/domain.py`, change `PooledQuote` and `PooledSource`:

```python
@dataclass(frozen=True)
class PooledQuote:
    quote_id: str          # real DB uuid (text form)
    text: str
    is_quantitative: bool
    quote_type: str        # factual | quoted_inference | data
    attached_primary_url: str | None
    span_start: int        # index into the owning source's raw_content
    span_end: int


@dataclass(frozen=True)
class PooledSource:
    source_id: str         # real DB uuid (text form)
    url: str
    domain: str
    is_primary: bool
    raw_content: str       # frozen cleaned main-content text; spans index into this
    quotes: list[PooledQuote]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/storage/test_pool_fields.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Widen `load_pool` to fetch the new columns**

In `marketwind/storage/repo.py`, update the two queries and the constructors in `load_pool`:

```python
async def load_pool(conn: asyncpg.Connection) -> list[PooledSource]:
    """Load the persisted quote pool with real DB UUIDs (Writer input)."""
    src_rows = await conn.fetch(
        "select source_id, url, domain, is_primary, raw_content from sources order by ingested_at;"
    )
    pool: list[PooledSource] = []
    for s in src_rows:
        q_rows = await conn.fetch(
            """
            select quote_id, text, is_quantitative, quote_type, attached_primary_url,
                   span_start, span_end
            from quotes where source_id = $1 order by span_start;
            """,
            s["source_id"],
        )
        quotes = [
            PooledQuote(
                quote_id=str(q["quote_id"]),
                text=q["text"],
                is_quantitative=q["is_quantitative"],
                quote_type=q["quote_type"],
                attached_primary_url=q["attached_primary_url"],
                span_start=q["span_start"],
                span_end=q["span_end"],
            )
            for q in q_rows
        ]
        pool.append(
            PooledSource(
                source_id=str(s["source_id"]),
                url=s["url"],
                domain=s["domain"],
                is_primary=s["is_primary"],
                raw_content=s["raw_content"],
                quotes=quotes,
            )
        )
    return pool
```

- [ ] **Step 6: Run the full writer + storage suites to confirm no construction site broke**

Run: `.venv/Scripts/python.exe -m pytest tests/writer tests/storage -v`
Expected: PASS. If any existing test constructs `PooledQuote`/`PooledSource` positionally and breaks, update those call sites to pass the new fields (search: `.venv/Scripts/python.exe -m pytest` failures will name them). Note: `tests/writer/test_writer.py`, `test_render.py`, `test_render_budget.py`, `test_repo_writer.py` may build pool objects — update each to include `span_start`/`span_end` (use `0`/`len(text)`) and `raw_content` (the quote text or a containing string).

- [ ] **Step 7: Commit**

```bash
git add marketwind/writer/domain.py marketwind/storage/repo.py tests/storage/test_pool_fields.py
git commit -m "feat(storage): plumb raw_content + quote spans into the pool for verifier re-resolution"
```

---

## Task 6: `claim_failures` table + `record_verifier_failures`

**Files:**
- Create: `migrations/0003_verifier_failures.sql`
- Modify: `marketwind/storage/repo.py` (add function)
- Test: `tests/storage/test_record_failures.py`

Context: existing repo functions hit a real DB. `tests/writer/test_repo_writer.py` shows the project's live-DB repo test pattern — mirror it (skip when no DB is reachable). The function inserts one row per `Violation`.

- [ ] **Step 1: Create the migration**

Create `migrations/0003_verifier_failures.sql`:

```sql
-- Verifier failures (CITATION_CONTRACT §7 / red-flags). One row per Violation
-- when the Law-5 gate declines to publish. The full claim state machine and
-- weekly-review loop are Tier-3 (deferred); this is the minimal persistence.

create table if not exists claim_failures (
    failure_id  uuid primary key default gen_random_uuid(),
    trace_id    text not null,
    check_name  text not null,   -- "RF-3" | "I3" | "RF-4" | "RF-10" | "I1" | "I10" | "judge_unavailable"
    locus       text not null,   -- claim local_id / "sentence[i]" / quote_id
    detail      text not null,
    created_at  timestamptz not null default now()
);

create index if not exists claim_failures_trace_id_idx on claim_failures (trace_id);
```

- [ ] **Step 2: Write the failing test**

Create `tests/storage/test_record_failures.py` (mirror the DB-availability guard used in `tests/writer/test_repo_writer.py` — copy its skip/connection helper exactly):

```python
import pytest
import asyncpg

from marketwind.config import settings
from marketwind.storage.repo import record_verifier_failures
from marketwind.verifier.domain import Violation


async def _conn_or_skip():
    try:
        return await asyncpg.connect(settings.database_url)
    except Exception:
        pytest.skip("no database available")


async def test_record_verifier_failures_inserts_one_row_per_violation():
    conn = await _conn_or_skip()
    try:
        await conn.execute("delete from claim_failures where trace_id = 'test-vf';")
        await record_verifier_failures(conn, "test-vf", [
            Violation("RF-4", "sentence[0]", "anonymous filler"),
            Violation("I3", "c-1", "no primary"),
        ])
        n = await conn.fetchval(
            "select count(*) from claim_failures where trace_id = 'test-vf';")
        assert n == 2
        await conn.execute("delete from claim_failures where trace_id = 'test-vf';")
    finally:
        await conn.close()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/storage/test_record_failures.py -v`
Expected: FAIL with `ImportError: cannot import name 'record_verifier_failures'` if no DB, OR (with DB up) the test runs and fails because the function does not exist. Since this is a repo I/O function (not pure logic) and may skip without a DB, **apply the migration and ensure the DB is reachable so the assertion (not the import) is what's exercised**: `docker compose exec -T db psql -U <user> -d <db> -f /migrations/0003_verifier_failures.sql` (or the project's migration runner). Then re-run; Expected: FAIL on `ImportError`/`AttributeError` for the missing function — acceptable here because this is an I/O-binding task, but prefer scaffolding the function as a stub `raise NotImplementedError` and watching the count assertion fail.

- [ ] **Step 4: Implement the function**

In `marketwind/storage/repo.py`, add:

```python
async def record_verifier_failures(conn, trace_id: str, violations) -> None:
    """Persist one claim_failures row per Verifier Violation (Law-5 gate decline)."""
    if not violations:
        return
    await conn.executemany(
        """
        insert into claim_failures (trace_id, check_name, locus, detail)
        values ($1, $2, $3, $4);
        """,
        [(trace_id, v.check, v.locus, v.detail) for v in violations],
    )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/storage/test_record_failures.py -v`
Expected: PASS (or skip if no DB; with DB up after migration, PASS).

- [ ] **Step 6: Commit**

```bash
git add migrations/0003_verifier_failures.sql marketwind/storage/repo.py tests/storage/test_record_failures.py
git commit -m "feat(storage): claim_failures table + record_verifier_failures"
```

---

## Task 7: `DraftBundle` + `draft_report` (Writer side)

**Files:**
- Modify: `marketwind/writer/domain.py` (add `DraftBundle`)
- Modify: `marketwind/writer/runner.py` (add `draft_report`; `run_writer` delegates)
- Test: `tests/writer/test_draft_bundle.py`

Context: the pipeline needs the *structured* draft (output + pool) plus the rendered body, with persistence deferred until after verify. `DraftBundle` carries a `commit` thunk that persists and returns `report_id`; `run_writer` keeps its `(report_id, body)` contract by calling `commit()` immediately.

- [ ] **Step 1: Add `DraftBundle` to `writer/domain.py`**

Append to `marketwind/writer/domain.py` (add `from collections.abc import Awaitable, Callable` to its imports):

```python
@dataclass(frozen=True)
class DraftBundle:
    output: WriterOutput
    pool: list[PooledSource]
    body: str
    commit: Callable[[], Awaitable[str]]   # persists the report, returns report_id;
                                           # called ONLY after the Verifier passes
```

- [ ] **Step 2: Write the failing test**

Create `tests/writer/test_draft_bundle.py`:

```python
from marketwind.writer.domain import (
    DraftBundle, DraftClaim, DraftSentence, PooledQuote, PooledSource, WriterOutput,
)
from marketwind.writer.runner import draft_report


class _FakeConn:
    """Minimal stand-in: load_pool/persist_report are monkeypatched, so this is unused."""


async def test_draft_report_returns_bundle_and_defers_commit(monkeypatch):
    committed = {"n": 0}
    pool = [PooledSource(source_id="s1", url="http://x", domain="x", is_primary=False,
                         raw_content="科创50收涨0.36%。", quotes=[
                             PooledQuote(quote_id="q1", text="科创50收涨0.36%",
                                         is_quantitative=True, quote_type="data",
                                         attached_primary_url="http://p",
                                         span_start=0, span_end=9)])]
    output = WriterOutput(
        claims=[DraftClaim("c-1", "科创50收涨0.36%", ["q1"])],
        sentences=[DraftSentence("科创50收涨0.36%。", ["c-1"], ["s1"], "factual")],
    )

    async def _fake_load_pool(conn):
        return pool

    async def _fake_assemble(p, *, call):
        return output

    async def _fake_persist(conn, claims, sentences):
        committed["n"] += 1
        return "report-123"

    monkeypatch.setattr("marketwind.writer.runner.load_pool", _fake_load_pool)
    monkeypatch.setattr("marketwind.writer.runner.assemble", _fake_assemble)
    monkeypatch.setattr("marketwind.writer.runner.persist_report", _fake_persist)

    async def _call(messages):
        return "{}"

    bundle = await draft_report(_FakeConn(), call=_call)
    assert isinstance(bundle, DraftBundle)
    assert bundle.output is output
    assert bundle.pool is pool
    assert "科创50" in bundle.body
    assert committed["n"] == 0          # NOT persisted yet — commit is deferred
    report_id = await bundle.commit()
    assert report_id == "report-123" and committed["n"] == 1
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/writer/test_draft_bundle.py -v`
Expected: FAIL with `ImportError: cannot import name 'draft_report'`. Scaffold a stub to get an assertion RED: add to `runner.py` `async def draft_report(conn, *, call, max_chars=500): return None`, re-run → FAIL on `assert isinstance(bundle, DraftBundle)` (None is not DraftBundle).

- [ ] **Step 4: Implement `draft_report` and delegate `run_writer`**

Replace `marketwind/writer/runner.py`:

```python
"""End-to-end Writer run: load pool → assemble → render → (deferred) persist.

draft_report returns a DraftBundle whose commit() persists only when called —
the Law-5 gate calls commit() AFTER the Verifier passes. run_writer keeps its
eager (report_id, body) contract by committing immediately. The LLM call is
injected so both are offline-testable; the live entrypoint passes call_deepseek."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from marketwind.storage.repo import load_pool, persist_report
from marketwind.writer.domain import DraftBundle
from marketwind.writer.render import render_brief
from marketwind.writer.writer import assemble

CallFn = Callable[[list[dict]], Awaitable[str]]


async def draft_report(conn, *, call: CallFn, max_chars: int = 500) -> DraftBundle:
    """Assemble + render the brief WITHOUT persisting. commit() persists on demand."""
    pool = await load_pool(conn)
    output = await assemble(pool, call=call)
    brief = render_brief(output, max_chars=max_chars)

    async def _commit() -> str:
        return await persist_report(conn, output.claims, brief.sentences)

    return DraftBundle(output=output, pool=pool, body=brief.body, commit=_commit)


async def run_writer(conn, *, call: CallFn, max_chars: int = 500) -> tuple[str, str]:
    """Eager variant kept for existing callers: draft then commit immediately."""
    bundle = await draft_report(conn, call=call, max_chars=max_chars)
    report_id = await bundle.commit()
    return report_id, bundle.body
```

- [ ] **Step 5: Run the writer suite to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/writer/test_draft_bundle.py tests/writer/test_repo_writer.py -v`
Expected: PASS (draft_bundle: 1 passed; repo_writer: unchanged, still passes since `run_writer` behavior is identical).

- [ ] **Step 6: Commit**

```bash
git add marketwind/writer/domain.py marketwind/writer/runner.py tests/writer/test_draft_bundle.py
git commit -m "feat(writer): DraftBundle + draft_report with deferred commit"
```

---

## Task 8: Hardcoded verify gate in `run_pipeline`

**Files:**
- Modify: `marketwind/orchestration/runner.py`
- Test: `tests/orchestration/test_floor_and_pipeline.py`

Context: `run_pipeline` currently takes `make_body: () -> Awaitable[str]`. Replace it with `draft: () -> Awaitable[DraftBundle]`, add injected `judge` and `record_fail` seams, and call `verify(...)` **directly** (hardcoded, like `evaluate_floor`). On verify-fail: `record_fail`, status to dev_channel, no publish. On pass: `bundle.commit()` then publish.

- [ ] **Step 1: Update the existing tests (they define the new contract)**

Rewrite `tests/orchestration/test_floor_and_pipeline.py`. Keep the `_src`/`_above_floor`/`_below_floor` helpers (lines 11-31) unchanged. Replace the two pipeline tests and add two new ones:

```python
import pytest

from marketwind.gateway.im.label import DEV_PREFIX
from marketwind.gateway.im.stub import StubSink
from marketwind.orchestration.runner import run_pipeline
from marketwind.scout.domain import Quote, Source
from marketwind.writer.domain import DraftBundle, WriterOutput
from datetime import datetime, timezone

# ... keep _src, _above_floor, _below_floor exactly as they are ...


async def _noop_commit():
    return "report-x"


def _bundle(body="科创50昨日收涨0.36%。[1]"):
    return DraftBundle(output=WriterOutput(claims=[], sentences=[]), pool=[],
                       body=body, commit=_noop_commit)


async def _judge_clean(prompt):
    return '{"violations": []}'


async def _record_noop(trace_id, violations):
    return None


@pytest.mark.asyncio
async def test_sub_floor_emits_status_and_does_not_draft():
    primary, dev = StubSink(), StubSink()
    called = {"drafted": False}

    async def draft():
        called["drafted"] = True
        return _bundle()

    await run_pipeline(
        sources=_below_floor(), draft=draft, judge=_judge_clean,
        record_fail=_record_noop, primary=primary, fallback=StubSink(),
        dev_channel=dev, trace_id="t-low",
    )
    assert primary.sent == []
    assert called["drafted"] is False        # Writer never invoked on sub-floor
    assert len(dev.sent) == 1 and "t-low" in dev.sent[0]
    assert "grounded_quotes=5" in dev.sent[0]


@pytest.mark.asyncio
async def test_above_floor_verifies_commits_labels_and_pushes():
    primary, dev = StubSink(), StubSink()
    committed = {"n": 0}

    async def _commit():
        committed["n"] += 1
        return "report-1"

    async def draft():
        return DraftBundle(output=WriterOutput(claims=[], sentences=[]), pool=[],
                           body="科创50昨日收涨0.36%，成交额约3.24万亿元。[1]", commit=_commit)

    await run_pipeline(
        sources=_above_floor(), draft=draft, judge=_judge_clean,
        record_fail=_record_noop, primary=primary, fallback=StubSink(),
        dev_channel=dev, trace_id="t-ok",
    )
    assert len(primary.sent) == 1 and primary.sent[0].startswith(DEV_PREFIX)
    assert len(primary.sent[0]) <= 500
    assert committed["n"] == 1               # committed exactly once, after verify
    assert dev.sent == []


@pytest.mark.asyncio
async def test_verify_failure_records_status_and_does_not_publish_or_commit():
    primary, dev = StubSink(), StubSink()
    recorded = {"violations": None}
    committed = {"n": 0}

    async def _commit():
        committed["n"] += 1
        return "report-1"

    async def draft():
        # one factual sentence with first-person inference -> RF-10 fires deterministically
        from marketwind.writer.domain import DraftSentence
        out = WriterOutput(claims=[], sentences=[
            DraftSentence("综合判断该股将上涨。", [], ["s1"], "structural")])
        return DraftBundle(output=out, pool=[], body="x", commit=_commit)

    async def record_fail(trace_id, violations):
        recorded["violations"] = violations

    await run_pipeline(
        sources=_above_floor(), draft=draft, judge=_judge_clean,
        record_fail=record_fail, primary=primary, fallback=StubSink(),
        dev_channel=dev, trace_id="t-bad",
    )
    assert primary.sent == []                                 # NOT published
    assert committed["n"] == 0                                # NOT committed
    assert recorded["violations"] and recorded["violations"][0].check == "RF-10"
    assert len(dev.sent) == 1 and "t-bad" in dev.sent[0] and "RF-10" in dev.sent[0]


@pytest.mark.asyncio
async def test_judge_unavailable_fails_closed_no_publish():
    primary, dev = StubSink(), StubSink()

    async def draft():
        return _bundle()

    async def _judge_boom(prompt):
        raise RuntimeError("network down")

    await run_pipeline(
        sources=_above_floor(), draft=draft, judge=_judge_boom,
        record_fail=_record_noop, primary=primary, fallback=StubSink(),
        dev_channel=dev, trace_id="t-judge",
    )
    assert primary.sent == []                                 # fail closed
    assert dev.sent and "judge_unavailable" in dev.sent[0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/orchestration/test_floor_and_pipeline.py -v`
Expected: FAIL — `TypeError: run_pipeline() got an unexpected keyword argument 'draft'` (signature still uses `make_body`). This is a real contract RED.

- [ ] **Step 3: Implement the gate**

Replace `marketwind/orchestration/runner.py`:

```python
"""P1c+verifier orchestrator: grounded-floor gate -> draft -> Law-5 verify gate
-> commit -> label -> push. Both gates are hardcoded (called directly), so no
caller can wire a pipeline that skips the floor or the Verifier."""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from marketwind.gateway.im.base import IMChannel, SendResult
from marketwind.gateway.im.label import apply_label
from marketwind.scout.domain import Source
from marketwind.scout.runner import evaluate_floor
from marketwind.verifier.domain import Violation
from marketwind.verifier.verifier import verify
from marketwind.writer.domain import DraftBundle

DraftFn = Callable[[], Awaitable[DraftBundle]]
JudgeFn = Callable[[str], Awaitable[str]]
RecordFailFn = Callable[[str, list[Violation]], Awaitable[None]]


def send_with_fallback(text: str, *, primary: IMChannel, fallback: IMChannel,
                       trace_id: str) -> None:
    """Try primary; on failure try fallback; if both fail raise with trace_id."""
    res: SendResult = primary.send(text)
    if res.ok:
        return
    res = fallback.send(text)
    if res.ok:
        return
    raise RuntimeError(f"both IM channels failed for trace_id={trace_id}: {res.error}")


def _floor_status(floor, trace_id: str) -> str:
    return (f"[MarketWind] sub-floor shortfall trace_id={trace_id} "
            f"grounded_quotes={floor.grounded_quotes} "
            f"primary_traced_quotes={floor.primary_traced_quotes} "
            f"independent_outlets={floor.independent_outlets} — brief NOT published")


def _verify_status(result, trace_id: str) -> str:
    checks = ",".join(sorted({v.check for v in result.violations}))
    return (f"[MarketWind] verifier gate failed trace_id={trace_id} "
            f"checks={checks} ({len(result.violations)} violations) — brief NOT published")


async def run_pipeline(*, sources: list[Source],
                       draft: DraftFn, judge: JudgeFn, record_fail: RecordFailFn,
                       primary: IMChannel, fallback: IMChannel,
                       dev_channel: IMChannel, trace_id: str) -> None:
    """Floor gate -> draft -> fresh Verifier pass (Law 5) -> commit -> label -> push.

    Sub-floor: status to dev_channel, no draft (draft is lazy → no Writer call).
    Verify-fail: persist violations, status to dev_channel, NO commit, NO publish.
    """
    floor = evaluate_floor(sources)
    if not floor.passed:
        dev_channel.send(_floor_status(floor, trace_id))
        return
    bundle = await draft()
    result = await verify(bundle.output, bundle.pool, judge=judge)
    if not result.passed:
        await record_fail(trace_id, result.violations)
        dev_channel.send(_verify_status(result, trace_id))
        return
    await bundle.commit()
    labeled = apply_label(bundle.body)
    send_with_fallback(labeled, primary=primary, fallback=fallback, trace_id=trace_id)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/orchestration/test_floor_and_pipeline.py -v`
Expected: PASS (5 passed — the 1 sub-floor + 4 new)

- [ ] **Step 5: Commit**

```bash
git add marketwind/orchestration/runner.py tests/orchestration/test_floor_and_pipeline.py
git commit -m "feat(orchestration): hardcoded Law-5 verify gate in run_pipeline"
```

---

## Task 9: Thread the seams through `run_once` + live `__main__`

**Files:**
- Modify: `marketwind/scheduling/run_once.py`
- Modify: `marketwind/scheduling/__main__.py` (live wiring, `# pragma: no cover`)
- Create: `marketwind/verifier/runner.py` (live judge seam, `# pragma: no cover`)
- Test: `tests/scheduling/test_run_once.py`, `tests/scheduling/test_integration_pipeline.py`

Context: `run_once` forwards `make_body` to `run_pipeline`. Replace it with `draft` and forward `judge` + `record_fail`. The calendar/freshness/sub-floor tests never reach verify, so they pass trivial fakes.

- [ ] **Step 1: Update `run_once` tests to the new seam**

In `tests/scheduling/test_run_once.py`, replace the `_make_body` helper and the `_run` wrapper, and update assertions that referenced `make_body`/`awaited` to use `draft`:

```python
from marketwind.writer.domain import DraftBundle, WriterOutput


async def _commit_noop():
    return "r"


def _draft(awaited):
    async def _d():
        awaited.append(1)
        return DraftBundle(output=WriterOutput(claims=[], sentences=[]), pool=[],
                           body="正文：科创50盘前。", commit=_commit_noop)
    return _d


async def _judge_clean(prompt):
    return '{"violations": []}'


async def _record_noop(trace_id, violations):
    return None


async def _run(now, *, gather, draft, primary, fallback, dev, force=False,
               tol=90, anchor=_ANCHOR):
    await run_once(now, sessions=_SESSIONS, anchor=anchor, tolerance_min=tol,
                   ceiling_cst=_CEIL, gather=gather, draft=draft,
                   judge=_judge_clean, record_fail=_record_noop,
                   primary=primary, fallback=fallback, dev_channel=dev,
                   trace_id="t", force_calendar=force)
```

Then update every call site: replace `make_body=_make_body(awaited)` with `draft=_draft(awaited)` (and `make_body=_make_body([])` with `draft=_draft([])`). The assertions on `awaited` remain valid (draft appends to it). The above-floor tests still assert `primary.sent[0].startswith("【DEV / UNVERIFIED")` — the empty `WriterOutput` verifies clean (no claims/sentences → no violations, `_judge_clean` returns empty), so it publishes.

- [ ] **Step 2: Update the integration test to the new seam**

In `tests/scheduling/test_integration_pipeline.py`, replace `_make_body` with a `_draft` helper and pass `judge`/`record_fail`:

```python
from marketwind.writer.domain import DraftBundle, WriterOutput


def _draft(awaited):
    async def _d():
        awaited.append(1)
        async def _commit():
            return "r"
        return DraftBundle(output=WriterOutput(claims=[], sentences=[]), pool=[],
                           body="正文：科创50盘前综述。", commit=_commit)
    return _d


async def _judge_clean(prompt):
    return '{"violations": []}'


async def _record_noop(trace_id, violations):
    return None
```

Update both `run_once(...)` calls: replace `make_body=_make_body(awaited)` with `draft=_draft(awaited), judge=_judge_clean, record_fail=_record_noop`. Assertions unchanged (`awaited == [1]` for the publishing case, `awaited == []` for sub-floor).

- [ ] **Step 3: Run both scheduling test files to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_run_once.py tests/scheduling/test_integration_pipeline.py -v`
Expected: FAIL — `TypeError: run_once() got an unexpected keyword argument 'draft'` (signature still uses `make_body`). Real contract RED.

- [ ] **Step 4: Update `run_once`'s signature to forward the new seams**

In `marketwind/scheduling/run_once.py`, change the import block, signature, and the `run_pipeline` call:

```python
from marketwind.verifier.domain import Violation
from marketwind.writer.domain import DraftBundle
# ... existing imports ...


async def run_once(now: datetime, *,
                   sessions: list,
                   anchor: datetime,
                   tolerance_min: int,
                   ceiling_cst: time,
                   gather: Callable[[], Awaitable[list[Source]]],
                   draft: Callable[[], Awaitable[DraftBundle]],
                   judge: Callable[[str], Awaitable[str]],
                   record_fail: Callable[[str, list[Violation]], Awaitable[None]],
                   primary: IMChannel,
                   fallback: IMChannel,
                   dev_channel: IMChannel,
                   trace_id: str,
                   force_calendar: bool = False) -> None:
    async with _RUN_LOCK:
        if not force_calendar and not is_trading_session(now.astimezone(CN_TZ).date(), sessions):
            dev_channel.send(_nontrading_status(now, trace_id))
            return
        fresh, reason = freshness_ok(now, anchor, tolerance_min=tolerance_min,
                                     ceiling_cst=ceiling_cst)
        if not fresh:
            dev_channel.send(_stale_status(reason, trace_id))
            return
        sources = await gather()
        await run_pipeline(sources=sources, draft=draft, judge=judge,
                           record_fail=record_fail, primary=primary, fallback=fallback,
                           dev_channel=dev_channel, trace_id=trace_id)
```

- [ ] **Step 5: Run the scheduling tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_run_once.py tests/scheduling/test_integration_pipeline.py -v`
Expected: PASS (all).

- [ ] **Step 6: Create the live judge seam**

Create `marketwind/verifier/runner.py`:

```python
"""Live DeepSeek judge seam for the Verifier's Tier-2 checks. Smoke/live only."""

from __future__ import annotations


async def call_judge(prompt: str) -> str:  # pragma: no cover - live
    """Single-prompt DeepSeek call returning the model's raw text (expected JSON)."""
    from marketwind.writer.client import call_deepseek
    return await call_deepseek([{"role": "user", "content": prompt}])
```

(If `call_deepseek`'s message/return shape differs, mirror exactly how `marketwind/writer/client.py` is invoked in `tests/writer/test_client.py` — keep the seam a thin one-prompt wrapper.)

- [ ] **Step 7: Wire the live `__main__` closures**

In `marketwind/scheduling/__main__.py` (inside `main`, `# pragma: no cover`), replace the `_make_body` closure and the `run_once(...)` call:

```python
        async def _draft():
            from marketwind.writer.client import call_deepseek
            from marketwind.writer.runner import draft_report
            return await draft_report(conn, call=call_deepseek)

        from marketwind.verifier.runner import call_judge
        from marketwind.storage.repo import record_verifier_failures

        async def _record_fail(tid, violations):
            await record_verifier_failures(conn, tid, violations)

        hh, mm = (int(x) for x in settings.freshness_ceiling_cst.split(":"))
        await run_once(now, sessions=sessions, anchor=anchor,
                       tolerance_min=settings.premarket_tolerance_min,
                       ceiling_cst=time(hh, mm), gather=_gather,
                       draft=_draft, judge=call_judge, record_fail=_record_fail,
                       primary=primary, fallback=fallback, dev_channel=dev,
                       trace_id=f"manual-{now:%Y%m%dT%H%M%S}",
                       force_calendar=args.force_calendar)
```

- [ ] **Step 8: Run the full offline suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (all offline tests, including the new `tests/verifier/*` and the rewired orchestration/scheduling tests).

- [ ] **Step 9: Commit**

```bash
git add marketwind/scheduling/run_once.py marketwind/scheduling/__main__.py marketwind/verifier/runner.py tests/scheduling/test_run_once.py tests/scheduling/test_integration_pipeline.py
git commit -m "feat(scheduling): thread draft/judge/record_fail seams + live verifier wiring"
```

---

## Task 10: Progress note

**Files:**
- Create: `docs/progress/verifier-law5-gate.md`

- [ ] **Step 1: Write the progress note**

Create `docs/progress/verifier-law5-gate.md` (follow the lightweight table+bullets template of `docs/progress/primary-tracing.md`):

```markdown
# Verifier — Law-5 publication gate

> **Read when:** picking up the Verifier, or before changing anything between the Writer draft and IM publication.

**Status:** complete. Branch `verifier-law5-gate`. Spec: `docs/superpowers/specs/2026-06-09-verifier-law5-gate-design.md`. Plan: `docs/superpowers/plans/2026-06-09-verifier-law5-gate.md`.

**What it delivers:** a fresh, independent, fail-closed Verifier pass between the Writer draft and IM publication. `run_pipeline` calls `verify` directly (hardcoded, like `evaluate_floor`) so Law 5 cannot be bypassed. Any violation → no publish, dev-channel status with trace_id + tripped checks, violations persisted to `claim_failures`.

## Modules
| Module | What it does |
|---|---|
| `verifier/domain.py` | `Violation`, `VerifyResult` |
| `verifier/checks.py` | Tier-1 deterministic: quote re-resolution (RF-3/RF-9), quant⇒primary (I3/RF-6), filler attribution (RF-4), first-person inference (RF-10) |
| `verifier/judge.py` | Tier-2 DeepSeek-judge: synthesis (I1/RF-2), contradiction (I10/RF-7); fails closed on judge error/garbage |
| `verifier/verifier.py` | `verify(output, pool, *, judge)` aggregator |
| `verifier/runner.py` | live judge seam (smoke-only) |
| `storage/repo.py` | pool now carries raw_content+spans; `record_verifier_failures` |
| `writer/runner.py` | `draft_report` → `DraftBundle` (deferred commit) |
| `orchestration/runner.py` | hardcoded verify gate |

## Invariants proved
- Fail-closed: judge unavailable, unresolved quote, quantitative claim with no primary → no publish.
- Hardcoded gate: no caller can skip verification (mirrors the floor gate).
- Persistence deferred: a report failing verification is never committed or published.

## Recorded Tier-3 gaps (deferred)
I12 (derived_metric), I3b/I2 (corroboration), I10 time-window precision, I6 (freshness search), I11 (cross-report), claim state machine / retry / failure-rate thresholds / 800-char digest. All need Writer metadata, network/history, or the state machine — out of this phase's Tier-1+2 scope.

## How to test
`.venv/Scripts/python.exe -m pytest tests/verifier tests/orchestration tests/scheduling -v` — offline.
```

- [ ] **Step 2: Commit**

```bash
git add docs/progress/verifier-law5-gate.md
git commit -m "docs(verifier): progress note for the Law-5 gate"
```

---

## Final verification (after all tasks)

- [ ] Run the full offline suite: `.venv/Scripts/python.exe -m pytest -q` — all green.
- [ ] Confirm `claim_failures` migration applies cleanly against the Docker DB.
- [ ] Dispatch a whole-branch independent code review (superpowers:requesting-code-review).
- [ ] Use superpowers:finishing-a-development-branch.
```
