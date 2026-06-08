# marketwind/scout/amount.py
"""Extract canonical money/percent values from Chinese financial text and
compare a quote's figures against a disclosure's within relative tolerance.

numbers.py only DETECTS a quantity; this module EXTRACTS the value, so the
primary-tracing match-guard can confirm a disclosure actually carries the
quote's number (defends Iron Law 3). Money is normalized to base 元; share
counts (股/手) are intentionally NOT parsed — those are exchange-venue claims,
out of scope for the cninfo path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# number (commas/decimals) + a money magnitude. Longest tokens first so 万亿 /
# 亿元 / 万元 win over 亿 / 万 / 元.
_AMOUNT = re.compile(r"(\d[\d,]*\.?\d*)\s*(万亿|亿元|万元|亿|万|元)")
_PERCENT = re.compile(r"(\d[\d,]*\.?\d*)\s*(%|％|个百分点)")
_MULT = {"万亿": 1e12, "亿元": 1e8, "万元": 1e4, "亿": 1e8, "万": 1e4, "元": 1.0}


@dataclass(frozen=True)
class NormalizedAmount:
    kind: str  # "value" | "percent"
    value: float


def parse_amount(text: str) -> list[NormalizedAmount]:
    out: list[NormalizedAmount] = []
    for m in _AMOUNT.finditer(text):
        num = float(m.group(1).replace(",", ""))
        out.append(NormalizedAmount("value", num * _MULT[m.group(2)]))
    for m in _PERCENT.finditer(text):
        num = float(m.group(1).replace(",", ""))
        out.append(NormalizedAmount("percent", num))
    return out


def _close(a: float, b: float, rel_tol: float) -> bool:
    if a == b:
        return True
    return abs(a - b) <= rel_tol * max(abs(a), abs(b))


def amount_matches(quote_text: str, disclosure_text: str, *, rel_tol: float = 0.02) -> bool:
    """True iff some money/percent figure in the quote appears in the disclosure
    within rel_tol (handling unit/rounding divergence). Same kind must match
    same kind (a value never matches a percent)."""
    q_amounts = parse_amount(quote_text)
    d_amounts = parse_amount(disclosure_text)
    for qa in q_amounts:
        for da in d_amounts:
            if qa.kind == da.kind and _close(qa.value, da.value, rel_tol):
                return True
    return False
