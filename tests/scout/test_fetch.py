import pytest

from marketwind.scout.fetch import FetchOutcome, classify_ceiling_hit, PermanentFetchError


def test_ceiling_with_content_is_transient():
    out = classify_ceiling_hit(content_loaded=True)
    assert out is FetchOutcome.TRANSIENT


def test_ceiling_without_content_is_permanent():
    out = classify_ceiling_hit(content_loaded=False)
    assert out is FetchOutcome.PERMANENT


def test_permanent_status_codes():
    from marketwind.scout.fetch import is_permanent_status
    assert is_permanent_status(404) is True
    assert is_permanent_status(403) is True
    assert is_permanent_status(500) is False  # 5xx is transient
    assert is_permanent_status(503) is False
