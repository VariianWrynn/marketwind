from marketwind.scout.amount import NormalizedAmount, parse_amount, amount_matches


def test_parse_money_magnitudes():
    assert NormalizedAmount("value", 3.6e8) in parse_amount("净利润3.6亿")
    assert NormalizedAmount("value", 3.6e8) in parse_amount("利润3.60亿元")
    assert NormalizedAmount("value", 3.6e8) in parse_amount("利润360,000,000元")
    assert NormalizedAmount("value", 1.2e12) in parse_amount("规模1.2万亿")
    assert NormalizedAmount("value", 5.0e4) in parse_amount("募资5万元")


def test_parse_percent():
    assert NormalizedAmount("percent", 7.0) in parse_amount("持股7.00%")
    assert NormalizedAmount("percent", 0.9) in parse_amount("下降0.9个百分点")


def test_match_across_unit_divergence():
    assert amount_matches("净利3.6亿", "本期净利润为360,000,000元") is True


def test_match_within_rounding_tolerance():
    # 3.6亿 vs 3.58亿 — within 2% default tolerance
    assert amount_matches("净利3.6亿", "净利润3.58亿元") is True


def test_wrong_number_does_not_match():
    # THE GUARD: a same-topic disclosure with a different figure must NOT match
    assert amount_matches("净利3.6亿", "净利润5亿元") is False


def test_no_parseable_amount_does_not_match():
    assert amount_matches("公司发布公告", "本期净利润为360,000,000元") is False
