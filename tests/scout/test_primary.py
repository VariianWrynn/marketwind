import pytest
from datetime import date

from marketwind.scout.primary import primary_venue_for, select_disclosure_urls, disclosure_window


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


# --- select_disclosure_urls ---

def test_select_disclosure_urls_returns_all_in_order():
    records = [{"公告链接": "http://a"}, {"公告链接": "http://b"}]
    assert select_disclosure_urls(records) == ["http://a", "http://b"]


def test_select_disclosure_urls_skips_empty_and_missing_keys():
    records = [{"公告链接": ""}, {"other": "x"}, {"公告链接": "http://c"}]
    assert select_disclosure_urls(records) == ["http://c"]


def test_select_disclosure_urls_empty_list():
    assert select_disclosure_urls([]) == []


# --- disclosure_window ---

def test_disclosure_window_90_day_lookback():
    result = disclosure_window(date(2024, 6, 30))
    assert result == ("20240401", "20240630")
