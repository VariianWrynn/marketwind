"""Pure value objects for the Scout quote pool. No I/O, no DB."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Quote:
    text: str
    span_start: int
    span_end: int
    context_before: str | None
    context_after: str | None
    is_quantitative: bool
    quote_type: str = "factual"  # factual | quoted_inference | data
    attached_primary_url: str | None = None


@dataclass
class Source:
    url: str
    domain: str
    publish_ts: datetime  # tz-aware
    raw_content: str  # frozen cleaned main-content text; spans index into this
    byline: str | None = None
    is_primary: bool = False
    quotes: list[Quote] = field(default_factory=list)


@dataclass(frozen=True)
class FloorResult:
    grounded_quotes: int
    primary_traced_quotes: int
    independent_outlets: int
    passed: bool


@dataclass
class ScoutResult:
    sources: list[Source]
    floor: FloorResult
