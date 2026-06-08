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


def freshness_ok(now: datetime, anchor: datetime, *,
                 tolerance_min: int, ceiling_cst: time) -> tuple[bool, str]:
    """(fresh, reason). Late if now is > tolerance_min past anchor; else stale if
    the CST wall-clock is past the absolute ceiling; else fresh."""
    late_by = (now - anchor).total_seconds() / 60.0
    if late_by > tolerance_min:
        return False, f"late: fired {late_by:.0f}min after anchor (tol {tolerance_min})"
    now_cst = now.astimezone(CN_TZ).timetz().replace(tzinfo=None)
    if now_cst > ceiling_cst:
        return False, f"past ceiling {ceiling_cst.strftime('%H:%M')} CST (now {now_cst.strftime('%H:%M')})"
    return True, "fresh"
