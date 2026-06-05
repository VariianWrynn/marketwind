"""Build the Writer (DeepSeek) prompt: Iron Laws + rationalization-table inline,
grounded-only, exact JSON output schema, and the serialized quote pool.

The Writer is also an enforcer of the Iron Laws (R10), not just a generator —
hence the rationalization table is inlined as a self-correction guardrail. Per
§5 the Writer does NOT load red-flags.md.
"""

from __future__ import annotations

import json
from pathlib import Path

from marketwind.writer.domain import PooledSource

_RATIONALIZATION = (
    Path(__file__).resolve().parents[2] / "citation" / "rationalization-table.md"
)

_IRON_LAWS = """\
THE IRON LAWS (violating the letter is violating the spirit):
1. NO FACTUAL SENTENCE WITHOUT A CLAIM_ID
2. NO CROSS-CLAIM SYNTHESIS IN A SINGLE SENTENCE
3. NO QUANTITATIVE CLAIM WITHOUT A PRIMARY SOURCE
4. NO MODEL-GENERATED INFERENCE — EVER
5. NO PUBLICATION WITHOUT FRESH VERIFIER PASS
The only legitimate inference is quoted_inference: the source itself made the
inference and you preserve its attribution (e.g. 据XX证券研报观点)."""

_OUTPUT_SPEC = """\
OUTPUT: a single JSON object, no prose, no markdown fences:
{
  "claims":    [{"id": "c-001", "statement": "...", "quote_ids": ["<quote_id>", ...]}],
  "sentences": [{"sentence": "...", "claim_ids": ["c-001"], "source_ids": ["<source_id>"],
                 "sentence_type": "factual"}]
}
Rules:
- Assemble ONLY from the quote pool below. No general knowledge, no fill (D-1).
- Do NOT write [1]/[n] markers — the renderer adds them. Write clean sentence text.
- Factual sentence: sentence_type="factual", >=1 claim_id. One claim chain per
  sentence (Law 2) — never fuse two different claims into one sentence.
- Structural sentence (section title / transition): sentence_type="structural",
  claim_ids=[], source_ids=[].
- Every claim.quote_ids must be ids from the pool; every sentence.source_ids must
  be source ids from the pool. The brief should be ~500 Chinese characters."""


def alias_pool(
    pool: list[PooledSource],
) -> tuple[list[dict], dict[str, str], dict[str, str]]:
    """Serialize the pool with short aliases.

    Returns (rows, q_alias_to_uuid, s_alias_to_uuid).
    Sources get s1, s2, … in pool order; quotes get q1, q2, … as a global
    counter across the whole pool in (source, then quote) order.
    Each row carries alias strings for source_id and quote_id; all other fields
    are the original values (domain, is_primary, text, is_quantitative,
    has_primary_trace).
    """
    rows: list[dict] = []
    q_alias_to_uuid: dict[str, str] = {}
    s_alias_to_uuid: dict[str, str] = {}
    q_counter = 0
    for s_idx, s in enumerate(pool):
        s_alias = f"s{s_idx + 1}"
        s_alias_to_uuid[s_alias] = s.source_id
        for q in s.quotes:
            q_counter += 1
            q_alias = f"q{q_counter}"
            q_alias_to_uuid[q_alias] = q.quote_id
            rows.append({
                "source_id": s_alias,
                "domain": s.domain,
                "is_primary": s.is_primary,
                "quote_id": q_alias,
                "text": q.text,
                "is_quantitative": q.is_quantitative,
                "has_primary_trace": q.attached_primary_url is not None,
            })
    return rows, q_alias_to_uuid, s_alias_to_uuid


def _serialize_pool(pool: list[PooledSource]) -> str:
    rows, _, _ = alias_pool(pool)
    return json.dumps(rows, ensure_ascii=False, indent=2)


def build_writer_prompt(pool: list[PooledSource]) -> list[dict]:
    rationalizations = _RATIONALIZATION.read_text(encoding="utf-8")
    system = "\n\n".join([
        "你是市风(MarketWind)的撰稿器(Writer)。只能基于给定的引用池(quote pool)装配中文简报。",
        _IRON_LAWS,
        "When you catch yourself rationalizing around a law, STOP. Known excuses and "
        "their rebuttals:\n\n" + rationalizations,
        _OUTPUT_SPEC,
    ])
    user = "QUOTE POOL (assemble the 昨日复盘 brief from these only):\n" + _serialize_pool(pool)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
