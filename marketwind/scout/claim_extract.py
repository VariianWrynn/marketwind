"""Rules-first claim classifier: map a quote to (claim_type, symbol) using a
closed-set constituent match + keyword table. Returns None when inconclusive
(caller falls back to the DeepSeek classifier). This only picks WHERE to look
for a primary — never asserts what is true (Iron Law 4 safe)."""
from __future__ import annotations

from dataclasses import dataclass

# Most specific first; first hit wins.
_CLAIM_KEYWORDS: list[tuple[str, str]] = [
    ("减持", "shareholding_reduction"),
    ("募资", "fundraising"),
    ("募集", "fundraising"),
    ("IPO", "fundraising"),
    ("净利", "earnings"),
    ("利润", "earnings"),
    ("营收", "earnings"),
    ("业绩", "earnings"),
    ("政策", "policy"),
    ("部委", "policy"),
]


@dataclass(frozen=True)
class ClaimRef:
    claim_type: str
    symbol: str


def _match_company(text: str, constituents: dict[str, str]) -> str | None:
    # Longest name first so a shorter name that is a prefix of another cannot
    # steal the match.
    for name in sorted(constituents, key=len, reverse=True):
        if name in text:
            return constituents[name]
    return None


def _match_claim_type(text: str) -> str | None:
    for keyword, claim_type in _CLAIM_KEYWORDS:
        if keyword in text:
            return claim_type
    return None


def extract_claim(text: str, constituents: dict[str, str]) -> ClaimRef | None:
    symbol = _match_company(text, constituents)
    claim_type = _match_claim_type(text)
    if symbol is None or claim_type is None:
        return None
    return ClaimRef(claim_type=claim_type, symbol=symbol)
