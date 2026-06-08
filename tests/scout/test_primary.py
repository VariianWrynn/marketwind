import pytest
from datetime import date

from marketwind.scout.primary import primary_venue_for, cninfo_category_for, select_disclosure_url, disclosure_window


@pytest.mark.parametrize("claim_type,venue", [
    ("ipo", "cninfo"),
    ("fundraising", "cninfo"),
    ("shareholding_reduction", "exchange"),
    ("earnings", "cninfo"),
    ("policy", "regulator"),
])
def test_claim_type_routes_to_venue(claim_type, venue):
    assert primary_venue_for(claim_type) == venue


def test_unknown_claim_type_returns_none():
    assert primary_venue_for("rumor") is None


# --- cninfo_category_for ---

@pytest.mark.parametrize("claim_type,expected", [
    ("earnings", "业绩预告"),
    ("ipo", "首发"),
    ("fundraising", "增发"),
    ("shareholding_reduction", ""),
    ("anything", ""),
])
def test_cninfo_category_for(claim_type, expected):
    assert cninfo_category_for(claim_type) == expected


# --- select_disclosure_url ---

def test_select_disclosure_url_returns_first():
    records = [{"公告链接": "http://a"}, {"公告链接": "http://b"}]
    assert select_disclosure_url(records) == "http://a"


def test_select_disclosure_url_skips_empty_and_returns_next():
    records = [{"公告链接": ""}, {"公告链接": "http://b"}]
    assert select_disclosure_url(records) == "http://b"


def test_select_disclosure_url_empty_list():
    assert select_disclosure_url([]) is None


def test_select_disclosure_url_missing_key_treated_as_empty():
    records = [{"other_key": "x"}, {"公告链接": "http://c"}]
    assert select_disclosure_url(records) == "http://c"


# --- disclosure_window ---

def test_disclosure_window_90_day_lookback():
    result = disclosure_window(date(2024, 6, 30))
    assert result == ("20240401", "20240630")
