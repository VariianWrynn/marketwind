"""Detect whether a Chinese sentence carries a financial quantity.

Conservative: a sentence is quantitative if it contains a digit adjacent to a
financial unit / percentage / magnitude word, or a 涨/跌 + 数字 movement.
"""

from __future__ import annotations

import re

# digit (incl. decimals/commas) followed by a financial unit or magnitude
_NUM_UNIT = re.compile(
    r"\d[\d,\.]*\s*"
    r"(%|％|个百分点|万亿|亿元?|万元?|亿|万|元|股|手|倍|个交易日|bp|BP)"
)
# 涨/跌/增长/下降 + (超)? + 数字
_MOVE = re.compile(r"(涨|跌|增长|下降|下滑|上涨|下跌)\s*超?\s*\d")


def is_quantitative(text: str) -> bool:
    return bool(_NUM_UNIT.search(text) or _MOVE.search(text))
