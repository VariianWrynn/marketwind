"""RunOutcome value object and seven canonical ledger-status constants (P2b)."""
from __future__ import annotations

from dataclasses import dataclass

PUBLISHED        = "published"
SKIPPED_CALENDAR = "skipped_calendar"
SKIPPED_STALE    = "skipped_stale"
SUB_FLOOR        = "sub_floor"
VERIFY_FAIL      = "verify_fail"
MISSED           = "missed"
FAILED_INFRA     = "failed_infra"


@dataclass(frozen=True)
class RunOutcome:
    status: str
    detail: str | None = None
