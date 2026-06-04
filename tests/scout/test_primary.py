import pytest

from marketwind.scout.primary import primary_venue_for


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
