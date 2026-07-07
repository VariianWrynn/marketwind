from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    oss_bucket: str
    oss_endpoint: str
    jobs: tuple[str, ...]
    period_seconds: int
    grace_seconds: int
    bark_base_url: str
    bark_key: str


def load(env: Mapping[str, str] | None = None) -> Config:
    import os
    if env is None:
        env = os.environ
    jobs = tuple(j.strip() for j in env.get("JOBS", "premarket,main").split(",") if j.strip())
    return Config(
        oss_bucket=env.get("OSS_BUCKET", ""),
        oss_endpoint=env.get("OSS_ENDPOINT", ""),
        jobs=jobs,
        period_seconds=int(env.get("PERIOD_SECONDS", "86400")),
        grace_seconds=int(env.get("GRACE_SECONDS", "10800")),
        bark_base_url=env.get("BARK_BASE_URL", ""),
        bark_key=env.get("BARK_KEY", ""),
    )
