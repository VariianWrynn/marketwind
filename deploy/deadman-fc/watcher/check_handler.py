import logging
from datetime import datetime, timedelta, timezone

from watcher.bark import send_bark
from watcher.config import load
from watcher.state import read_state, mark_alerted

logger = logging.getLogger(__name__)


def run_check(store, cfg, now, *, bark=send_bark) -> list[str]:
    paged = []
    for job in cfg.jobs:
        try:
            st = read_state(store, job)
            if st is None:                      # not armed
                continue
            deadline = st.last_ping + timedelta(seconds=cfg.period_seconds + cfg.grace_seconds)
            if now <= deadline:                 # healthy
                continue
            if st.alerted:                      # already paged this silence
                continue
            title = f"MarketWind watchdog: {job} missed check-in"
            body = (f"No '{job}' check-in since {st.last_ping:%Y-%m-%d %H:%M UTC}. "
                    f"The morning report may not have been delivered — check the node.")
            if bark(cfg, title, body):
                mark_alerted(store, job)
                paged.append(job)
        except Exception:
            logger.exception("check failed for job %s", job)
            continue
    return paged


def handler(event, context):  # pragma: no cover
    from watcher.oss_store import OssObjectStore
    cfg = load()
    store = OssObjectStore(cfg.oss_endpoint, cfg.oss_bucket, context.credentials)
    paged = run_check(store, cfg, datetime.now(timezone.utc))
    return {"paged": paged}
