# Glossary

> **Read when:** you need the canonical definition of any contract term.

**Parent**: `CITATION_CONTRACT.md`

Every module, prompt, and spec must use the definitions here. Wording drift of the same term across locations is a defect. Changing this table requires an ADR.

(Detection strings, render prefixes, and example sentences are kept in Chinese because they appear in or match the Chinese report.)

---

## Core terms

| Term | Definition |
|---|---|
| **Primary source** | Information directly from the entity itself: company announcements (巨潮 / HKEX / SEC), financial reports (10-Q / 10-K / annual), regulatory filings (CSRC / PBoC / MIIT / NFRA / CAC), the company's official site or verified official account, government postings |
| **Independent source** | Different `domain` **AND** different `byline`. Judged as **AND**, not OR. The same piece reprinted (even on a different domain) counts as the same source; the same reporter across platforms (even different domains) counts as the same source. |
| **Quoted inference** | An inference the source itself made in its own text. The Writer must preserve attribution when quoting it (e.g. 据 XX 证券研报观点). Legal; maps to Claim category `quoted_inference`. |
| **Model inference** | An inference an LLM generates from general knowledge or by combining facts. **Forbidden.** Includes A → B logical derivation (even if necessary), cross-source synthesis, "common sense" completion of what the source didn't state, and judgments after lead-ins like "显然/必然". |
| **Misattribution** | The claim's content is true but attributed to a source that doesn't contain it. Most common failure mode: number misplacement (a number from company X attached to company Y); period misplacement (Q2 data reported as Q3). |
| **Synthesis violation** | One sentence cites multiple sources that don't support the same claim (I1 / RF-2). Judged **sentence-level**, not claim-level — the claims are unchanged, only the sentence is re-assembled. |
| **Corroboration** | A claim supported by ≥ 2 independent sources. De-duplicate by the "Independent source" rule before counting. Counting logic = the I2 verification function. |
| **Attributed single** | The legal degradation state for a quantitative claim with only one independent source. Must render with a 据 X 报道 prefix or equivalent attribution. **Does not count toward the failure rate** (a designed degradation path, D-15-adjacent). |
| **Freshness claim** | (v0.3, widened) Two kinds: (a) subject attributes (executives, subsidiary ownership, licenses, regulatory status); (b) rolling numeric state carrying a present-tense indicator (目前/现/截至) — shareholding %, capacity, order backlog, equity structure. Even when the source is true and the quote matches, a state changed within 90 days is a violation. Requires a change search (I6). |
| **Derived metric** | (v0.3, new) A number a source computes over base data ("日赚 X 亿", "合计减持额", "市值排名第 N"). Different methodologies give different results. Maps to Claim category `derived_metric`; `methodology` is required, else it violates I12. |
| **Correction claim** | (v0.3, new) Generated when today's data overturns a claim the system published yesterday. Maps to category `correction`, rendered as 更正：昨日报告 X，经更精确来源核实应为 Y. Triggered by I11; silently changing the story is forbidden. |
| **Attributed sentiment** | (v0.3 stub, currently forbidden) Market sentiment attributable to a specific platform/discussion (e.g. "雪球讨论区出现 X 担忧", platform as source). Currently rejected under RF-4 / Law 4. Reserved as a future sub-type, to be distinguished from the system's own judgment. Until implemented, any sentiment-aggregation claim is a violation. |
| **Factual / Structural sentence** | Factual = carries ≥ 1 factual claim, must have ≥ 1 `claim_id`. Structural = titles / transitions / lead-ins / date stamps, `claim_ids = []`. |
| **Quote pool** | The sentence-level quote set Scout provides to the Writer, each with source_id, span offsets, and surrounding context (one sentence each side). The Writer assembles only from this pool; out-of-pool content is forbidden. |

---

## Boundary notes

### Independent source: why AND, not OR

Logic: different `domain` **AND** different `byline`. Common cases:

| Case | domain | byline | AND verdict | Matches intuition |
|---|---|---|---|---|
| 新华社 piece reprinted by 东财, 雪球 | ≠ | each may sign its own editor | "independent" | No (same source) → caught by **primary-source extraction**: the wire original is the primary, reprints don't add to corroboration |
| Same reporter across platforms | ≠ | = | NOT independent | Yes |
| Same outlet, two reporters, same event | = | ≠ | NOT independent | Yes (shared newsroom = shared fact-check) |
| Two brokerages, two analysts, similar conclusion | ≠ | ≠ | independent | Yes |

**What OR would do**: misjudge "same outlet, two reporters" as independent — loosening where it shouldn't. Keep AND.

### Quoted inference vs Model inference: the test

**The test**: **did the source itself state the inference?**

| Situation | Verdict |
|---|---|
| Source: "光刻胶国产化将利好 X 公司". Writer: "据 X 研报观点，光刻胶国产化对该公司构成利好 [n]" | quoted_inference, legal |
| Source A: "光刻胶国产化进程加速". Source B: "X 公司是国内光刻胶主要厂商". Writer fuses: "光刻胶国产化利好 X 公司 [a][b]" | **model_inference, violates Law 4** |
| Source: "X 公司 Q3 营收同比 +35%". Writer: "X 公司 Q3 业绩超预期 [n]" | **model_inference**: "超预期" is a judgment, not a fact, unless the source used "超预期" |
| Source: "分析师预测 X 公司 Q4 EPS 1.2 元". Writer: "据 XX 分析师预测，X 公司 Q4 EPS 为 1.2 元 [n]" | quoted_inference, legal |

Edge rule: when the source writes a quoted_inference, the Writer's claim category must also be `quoted_inference`, not mixed into `quantitative` or `comparative`.

### Anonymous "据报道" attribution

Any phrasing like 据报道、业内人士、分析人士、知情人士、有消息称 is **not** legal attribution; trips RF-4.

The one exception: if that phrasing **appears in the source's own text**, the Writer may keep it but must use the source's own `byline` as the attribution (i.e. 据 XX 媒体引述业内人士……[n], not 据业内人士……[n]).

### Time window enum (v0.3)

Each claim's `time_window` names the temporal window the fact belongs to. I10 / RF-7 align `time_window` before comparing — two opposite-direction claims are a contradiction only if same window and same subject.

| Value | Meaning |
|---|---|
| `overnight_us` | last night's US session (EST prev trading day 9:30–16:00) |
| `us_extended` | US after-hours / pre-market |
| `cn_prev_session` | A-share previous full trading session |
| `cn_intraday` | a point during the A-share session |
| `point_in_time` | a state at a specific instant (shareholding %, market-cap snapshot) |
| `period` | fiscal quarter/year range (Q1, FY2025) |
| `policy_event` | a policy-release timestamp |
| `undated` | no clear time (avoid; the Writer should return to Scout for time metadata) |

**Real case** (5/28 quote pool): item 1 "隔夜半导体领跌" = `overnight_us`; item 6 "周二费半涨近6%" = also US but a **different trading day**, so it needs day-level disambiguation. The two are opposite-direction but not contradictory — once `time_window` is aligned they fall in different windows and pass. A naive contradiction check would misfire RF-7, which is why I10 must be time-window-aware.

### "Verified" — what it means here

`Claim.status = 'verified'` does **not** mean "absolutely true in the world". Its precise meaning: it passed all relevant I-series invariants and Red Flags, `corroboration_status` is not `insufficient`, and the judge (DeepSeek V4 Pro) confirmed the claim is semantically aligned with its quote. `verified` is a conjunction of mechanically-checkable properties, not an omniscient truth claim — it guarantees consistency with the cited source, not correctness about the world.
