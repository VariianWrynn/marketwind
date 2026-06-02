from datetime import datetime

from marketwind.scout.domain import Quote, Source
from marketwind.scout.runner import evaluate_floor
from marketwind.scout.timeparse import CN_TZ


def _src(url, domain, n_quotes, primary_url=None, is_primary=False):
    quotes = []
    for i in range(n_quotes):
        quotes.append(
            Quote(
                text=f"句子{i}。", span_start=i, span_end=i + 1,
                context_before=None, context_after=None,
                is_quantitative=(i == 0),
                quote_type="factual",
                attached_primary_url=primary_url if i == 0 else None,
            )
        )
    return Source(
        url=url, domain=domain,
        publish_ts=datetime(2026, 5, 29, 15, 0, tzinfo=CN_TZ),
        raw_content="x" * (n_quotes + 1), is_primary=is_primary, quotes=quotes,
    )


def test_floor_passes_with_8_quotes_1_primary_2_outlets():
    sources = [
        _src("https://m.cls.cn/a/1", "m.cls.cn", 5, primary_url="https://cninfo.com.cn/x"),
        _src("https://finance.sina.com.cn/y", "finance.sina.com.cn", 3),
    ]
    floor = evaluate_floor(sources)
    assert floor.grounded_quotes == 8
    assert floor.primary_traced_quotes == 1
    assert floor.independent_outlets == 2
    assert floor.passed is True


def test_sub_floor_5_quotes_1_outlet_fails():
    # 5 quotes, single outlet, no primary trace → must NOT pass.
    sources = [_src("https://m.cls.cn/a/1", "m.cls.cn", 5)]
    floor = evaluate_floor(sources)
    assert floor.grounded_quotes == 5
    assert floor.primary_traced_quotes == 0
    assert floor.independent_outlets == 1
    assert floor.passed is False


def test_floor_fails_when_no_primary_even_if_counts_ok():
    sources = [
        _src("https://m.cls.cn/a/1", "m.cls.cn", 5),
        _src("https://finance.sina.com.cn/y", "finance.sina.com.cn", 4),
    ]
    floor = evaluate_floor(sources)
    assert floor.grounded_quotes == 9
    assert floor.independent_outlets == 2
    assert floor.primary_traced_quotes == 0
    assert floor.passed is False  # conjunctive: zero primary fails the whole gate


def test_empty_source_does_not_inflate_outlet_count():
    # A fetched-but-empty source (0 quotes) is not a corroborating outlet.
    sources = [
        _src("https://m.cls.cn/a/1", "m.cls.cn", 5, primary_url="https://cninfo.com.cn/x"),
        _src("https://finance.sina.com.cn/y", "finance.sina.com.cn", 0),
    ]
    floor = evaluate_floor(sources)
    assert floor.grounded_quotes == 5
    assert floor.independent_outlets == 1, "empty source must not count as an outlet"
    assert floor.passed is False  # only one real outlet, under the floor


# --- Explicit per-condition boundary coverage (8/1/2 conjunctive gate) ---


def test_floor_passes_at_exact_minimums():
    # Exactly 8 grounded / 1 primary / 2 outlets — the lowest passing pool.
    sources = [
        _src("https://m.cls.cn/a/1", "m.cls.cn", 4, primary_url="https://cninfo.com.cn/x"),
        _src("https://finance.sina.com.cn/y", "finance.sina.com.cn", 4),
    ]
    floor = evaluate_floor(sources)
    assert floor.grounded_quotes == 8
    assert floor.primary_traced_quotes == 1
    assert floor.independent_outlets == 2
    assert floor.passed is True


def test_floor_fails_one_quote_under_grounded_minimum():
    # 7 grounded (< 8) with primary + 2 outlets otherwise satisfied → fail on count.
    sources = [
        _src("https://m.cls.cn/a/1", "m.cls.cn", 4, primary_url="https://cninfo.com.cn/x"),
        _src("https://finance.sina.com.cn/y", "finance.sina.com.cn", 3),
    ]
    floor = evaluate_floor(sources)
    assert floor.grounded_quotes == 7
    assert floor.primary_traced_quotes == 1
    assert floor.independent_outlets == 2
    assert floor.passed is False  # grounded quotes below the floor


def test_floor_fails_single_outlet_even_when_quotes_and_primary_ok():
    # 8 grounded + 1 primary, but a single outlet → fail on independence alone.
    sources = [
        _src("https://m.cls.cn/a/1", "m.cls.cn", 8, primary_url="https://cninfo.com.cn/x"),
    ]
    floor = evaluate_floor(sources)
    assert floor.grounded_quotes == 8
    assert floor.primary_traced_quotes == 1
    assert floor.independent_outlets == 1
    assert floor.passed is False  # one outlet is not corroboration


def test_same_domain_sources_count_as_one_outlet():
    # Two pages from the same outlet are one independent source, not two.
    sources = [
        _src("https://m.cls.cn/a/1", "m.cls.cn", 4, primary_url="https://cninfo.com.cn/x"),
        _src("https://m.cls.cn/a/2", "m.cls.cn", 4),
    ]
    floor = evaluate_floor(sources)
    assert floor.grounded_quotes == 8
    assert floor.primary_traced_quotes == 1
    assert floor.independent_outlets == 1, "same domain must not double-count"
    assert floor.passed is False


def test_empty_pool_fails_closed():
    # No sources at all → every metric zero, gate fails closed.
    floor = evaluate_floor([])
    assert floor.grounded_quotes == 0
    assert floor.primary_traced_quotes == 0
    assert floor.independent_outlets == 0
    assert floor.passed is False
