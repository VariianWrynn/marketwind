# Source-tier + primary-grade gate + officially-verified badge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> This plan is written at **controller altitude** (CLAUDE.md §2): it fixes contracts
> (signatures, types, field names, return shapes), the **RED assertion** each test must
> fail on for the right reason, and the **spec-critical literals** (the domain lists — the
> spec *is* the value). Implementation bodies are described in behavioral prose, **not**
> pre-written. The sub-agent reasons against the real files; do not hand it finished code.

**Goal:** Widen what counts as "primary-grade" for the I3 gate to include CSRC-designated
and curated-trusted disclosure media (so trusted outlets can lawfully back a number), and
add a mechanical "✓官方核实" reader signal for genuinely primary-corroborated claims —
without moving the Tier-0 "Primary source" definition.

**Architecture:** One new pure module (`scout/source_tier.py`: a 5-tier classifier + two
predicates) plus four one-line edits at existing seams (`writer/select.py`,
`verifier/checks.py`, `scout/gather.py`, `writer/render.py`+`runner.py`). No new pipeline
stage; no flow change. Phase B (cninfo-direct via akshare) is spike-gated and deferred.

**Tech Stack:** Python 3.11 · asyncpg/Postgres · pytest (`PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q`).

**Design spec:** `docs/superpowers/specs/2026-06-17-source-tier-primary-grade-design.md`.

---

## Task 0: Commit the precursor I3 fixes

The two prior, uncommitted fixes (`storage/repo.py::persist_enriched` + its call in
`scout/enrich.py`; `writer/select.py::eligible_pool` + its wiring in `writer/runner.py`)
are the base this plan extends. Commit them first so the tier work has a clean base.

**Files (already modified, just staging + commit):**
- `marketwind/storage/repo.py`, `marketwind/scout/enrich.py`, `marketwind/writer/select.py`,
  `marketwind/writer/runner.py`, `tests/scout/test_repo.py`, `tests/writer/test_draft_bundle.py`,
  `marketwind/writer/select.py`, `tests/writer/test_select.py`, `docs/progress/writer-i3-publish-path.md`.

- [ ] **Step 1: Confirm the precursor tests are green**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/writer/test_select.py tests/scout/test_repo.py tests/writer/test_draft_bundle.py`
Expected: PASS.

- [ ] **Step 2: Commit** (requires user authorization — CLAUDE.md git-safety: only commit when asked)

Commit message subject e.g. `fix(writer): persist enriched primaries + structural I3 pool filter`.

---

## Task 1: `scout/source_tier.py` — tier classifier

**Files:**
- Create: `marketwind/scout/source_tier.py`
- Test: `tests/scout/test_source_tier.py`

**Contract (fix exactly):**
- `class SourceTier(IntEnum)` with members **in this order/value**: `EXCLUDED = 0`,
  `SECONDARY = 1`, `TRUSTED = 2`, `DESIGNATED = 3`, `OFFICIAL = 4`. (IntEnum so `>=`
  comparisons work.)
- `def classify(domain: str) -> SourceTier`.

**Spec-critical literals — encode verbatim as module-level `frozenset`s. The spec IS these strings:**

```
_OFFICIAL = {
    "cninfo.com.cn", "sse.com.cn", "szse.cn", "csrc.gov.cn",
    "pbc.gov.cn", "miit.gov.cn", "nfra.gov.cn",
}
_DESIGNATED = {
    "cs.com.cn", "cnstock.com", "stcn.com", "zqrb.cn",
    "financialnews.com.cn", "jjckb.cn", "chinadaily.com.cn",
}
_TRUSTED = {
    "finance.sina.com.cn", "yicai.com", "cls.cn", "caixin.com",
}
_SECONDARY = {
    "news.cn", "xinhuanet.com", "people.com.cn", "21jingji.com", "jiemian.com",
    "finance.eastmoney.com", "data.eastmoney.com", "zhitongcaijing.com",
    "wallstreetcn.com", "thepaper.cn", "cnfin.com",
}
_DENYLIST = {
    "caifuhao.eastmoney.com", "guba.eastmoney.com", "mguba.eastmoney.com",
    "quote.eastmoney.com", "emwap.eastmoney.com", "q.stock.sohu.com",
    "k.sina.com.cn", "k.sina.cn", "cj.sina.com.cn",
    "vip.stock.finance.sina.com.cn", "money.finance.sina.com.cn",
    "xueqiu.com", "tgb.cn",
}
```

**Behavior to implement (prose, not code):** `classify` first checks the **denylist by exact
membership** — if the domain is in `_DENYLIST`, return `EXCLUDED` immediately (this must win
over any allowlist suffix-match). Otherwise, walk the allowlists from highest tier to
lowest (`OFFICIAL → DESIGNATED → TRUSTED → SECONDARY`); a domain matches an entry `E` iff
`domain == E or domain.endswith("." + E)` (suffix match, so subdomains inherit the tier of
their registered root). Return the tier of the first matching allowlist. No match ⇒
`EXCLUDED` (default-deny). Input is an already-normalised domain (no `www.`), per
`scout/outlets.py::domain_of`.

- [ ] **Step 1: Write the failing test** (`tests/scout/test_source_tier.py`)

The RED assertions that discriminate the real algorithm from a stub. These must fail on an
**assertion**, not an ImportError — so scaffold the module first (Step 3 order below: write
test, scaffold stub that returns a wrong sentinel, watch assert fail, then implement).

```python
import pytest
from marketwind.scout.source_tier import SourceTier, classify

@pytest.mark.parametrize("domain, tier", [
    ("cninfo.com.cn", SourceTier.OFFICIAL),
    ("csrc.gov.cn", SourceTier.OFFICIAL),
    ("cs.com.cn", SourceTier.DESIGNATED),
    ("cnstock.com", SourceTier.DESIGNATED),
    ("finance.sina.com.cn", SourceTier.TRUSTED),
    ("caixin.com", SourceTier.TRUSTED),
    ("finance.eastmoney.com", SourceTier.SECONDARY),
    ("jiemian.com", SourceTier.SECONDARY),
])
def test_classify_known_domains(domain, tier):
    assert classify(domain) == tier

def test_subdomain_inherits_root_tier():
    # suffix-match: a subdomain of a DESIGNATED root is DESIGNATED
    assert classify("news.cs.com.cn") == SourceTier.DESIGNATED

def test_denylist_beats_trusted_suffix():
    # money.finance.sina.com.cn is a subdomain of TRUSTED finance.sina.com.cn,
    # but the denylist is checked FIRST -> EXCLUDED. This is the load-bearing case.
    assert classify("money.finance.sina.com.cn") == SourceTier.EXCLUDED
    assert classify("guba.eastmoney.com") == SourceTier.EXCLUDED

def test_unknown_domain_default_denies():
    assert classify("randomblog.example") == SourceTier.EXCLUDED
```

- [ ] **Step 2: Run, confirm RED for the right reason**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/scout/test_source_tier.py`
Expected: with a scaffolded `classify` that returns `SourceTier.EXCLUDED` for everything, the
OFFICIAL/DESIGNATED/TRUSTED/SECONDARY/subdomain assertions FAIL on `assert ... == SourceTier.X`
(not ImportError). The denylist/default-deny cases will pass against the stub — that is fine;
the discriminating REDs are the tier-positive ones.

- [ ] **Step 3: Implement** the §2.2 algorithm over the frozensets above.

- [ ] **Step 4: Run, confirm GREEN.**

- [ ] **Step 5: Commit** (`feat(scout): tier classifier for source authority`).

---

## Task 2: the two predicates

**Files:**
- Modify: `marketwind/scout/source_tier.py`
- Test: `tests/scout/test_source_tier.py` (extend)

**Contract (fix exactly):**
- `def clears_law3(domain: str, source_is_primary: bool, attached_primary_url: str | None) -> bool`
- `def is_officially_verified(domain: str, source_is_primary: bool, attached_primary_url: str | None) -> bool`

**Behavior (prose):**
- `clears_law3` = `attached_primary_url is not None or source_is_primary or classify(domain) >= SourceTier.TRUSTED`.
- `is_officially_verified` = same, but threshold `>= SourceTier.DESIGNATED`.
- Primitive args (not dataclasses) so the module imports nothing from `writer.domain`.

- [ ] **Step 1: Write the failing test** — the discriminating RED is that TRUSTED clears the
  *gate* but NOT the *badge*:

```python
from marketwind.scout.source_tier import clears_law3, is_officially_verified

def test_trusted_clears_gate_but_not_badge():
    # finance.sina.com.cn is TRUSTED: may back a number (gate), but is NOT celebrated (badge)
    assert clears_law3("finance.sina.com.cn", False, None) is True
    assert is_officially_verified("finance.sina.com.cn", False, None) is False

def test_designated_clears_both():
    assert clears_law3("cs.com.cn", False, None) is True
    assert is_officially_verified("cs.com.cn", False, None) is True

def test_excluded_clears_neither_without_primary():
    assert clears_law3("randomblog.example", False, None) is False
    assert is_officially_verified("randomblog.example", False, None) is False

def test_attached_primary_or_is_primary_clears_both_regardless_of_domain():
    assert clears_law3("randomblog.example", False, "http://cninfo.com.cn/x") is True
    assert is_officially_verified("randomblog.example", True, None) is True
```

- [ ] **Step 2: Run, confirm RED** — scaffold both predicates returning `False`; the
  `is True` assertions fail on assertion. (Confirm not ImportError.)

- [ ] **Step 3: Implement** per prose above.

- [ ] **Step 4: Run, confirm GREEN.**

- [ ] **Step 5: Commit** (`feat(scout): primary-grade + officially-verified predicates`).

---

## Task 3: extend `writer/select.py::eligible_pool`

**Files:**
- Modify: `marketwind/writer/select.py`
- Test: `tests/writer/test_select.py` (extend existing)

**Contract:** signature unchanged — `eligible_pool(pool: list[PooledSource]) -> list[PooledSource]`.

**Behavior (prose):** import `classify`, `SourceTier`, `clears_law3` from
`marketwind.scout.source_tier`. For each source: if `classify(s.domain) == SourceTier.EXCLUDED`,
drop the **whole source** (no quote from a no-accountability host reaches the Writer, quant
or not). For surviving sources, keep a quote iff it is non-quantitative **or**
`clears_law3(s.domain, s.is_primary, q.attached_primary_url)`. Drop any source left with
zero kept quotes. (This widens the prior filter: a TRUSTED-domain quant quote now survives
on domain authority even with `attached_primary_url=None` and `is_primary=False`.)

- [ ] **Step 1: Write the failing test.** The discriminating REDs vs. the *current*
  `eligible_pool` (which would drop the TRUSTED quant quote, and would NOT drop the EXCLUDED
  non-quant source):

```python
from marketwind.writer.domain import PooledQuote, PooledSource
from marketwind.writer.select import eligible_pool

def _q(qid, quant, url=None):
    return PooledQuote(qid, "数字0.36%" if quant else "情绪谨慎", quant, "data", url, 0, 5)

def test_trusted_domain_quant_survives_without_attached_primary():
    pool = [PooledSource("S1", "https://finance.sina.com.cn/a", "finance.sina.com.cn",
                         False, [_q("Q1", True)], raw_content="x")]
    out = eligible_pool(pool)
    assert [q.quote_id for s in out for q in s.quotes] == ["Q1"]  # KEPT (new behavior)

def test_excluded_source_dropped_whole_even_if_nonquant():
    pool = [PooledSource("S2", "https://guba.eastmoney.com/a", "guba.eastmoney.com",
                         False, [_q("Q2", False)], raw_content="x")]
    assert eligible_pool(pool) == []  # whole source gone

def test_secondary_domain_quant_without_primary_still_dropped():
    pool = [PooledSource("S3", "https://finance.eastmoney.com/a", "finance.eastmoney.com",
                         False, [_q("Q3", True), _q("Q4", False)], raw_content="x")]
    out = eligible_pool(pool)
    assert [q.quote_id for s in out for q in s.quotes] == ["Q4"]  # quant dropped, non-quant kept
```

- [ ] **Step 2: Run, confirm RED** — against the *current* `eligible_pool`,
  `test_trusted_domain_quant_survives...` fails (Q1 dropped → empty) and
  `test_excluded_source_dropped...` fails (source kept). These assertion failures are the RED.
  (`PooledSource`/`PooledQuote` construction makes the test run, so no ImportError.)

- [ ] **Step 3: Implement** per prose.

- [ ] **Step 4: Run the full select + draft-bundle suite, confirm GREEN.**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/writer/test_select.py tests/writer/test_draft_bundle.py`

- [ ] **Step 5: Commit** (`feat(writer): tier-aware eligible_pool`).

---

## Task 4: extend `verifier/checks.py::check_quant_has_primary`

**Files:**
- Modify: `marketwind/verifier/checks.py`
- Test: `tests/verifier/test_checks.py` (extend; confirm path during implementation)

**Contract:** signature unchanged. Replace the inline primary test
`quote.attached_primary_url or source.is_primary` with
`clears_law3(source.domain, source.is_primary, quote.attached_primary_url)` (import from
`marketwind.scout.source_tier`). Everything else in the function (the `has_quant` accumulation,
the I3 Violation shape `check="I3"`, locus=`claim.local_id`) stays identical.

**Why:** Writer (`eligible_pool`) and Verifier now apply the **same** predicate, so a claim
that survived selection cannot fail I3 — the structural guarantee holds with the widened
predicate.

- [ ] **Step 1: Write the failing test.** Discriminating RED: a TRUSTED-domain quant quote
  with no attached primary must now produce **no** I3 violation:

```python
def test_trusted_domain_quant_does_not_violate_i3():
    pool = [PooledSource("S1", "https://finance.sina.com.cn/a", "finance.sina.com.cn",
                         False, [PooledQuote("Q1", "0.36%", True, "data", None, 0, 4)],
                         raw_content="0.36")]
    idx = index_quotes(pool)
    out = WriterOutput(claims=[DraftClaim("c1", "科创50涨0.36%", ["Q1"])], sentences=[])
    assert check_quant_has_primary(out, idx) == []  # no I3 (TRUSTED clears)

def test_unknown_domain_quant_still_violates_i3():
    pool = [PooledSource("S2", "https://randomblog.example/a", "randomblog.example",
                         False, [PooledQuote("Q2", "0.36%", True, "data", None, 0, 4)],
                         raw_content="0.36")]
    idx = index_quotes(pool)
    out = WriterOutput(claims=[DraftClaim("c2", "某数字0.36%", ["Q2"])], sentences=[])
    v = check_quant_has_primary(out, idx)
    assert len(v) == 1 and v[0].check == "I3"
```

(Use the real imports already used by `tests/verifier/test_checks.py`: `index_quotes`,
`check_quant_has_primary`, `PooledQuote`, `PooledSource`, `WriterOutput`, `DraftClaim`.)

- [ ] **Step 2: Run, confirm RED** — against current code,
  `test_trusted_domain_quant_does_not_violate_i3` fails (current code emits one I3 because
  sina has no attached primary and `is_primary=False`). Assertion failure = valid RED.

- [ ] **Step 3: Implement** the one-line predicate swap.

- [ ] **Step 4: Run the verifier suite, confirm GREEN.**

- [ ] **Step 5: Commit** (`feat(verifier): tier-aware I3 primary check`).

---

## Task 5: set `is_primary=True` at ingest for OFFICIAL domains

**Files:**
- Modify: `marketwind/scout/gather.py` (the `Source(...)` construction in `build_pool`, ~line 49)
- Create: `tests/scout/test_gather_tier.py` (new focused test — `build_pool` has no existing
  `tests/scout/` unit file; it is exercised only indirectly. Import `build_pool` from
  `marketwind.scout.gather` and `Quote` from `marketwind.scout.domain`.)

**Contract:** `build_pool` signature unchanged. At the `Source(...)` construction, set
`is_primary = classify(domain_of(url)) >= SourceTier.OFFICIAL` (import `classify`,
`SourceTier`; `domain_of` is already imported). No other change.

**Why:** activates the dead `is_primary` path — a source pulled straight from an official
venue *is* primary. Via Bocha this rarely fires; it is the seam Phase B feeds.

- [ ] **Step 1: Write the failing test** using `build_pool`'s injected seams (search,
  fetch_page, parse, persist) with a spy persist that captures the constructed Source:

```python
import datetime as dt

async def test_official_domain_source_marked_primary():
    captured = []
    async def search(q): return [("https://www.cninfo.com.cn/x", "snip")]
    async def fetch_page(u): return "<html/>"
    def parse(html): return ("正文", [Quote("正文", 0, 2, None, None, True)])
    async def persist(src): captured.append(src)
    out = await build_pool(prev_session=dt.date(2026, 6, 16), names=[], search=search,
                           fetch_page=fetch_page, parse=parse, persist=persist,
                           now=dt.datetime(2026, 6, 17))
    assert captured and captured[0].is_primary is True

async def test_trusted_domain_source_not_marked_primary():
    captured = []
    async def search(q): return [("https://finance.sina.com.cn/x", "snip")]
    async def fetch_page(u): return "<html/>"
    def parse(html): return ("正文", [Quote("正文", 0, 2, None, None, True)])
    async def persist(src): captured.append(src)
    await build_pool(prev_session=dt.date(2026, 6, 16), names=[], search=search,
                     fetch_page=fetch_page, parse=parse, persist=persist,
                     now=dt.datetime(2026, 6, 17))
    assert captured and captured[0].is_primary is False  # TRUSTED < OFFICIAL
```

(`Quote` signature: `text, span_start, span_end, context_before, context_after, is_quantitative`.
Note `build_recap_queries` always prepends recap queries; the spy will also capture those —
assert on the *cninfo* source specifically if recap queries surface other domains. Since the
injected `search` returns the same single URL for every query and `seen` dedupes, exactly one
source is captured. Keep the stub `search` returning the one URL so dedup yields one source.)

- [ ] **Step 2: Run, confirm RED** — against current code (which never sets `is_primary`),
  `test_official_domain_source_marked_primary` fails on `assert ... is True` (default False).
  Assertion failure = valid RED.

- [ ] **Step 3: Implement** the one-line `is_primary=` at construction.

- [ ] **Step 4: Run the gather suite, confirm GREEN.**

- [ ] **Step 5: Commit** (`feat(scout): mark official-venue sources as primary at ingest`).

---

## Task 6: the "officially verified" badge

**Files:**
- Modify: `marketwind/writer/select.py` (add the pure helper)
- Modify: `marketwind/writer/render.py` (add optional param + marker injection)
- Modify: `marketwind/writer/runner.py` (compute ids, pass through)
- Test: `tests/writer/test_select.py` + `tests/writer/test_render.py` (extend)

**Contract (fix exactly):**
- New helper in `select.py`:
  `def officially_verified_claims(output: WriterOutput, pool: list[PooledSource]) -> set[str]`
  — returns the set of `claim.local_id` for claims having **≥1 backing quote** (by
  `quote_id` in `claim.quote_ids`) whose owning source satisfies `is_officially_verified(
  source.domain, source.is_primary, quote.attached_primary_url)`. Build a quote→source index
  the same way `verifier.checks.index_quotes` does (or reuse it).
- `render_brief` signature becomes
  `def render_brief(output: WriterOutput, max_chars: int = MAX_CHARS, official_ids: set[str] = frozenset()) -> RenderedBrief`
  (back-compatible default).
- Marker literal: `"✓官方核实"` (spec-critical).
- `runner.draft_report` computes `official_ids = officially_verified_claims(output, pool)`
  (using the **filtered** pool) and passes it into `render_brief`.

**Behavior (prose):** Inside `_render_kept`, after the `[n]` markers are appended for a
**factual** sentence, if the sentence's `claim_ids` is non-empty **and every** id is in
`official_ids`, append the marker `✓官方核实` to that sentence's `text`. Non-factual
(structural) sentences and sentences with any non-official claim get no marker. The marker
participates in the `max_chars` length accounting naturally (it is part of `text`).

- [ ] **Step 1: Write the failing tests.**

Helper RED (`test_select.py`) — DESIGNATED earns membership, TRUSTED-only does not:

```python
from marketwind.writer.select import officially_verified_claims
from marketwind.writer.domain import DraftClaim, WriterOutput

def test_officially_verified_includes_designated_excludes_trusted_only():
    pool = [
        PooledSource("S1", "https://cs.com.cn/a", "cs.com.cn", False,
                     [PooledQuote("Q1", "0.36%", True, "data", None, 0, 4)], raw_content="0.36"),
        PooledSource("S2", "https://finance.sina.com.cn/a", "finance.sina.com.cn", False,
                     [PooledQuote("Q2", "0.36%", True, "data", None, 0, 4)], raw_content="0.36"),
    ]
    out = WriterOutput(
        claims=[DraftClaim("c1", "x", ["Q1"]), DraftClaim("c2", "y", ["Q2"])], sentences=[])
    assert officially_verified_claims(out, pool) == {"c1"}  # designated only
```

Render RED (`test_render.py`) — marker appears iff sentence's claim is official:

```python
def test_marker_on_official_sentence_only():
    out = WriterOutput(
        claims=[DraftClaim("c1", "科创50涨0.36%", ["Q1"])],
        sentences=[DraftSentence("科创50涨0.36%。", ["c1"], ["S1"], "factual")])
    brief = render_brief(out, official_ids={"c1"})
    assert "✓官方核实" in brief.body

def test_no_marker_when_not_official():
    out = WriterOutput(
        claims=[DraftClaim("c1", "科创50涨0.36%", ["Q1"])],
        sentences=[DraftSentence("科创50涨0.36%。", ["c1"], ["S1"], "factual")])
    brief = render_brief(out, official_ids=set())
    assert "✓官方核实" not in brief.body
```

(Use the `DraftSentence`/`DraftClaim`/`WriterOutput` constructors already used in the writer
tests.)

- [ ] **Step 2: Run, confirm RED** — `officially_verified_claims` import + the `✓官方核实`
  assertions fail on assertion against a scaffolded helper returning `set()` and the
  pre-change `render_brief` (which has no `official_ids` param → call the render REDs only
  after adding the param signature stub so the test runs and the *assertion* fails, not a
  TypeError). Order: add the `official_ids` param accepting+ignoring it (stub), scaffold the
  helper returning `set()`, watch `assert "✓官方核实" in body` fail, then implement.

- [ ] **Step 3: Implement** the helper, the marker injection, and the runner wiring.

- [ ] **Step 4: Run the writer suite (select, render, draft_bundle, runner), confirm GREEN.**

- [ ] **Step 5: Commit** (`feat(writer): officially-verified reader badge`).

---

## Task 7: contract, glossary, ADR + ground-truth regression

**Files:**
- Create: `docs/adr/0003-trusted-outlet-primary-grade-tier.md`
- Modify: `citation/glossary.md` (add a tier-table term block; **leave "Primary source" unchanged**)
- Modify: `CITATION_CONTRACT.md` (annotate I3; bump version 0.4 → 0.5 + changelog line)
- Modify: `DECISIONS.md` (note ADR-0003 against the relevant primary/quant decisions: D-5, D-7)
- Modify: `docs/progress/writer-i3-publish-path.md` (link this design as the recall-lever follow-up)

**This is a docs + regression-guard task, not TDD.** The contract touch *should* trigger the
`tests/citation_ground_truth/` regression (CLAUDE.md §8.2; DECISIONS ADR process step 3) —
**but that regression is not yet built**: `make test-gt` is a P2 stub (`exit 1`) and
`tests/citation_ground_truth/` contains only `samples.md` (labeled samples, no runner). We
therefore **cannot mechanically confirm** the labeled-sample verdicts. Per "silent-fail
strongly unwelcomed", Task 7 must **surface this loudly** (record it as a known gap), not
quietly claim a green regression. The annotation only *widens* an allowance (a quant claim
on a TRUSTED+ domain now satisfies `has_primary`); it cannot make a previously-passing
sample fail I3, but a real regression would still be the proper gate once built.

**ADR-0003 content (follow the `docs/adr/0002-*.md` shape):** Status accepted, grantor
project owner, date 2026-06-17, scope permanent. Triggering situation: the Bocha spike
(can't reach cninfo, ignores `site:`) + the near-zero live Tier-0 supply leaving I3 starved.
Decision: CSRC-designated (Tier 3) and curated-trusted (Tier 2) outlets are accepted as
**primary-grade for the I3 *gate*** — they may back a quantitative claim — **without**
changing the Tier-0 "Primary source" definition; the badge (Tier ≥ DESIGNATED) is the
honest reader signal separating them. Accepted residual risk: a designated/trusted outlet
may occasionally mis-transcribe a number — a calculated risk taken knowingly by the owner.
Affected modules: `scout/source_tier.py` (new), `writer/select.py`, `verifier/checks.py`,
`scout/gather.py`, `writer/render.py`, `writer/runner.py`, `citation/glossary.md`,
`CITATION_CONTRACT.md`. Relationship to DECISIONS: refines D-7/D-5 (quant needs a primary)
by defining "primary-grade"; does not overturn them.

**glossary.md:** add a "Source tiers" block with the 5-tier table (§2 of the spec) and the
two predicates. Add a one-line note under "Primary source" that it is **Tier 0** and
unchanged.

**CITATION_CONTRACT.md:** at I3 (line ~146), append a clause: `has_primary` is satisfied by
a **primary-grade** source (`tier ≥ TRUSTED`, per ADR-0003) as well as a true attached
primary or `is_primary`. Bump `**Version**: 0.4` → `0.5`, add a v0.5 changelog line.

- [ ] **Step 1: Write ADR-0003, the glossary block, the contract annotation + version bump,
  the DECISIONS note, the progress-doc link.**

- [ ] **Step 2: Surface the missing ground-truth regression as a known gap.** Since
  `tests/citation_ground_truth/` has no runner (P2 stub), add an explicit note to the ADR
  and to `docs/GAPS.md` that the contract bumped to v0.5 **without** a mechanical
  ground-truth regression run, because the harness is unbuilt — this is the loud,
  non-silent acknowledgement the project requires. Do **not** fabricate a passing run.

- [ ] **Step 3: Run the full existing suite once, confirm GREEN** (this is the real,
  runnable gate available today):

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q`
Expected: PASS. This exercises the tier classifier, both predicates, `eligible_pool`, the
I3 check, ingest `is_primary`, and the badge end-to-end.

- [ ] **Step 4: Commit** (`docs: ADR-0003 trusted-outlet primary-grade tier + contract v0.5`).

---

## Phase B (spike-gated, deferred — do NOT start without a passing B1)

**B1 — live spike (research, go/no-go, not TDD):** verify whether akshare returns usable,
numeric STAR50-constituent disclosure data (e.g. via a disclosure/announcement endpoint)
that we could mint as `is_primary=True` OFFICIAL-domain sources, bypassing Bocha's cninfo
blindness. Deliverable: a short evidence note (does it return numbers we can match to a
quote?) + a go/no-go. Run against the live constituent list (`fetch_star50_constituents`).

**B2 — only if B1 passes:** a `gather_primary_disclosures` path that emits OFFICIAL-domain,
`is_primary=True` sources into the pool ahead of `eligible_pool`. Exact shape depends on
B1's findings — **not specified ahead of evidence** (specifying it now would be guessing).

If B1 shows the data is unusable, drop Phase B; Phase A stands on its own.

---

## Self-review (run before handoff)

- **Spec coverage:** §1 classifier → Task 1; §2.1 predicates → Task 2; §3.2 select → Task 3;
  §3.3 verifier → Task 4; §3.4 ingest → Task 5; §3.5 badge → Task 6; §6 contract/ADR → Task 7;
  §4 Phase B → Phase B section. All covered.
- **Type consistency:** `SourceTier` (IntEnum) used with `>=` everywhere; `clears_law3` /
  `is_officially_verified` signatures identical across Tasks 2/3/4/6; `classify` returns
  `SourceTier` throughout; marker literal `✓官方核实` identical in spec §3.5 and Tasks 6/render.
- **Placeholder scan:** no TBD/placeholder; every code-touching step has either an exact
  signature, an exact RED assertion block, or named behavioral prose (bodies intentionally
  left to the sub-agent per CLAUDE.md §2).
