from marketwind.scout.market import is_primary_metric


def test_index_aggregates_are_primary():
    assert is_primary_metric("index_level") is True
    assert is_primary_metric("turnover") is True
    assert is_primary_metric("pct_change") is True


def test_company_financials_are_not_primary_via_akshare():
    assert is_primary_metric("net_profit") is False
    assert is_primary_metric("revenue") is False
    assert is_primary_metric("shareholding_reduction") is False
