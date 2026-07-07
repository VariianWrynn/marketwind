from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from watcher.config import Config, load
from watcher.state import ObjectStore, put_ping

logger = logging.getLogger(__name__)


def process_ping(store: ObjectStore, cfg: Config, job: str | None, now: datetime) -> int:
    if job not in cfg.jobs:
        return 400
    try:
        put_ping(store, job, now)
    except Exception:
        # Spec §5.1.5: fail loud on a failed OSS write. Returning 500 (never 200)
        # means the ping did not persist and the deadline stays un-refreshed, so
        # the job trends toward a page — the safe direction, never a false silence.
        logger.exception("ping: OSS write failed for job %s", job)
        return 500
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
    body = {200: "ok", 400: "unknown job", 500: "state write failed"}.get(code, "error")
    return {
        "statusCode": code,
        "body": body,
    }
