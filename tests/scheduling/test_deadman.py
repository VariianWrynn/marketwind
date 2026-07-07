from marketwind.scheduling.deadman import check_in


def test_pings_exact_url_when_set():
    calls = []
    check_in("http://hc.example/ping/abc", post=calls.append)
    assert calls == ["http://hc.example/ping/abc"]


def test_no_op_when_url_empty():
    calls = []
    check_in("", post=calls.append)
    check_in(None, post=calls.append)
    assert calls == []


def test_swallows_post_error():
    def boom(url):
        raise RuntimeError("network down")
    # Must return normally — a ping failure must never propagate into the caller.
    check_in("http://hc.example/ping/abc", post=boom)
