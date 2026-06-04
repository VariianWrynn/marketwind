from marketwind.writer.domain import PooledQuote, PooledSource
from marketwind.writer.prompt import build_writer_prompt

POOL = [
    PooledSource("s1", "https://m.cls.cn/a/1", "m.cls.cn", False, [
        PooledQuote("q1", "科创50收涨0.36%。", True, "data", "https://cninfo.com.cn/x"),
        PooledQuote("q2", "市场情绪偏谨慎。", False, "factual", None),
    ]),
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
    assert "q1" in text and "科创50收涨0.36%。" in text
    assert "s1" in text


def test_prompt_demands_json_no_freeform():
    msgs = build_writer_prompt(POOL)
    text = " ".join(m["content"] for m in msgs).lower()
    assert "json" in text
    assert "claims" in text and "sentences" in text
