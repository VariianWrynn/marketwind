from marketwind.writer.domain import DraftClaim, DraftSentence, WriterOutput
from marketwind.writer.render import MAX_CHARS, render_brief, render_source_tail


def _out(sentences):
    return WriterOutput(claims=[], sentences=sentences)


def test_markers_assigned_from_source_ids_in_order():
    out = _out([
        DraftSentence("甲事实。", ["c-1"], ["s1"], "factual"),
        DraftSentence("乙事实。", ["c-2"], ["s2"], "factual"),
        DraftSentence("丙事实，与甲同源。", ["c-3"], ["s1"], "factual"),
    ])
    brief = render_brief(out)
    assert brief.sentences[0].text.endswith("[1]")
    assert brief.sentences[1].text.endswith("[2]")
    assert brief.sentences[2].text.endswith("[1]")  # s1 reused → same number
    assert brief.footnotes == [(1, "s1"), (2, "s2")]


def test_structural_sentence_has_no_marker():
    out = _out([
        DraftSentence("## 大盘动态", [], [], "structural"),
        DraftSentence("科创50收涨0.36%。", ["c-1"], ["s1"], "factual"),
    ])
    brief = render_brief(out)
    assert brief.sentences[0].text == "## 大盘动态"
    assert "[" not in brief.sentences[0].text


def test_multi_source_sentence_gets_multiple_markers():
    out = _out([DraftSentence("两家媒体同述此事。", ["c-1"], ["s1", "s2"], "factual")])
    brief = render_brief(out)
    assert brief.sentences[0].text.endswith("[1][2]")


def test_over_length_drops_whole_trailing_sentences():
    long = "这是一个很长的句子用来撑满预算" * 5 + "。"  # ~76 chars each
    sents = [DraftSentence(long, [f"c-{i}"], ["s1"], "factual") for i in range(10)]
    brief = render_brief(_out(sents))
    assert len(brief.body) <= MAX_CHARS
    assert len(brief.sentences) < 10            # some tail dropped
    # every surviving marker resolves to a footnote (no orphans)
    nums = {n for n, _ in brief.footnotes}
    for s in brief.sentences:
        for token in s.text.split("[")[1:]:
            assert int(token.split("]")[0]) in nums


def test_empty_output_renders_empty():
    brief = render_brief(_out([]))
    assert brief.body == ""
    assert brief.sentences == []


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


def test_source_tail_empty_footnotes_is_empty_string():
    assert render_source_tail([], {}) == ""


def test_source_tail_single_entry_format():
    tail = render_source_tail([(1, "s1")], {"s1": "https://finance.sina.com.cn/x"})
    assert tail == "—— 来源 ——\n[1] finance.sina.com.cn — https://finance.sina.com.cn/x"


def test_source_tail_url_is_bare_not_markdown():
    tail = render_source_tail([(1, "s1")], {"s1": "https://sse.com.cn/d/1"})
    assert "https://sse.com.cn/d/1" in tail
    assert "](" not in tail


def test_source_tail_multiple_entries_map_number_to_url():
    tail = render_source_tail(
        [(1, "s1"), (2, "s2")],
        {"s1": "https://a.com/1", "s2": "https://b.com/2"},
    )
    assert tail.splitlines() == [
        "—— 来源 ——",
        "[1] a.com — https://a.com/1",
        "[2] b.com — https://b.com/2",
    ]
