from marketwind.writer.domain import (
    DraftClaim, DraftSentence, PooledQuote, PooledSource, WriterOutput,
)


def test_value_objects_construct():
    text = "科创50收涨0.36%。"
    q = PooledQuote("q1", text, True, "data", "https://cninfo.com.cn/x",
                    span_start=0, span_end=len(text))
    s = PooledSource("s1", "https://m.cls.cn/a/1", "m.cls.cn", False, [q],
                     raw_content=text)
    out = WriterOutput(
        claims=[DraftClaim("c-001", "科创50上一交易日收涨0.36%", ["q1"])],
        sentences=[DraftSentence("科创50上一交易日收涨0.36%。", ["c-001"], ["s1"], "factual")],
    )
    assert s.quotes[0].quote_id == "q1"
    assert out.sentences[0].claim_ids == ["c-001"]


def test_pooled_quote_carries_span_and_source_carries_raw_content():
    text = "科创50收涨0.36%。"
    q = PooledQuote(
        "q1", text, True, "data", "https://cninfo.com.cn/x",
        span_start=0, span_end=len(text),
    )
    raw = text
    s = PooledSource(
        "s1", "https://m.cls.cn/a/1", "m.cls.cn", False, [q],
        raw_content=raw,
    )
    assert q.span_start == 0
    assert q.span_end == len(text)
    assert s.raw_content == raw
    # Re-resolution invariant: the slice of raw matches the quote text
    assert s.raw_content[q.span_start:q.span_end] == q.text


def test_draftclaim_carries_category_and_methodology():
    from marketwind.writer.domain import DraftClaim
    c = DraftClaim(
        local_id="c-001",
        statement="长鑫存储去年日赚3.6亿元。",
        quote_ids=["q-1"],
        category="derived_metric",
        methodology="按净利润计",
    )
    assert c.category == "derived_metric"
    assert c.methodology == "按净利润计"


def test_draftclaim_defaults_are_non_derived():
    from marketwind.writer.domain import DraftClaim
    c = DraftClaim(local_id="c-002", statement="营收508亿元。", quote_ids=["q-2"])
    assert c.category == "quantitative"
    assert c.methodology is None
