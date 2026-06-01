"""P0 success criterion: /health returns 200 with both deps reachable.

Runs against the docker-compose stack. The app port is taken from
APP_BASE_URL (default http://localhost:8000).
"""

import os

import httpx

BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000")


def test_health_reports_both_dependencies_up():
    resp = httpx.get(f"{BASE_URL}/health", timeout=10)
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "postgres": True, "redis": True}
