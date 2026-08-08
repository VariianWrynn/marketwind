"""Build the Writer (DeepSeek) prompt: Iron Laws + rationalization-table inline,
grounded-only, exact JSON output schema, and the serialized quote pool.

The Writer is also an enforcer of the Iron Laws (R10), not just a generator —
hence the rationalization table is inlined as a self-correction guardrail. Per
§5 the Writer does NOT load red-flags.md.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from marketwind.writer.domain import PooledSource

_RATIONALIZATION = (
    Path(__file__).resolve().parents[2] / "citation" / "rationalization-table.md"
)

_IRON_LAWS = """\
THE IRON LAWS (violating the letter is violating the spirit):
1. NO FACTUAL SENTENCE WITHOUT A CLAIM_ID
2. NO CROSS-CLAIM SYNTHESIS IN A SINGLE SENTENCE
3. NO QUANTITATIVE CLAIM WITHOUT A PRIMARY-GRADE SOURCE
4. NO MODEL-GENERATED INFERENCE — EVER
5. NO PUBLICATION WITHOUT FRESH VERIFIER PASS
The only legitimate inference is quoted_inference: the source itself made the
inference and you preserve its attribution (e.g. 据XX证券研报观点)."""

# Law 3 / I3 clarification (v0.5, ADR-0003): the pool is pre-filtered.
_LAW3_CLARIFICATION = """\
关于法则3（PRIMARY-GRADE SOURCE）的说明：
- "primary-grade"指以下任一条件满足：(a) 附有主要来源URL（attached_primary_url），
  (b) 来源本身为一手来源（is_primary=true），或 (c) 来源域名达到 tier ≥ TRUSTED——
  既包括交易所/监管机构（上交所、证监会）与证监会指定信息披露媒体（中证网、上证报、
  证券时报、证券日报），也包括受信任财经媒体（财联社、第一财经、新浪财经、财新）。
- 引用池已预先过滤：每一条出现在池中的定量引文（is_quantitative=true）均已通过
  primary-grade检验，无需再次核查。
- 字段 has_primary_trace 仅表示"是否附有单独的主要来源URL"，值为 false 并不表示
  该引文不符合法则3，也不能作为回避引用该引文支撑数字的理由。绝大多数引文
  has_primary_trace=false，但它们已经通过了域名级别的primary-grade校验。"""

_SCOPE = """\
报道范围(科创50):
- 本简报的主题是科创50指数(sh000688)及其成分股(688开头)。开篇先写科创50指数本身的
  表现,其次写688成分股的个股与公司事件。
- 上证指数/创业板/其他行业板块只能作为背景陪衬,不得成为简报重心;不得把非科创板
  标的(如主板600/601/603开头)当作科创板标的来写。
- 范围服从引用池:若池中缺少科创50相关材料,就如实少写或不写,绝不可为满足范围而
  编造、外推或夸大(违反法则1/4)。宁可范围不满足,也不可无中生有。"""

_CONTRACT_INVARIANTS = """\
合同不变量（CITATION_CONTRACT.md § 4，违反即自动拒绝）：
- I1: 同一句话引用的所有claims必须语义对齐，不得跨claim合成新含义（法则2的句级实现）。
- I3b: 定量claim须有≥2个独立来源佐证；若仅有单一来源，则句子必须携带归因前缀
  （如"据财联社报道"）。
- I4: 禁止模型自行推断；仅允许quoted_inference（来源本身作出的推断），且必须在正文中
  保留来源归因（如"据XX证券研报观点"）。
- I12: derived_metric类claim（来源对基础数据进行的二次计算，如日赚、合计减持额）须在
  正文中注明计算方法或依据；直接写裸数字而不说明口径，即违反I12。"""

_OUTPUT_SPEC = """\
OUTPUT: a single JSON object, no prose, no markdown fences:
{
  "claims":    [{"id": "c-001", "statement": "...", "quote_ids": ["<quote_id>", ...], "category": "quantitative", "methodology": ""}],
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
  be source ids from the pool. The brief should be ~500 Chinese characters.
- Number fidelity: render every figure EXACTLY as its source quote states it —
  same digits, same unit. Never unit-convert-and-round (e.g. a source's
  17539.73万元 must stay 17539.73万元, never become 1.75亿元): rounding loses
  precision and breaks the source's own arithmetic.
- Self-contained claims (自包含主体): every claim.statement must name its own
  subject — the specific 股票/公司/指数 it is about. Never use 该股/该公司/
  该指数/它/其 as a stand-in for a subject named in another claim, because each
  claim is verified in isolation. BAD: "该股当日收盘价涨幅达15%" (reader cannot
  tell which stock). GOOD: "南芯科技(688484)当日收盘价涨幅达15%".
- 数据类型标注（I12）：每条claim的category默认为"quantitative"；若该数字是来源方对基础数据的二次计算结果（举例：日赚、合计减持额、净利润增速等），则标记为"derived_metric"，同时必须在methodology字段中注明计算依据（如 按净利润计、按区间累计减持股数×均价计），不得省略；若无法确定计算方式，则直接引用基础数据原值，不得推断合计或换算。
- **category 白名单（必须严格使用以下值之一，不得自创）**：
  - `quantitative` — 直接引用来源的原始数字（默认值）
  - `temporal` — 时间相关的事实（如交易日期、发布时间）
  - `comparative` — 比较性陈述（如涨幅、跌幅、排名）
  - `attribution` — 归因陈述（如"据XX报道"）
  - `causal` — 因果关系（如"因XX导致YY"）
  - `quoted_inference` — 来源本身作出的推断（必须保留归因）
  - `freshness` — 时效性声明（如"今日"、"昨日"）
  - `derived_metric` — 来源对基础数据的二次计算（必须在methodology中注明计算依据）
  - `correction` — 更正声明
  - **禁止使用**：`qualitative`、空字符串、或任何不在上述列表中的值。若不确定，使用 `quantitative`。"""


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


def build_writer_prompt(pool: list[PooledSource], *, session_date: date) -> list[dict]:
    rationalizations = _RATIONALIZATION.read_text(encoding="utf-8")
    date_anchor = (
        f"复盘的交易日：{session_date.isoformat()}。"
        "本简报仅复盘该交易日（北京时间）发生的市场事实。"
        "引用池中属于其他日期的材料不得作为该交易日的事实陈述。"
    )
    system = "\n\n".join([
        "你是市风(MarketWind)的撰稿器(Writer)。只能基于给定的引用池(quote pool)装配中文简报。",
        date_anchor,
        _IRON_LAWS,
        _LAW3_CLARIFICATION,
        _CONTRACT_INVARIANTS,
        "When you catch yourself rationalizing around a law, STOP. Known excuses and "
        "their rebuttals:\n\n" + rationalizations,
        _SCOPE,
        _OUTPUT_SPEC,
    ])
    user = "QUOTE POOL (assemble the 科创50 昨日复盘 brief from these only):\n" + _serialize_pool(pool)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
