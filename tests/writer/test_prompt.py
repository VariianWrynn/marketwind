from marketwind.writer.domain import PooledQuote, PooledSource
from marketwind.writer.prompt import alias_pool, build_writer_prompt

_RAW_AAA = "科创50收涨0.36%。市场情绪偏谨慎。"
POOL = [
    PooledSource("SRC-AAA", "https://m.cls.cn/a/1", "m.cls.cn", False, [
        PooledQuote("QUO-111", "科创50收涨0.36%。", True, "data", "https://cninfo.com.cn/x",
                    span_start=0, span_end=len("科创50收涨0.36%。")),
        PooledQuote("QUO-222", "市场情绪偏谨慎。", False, "factual", None,
                    span_start=len("科创50收涨0.36%。"), span_end=len(_RAW_AAA)),
    ], raw_content=_RAW_AAA),
]


def test_prompt_embeds_iron_laws_and_rationalizations():
    msgs = build_writer_prompt(POOL)
    text = " ".join(m["content"] for m in msgs)
    assert "NO FACTUAL SENTENCE WITHOUT A CLAIM_ID" in text   # Iron Laws inline
    assert "Rationalization" in text or "rationaliz" in text.lower()  # table inline
    assert "据" in text  # rebuttal content (attribution) present


def test_prompt_serializes_pool_ids_and_text():
    msgs = build_writer_prompt(POOL)
    text = " ".join(m["content"] for m in msgs)
    # Aliases must appear, not raw UUIDs
    assert "q1" in text
    assert "s1" in text
    assert "科创50收涨0.36%。" in text
    # Raw ids must NOT appear in the prompt (we don't leak raw UUIDs to the model)
    assert "QUO-111" not in text
    assert "SRC-AAA" not in text


def test_prompt_demands_json_no_freeform():
    msgs = build_writer_prompt(POOL)
    text = " ".join(m["content"] for m in msgs).lower()
    assert "json" in text
    assert "claims" in text and "sentences" in text


def test_prompt_demands_number_fidelity():
    # The Writer must render every figure exactly as its source quote states it
    # and never unit-convert-and-round. Anchored on the real failure where a
    # source's 17539.73万元 was rendered as 1.75亿元, breaking the arithmetic
    # and tripping the I10 contradiction check.
    msgs = build_writer_prompt(POOL)
    text = " ".join(m["content"] for m in msgs)
    assert "17539.73万元" in text
    assert "1.75亿元" in text


def test_alias_pool_returns_correct_maps_and_rows():
    rows, q_map, s_map = alias_pool(POOL)
    # alias maps
    assert q_map == {"q1": "QUO-111", "q2": "QUO-222"}
    assert s_map == {"s1": "SRC-AAA"}
    # rows carry alias ids, not real ids
    assert rows[0]["quote_id"] == "q1"
    assert rows[0]["source_id"] == "s1"
    assert rows[1]["quote_id"] == "q2"
    assert rows[1]["source_id"] == "s1"


def test_prompt_demands_self_contained_claims():
    msgs = build_writer_prompt(POOL)
    text = " ".join(m["content"] for m in msgs)
    # Each claim statement must name its own subject; no dangling 该股/该公司
    # references, because claims are verified in isolation. Root cause of the
    # 涨停-vs-15% I10 mis-binding (a subject-less "+15%" bound to 南芯科技).
    assert "该股" in text
    assert "自包含" in text or "主体" in text
