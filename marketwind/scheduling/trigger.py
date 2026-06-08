"""Unified Trigger seam (CLAUDE.md §6). P2a implements cron ONLY — no registry.

Future implementers (NOT built here): IntervalTrigger (keyword polling),
EventTrigger (Redis Streams -> ConciergeBot, P3). They will satisfy the same
Protocol and register without touching run_once.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from apscheduler.triggers.cron import CronTrigger


class Trigger(Protocol):
    job_id: str

    def to_apscheduler(self): ...


@dataclass(frozen=True)
class CronJob:
    job_id: str
    hour: int
    minute: int
    tz: str

    def to_apscheduler(self) -> CronTrigger:
        return CronTrigger(hour=self.hour, minute=self.minute, timezone=self.tz)
