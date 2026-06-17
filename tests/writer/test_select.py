from marketwind.writer.domain import PooledQuote, PooledSource
from marketwind.writer.select import eligible_pool


def _q(qid, quant, primary_url):
    return PooledQuote(qid, "x", quant, "data" if quant else "factual",
                       primary_url, 0, 1)


def _by_id(pool):
    return {s.source_id: [q.quote_id for q in s.quotes] for s in pool}


def test_eligible_pool_drops_unbacked_quant_keeps_rest():
    # Use SECONDARY-tier domains (finance.eastmoney.com) so sources survive
    # the EXCLUDED filter but unbacked quant quotes still fail Law 3.
    sA = PooledSource("sA", "http://finance.eastmoney.com", "finance.eastmoney.com", False, [
        _q("qA1", True, "http://cninfo/x"),   # backed quant  -> keep
        _q("qA2", True, None),                 # unbacked quant -> DROP
        _q("qA3", False, None),                # non-quant      -> keep
    ], "raw")
    sB = PooledSource("sB", "http://finance.eastmoney.com/b", "finance.eastmoney.com", True, [
        _q("qB1", True, None),                 # unbacked quant but source is_primary -> keep
    ], "raw")
    sC = PooledSource("sC", "http://finance.eastmoney.com/c", "finance.eastmoney.com", False, [
        _q("qC1", True, None),                 # unbacked quant, only quote -> source DROPPED
    ], "raw")

    out = eligible_pool([sA, sB, sC])
    ids = _by_id(out)

    assert set(ids) == {"sA", "sB"}            # sC dropped entirely (no quotes left)
    assert ids["sA"] == ["qA1", "qA3"]         # qA2 (unbacked quant) removed
    assert ids["sB"] == ["qB1"]                # kept via source.is_primary
    # invariant: no surviving quant quote lacks a primary
    for s in out:
        for q in s.quotes:
            if q.is_quantitative:
                assert q.attached_primary_url or s.is_primary


def test_trusted_domain_quant_survives_without_attached_primary():
    pool = [PooledSource("S1", "https://finance.sina.com.cn/a", "finance.sina.com.cn",
                         False, [PooledQuote("Q1", "数字0.36%", True, "data", None, 0, 5)],
                         raw_content="x")]
    out = eligible_pool(pool)
    assert [q.quote_id for s in out for q in s.quotes] == ["Q1"]  # KEPT (new behavior)


def test_excluded_source_dropped_whole_even_if_nonquant():
    pool = [PooledSource("S2", "https://guba.eastmoney.com/a", "guba.eastmoney.com",
                         False, [PooledQuote("Q2", "情绪谨慎", False, "factual", None, 0, 4)],
                         raw_content="x")]
    assert eligible_pool(pool) == []  # whole source gone


def test_secondary_domain_quant_without_primary_still_dropped():
    pool = [PooledSource("S3", "https://finance.eastmoney.com/a", "finance.eastmoney.com",
                         False, [PooledQuote("Q3", "数字0.36%", True, "data", None, 0, 5),
                                 PooledQuote("Q4", "情绪谨慎", False, "factual", None, 5, 9)],
                         raw_content="x")]
    out = eligible_pool(pool)
    assert [q.quote_id for s in out for q in s.quotes] == ["Q4"]  # quant dropped, non-quant kept
