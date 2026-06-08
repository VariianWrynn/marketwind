"""Pure scheduling math: DST-aware anchors + per-job freshness."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from marketwind.scout.timeparse import CN_TZ


def anchor_utc(d: date, hour: int, minute: int, tz_name: str) -> datetime:
    """The UTC instant of `hour:minute` local time on date `d` in `tz_name`.

    zoneinfo resolves the offset for that calendar date, so DST is handled
    automatically (18:00 ET is 22:00 UTC in summer, 23:00 UTC in winter).
    """
    local = datetime(d.year, d.month, d.day, hour, minute, tzinfo=ZoneInfo(tz_name))
    return local.astimezone(timezone.utc)
