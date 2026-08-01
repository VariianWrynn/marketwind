from dataclasses import replace
from datetime import datetime, timezone

from marketwind.scout.claim_extract import ClaimRef
from marketwind.scout.domain import Quote, Source
from marketwind.scout.enrich import enrich_primary

NOW = datetime(2026, 6, 5, tzinfo=timezone.utc)
CONS = {"中芯国际": "688981"}


def _q(text, quant=True):
    return Quote(text=text, span_start=0, span_end=len(text), context_before=None,
                 context_after=None, is_quantitative=quant)


def _src(quotes):
    return Source(url="https://news.example.com/a", domain="example.com",
                  publish_ts=NOW, raw_content="x", quotes=quotes)


async def _classify_none(text):
    return None


async def _never_fetch(url):
    raise AssertionError("fetch must not be called")


async def _never_trace(ct, sym, on_date):
    raise AssertionError("trace must not be called")


async def test_confirmed_number_attaches_primary():
    async def trace(ct, sym, on_date):
        assert (ct, sym) == ("earnings", "688981")
        return ["https://cninfo.com.cn/d1"]

    async def fetch(url):
        return "本期净利润为360,000,000元"

    out = await enrich_primary([_src([_q("中芯国际净利润3.6亿元")])],
                               classify=_classify_none, trace=trace, fetch=fetch,
                               constituents=CONS, on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url == "https://cninfo.com.cn/d1"


async def test_wrong_number_does_not_attach():
    async def trace(ct, sym, on_date):
        return ["https://cninfo.com.cn/d1"]

    async def fetch(url):
        return "本期净利润为5亿元"  # different figure

    out = await enrich_primary([_src([_q("中芯国际净利润3.6亿元")])],
                               classify=_classify_none, trace=trace, fetch=fetch,
                               constituents=CONS, on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url is None


async def test_non_quantitative_quote_skipped():
    out = await enrich_primary([_src([_q("中芯国际发布公告", quant=False)])],
                               classify=_classify_none, trace=_never_trace,
                               fetch=_never_fetch, constituents=CONS, on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url is None


async def test_fetch_failure_degrades_to_no_attach():
    async def trace(ct, sym, on_date):
        return ["https://cninfo.com.cn/d1"]

    async def fetch(url):
        raise RuntimeError("network down")

    out = await enrich_primary([_src([_q("中芯国际净利润3.6亿元")])],
                               classify=_classify_none, trace=trace, fetch=fetch,
                               constituents=CONS, on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url is None


async def test_deepseek_fallback_used_when_rules_inconclusive():
    async def classify(text):
        return ClaimRef(claim_type="earnings", symbol="688981")

    async def trace(ct, sym, on_date):
        return ["https://cninfo.com.cn/d1"]

    async def fetch(url):
        return "净利润3.6亿元"

    # No known company in text → rules return None → fallback resolves it.
    out = await enrich_primary([_src([_q("某半导体大厂净利润3.6亿元")])],
                               classify=classify, trace=trace, fetch=fetch,
                               constituents=CONS, on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url == "https://cninfo.com.cn/d1"


async def test_trace_none_does_not_attach():
    """trace returning None → no attach; fetch must never be reached."""
    async def trace(ct, sym, on_date):
        return []  # no disclosure found

    out = await enrich_primary([_src([_q("中芯国际净利润3.6亿元")])],
                               classify=_classify_none, trace=trace,
                               fetch=_never_fetch, constituents=CONS,
                               on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url is None


async def test_non_cninfo_venue_does_not_attach():
    """shareholding_reduction routes to 'exchange', not 'cninfo' → venue guard
    fires before trace; trace must never be called."""
    out = await enrich_primary([_src([_q("中芯国际减持1000万股")])],
                               classify=_classify_none, trace=_never_trace,
                               fetch=_never_fetch, constituents=CONS,
                               on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url is None


async def test_one_bad_quote_does_not_abort_rest():
    async def trace(ct, sym, on_date):
        return ["https://cninfo.com.cn/d1"]

    good = _q("中芯国际净利润3.6亿元")
    bad = _q("中芯国际净利润3.6亿元")
    src = _src([bad, good])

    calls = {"n": 0}

    async def flaky_fetch(url):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return "净利润3.6亿元"

    out = await enrich_primary([src], classify=_classify_none, trace=trace,
                               fetch=flaky_fetch, constituents=CONS, on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url is None        # first fetch failed
    assert out[0].quotes[1].attached_primary_url == "https://cninfo.com.cn/d1"


async def test_resolve_picks_second_candidate_when_first_mismatches():
    async def trace(ct, sym, on_date):
        return ["https://cninfo.com.cn/d1", "https://cninfo.com.cn/d2"]

    async def fetch(url):
        return "本期净利润为5亿元" if url.endswith("d1") else "本期净利润为3.6亿元"

    out = await enrich_primary([_src([_q("中芯国际净利润3.6亿元")])],
                               classify=_classify_none, trace=trace, fetch=fetch,
                               constituents=CONS, on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url == "https://cninfo.com.cn/d2"


async def test_resolve_none_when_no_candidate_matches():
    async def trace(ct, sym, on_date):
        return ["https://cninfo.com.cn/d1", "https://cninfo.com.cn/d2"]

    async def fetch(url):
        return "本期净利润为9亿元"  # neither carries 3.6亿

    out = await enrich_primary([_src([_q("中芯国际净利润3.6亿元")])],
                               classify=_classify_none, trace=trace, fetch=fetch,
                               constituents=CONS, on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url is None


async def test_resolve_empty_candidate_list_no_attach():
    async def trace(ct, sym, on_date):
        return []

    out = await enrich_primary([_src([_q("中芯国际净利润3.6亿元")])],
                               classify=_classify_none, trace=trace,
                               fetch=_never_fetch, constituents=CONS, on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url is None


async def test_trace_failure_is_reported():
    """A cninfo trace outage must surface, not vanish behind a bare no-attach."""
    failures = []

    async def trace(ct, sym, on_date):
        raise RuntimeError("cninfo 503")

    async def on_failure(stage, locus, detail):
        failures.append((stage, locus, detail))

    await enrich_primary([_src([_q("中芯国际净利润3.6亿元")])],
                         classify=_classify_none, trace=trace, fetch=_never_fetch,
                         constituents=CONS, on_date=NOW.date(), on_failure=on_failure)
    assert len(failures) == 1, f"expected 1 reported failure, got {failures}"
    stage, locus, detail = failures[0]
    assert stage == "enrich_trace"
    assert locus == "earnings:688981"
    assert "cninfo 503" in detail


async def test_disclosure_fetch_failure_is_reported():
    """Each failed disclosure candidate is reported, and the pass still degrades."""
    failures = []

    async def trace(ct, sym, on_date):
        return ["https://cninfo.com.cn/d1"]

    async def fetch(url):
        raise RuntimeError("pdf 500")

    async def on_failure(stage, locus, detail):
        failures.append((stage, locus, detail))

    out = await enrich_primary([_src([_q("中芯国际净利润3.6亿元")])],
                               classify=_classify_none, trace=trace, fetch=fetch,
                               constituents=CONS, on_date=NOW.date(),
                               on_failure=on_failure)
    assert out[0].quotes[0].attached_primary_url is None
    assert len(failures) == 1, f"expected 1 reported failure, got {failures}"
    stage, locus, detail = failures[0]
    assert stage == "enrich_fetch"
    assert locus == "https://cninfo.com.cn/d1"
    assert "pdf 500" in detail


async def test_resolve_skips_candidate_whose_fetch_errors():
    async def trace(ct, sym, on_date):
        return ["https://cninfo.com.cn/d1", "https://cninfo.com.cn/d2"]

    async def fetch(url):
        if url.endswith("d1"):
            raise RuntimeError("pdf 500")
        return "本期净利润为3.6亿元"

    out = await enrich_primary([_src([_q("中芯国际净利润3.6亿元")])],
                               classify=_classify_none, trace=trace, fetch=fetch,
                               constituents=CONS, on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url == "https://cninfo.com.cn/d2"
