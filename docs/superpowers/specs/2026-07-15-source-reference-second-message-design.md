# Source-reference second message (G4.6) — design

> **Read when:** implementing the reader-facing source reference list, or touching Writer render / the publish path in `orchestration/runner.py`. Closes **G4.6**; **G4.7 (budget raise) is dropped as unnecessary** under the two-message approach.

## 1. Goal

Give the reader a clickable "show your work" source list. The brief already renders inline `[n]` markers after each factual sentence (`render.py::_render_kept`) and returns `footnotes: list[(n, source_id)]`, but that list is **computed and thrown away** — never delivered, and it maps `n → source_id` UUID, not to anything a human can read or tap.

Deliver the footnotes as a **separate second IM message** (`—— 来源 ——` list) sent right after the brief. Each entry is `[n] <domain> — <full-url>`, the URL bare so WeChat/WeCom auto-linkify it into a tappable link.

**This is pure presentation.** It does not change what the Verifier gates, what the Writer emits, or the text of any verified sentence. Law-5-neutral.

## 2. Why two messages (not an appended tail)

- The 500-char body stays a glanceable brief — **no budget raise, no `MAX_TOTAL` change, no fail-closed combined-message math** (G4.7 evaporates).
- The reference message owns its own budget (its own IM message, WeChat hard cap ~4000), so **URLs are never truncated** — a cut URL is a dead link.
- Clean isolation: the tail is a separate pure function + a separate `send`.

## 3. Data reality (constrains the format)

There is **no article-title field** anywhere in the data model. `PooledSource` / `scout.Source` carry only `url` + `domain`. `scout/outlets.py` has `domain_of(url)` but **no** friendly-name map. So each entry renders as `[n] <domain> — <url>` using data we already hold. **No title fabrication** (a wrong/invented headline on a financial report violates the spirit of the Iron Laws).

Every cited `source_id` is guaranteed present in the (eligible-filtered) `pool` that produced the sentences, so URL resolution is a direct pool lookup — no defensive "link unavailable" branch (trust internal code; the pool is the closed set the sentences reference).

## 4. Contracts

### 4.1 `writer/render.py` — new pure function

```python
def render_source_tail(
    footnotes: list[tuple[int, str]],   # (n, source_id) from render_brief, already
                                        # numbered per-report, first-appearance order,
                                        # de-duplicated (one number per shared source)
    url_by_id: dict[str, str],          # source_id -> url, built from the pool
) -> str
```

Behavior:
- Empty `footnotes` → return `""` (caller sends no second message).
- Otherwise return the header `—— 来源 ——` followed by one line per footnote, joined by `"\n"`, no trailing newline:
  ```
  —— 来源 ——
  [1] finance.sina.com.cn — https://finance.sina.com.cn/…
  [2] sse.com.cn — https://sse.com.cn/disclosure/…
  ```
- Each line: `f"[{n}] {domain_of(url)} — {url}"` where `url = url_by_id[source_id]` (direct index) and `domain_of` is imported from `marketwind.scout.outlets`.
- The URL is emitted **bare** (never markdown-wrapped, never truncated) and sits at end of line so nothing is glued to it → clickable in WeChat/WeCom plain-text messages.
- `render_brief` is **unchanged** (keeps its purity); the tail is a separate unit.

### 4.2 `writer/domain.py` — `DraftBundle` gains one field

```python
@dataclass(frozen=True)
class DraftBundle:
    output: WriterOutput
    pool: list[PooledSource]
    body: str
    reference: str                      # NEW: the "—— 来源 ——" second-message text; "" if none
    commit: Callable[[], Awaitable[str]]
```

Constructed by keyword everywhere; add `reference=...`.

### 4.3 `writer/runner.py::draft_report` — build the reference

After `brief = render_brief(...)`:
```python
url_by_id = {s.source_id: s.url for s in pool}     # pool = the eligible-filtered pool
reference = render_source_tail(brief.footnotes, url_by_id)
```
and pass `reference=reference` into the returned `DraftBundle`. `run_writer` needs no change (it reads `bundle.body` only). `run_once` needs no change (it forwards `draft`).

### 4.4 `orchestration/runner.py::run_pipeline` — send message 2 (option A)

New soft-send helper (does **not** raise) alongside the existing `send_with_fallback`:
```python
def _send_soft(text, *, primary, fallback) -> SendResult:
    res = primary.send(text)
    if res.ok:
        return res
    return fallback.send(text)          # returns fallback's result (ok or not)
```

In the fresh-publish branch, after the existing message-1 `send_with_fallback(labeled, …)` (unchanged — still raises on total failure of the **report**):
```python
if bundle.reference:
    ref = _send_soft(bundle.reference, primary=primary, fallback=fallback)
    if not ref.ok:
        return RunOutcome(
            PUBLISHED,
            detail=f"report published; source-reference message FAILED on both channels: {ref.error} trace_id={trace_id}",
        )
return RunOutcome(PUBLISHED)
```

**Option A rationale (loud, non-fatal).** The report itself was delivered, so the run is genuinely `PUBLISHED`. A reference-send failure is **recorded, never swallowed**: `dispatch_job` persists `outcome.detail` into the durable ledger row (`record_run(..., detail=outcome.detail)`), so the failure is visible on review. It deliberately does **not** page the owner — `_status_text` keeps `PUBLISHED` silent to avoid daily heartbeat spam, and the *report* (the thing that matters) went out. This satisfies "obvious fail welcomed, silent fail strongly unwelcomed": the ledger is the durable surface, not a swallowed error. (Raising here — option B — would mislabel a delivered report as a failed run.)

The reference message carries **no `DEV/UNVERIFIED` prefix** (it is a continuation, not a standalone report) and is sent as-is via `_send_soft`. Message 2 only ever fires in the fresh-publish branch — the idempotent `already_published()` short-circuit returns before any send, so a re-run sends neither message.

## 5. Testing (TDD — RED first, assertion must fail for the right reason)

**`render_source_tail` (`tests/writer/test_render.py` or a sibling):**
- Empty footnotes → `""`.
- Single footnote → exact string `"—— 来源 ——\n[1] finance.sina.com.cn — https://finance.sina.com.cn/x"` (pin the format: header, `[n]`, `domain — url`, bare URL substring present, no markdown `](`).
- Two footnotes → two lines, correct `[1]`/`[2]` → url mapping.
- A source shared by two sentences already yields **one** footnote entry (footnotes are pre-deduplicated by `render_brief`) — verify one line, one number.

**`DraftBundle.reference` (`tests/writer/test_draft_bundle.py`):**
- Given a stub `call` producing factual sentences with source_ids over a known pool, `draft_report(...).reference` equals the expected `—— 来源 ——` block (URLs resolved from the pool).
- A brief with no factual sentences (no footnotes) → `reference == ""`.

**Publish path (`tests/orchestration/test_floor_and_pipeline.py` / `test_fallback.py`):**
- Happy path: brief with a non-empty `reference` → the fake primary channel receives **two** sends; send #1 is the labeled body, send #2 equals `bundle.reference` (no DEV prefix). Outcome `PUBLISHED`, `detail is None`.
- Empty `reference` → exactly **one** send; outcome `PUBLISHED`.
- Option A: fake channels where send #1 (body) succeeds but the reference send fails on **both** primary and fallback → outcome is `PUBLISHED` with `detail` containing `"source-reference message FAILED"`; the body send still happened (message 1 delivered).

## 6. Out of scope / non-goals

- **G4.7 budget raise** — dropped; the two-message split removes the need.
- **Friendly outlet names** — no domain→name map exists; `domain — url` only.
- **Title extraction / page `<title>` fetch** — correctness risk, not built.
- **Markdown message type** — sinks send plain text; bare URLs are the clickable path.
- Any change to `render_brief`, the Verifier, or verified sentence text.

## 7. Files touched

| File | Change |
|---|---|
| `marketwind/writer/render.py` | add `render_source_tail` (pure) |
| `marketwind/writer/domain.py` | `DraftBundle` gains `reference: str` |
| `marketwind/writer/runner.py` | `draft_report` builds + sets `reference` |
| `marketwind/orchestration/runner.py` | `_send_soft` helper + send message 2 (option A) in `run_pipeline` |
| `tests/writer/test_render.py` | `render_source_tail` cases |
| `tests/writer/test_draft_bundle.py` | `reference` populated / empty |
| `tests/orchestration/test_floor_and_pipeline.py` (or `test_fallback.py`) | two-send happy path, empty-reference single-send, option-A partial failure |
