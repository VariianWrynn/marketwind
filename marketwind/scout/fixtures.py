"""Dry-run loaders: build Source/Quote records from saved artifacts, no network."""

from __future__ import annotations

from datetime import datetime

from marketwind.scout.clean import clean_main_content, extract_quotes
from marketwind.scout.domain import Source
from marketwind.scout.outlets import domain_of
from marketwind.scout.timeparse import parse_publish_ts


def source_from_html_fixture(
    html: str, *, url: str, publish_raw: str, ingested_at: datetime,
    is_primary: bool = False, byline: str | None = None,
) -> Source:
    raw_content = clean_main_content(html)
    quotes = extract_quotes(raw_content)
    return Source(
        url=url,
        domain=domain_of(url),
        publish_ts=parse_publish_ts(publish_raw, ingested_at),
        raw_content=raw_content,
        byline=byline,
        is_primary=is_primary,
        quotes=quotes,
    )
