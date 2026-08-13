# I10 false positive (占比 denominator) + time_window enforcement

> **Read when:** the I10 contradiction judge flags a percentage metric (e.g. 主力净流入占比)
> as contradicting another claim's absolute figure; or the writer leaves `time_window` empty
> on date-specific claims.

**Status:** complete, 2026-08-13. Deployed to scheduler image `9d50200d`. Branch
`feat/tier2-quality-and-verification-depth`.

**No new ADR.** These changes restore conformance to existing locked decisions (D-13
time_window-aware I10; writer prompt OUTPUT_SPEC time_window rule). Nothing here is a
new design choice.

---

## Triggering incident

Run `cron-main-20260812T230000` (trading_date 2026-08-13) failed the Law-5 verifier
gate with `checks=I10 (1 violations)`. The brief was not published.

**DB evidence** (`claim_failures`):

```
check_name: I10
locus:      c7
detail:     c7称艾力斯主力净流入占比0.01%，但与c1所述成交额15.55亿元及净流入1897.79万元
            计算出的占比约1.22%相矛盾。
```

**Source data** (both claims from `finance.sina.com.cn`, same source):

| claim | quote text |
|-------|-----------|
| c1 | 8月11日，艾力斯涨1.54%，成交额15.55亿元，换手率2.90%，总市值530.87亿元。 |
| c7 | 今日主力净流入1897.79万，占比0.01%，行业排名13/157，连续3日被主力资金增仓。 |

**Root cause:** The judge reverse-engineered the denominator of c7's "占比0.01%" by
dividing 净流入 (1897.79万) by c1's 成交额 (15.55亿), getting ~1.22%, and flagged the
discrepancy. But "主力净流入占比" on Chinese financial data platforms uses a
market-wide denominator (total market net inflow), not the individual stock's trading
volume. The source data is internally consistent; the judge performed unauthorized
cross-claim arithmetic.

**Secondary finding:** All 7 claims in the rejected draft had `time_window` empty despite
citing specific dates (8月11日). The writer prompt's time_window rule was advisory
("必须填写") but lacked enforcement language, so the model ignored it.

---

## Changes

| File | Change | Rationale |
|------|--------|-----------|
| `marketwind/verifier/judge.py` | Added one constraint to I10 prompt: data-platform percentage metrics' denominators may not be reverse-engineered from other claims; cross-claim arithmetic to determine contradiction is forbidden unless both claims explicitly share the same denominator. | Prevents the false positive where the judge divided one claim's figure by another's to "discover" a contradiction that doesn't exist. |
| `marketwind/writer/prompt.py` | Strengthened time_window rule: marked "必填" (mandatory), added concrete example (`claim提到"8月11日"则time_window="2026-08-11"`), added consequence warning ("违反将导致验证门失败"). | The previous wording was advisory; the model ignored it. Stronger language with a concrete example and explicit consequence should improve compliance. |

## Verification

- Both files pass `python -c "import ast; ast.parse(...)"` syntax check.
- Image rebuilt (`docker compose build scheduler`), container restarted.
- In-container import check confirms both patches are present in the running code.
- I10 prompt verified to contain the new denominator rule via mock judge test.

## What this does NOT change

- No changes to `checks.py` (Tier-1 deterministic checks).
- No changes to the I1 (synthesis) or I11 (cross-report) judge prompts.
- No changes to the database schema or `claim_failures` recording logic.
- No changes to the writer's number-fidelity or self-contained-subject rules.
