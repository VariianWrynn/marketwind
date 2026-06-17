"""Tests for marketwind/verifier/checks.py — Tier-1 deterministic checks."""

from __future__ import annotations

import pytest

from marketwind.verifier.checks import (
    index_quotes,
    check_quotes_resolve,
    check_quant_has_primary,
    check_no_filler_attribution,
    check_no_first_person_inference,
)
from marketwind.writer.domain import (
    DraftClaim,
    DraftSentence,
    PooledQuote,
    PooledSource,
    WriterOutput,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_source(
    source_id: str,
    raw_content: str,
    quotes: list[PooledQuote],
    is_primary: bool = False,
    url: str = "http://example.com",
    domain: str = "example.com",
) -> PooledSource:
    return PooledSource(
        source_id=source_id,
        url=url,
        domain=domain,
        is_primary=is_primary,
        quotes=quotes,
        raw_content=raw_content,
    )


def make_quote(
    quote_id: str,
    text: str,
    raw_content: str,
    offset: int = 0,
    is_quantitative: bool = False,
    attached_primary_url: str | None = None,
    quote_type: str = "factual",
) -> PooledQuote:
    """Build a PooledQuote whose span correctly covers *text* in *raw_content*."""
    span_start = offset
    span_end = offset + len(text)
    return PooledQuote(
        quote_id=quote_id,
        text=text,
        is_quantitative=is_quantitative,
        quote_type=quote_type,
        attached_primary_url=attached_primary_url,
        span_start=span_start,
        span_end=span_end,
    )


def empty_output() -> WriterOutput:
    return WriterOutput(claims=[], sentences=[])


# ---------------------------------------------------------------------------
# index_quotes
# ---------------------------------------------------------------------------

def test_index_quotes_basic():
    raw = "hello world"
    q = make_quote("q-1", "hello", raw, offset=0)
    src = make_source("s-1", raw, [q])
    idx = index_quotes([src])
    assert "q-1" in idx
    quote, source = idx["q-1"]
    assert quote is q
    assert source is src


def test_index_quotes_empty_pool():
    assert index_quotes([]) == {}


# ---------------------------------------------------------------------------
# check_quotes_resolve — RF-3
# ---------------------------------------------------------------------------

class TestCheckQuotesResolve:
    def _claim(self, qids: list[str]) -> DraftClaim:
        return DraftClaim(local_id="c-001", statement="stmt", quote_ids=qids)

    # (a) span mismatch → RF-3
    def test_span_mismatch_fires(self):
        raw = "hello world"
        # Deliberately wrong: text says "hello" but span covers " world"
        q = PooledQuote(
            quote_id="q-1",
            text="hello",
            is_quantitative=False,
            quote_type="factual",
            attached_primary_url=None,
            span_start=5,  # points at " world"
            span_end=10,
        )
        src = make_source("s-1", raw, [q])
        idx = index_quotes([src])
        output = WriterOutput(claims=[self._claim(["q-1"])], sentences=[])
        violations = check_quotes_resolve(output, idx)
        assert len(violations) == 1
        v = violations[0]
        assert v.check == "RF-3"
        assert v.locus == "c-001"

    # (b) byte-exact match → []
    def test_exact_match_clean(self):
        raw = "hello world"
        q = make_quote("q-1", "hello", raw, offset=0)
        src = make_source("s-1", raw, [q])
        idx = index_quotes([src])
        output = WriterOutput(claims=[self._claim(["q-1"])], sentences=[])
        assert check_quotes_resolve(output, idx) == []

    # (c) missing quote_id → RF-3
    def test_missing_quote_id_fires(self):
        idx: dict = {}  # empty pool
        output = WriterOutput(claims=[self._claim(["q-missing"])], sentences=[])
        violations = check_quotes_resolve(output, idx)
        assert len(violations) == 1
        v = violations[0]
        assert v.check == "RF-3"
        assert v.locus == "c-001"


# ---------------------------------------------------------------------------
# check_quant_has_primary — I3
# ---------------------------------------------------------------------------

class TestCheckQuantHasPrimary:
    def _output(self, claim: DraftClaim) -> WriterOutput:
        return WriterOutput(claims=[claim], sentences=[])

    # (a) quantitative + no primary → I3
    def test_quant_no_primary_fires(self):
        raw = "涨幅5%"
        q = make_quote(
            "q-1", "涨幅5%", raw, offset=0,
            is_quantitative=True,
            attached_primary_url=None,
        )
        src = make_source("s-1", raw, [q], is_primary=False)
        idx = index_quotes([src])
        claim = DraftClaim(local_id="c-001", statement="涨幅5%", quote_ids=["q-1"])
        violations = check_quant_has_primary(self._output(claim), idx)
        assert len(violations) == 1
        v = violations[0]
        assert v.check == "I3"
        assert v.locus == "c-001"

    # (b) quantitative + attached_primary_url set → []
    def test_quant_with_attached_url_clean(self):
        raw = "涨幅5%"
        q = make_quote(
            "q-1", "涨幅5%", raw, offset=0,
            is_quantitative=True,
            attached_primary_url="http://primary.example.com/report.pdf",
        )
        src = make_source("s-1", raw, [q], is_primary=False)
        idx = index_quotes([src])
        claim = DraftClaim(local_id="c-001", statement="涨幅5%", quote_ids=["q-1"])
        assert check_quant_has_primary(self._output(claim), idx) == []

    # (c) quantitative + owning source is_primary=True → []
    def test_quant_with_primary_source_clean(self):
        raw = "涨幅5%"
        q = make_quote(
            "q-1", "涨幅5%", raw, offset=0,
            is_quantitative=True,
            attached_primary_url=None,
        )
        src = make_source("s-1", raw, [q], is_primary=True)
        idx = index_quotes([src])
        claim = DraftClaim(local_id="c-001", statement="涨幅5%", quote_ids=["q-1"])
        assert check_quant_has_primary(self._output(claim), idx) == []

    # non-quantitative quote → []
    def test_non_quant_clean(self):
        raw = "公司表示业绩良好"
        q = make_quote("q-1", "公司表示业绩良好", raw, offset=0, is_quantitative=False)
        src = make_source("s-1", raw, [q], is_primary=False)
        idx = index_quotes([src])
        claim = DraftClaim(local_id="c-001", statement="公司表示", quote_ids=["q-1"])
        assert check_quant_has_primary(self._output(claim), idx) == []

    # non-resolving quote_id → should not crash; no I3 (check_quotes_resolve handles it)
    def test_nonresolving_quote_no_crash(self):
        idx: dict = {}
        claim = DraftClaim(local_id="c-001", statement="stmt", quote_ids=["q-ghost"])
        violations = check_quant_has_primary(self._output(claim), idx)
        # should return [] — non-resolving contributes nothing to primary check
        assert violations == []


def test_trusted_domain_quant_does_not_violate_i3():
    pool = [PooledSource("S1", "https://finance.sina.com.cn/a", "finance.sina.com.cn",
                         False, [PooledQuote("Q1", "0.36%", True, "data", None, 0, 4)],
                         raw_content="0.36")]
    idx = index_quotes(pool)
    out = WriterOutput(claims=[DraftClaim("c1", "科创50涨0.36%", ["Q1"])], sentences=[])
    assert check_quant_has_primary(out, idx) == []  # no I3 (TRUSTED clears)


def test_unknown_domain_quant_still_violates_i3():
    pool = [PooledSource("S2", "https://randomblog.example/a", "randomblog.example",
                         False, [PooledQuote("Q2", "0.36%", True, "data", None, 0, 4)],
                         raw_content="0.36")]
    idx = index_quotes(pool)
    out = WriterOutput(claims=[DraftClaim("c2", "某数字0.36%", ["Q2"])], sentences=[])
    v = check_quant_has_primary(out, idx)
    assert len(v) == 1 and v[0].check == "I3"


# ---------------------------------------------------------------------------
# check_no_filler_attribution — RF-4
# ---------------------------------------------------------------------------

class TestCheckNoFillerAttribution:
    # tripping: sentence contains 据报道 → RF-4 with locus=sentence[0]
    def test_filler_in_sentence_fires(self):
        sent = DraftSentence(
            sentence="据报道该公司业绩大幅提升。",
            claim_ids=["c-001"],
            source_ids=["s-1"],
            sentence_type="factual",
        )
        output = WriterOutput(claims=[], sentences=[sent])
        violations = check_no_filler_attribution(output, {})
        assert len(violations) == 1
        v = violations[0]
        assert v.check == "RF-4"
        assert v.locus == "sentence[0]"

    # clean sentence → []
    def test_clean_sentence(self):
        sent = DraftSentence(
            sentence="公司今日公告净利润增长20%。",
            claim_ids=["c-001"],
            source_ids=["s-1"],
            sentence_type="factual",
        )
        output = WriterOutput(claims=[], sentences=[sent])
        assert check_no_filler_attribution(output, {}) == []

    # filler in claim statement → locus=claim.local_id
    def test_filler_in_claim_statement_fires(self):
        claim = DraftClaim(
            local_id="c-002",
            statement="分析人士认为市场将回调。",
            quote_ids=[],
        )
        output = WriterOutput(claims=[claim], sentences=[])
        violations = check_no_filler_attribution(output, {})
        assert len(violations) == 1
        v = violations[0]
        assert v.check == "RF-4"
        assert v.locus == "c-002"

    # other filler patterns
    def test_market_renwei_fires(self):
        sent = DraftSentence(
            sentence="市场认为本次调整属于正常现象。",
            claim_ids=[],
            source_ids=[],
            sentence_type="structural",
        )
        output = WriterOutput(claims=[], sentences=[sent])
        violations = check_no_filler_attribution(output, {})
        assert len(violations) == 1
        assert violations[0].check == "RF-4"
        assert violations[0].locus == "sentence[0]"

    def test_second_sentence_correct_locus(self):
        s0 = DraftSentence(sentence="正常句子。", claim_ids=[], source_ids=[], sentence_type="structural")
        s1 = DraftSentence(sentence="业内人士指出这是大趋势。", claim_ids=[], source_ids=[], sentence_type="structural")
        output = WriterOutput(claims=[], sentences=[s0, s1])
        violations = check_no_filler_attribution(output, {})
        assert len(violations) == 1
        assert violations[0].locus == "sentence[1]"


# ---------------------------------------------------------------------------
# check_no_first_person_inference — RF-10
# ---------------------------------------------------------------------------

class TestCheckNoFirstPersonInference:
    # tripping: sentence contains 系统认为 → RF-10
    def test_first_person_in_sentence_fires(self):
        sent = DraftSentence(
            sentence="系统认为当前市场存在风险。",
            claim_ids=["c-001"],
            source_ids=["s-1"],
            sentence_type="factual",
        )
        output = WriterOutput(claims=[], sentences=[sent])
        violations = check_no_first_person_inference(output, {})
        assert len(violations) == 1
        v = violations[0]
        assert v.check == "RF-10"
        assert v.locus == "sentence[0]"

    # clean sentence → []
    def test_clean_sentence(self):
        sent = DraftSentence(
            sentence="公司公告称净利润增长。",
            claim_ids=["c-001"],
            source_ids=["s-1"],
            sentence_type="factual",
        )
        output = WriterOutput(claims=[], sentences=[sent])
        assert check_no_first_person_inference(output, {}) == []

    # first-person inference in claim statement
    def test_first_person_in_claim_fires(self):
        claim = DraftClaim(
            local_id="c-003",
            statement="综合判断后市将继续上涨。",
            quote_ids=[],
        )
        output = WriterOutput(claims=[claim], sentences=[])
        violations = check_no_first_person_inference(output, {})
        assert len(violations) == 1
        v = violations[0]
        assert v.check == "RF-10"
        assert v.locus == "c-003"

    def test_jing_cesuan_fires(self):
        sent = DraftSentence(
            sentence="经测算该股估值偏高。",
            claim_ids=[],
            source_ids=[],
            sentence_type="structural",
        )
        output = WriterOutput(claims=[], sentences=[sent])
        violations = check_no_first_person_inference(output, {})
        assert len(violations) == 1
        assert violations[0].check == "RF-10"
