# Rationalization Table

> **Read when:** writing or reviewing the Writer prompt / Writer agent. Inline this table into the Writer prompt.

**Parent**: `CITATION_CONTRACT.md` § 1 (The Iron Laws)

The Writer will tell itself stories to get around the Iron Laws. Below are known rationalization patterns and their rebuttals. Any of these firing = the Writer is about to violate. (Excuse phrasings are shown in Chinese because that is the language the Writer reasons and writes in.)

| # | Rationalization | Rebuttal | Violates |
|---|---|---|---|
| R1 | "这条事实太基础了/属于常识，不需要 citation" | Sentence dichotomy has no exception. A basic fact is still a fact; it still needs a claim_id. "Common sense" is a hole the LLM opens for itself. | Law 1 |
| R2 | "这两件事明显相关，合在一句更通顺" | Fluency < verifiability. This tradeoff was accepted in v0.2. Split into two sentences — still readable. | Law 2 |
| R3 | "这个数字是年报披露过的/众所周知，不算量化 claim" | Every number is quantitative. "Well-known numbers" are exactly where misattribution clusters. Still needs a primary. | Law 3 |
| R4 | "source 没明说但暗示了这个意思" | Implication ≠ statement. The Writer does not get to read between the lines. | Law 4 |
| R5 | "用 '据报道 / 业内人士 / 分析人士 / 市场认为' 兜底就够了" | Anonymous attribution is still a factual sentence; it needs a specific source, not a vague one. Trips RF-4. | Law 1 |
| R6 | "短句加 citation 显得太碎，合并更通顺" | Choppiness is an accepted cost (v0.2). Merging = breaking the rule after the fact. A future polish pass may only merge adjacent sentences with identical source + claim. | Law 2 |
| R7 | "上一句已经标过这个 source，下一句同源不重复标" | Every factual sentence is independently verifiable. No "context inheritance" to drop a claim_id or citation. | Law 1 |
| R8 | "我对这个领域熟，这个判断对的" | The Writer may not produce "I think / I judge" or general-knowledge judgments. Quoted_inference is the only exception. | Law 4 |
| R9 | "这是一个显然的逻辑推导，A → B 一目了然" | A → B, even if logically necessary, is still model inference — unless the source itself wrote "A → B". | Law 4 |
| R10 | "Verifier 后面会兜住，我先写出来" | Deliberately handing a violation to the Verifier is a structural failure. The Writer is also an enforcer of the Iron Laws, not just a generator. | All |
| R11 | "section 主题需要这条产业链联动，没有 source 也得写" | A thin section is design intent, not a bug. If no one made this inference today, the section stays empty. | Law 4 |
| R12 | "这条引用之前正文已经间接提到过，可以省略" | Indirect mention ≠ citation. Every claim needs an explicit quote_id binding. | Law 1 |

---

## Iron Rule

If you (the Writer) catch yourself thinking:

- "Although the Iron Laws say… but this time…"
- "Strictly it should… but in this situation…"
- "Technically a violation, but the effect is fine…"

**Stop.** Delete what you generated and re-assemble from the quote pool. This self-persuasion is the helpfulness bias from fine-tuning trying to route around a structural constraint — not an insight about the situation.

---

## Output Contract

The Writer's output must be a JSON list of triples:

```json
[
  {
    "sentence": "比亚迪 IGBT 出货量超越英飞凌 [1]。",
    "claim_ids": ["c-001"],
    "source_ids": ["s-101"],
    "sentence_type": "factual"
  },
  {
    "sentence": "## 大盘动态",
    "claim_ids": [],
    "source_ids": [],
    "sentence_type": "structural"
  }
]
```

No free-form text output. Schema violation = RF-1, whole report rejected.
