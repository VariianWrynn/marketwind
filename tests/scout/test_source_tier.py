import pytest
from marketwind.scout.source_tier import (
    SourceTier, classify, clears_law3, is_officially_verified,
)

@pytest.mark.parametrize("domain, tier", [
    ("cninfo.com.cn", SourceTier.OFFICIAL),
    ("csrc.gov.cn", SourceTier.OFFICIAL),
    ("cs.com.cn", SourceTier.DESIGNATED),
    ("cnstock.com", SourceTier.DESIGNATED),
    ("finance.sina.com.cn", SourceTier.TRUSTED),
    ("caixin.com", SourceTier.TRUSTED),
    ("finance.eastmoney.com", SourceTier.SECONDARY),
    ("jiemian.com", SourceTier.SECONDARY),
])
def test_classify_known_domains(domain, tier):
    assert classify(domain) == tier

def test_subdomain_inherits_root_tier():
    assert classify("news.cs.com.cn") == SourceTier.DESIGNATED

def test_denylist_beats_trusted_suffix():
    assert classify("money.finance.sina.com.cn") == SourceTier.EXCLUDED
    assert classify("guba.eastmoney.com") == SourceTier.EXCLUDED

def test_unknown_domain_default_denies():
    assert classify("randomblog.example") == SourceTier.EXCLUDED

def test_trusted_clears_gate_but_not_badge():
    assert clears_law3("finance.sina.com.cn", False, None) is True
    assert is_officially_verified("finance.sina.com.cn", False, None) is False

def test_designated_clears_both():
    assert clears_law3("cs.com.cn", False, None) is True
    assert is_officially_verified("cs.com.cn", False, None) is True

def test_excluded_clears_neither_without_primary():
    assert clears_law3("randomblog.example", False, None) is False
    assert is_officially_verified("randomblog.example", False, None) is False

def test_attached_or_isprimary_clears_both():
    assert clears_law3("randomblog.example", False, "http://cninfo.com.cn/x") is True
    assert is_officially_verified("randomblog.example", True, None) is True
