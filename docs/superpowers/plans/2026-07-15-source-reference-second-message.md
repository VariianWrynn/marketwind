# Source-reference second message (G4.6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the brief's already-computed `[n]` footnotes as a separate, clickable `—— 来源 ——` second IM message sent right after the report.

**Architecture:** A new pure `render_source_tail` turns footnotes + a `source_id→url` map into a bare-URL reference block. `draft_report` builds it and carries it on `DraftBundle.reference`. `run_pipeline` sends it as message 2 via a non-raising `_send_soft`; a total send failure is recorded in the ledger (option A: loud, non-fatal) while the delivered report stays `PUBLISHED`.

**Tech Stack:** Python 3.11, pytest (`asyncio_mode=auto`), frozen dataclasses. Spec: `docs/superpowers/specs/2026-07-15-source-reference-second-message-design.md`.

**Controller note (CLAUDE.md §2):** Test code below is verbatim (the RED assertion is the contract). Implementation is described in prose with exact signatures — do NOT expand it into pre-written bodies; reason against the real files.

**RED discipline (Iron Law, CLAUDE.md §8):** Every RED must fail on the *assertion* (or a domain error) for the stated reason. `render_source_tail` and `_send_soft` are brand-new symbols, so their first test fails at import/attribute — scaffold a minimal stub returning a wrong sentinel first, then watch the assertion fail. Do not accept a bare `ImportError` as the RED for a behavioral test.

---

## Task 1: `render_source_tail` pure function

**Files:**
- Modify: `marketwind/writer/render.py`
- Test: `tests/writer/test_render.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/writer/test_render.py`)

```python
from marketwind.writer.render import render_source_tail


def test_source_tail_empty_footnotes_is_empty_string():
    assert render_source_tail([], {}) == ""


def test_source_tail_single_entry_format():
    tail = render_source_tail([(1, "s1")], {"s1": "https://finance.sina.com.cn/x"})
    assert tail == "—— 来源 ——\n[1] finance.sina.com.cn — https://finance.sina.com.cn/x"


def test_source_tail_url_is_bare_not_markdown():
    tail = render_source_tail([(1, "s1")], {"s1": "https://sse.com.cn/d/1"})
    assert "https://sse.com.cn/d/1" in tail   # full URL present, clickable
    assert "](" not in tail                    # never markdown-wrapped


def test_source_tail_multiple_entries_map_number_to_url():
    tail = render_source_tail(
        [(1, "s1"), (2, "s2")],
        {"s1": "https://a.com/1", "s2": "https://b.com/2"},
    )
    assert tail.splitlines() == [
        "—— 来源 ——",
        "[1] a.com — https://a.com/1",
        "[2] b.com — https://b.com/2",
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/writer/test_render.py -k source_tail -v`
Expected: FAIL — `ImportError: cannot import name 'render_source_tail'`. Because this is behavioral, add the stub in Step 3a **before** trusting the RED.

- [ ] **Step 3a: Scaffold a wrong-sentinel stub, re-run, watch the assertion fail**

Add to `render.py`: `def render_source_tail(footnotes, url_by_id): return "WRONG"`.
Run the same command. Expected now: FAIL on the **assertion** (e.g. `assert 'WRONG' == '—— 来源 ——\n[1] …'`) — this is the real RED.

- [ ] **Step 3b: Write the real implementation**

Replace the stub with the true `render_source_tail(footnotes: list[tuple[int, str]], url_by_id: dict[str, str]) -> str`:
- Import `domain_of` from `marketwind.scout.outlets` (add the import at top of `render.py`).
- If `footnotes` is empty, return `""`.
- Otherwise build a list starting with the header `"—— 来源 ——"`, then for each `(n, source_id)` in `footnotes` append `f"[{n}] {domain_of(url)} — {url}"` where `url = url_by_id[source_id]` (direct index — the cited source is always in the pool; no defensive branch).
- Return the lines joined by `"\n"` (no trailing newline).
- Leave `render_brief` and `_render_kept` untouched.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/writer/test_render.py -v`
Expected: PASS (all new + all pre-existing render tests).

- [ ] **Step 5: Commit**

```bash
git add marketwind/writer/render.py tests/writer/test_render.py
git commit -m "feat(writer): render_source_tail — clickable bare-URL source list"
```

---

## Task 2: `DraftBundle.reference` field + `draft_report` wiring

**Files:**
- Modify: `marketwind/writer/domain.py` (add field to `DraftBundle`)
- Modify: `marketwind/writer/runner.py` (`draft_report` builds `reference`)
- Modify: `tests/orchestration/test_floor_and_pipeline.py` (`_make_bundle` construction — the frozen dataclass gains a required field)
- Test: `tests/writer/test_draft_bundle.py`

- [ ] **Step 1: Write the failing test** (append to `tests/writer/test_draft_bundle.py`)

The canned pool's source `SRC-A` has url `https://m.cls.cn/a/1`; the stub output's factual sentence cites `source_ids=["s1"]` which the alias layer resolves to `SRC-A`. So the single footnote resolves to that source.

```python
async def test_bundle_reference_is_source_tail(monkeypatch):
    async def fake_load_pool(conn):
        return _CANNED_POOL

    monkeypatch.setattr("marketwind.writer.runner.load_pool", fake_load_pool)
    monkeypatch.setattr("marketwind.writer.runner.persist_report", _PersistSpy())

    bundle = await draft_report(object(), call=_stub_call)
    assert bundle.reference == "—— 来源 ——\n[1] m.cls.cn — https://m.cls.cn/a/1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/writer/test_draft_bundle.py::test_bundle_reference_is_source_tail -v`
Expected: FAIL — `TypeError: __init__() missing 1 required positional argument: 'reference'` (draft_report constructs `DraftBundle` without the new field) or `AttributeError: 'DraftBundle' object has no attribute 'reference'`. This is a construction/attribute test, so this is a legitimate RED once the field exists and the value is wrong — proceed to Step 3, then confirm it fails on the **assertion** (wrong string) before the final impl line, by temporarily wiring `reference=""`.

- [ ] **Step 3: Implement**

1. `domain.py` — add `reference: str` to the frozen `DraftBundle`, positioned **before** `commit` (which has no default), after `body`:
   ```
   output: WriterOutput
   pool: list[PooledSource]
   body: str
   reference: str
   commit: Callable[[], Awaitable[str]]
   ```
   No default value (keeps `commit` last-without-default valid; all constructors updated below).
2. `runner.py::draft_report` — after `brief = render_brief(...)`, add:
   ```python
   url_by_id = {s.source_id: s.url for s in pool}
   reference = render_source_tail(brief.footnotes, url_by_id)
   ```
   Import `render_source_tail` from `marketwind.writer.render`. Pass `reference=reference` into the returned `DraftBundle(...)`. (`pool` here is the eligible-filtered pool; every cited source_id is present.)
3. `tests/orchestration/test_floor_and_pipeline.py::_make_bundle` — give it a `reference: str = ""` parameter and pass `reference=reference` into the `DraftBundle(...)` construction, so existing pipeline tests keep constructing a valid bundle (default `""` = no second message).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/writer/test_draft_bundle.py tests/orchestration/test_floor_and_pipeline.py -v`
Expected: PASS (new reference test + all pre-existing bundle/pipeline tests still green).

- [ ] **Step 5: Commit**

```bash
git add marketwind/writer/domain.py marketwind/writer/runner.py tests/writer/test_draft_bundle.py tests/orchestration/test_floor_and_pipeline.py
git commit -m "feat(writer): carry source-reference text on DraftBundle"
```

---

## Task 3: `run_pipeline` sends message 2 (option A)

**Files:**
- Modify: `marketwind/orchestration/runner.py` (add `_send_soft`; send reference in the publish branch)
- Test: `tests/orchestration/test_floor_and_pipeline.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/orchestration/test_floor_and_pipeline.py`)

```python
from marketwind.gateway.im.base import SendResult


class _RefFailSink:
    """Succeeds on the report body, fails on the reference (header contains 来源)."""
    def __init__(self):
        self.sent = []
    def send(self, text):
        if "来源" in text:
            return SendResult(ok=False, error="ref boom")
        self.sent.append(text)
        return SendResult(ok=True)


@pytest.mark.asyncio
async def test_reference_sent_as_second_message():
    primary = StubSink()
    bundle, _ = _make_bundle(_clean_pool(), reference="—— 来源 ——\n[1] x.com — http://x/a")

    async def draft() -> DraftBundle:
        return bundle

    out = await run_pipeline(
        sources=_above_floor(), draft=draft, judge=_fake_judge,
        record_fail=_noop_record, already_published=_never,
        primary=primary, fallback=StubSink(), trace_id="t-ref",
    )
    assert out.status == PUBLISHED
    assert out.detail is None
    assert len(primary.sent) == 2
    assert primary.sent[0].startswith(DEV_PREFIX)            # message 1 = labeled body
    assert primary.sent[1] == "—— 来源 ——\n[1] x.com — http://x/a"  # message 2 = reference, no prefix


@pytest.mark.asyncio
async def test_empty_reference_sends_only_one_message():
    primary = StubSink()
    bundle, _ = _make_bundle(_clean_pool(), reference="")

    async def draft() -> DraftBundle:
        return bundle

    out = await run_pipeline(
        sources=_above_floor(), draft=draft, judge=_fake_judge,
        record_fail=_noop_record, already_published=_never,
        primary=primary, fallback=StubSink(), trace_id="t-noref",
    )
    assert out.status == PUBLISHED
    assert len(primary.sent) == 1


@pytest.mark.asyncio
async def test_reference_send_failure_is_published_with_detail():
    primary, fallback = _RefFailSink(), _RefFailSink()
    bundle, _ = _make_bundle(_clean_pool(), reference="—— 来源 ——\n[1] x.com — http://x/a")

    async def draft() -> DraftBundle:
        return bundle

    out = await run_pipeline(
        sources=_above_floor(), draft=draft, judge=_fake_judge,
        record_fail=_noop_record, already_published=_never,
        primary=primary, fallback=fallback, trace_id="t-reffail",
    )
    assert out.status == PUBLISHED                              # report WAS delivered
    assert "source-reference message FAILED" in out.detail     # loud in the ledger
    assert "t-reffail" in out.detail
    assert primary.sent and primary.sent[0].startswith(DEV_PREFIX)  # message 1 delivered
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestration/test_floor_and_pipeline.py -k "reference or one_message" -v`
Expected: FAIL — `test_reference_sent_as_second_message` fails on `assert len(primary.sent) == 2` (currently only the body is sent), and `test_reference_send_failure...` fails on the `out.detail` assertion (currently `detail is None`). Assertion-level RED, correct reasons.

- [ ] **Step 3: Implement**

In `marketwind/orchestration/runner.py`:
1. Add a non-raising soft sender next to `send_with_fallback`:
   ```python
   def _send_soft(text: str, *, primary: IMChannel, fallback: IMChannel) -> SendResult:
       res = primary.send(text)
       if res.ok:
           return res
       return fallback.send(text)
   ```
2. In `run_pipeline`, in the final publish branch, **after** the existing `send_with_fallback(labeled, primary=primary, fallback=fallback, trace_id=trace_id)` (which stays as-is — the report still raises on total failure), replace the final `return RunOutcome(PUBLISHED)` with:
   ```python
   if bundle.reference:
       ref = _send_soft(bundle.reference, primary=primary, fallback=fallback)
       if not ref.ok:
           return RunOutcome(
               PUBLISHED,
               detail=f"report published; source-reference message FAILED "
                      f"on both channels: {ref.error} trace_id={trace_id}",
           )
   return RunOutcome(PUBLISHED)
   ```
   The reference is sent raw (no `apply_label`, no DEV prefix). This branch is only reached on a fresh publish — `already_published()` returns earlier, so a re-run sends neither message.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_floor_and_pipeline.py -v`
Expected: PASS (three new tests + all pre-existing pipeline tests, including `test_pass_publishes_and_returns_published` whose default-`""` reference sends one message).

- [ ] **Step 5: Commit**

```bash
git add marketwind/orchestration/runner.py tests/orchestration/test_floor_and_pipeline.py
git commit -m "feat(orchestration): send source-reference as second message (option A)"
```

---

## Task 4: Full-suite verification + progress note

**Files:**
- Create: `docs/progress/source-reference-second-message.md`

- [ ] **Step 1: Run the full suite**

Run: `pytest -q`
Expected: PASS with no regressions. If anything unrelated was already failing before this work, note it — do not fix out of scope.

- [ ] **Step 2: Write the progress note** (lightweight — a table + a few bullets, per CLAUDE.md §8.6; see `docs/progress/P1a-scout.md` for the template)

Cover: the four modules touched, what each does, the commit SHAs, and the invariants proved (two-message split, bare clickable URLs, option-A loud-non-fatal, `render_brief` untouched / Law-5-neutral). Mark **G4.6 closed** and **G4.7 dropped** — and update those rows in `docs/GAPS.md` accordingly (move G4.6 to the "Recently closed" section; note G4.7 dropped as superseded by the two-message approach).

- [ ] **Step 3: Commit**

```bash
git add docs/progress/source-reference-second-message.md docs/GAPS.md
git commit -m "docs: progress note + close G4.6 (source-reference second message)"
```

---

## Self-Review

**Spec coverage:** §4.1 → Task 1; §4.2 → Task 2 (domain); §4.3 → Task 2 (runner); §4.4 → Task 3; §5 tests → Tasks 1-3; §6 out-of-scope respected (no budget/label/render_brief changes). §7 files-touched all mapped. ✓

**Placeholder scan:** No TBD/TODO; every code step shows exact test code or exact signature + prose impl (per controller altitude); commands are concrete with expected output. ✓

**Type consistency:** `render_source_tail(footnotes: list[tuple[int,str]], url_by_id: dict[str,str]) -> str`, `DraftBundle.reference: str`, `_send_soft(...) -> SendResult`, `RunOutcome(PUBLISHED, detail=...)` — consistent across tasks. `footnotes` shape matches `render_brief`'s existing `list[(n, source_id)]`; `_make_bundle` gains `reference: str = ""`. ✓
