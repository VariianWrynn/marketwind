"""render_brief honors a custom max_chars and keeps every [n] resolvable."""
from marketwind.writer.domain import DraftClaim, DraftSentence, WriterOutput
from marketwind.writer.render import render_brief
from marketwind.gateway.im.label import BODY_BUDGET


def _output(n_sentences: int) -> WriterOutput:
    claims = [DraftClaim(local_id=f"c{i}", statement=f"s{i}", quote_ids=[f"q{i}"])
              for i in range(n_sentences)]
    sentences = [
        DraftSentence(sentence="科创50昨日成交额约三点二四万亿元人民币。",
                      claim_ids=[f"c{i}"], source_ids=[f"src{i}"], sentence_type="factual")
        for i in range(n_sentences)
    ]
    return WriterOutput(claims=claims, sentences=sentences)


def test_render_respects_custom_budget():
    brief = render_brief(_output(40), max_chars=BODY_BUDGET)
    assert len(brief.body) <= BODY_BUDGET
    # every footnote marker [n] present in body resolves to a footnote
    nums = {n for n, _sid in brief.footnotes}
    for n in nums:
        assert f"[{n}]" in brief.body


def test_default_max_chars_unchanged():
    # Back-compat: default budget is still 500 (P1b behavior).
    brief = render_brief(_output(40))
    assert len(brief.body) <= 500
