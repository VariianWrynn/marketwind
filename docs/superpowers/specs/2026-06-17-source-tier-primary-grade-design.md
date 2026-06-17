# Source-tier model + primary-grade gate + "officially verified" badge — design

> **Read when:** working on the I3 (Iron Law 3) clearance path — how a quantitative
> claim earns the right to appear, and how a primary-backed claim is signalled to the
> reader. Companion to `docs/progress/writer-i3-publish-path.md` (the prior two fixes
> this design extends) and `citation/glossary.md` (the "Primary source" term, left
> unchanged here).

**Status:** approved 2026-06-17 (brainstorming). Implementation plan:
`docs/superpowers/plans/2026-06-17-source-tier-primary-grade.md`.

**Standing goal this serves:** the first real autonomous WeChat morning push needs the
grounded floor to clear `primary≥1` **and** the Verifier (Law 5) to pass — specifically
I3 must stop failing. The prior two fixes (`persist_enriched`, `eligible_pool`) made the
pipeline *lawful* by dropping every quant quote without a primary trace, but left the
brief *thin*: today the only live route to a primary-backed quote is the fragile
"secondary outlet → cninfo PDF number-match", and Bocha cannot reach cninfo at all. This
design widens what counts as "primary-grade" on a principled, statutory basis so trusted
disclosure media can lawfully back a number, and adds a reader-facing signal that
separates genuinely primary-corroborated claims from merely-trusted ones.

---

## 1. The problem, precisely

Two facts collide:

1. **I3 is correct and must stay strict.** A bare number with no responsible source is
   exactly the financial failure mode the project exists to prevent. We do **not** loosen
   the "Primary source" definition in `glossary.md` (that is Tier 0; changing it needs its
   own ADR and we are not making that case).

2. **The live supply of Tier-0 primaries is near zero.** Empirical Bocha spike (real API,
   cost ignored): Bocha **ignores the `site:` operator**, **cannot reach `cninfo.com.cn`
   at all**, and official venue / regulator domains barely surface. What *does* dominate
   Bocha results are trusted financial outlets: Sina Finance, 第一财经, 财联社, 财新,
   中证网, 上证, 证券时报. These are the CSRC-designated disclosure media — by statute the
   venues a listed company *must* publish into.

The resolution is **not** to call Sina a primary source (it isn't), but to recognise a
**tier between "the company itself" and "random aggregator"**: media that Chinese
securities law designates as official disclosure channels. A number reported by 中证网 is
not a primary, but it is *regulatorily accountable* in a way a self-publishing 财富号 post
is not. The owner explicitly accepts the residual risk that a designated/trusted outlet
occasionally mis-transcribes a number — a calculated risk, taken knowingly.

---

## 2. The tier model

A single classifier maps a normalised domain to one of five ordered tiers. Higher = more
authoritative. The tiers are grounded in the **CSRC "Provisions on Information Disclosure
of Listed Companies" + Securities Law Art. 86** designation of disclosure media — they are
*statutory categories*, not our taste.

| Tier | Name | Meaning | Examples |
|---|---|---|---|
| 4 | `OFFICIAL` | The disclosure venue / regulator itself. A document here **is** a primary. | cninfo, SSE, SZSE, CSRC, PBoC, MIIT, NFRA |
| 3 | `DESIGNATED` | CSRC-designated statutory disclosure newspapers/sites. | 中证网, 上证(中国证券网), 证券时报网, 证券日报, 金融时报, 经济参考报, 中国日报 |
| 2 | `TRUSTED` | Major financial media with strong editorial accountability, not statutorily designated. | Sina Finance, 第一财经, 财联社, 财新 |
| 1 | `SECONDARY` | Mainstream news / data portals; reporting is real but not disclosure-grade. | 新华网, 人民网, 21世纪, 界面, 东方财富(新闻/数据频道), 智通财经, 华尔街见闻, 澎湃 |
| 0 | `EXCLUDED` | Self-publishing platforms, forums, quote tables — no editorial accountability. | 财富号, 股吧, 雪球, 同花顺贴吧, quote pages, 自媒体 sub-hosts |

### 2.1 Two predicates derived from the tier

The whole design reduces to two boolean predicates, both pure functions of
`(domain, source.is_primary, quote.attached_primary_url)`:

- **Primary-grade (clears I3 — the *gate*):**
  `attached_primary_url is not None  OR  source.is_primary  OR  tier(domain) ≥ TRUSTED`
  → A quantitative quote may lawfully back a claim iff it is primary-grade. This is the
  widened gate: a Tier-2 (Sina) number now clears I3 on domain authority alone.

- **Officially-verified (earns the badge — the *signal*):**
  `attached_primary_url is not None  OR  source.is_primary  OR  tier(domain) ≥ DESIGNATED`
  → A claim is flagged to the reader as primary-corroborated iff it is officially-verified.
  Tier-2 (TRUSTED, e.g. Sina) clears the *gate* but **not** the *badge* — it still appears,
  but without the "✓官方核实" mark, and keeps any 据X报道 attribution it already carries.

The gap between the two predicates is the whole point: **everything ≥ TRUSTED may appear;
only ≥ DESIGNATED (or a real primary) is celebrated as verified.** This reuses the existing
`attached_primary_url` / `is_primary` machinery as a *signal*, exactly as the owner asked —
not just as a gate.

### 2.2 Classification rules (subdomain-aware, default-deny)

`domain_of(url)` (in `scout/outlets.py`) strips only `www.`, so **subdomains are
preserved** — `finance.sina.com.cn` and `money.finance.sina.com.cn` arrive as distinct
domains. The classifier must therefore be subdomain-aware:

1. **Denylist first (exact sub-host match).** A curated set of junk sub-hosts is checked
   *before* any allowlist, so an excluded sub-host of an otherwise-trusted root (e.g.
   `money.finance.sina.com.cn` under TRUSTED `finance.sina.com.cn`) resolves to `EXCLUDED`.
2. **Then tier allowlists (suffix match), highest tier first.** A domain matches an
   allowlist entry `E` iff `domain == E or domain.endswith("." + E)`. Return the tier of
   the first (highest) matching entry.
3. **Default-deny.** An unknown domain → `EXCLUDED`. We never let an unclassified domain
   back a number; widening recall is a deliberate, reviewed act of adding a domain to a
   list, never an accident.

The denylist-first ordering is load-bearing: it is the only thing that lets us trust
`finance.sina.com.cn` while still excluding its `money.`/`vip.stock.` self-quote sub-hosts.

### 2.3 The domain lists (spec-critical literals)

These exact strings are the spec. They live in `marketwind/scout/source_tier.py` as
frozensets. Extend by adding a domain (a reviewed act), never by loosening the matching.

```
OFFICIAL   = cninfo.com.cn, sse.com.cn, szse.cn, csrc.gov.cn, pbc.gov.cn,
             miit.gov.cn, nfra.gov.cn
DESIGNATED = cs.com.cn, cnstock.com, stcn.com, zqrb.cn, financialnews.com.cn,
             jjckb.cn, chinadaily.com.cn
TRUSTED    = finance.sina.com.cn, yicai.com, cls.cn, caixin.com
SECONDARY  = news.cn, xinhuanet.com, people.com.cn, 21jingji.com, jiemian.com,
             finance.eastmoney.com, data.eastmoney.com, zhitongcaijing.com,
             wallstreetcn.com, thepaper.cn, cnfin.com
DENYLIST   = caifuhao.eastmoney.com, guba.eastmoney.com, mguba.eastmoney.com,
             quote.eastmoney.com, emwap.eastmoney.com, q.stock.sohu.com,
             k.sina.com.cn, k.sina.cn, cj.sina.com.cn,
             vip.stock.finance.sina.com.cn, money.finance.sina.com.cn,
             xueqiu.com, tgb.cn
```

(The DENYLIST supersedes the existing `is_quote_aggregator` frozenset in `outlets.py`,
which held two of these hosts; see §5 wiring note.)

---

## 3. Wiring — three call sites, one new module

The model is one new pure module plus three one-line edits at existing seams. No flow
changes, no new pipeline stage.

### 3.1 `marketwind/scout/source_tier.py` (new)

- `class SourceTier(IntEnum)`: `EXCLUDED=0, SECONDARY=1, TRUSTED=2, DESIGNATED=3, OFFICIAL=4`.
- `classify(domain: str) -> SourceTier` — §2.2 algorithm over the §2.3 frozensets.
- `clears_law3(domain, source_is_primary, attached_primary_url) -> bool` — §2.1 primary-grade.
- `is_officially_verified(domain, source_is_primary, attached_primary_url) -> bool` — §2.1 badge.

Predicates take primitives (not `PooledSource`) so the module imports nothing from
`writer.domain` — keeps it dependency-free and trivially unit-testable.

### 3.2 `writer/select.py::eligible_pool` (extend)

Today it keeps a quant quote iff `attached_primary_url or is_primary`. Extend to:
- drop a whole source whose domain classifies `EXCLUDED` (no quote from a no-accountability
  host reaches the Writer, quant or not);
- for surviving sources, keep a quant quote iff `clears_law3(...)` (so Tier-2 quant now
  survives), keep every non-quant quote.

### 3.3 `verifier/checks.py::check_quant_has_primary` (extend)

Replace the inline `quote.attached_primary_url or source.is_primary` primary test with
`clears_law3(source.domain, source.is_primary, quote.attached_primary_url)`. The Writer's
pool (post-`eligible_pool`) and the Verifier now apply the *same* predicate, so a claim
that survived selection cannot fail I3 — the structural guarantee from the prior fix is
preserved, just with the widened predicate.

### 3.4 Ingest — set `is_primary=True` for OFFICIAL domains

`gather.py::build_pool` constructs each `Source(...)` with the default `is_primary=False`.
Set `is_primary = classify(domain_of(url)) >= SourceTier.OFFICIAL` at construction. This
*activates the dead `is_primary` path* (defined and honoured by the Verifier but never set
`True` anywhere live). Via Bocha this rarely fires (Bocha can't reach cninfo); it is the
mechanism Phase B (akshare→cninfo direct) will feed.

### 3.5 The "officially verified" badge (reader signal)

A mechanical, **non-LLM** property computed at the runner/render boundary — never a model
judgement (Law 4 safe).

- New pure helper (in `writer/select.py`): `officially_verified_claims(output, pool) ->
  set[str]` — the set of claim `local_id`s having **≥1 backing quote** that is
  officially-verified (§2.1 second predicate).
- `render_brief` gains an optional `official_ids: set[str] = frozenset()` parameter
  (back-compatible). When a *factual* sentence's `claim_ids` are non-empty and **all** lie
  in `official_ids`, append the marker `✓官方核实` to that sentence's rendered text (after
  the `[n]` markers).
- `runner.py::draft_report` computes `official_ids` from the filtered pool + output and
  passes it to `render_brief`.

Tier-2-only quant claims (cleared the gate, not the badge) render **without** the marker
and keep their existing attribution prefix — the badge task adds no attribution logic
(that is I3b, a separate mechanism left untouched).

---

## 4. Phase B (spike-gated, deferred) — cninfo-direct via akshare

Phase A makes the pipeline both lawful and reasonably rich off Bocha's trusted-outlet
stream. Phase B raises *true* primary recall by pulling official disclosures directly,
bypassing Bocha's cninfo blindness — but only if it actually works.

- **B1 (spike, must pass first):** a live verification — does akshare return usable, numeric
  STAR50-constituent disclosure data we can mint as `is_primary=True` sources? This is a
  research spike, not TDD; its result is a go/no-go.
- **B2 (only if B1 passes):** a `gather_primary_disclosures` path that emits OFFICIAL-domain,
  `is_primary=True` sources into the pool. Shape depends on B1's findings; not specified
  ahead of evidence.

If B1 shows akshare disclosure data is unusable, Phase B is dropped and Phase A stands on
its own.

---

## 5. Explicitly dropped / out of scope

- **Bocha query-string biasing toward primary domains** — dropped. The spike proved Bocha
  ignores `site:` and can't reach cninfo, so biasing queries is near-zero ROI.
- **Webfetch stays a fast tool, not an agent.** Researched: the problem is domain-targeting,
  not multi-hop reasoning; an agentic fetch loop adds 3–20× latency/cost, a wider attack
  surface, and worse debuggability for no recall gain.
- **The Tier-0 "Primary source" glossary definition is unchanged.** We add tiers *around*
  it; we do not redefine it.
- **No new attribution / corroboration logic.** I3b (据X报道 single-source attribution)
  is untouched.

---

## 6. Contract & decision-log changes

- **ADR-0003** (`docs/adr/0003-trusted-outlet-primary-grade-tier.md`): records that
  CSRC-designated + curated-trusted outlets are accepted as *primary-grade for the I3 gate*
  (not as Tier-0 primaries), with the owner as grantor and the accepted residual risk.
- **`citation/glossary.md`:** add the five-tier table as a new term block. **Leave "Primary
  source" (Tier 0) exactly as-is.**
- **`CITATION_CONTRACT.md`:** annotate I3 to note that `has_primary` is satisfied by
  primary-grade (tier ≥ TRUSTED) as well as a true attached primary; bump version
  0.4 → 0.5 with a changelog line. **This touches the contract → triggers the full
  `tests/citation_ground_truth/` regression** (must stay green).
- **Precursor:** the two prior fixes (`persist_enriched`, `eligible_pool`) are still
  uncommitted; commit them first as the base this design extends.

---

## 7. Key invariants (must survive implementation)

- **Floor gate untouched.** The grounded floor runs earlier, on the full enriched in-memory
  pool; tiering only narrows/annotates the Writer's draft input. `primary≥1` at the floor is
  unaffected.
- **Same predicate to Writer and Verifier.** `eligible_pool` and `check_quant_has_primary`
  both use `clears_law3` — no Writer/Verifier divergence, so I3 stays structurally
  unviolable for anything that survived selection.
- **Default-deny.** Unknown domain ⇒ EXCLUDED ⇒ never backs a number. Recall is widened only
  by a reviewed list edit.
- **Badge is mechanical.** `officially_verified_claims` is a pure set computation over pool
  fields; the model never decides who gets the mark (Law 4).
- **Tier 0 is sacred.** The "Primary source" definition does not move.
