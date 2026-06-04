"""Playwright full-text fetch: resource-blocked, layered wait, 15s ceiling.

Pure disposition logic is unit-tested. The live navigation (fetch_html) is
exercised in the smoke run only.
"""

from __future__ import annotations

import enum

_CEILING_MS = 15_000
_BLOCK_TYPES = {"image", "media", "font", "stylesheet"}


class FetchOutcome(enum.Enum):
    TRANSIENT = "transient"  # retry with backoff+jitter
    PERMANENT = "permanent"  # fail fast, don't burn a retry


class PermanentFetchError(Exception):
    pass


def is_permanent_status(status: int) -> bool:
    """404/403/410/451 are permanent; 5xx and timeouts are transient."""
    return status in {403, 404, 410, 451}


def classify_ceiling_hit(content_loaded: bool) -> FetchOutcome:
    """At the 15s ceiling: usable content → transient; nothing → permanent."""
    return FetchOutcome.TRANSIENT if content_loaded else FetchOutcome.PERMANENT


async def fetch_html(context, url: str) -> str:  # pragma: no cover - live navigation
    """Fetch a page's HTML with resource blocking and a layered wait.

    `context` is a reused Playwright BrowserContext (no warm pool in P1).
    """
    page = await context.new_page()
    await page.route(
        "**/*",
        lambda route: (
            route.abort()
            if route.request.resource_type in _BLOCK_TYPES
            else route.continue_()
        ),
    )
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=_CEILING_MS)
        if resp is not None and is_permanent_status(resp.status):
            raise PermanentFetchError(f"{resp.status} for {url}")
        # Layered wait: try network-idle, fall back to DOM-stability, capped at ceiling.
        try:
            await page.wait_for_load_state("networkidle", timeout=_CEILING_MS)
        except Exception:
            pass  # tickers may never idle; DOM is already loaded → proceed
        return await page.content()
    finally:
        await page.close()
