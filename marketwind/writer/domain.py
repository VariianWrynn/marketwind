"""Pure value objects for the Writer. No I/O, no DB, no LLM."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass


# ---- Input: the quote pool as loaded from Postgres (carries real DB UUIDs) ----

@dataclass(frozen=True)
class PooledQuote:
    quote_id: str          # real DB uuid (text form)
    text: str
    is_quantitative: bool
    quote_type: str        # factual | quoted_inference | data
    attached_primary_url: str | None
    span_start: int
    span_end: int


@dataclass(frozen=True)
class PooledSource:
    source_id: str         # real DB uuid (text form)
    url: str
    domain: str
    is_primary: bool
    quotes: list[PooledQuote]
    raw_content: str


# ---- Output: what the Writer (DeepSeek) emits, after schema validation ----

@dataclass(frozen=True)
class DraftClaim:
    local_id: str          # Writer-invented, e.g. "c-001"; mapped to a uuid on persist
    statement: str
    quote_ids: list[str]   # references PooledQuote.quote_id (real uuids); >= 1
    category: str = "quantitative"   # one of schema._VALID_CATEGORIES (e.g. derived_metric)
    methodology: str | None = None   # required when category == "derived_metric" (I12)
    time_window: str | None = None   # temporal scope for I10 (e.g. "2026-Q1", "2026-05-27")


@dataclass(frozen=True)
class DraftSentence:
    sentence: str          # text WITHOUT [n] markers (renderer adds them)
    claim_ids: list[str]   # references DraftClaim.local_id; factual >= 1, structural == 0
    source_ids: list[str]  # references PooledSource.source_id (real uuids)
    sentence_type: str     # factual | structural


@dataclass(frozen=True)
class WriterOutput:
    claims: list[DraftClaim]
    sentences: list[DraftSentence]


# ---- Render result ----

@dataclass(frozen=True)
class RenderedSentence:
    text: str              # final text WITH [n] markers appended (factual) or plain (structural)
    claim_ids: list[str]   # local claim ids carried through for persistence
    source_ids: list[str]
    sentence_type: str
    position: int


@dataclass(frozen=True)
class RenderedBrief:
    body: str                       # the joined ≤500-char brief
    sentences: list[RenderedSentence]   # kept sentences only (after over-length drop)
    footnotes: list[tuple[int, str]]    # (n, source_id) in assignment order


# ---- Deferred-persistence bundle returned by draft_report ----

@dataclass(frozen=True)
class DraftBundle:
    output: WriterOutput
    pool: list[PooledSource]
    body: str
    reference: str                          # the "—— 来源 ——" second-message text; "" if none
    commit: Callable[[], Awaitable[str]]   # zero-arg async thunk → report_id
