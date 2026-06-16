from marketwind.writer.domain import PooledQuote, PooledSource
from marketwind.writer.select import eligible_pool


def _q(qid, quant, primary_url):
    return PooledQuote(qid, "x", quant, "data" if quant else "factual",
                       primary_url, 0, 1)


def _by_id(pool):
    return {s.source_id: [q.quote_id for q in s.quotes] for s in pool}


def test_eligible_pool_drops_unbacked_quant_keeps_rest():
    sA = PooledSource("sA", "http://a", "a.com", False, [
        _q("qA1", True, "http://cninfo/x"),   # backed quant  -> keep
        _q("qA2", True, None),                 # unbacked quant -> DROP
        _q("qA3", False, None),                # non-quant      -> keep
    ], "raw")
    sB = PooledSource("sB", "http://b", "b.com", True, [
        _q("qB1", True, None),                 # unbacked quant but source is_primary -> keep
    ], "raw")
    sC = PooledSource("sC", "http://c", "c.com", False, [
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
