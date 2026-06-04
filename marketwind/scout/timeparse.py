"""Parse Chinese / relative publish-time strings to tz-aware datetimes.

Year-boundary rule (spec §6): a bare 月日 with no year resolves to the most
recent occurrence at or before ingest time; relative terms resolve against
ingested_at in its tz. This gates I9, so a wrong year silently drops sources.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

CN_TZ = timezone(timedelta(hours=8))  # Asia/Shanghai, no DST

_FULL = re.compile(r"(?P<y>\d{4})年(?P<m>\d{1,2})月(?P<d>\d{1,2})日(?:\s*(?P<H>\d{1,2}):(?P<M>\d{2}))?")
_MD = re.compile(r"(?P<m>\d{1,2})月(?P<d>\d{1,2})日(?:\s*(?P<H>\d{1,2}):(?P<M>\d{2}))?")
_HOURS_AGO = re.compile(r"(?P<n>\d+)\s*小时前")
_MIN_AGO = re.compile(r"(?P<n>\d+)\s*分钟前")


def parse_publish_ts(raw: str, ingested_at: datetime) -> datetime:
    raw = raw.strip()

    m = _FULL.search(raw)
    if m:
        return datetime(
            int(m["y"]), int(m["m"]), int(m["d"]),
            int(m["H"] or 0), int(m["M"] or 0), tzinfo=CN_TZ,
        )

    m = _HOURS_AGO.search(raw)
    if m:
        return ingested_at - timedelta(hours=int(m["n"]))

    m = _MIN_AGO.search(raw)
    if m:
        return ingested_at - timedelta(minutes=int(m["n"]))

    if "今晨" in raw:
        return ingested_at.replace(hour=6, minute=0, second=0, microsecond=0)
    if "今天" in raw or "今日" in raw:
        return ingested_at.replace(hour=0, minute=0, second=0, microsecond=0)

    m = _MD.search(raw)
    if m:
        candidate = datetime(
            ingested_at.year, int(m["m"]), int(m["d"]),
            int(m["H"] or 0), int(m["M"] or 0), tzinfo=CN_TZ,
        )
        if candidate > ingested_at:  # future → most recent occurrence is last year
            candidate = candidate.replace(year=ingested_at.year - 1)
        return candidate

    raise ValueError(f"unparseable publish_ts: {raw!r}")
