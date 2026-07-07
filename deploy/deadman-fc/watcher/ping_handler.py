from __future__ import annotations

import json
from datetime import datetime, timezone

from watcher.config import Config, load
from watcher.state import ObjectStore, put_ping


def process_ping(store: ObjectStore, cfg: Config, job: str | None, now: datetime) -> int:
    if job not in cfg.jobs:
        return 400
    put_ping(store, job, now)
    return 200


def handler(event, context):  # pragma: no cover
    # NOTE: the exact FC HTTP event shape for query params is unverified offline.
    # Best-effort: FC passes a bytes/str JSON blob; queryParameters holds URL params.
    if isinstance(event, (bytes, bytearray)):
        event = json.loads(event.decode())
    elif isinstance(event, str):
        event = json.loads(event)
    job = event.get("queryParameters", {}).get("job") if isinstance(event, dict) else None

    from watcher.oss_store import OssObjectStore  # noqa: PLC0415
    cfg = load()
    store = OssObjectStore(cfg.oss_endpoint, cfg.oss_bucket, context.credentials)
    code = process_ping(store, cfg, job, datetime.now(timezone.utc))
    return {
        "statusCode": code,
        "body": "ok" if code == 200 else "unknown job",
    }
