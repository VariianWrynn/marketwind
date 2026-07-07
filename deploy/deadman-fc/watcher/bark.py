from __future__ import annotations
import logging
import urllib.request
from urllib.parse import quote

from watcher.config import Config

logger = logging.getLogger(__name__)


def _http_post(url: str) -> None:  # pragma: no cover
    urllib.request.urlopen(url, timeout=5)


def send_bark(cfg: Config, title: str, body: str, *, post=_http_post) -> bool:
    url = f"{cfg.bark_base_url.rstrip('/')}/{cfg.bark_key}/{quote(title)}/{quote(body)}"
    try:
        post(url)
        return True
    except Exception as exc:
        logger.warning("bark push failed: %s", exc)
        return False
