import pytest

from marketwind.scout.numbers import is_quantitative

QUANT = [
    "科创50指数收盘涨0.36%",
    "成交额达3.24万亿元",
    "公司净利330.12亿元",
    "募资295亿元",
    "同比增长44.8%",
    "减持630万股",
    "连续48个交易日",
    "跌超3%",
]
NON_QUANT = [
    "公司发布重大资产重组公告",
    "市场情绪整体偏谨慎",
    "证监会受理其上市申请",
]


@pytest.mark.parametrize("s", QUANT)
def test_detects_quantitative(s):
    assert is_quantitative(s) is True


@pytest.mark.parametrize("s", NON_QUANT)
def test_rejects_non_quantitative(s):
    assert is_quantitative(s) is False
