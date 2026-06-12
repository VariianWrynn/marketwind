"""Per-job anchor + tolerance resolution (P2b item A).

Later tasks in P2b will add dispatch_job and catch_up to this file.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from marketwind.scheduling.anchor import anchor_utc
from marketwind.scout.timeparse import CN_TZ


@dataclass(frozen=True)
class JobPlan:
    job_id: str
    anchor: datetime
    tolerance_min: int
    ceiling_cst: time
    trading_date: date


def resolve_job(
    job_id: str,
    now: datetime,
    *,
    premarket_tol_min: int,
    main_tol_min: int,
    ceiling_cst: time,
) -> JobPlan:
    """Return a JobPlan giving this job its own anchor, tolerance, and trading date.

    - "main"      → 07:00 Asia/Shanghai anchor, main_tol_min tolerance
    - "premarket" → 18:00 America/New_York anchor, premarket_tol_min tolerance
    - anything else → ValueError
    """
    trading_date: date = now.astimezone(CN_TZ).date()

    if job_id == "main":
        anchor = anchor_utc(trading_date, 7, 0, "Asia/Shanghai")
        tolerance_min = main_tol_min
    elif job_id == "premarket":
        anchor = anchor_utc(trading_date, 18, 0, "America/New_York")
        tolerance_min = premarket_tol_min
    else:
        raise ValueError(f"unknown job_id: {job_id!r}")

    return JobPlan(
        job_id=job_id,
        anchor=anchor,
        tolerance_min=tolerance_min,
        ceiling_cst=ceiling_cst,
        trading_date=trading_date,
    )
