from marketwind.scout.claim_extract import ClaimRef, extract_claim

CONS = {"中芯国际": "688981", "澜起科技": "688008"}


def test_earnings_keyword_and_company():
    ref = extract_claim("中芯国际净利润3.6亿元", CONS)
    assert ref == ClaimRef(claim_type="earnings", symbol="688981")


def test_fundraising_keyword():
    assert extract_claim("澜起科技募资5亿元", CONS).claim_type == "fundraising"


def test_shareholding_reduction_keyword():
    assert extract_claim("中芯国际遭股东减持100万股", CONS).claim_type == "shareholding_reduction"


def test_no_known_company_returns_none():
    assert extract_claim("某未知公司净利润3.6亿元", CONS) is None


def test_no_claim_keyword_returns_none():
    assert extract_claim("中芯国际发布了一则公告", CONS) is None
