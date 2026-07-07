from __future__ import annotations

import logging
import urllib.request
from collections.abc import Callable

logger = logging.getLogger(__name__)


def _http_post(url: str) -> None:  # pragma: no cover
    urllib.request.urlopen(url, timeout=5)


def check_in(url: str | None, *, post: Callable[[str], None] = _http_post) -> None:
    if not url:
        return
    try:
        post(url)
    except Exception:
        logger.warning("deadman check_in failed for %r — ping was NOT delivered", url)
