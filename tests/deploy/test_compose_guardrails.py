"""Structural guards on the compose files.

Only constraints that are NOT obvious from reading the YAML belong here — a test
that restates the file it just parsed is tautological (CLAUDE.md §4②). Each test
below pins something a later editor would plausibly and wrongly simplify away.

Every lookup goes through .get(...) so a missing key fails as an assertion, not a
KeyError — a KeyError fires identically for a good test and a broken one and so
proves nothing (CLAUDE.md §8.2).
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "docker-compose.yml"
PROD = ROOT / "deploy" / "report-node" / "docker-compose.prod.yml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_postgres_data_lives_on_a_named_volume():
    compose = _load(BASE)
    mounts = compose.get("services", {}).get("postgres", {}).get("volumes", []) or []
    assert any(str(m).startswith("pgdata:") for m in mounts), (
        "postgres must mount the named volume pgdata; on an anonymous volume a plain "
        "`docker compose down` destroys the database"
    )
    assert "pgdata" in (compose.get("volumes") or {}), (
        "pgdata must be declared in the top-level volumes: block"
    )


def test_app_healthcheck_probes_with_stdlib_python_not_curl():
    app = _load(BASE).get("services", {}).get("app", {})
    probe = app.get("healthcheck", {}).get("test", []) or []
    assert "python" in probe, (
        "the image is python:3.11-slim, which ships neither curl nor wget — a curl "
        "probe would mark app unhealthy forever, the exact false signal this guards"
    )


def test_migrate_service_sets_redis_url_even_though_it_never_uses_redis():
    services = _load(BASE).get("services", {})
    env = services.get("migrate", {}).get("environment", {}) or {}
    assert "REDIS_URL" in env, (
        "config.py declares redis_url with no default and instantiates Settings() at "
        "import time, and .env is not in the image - a migrate service given only "
        "DATABASE_URL dies in pydantic validation, never satisfies "
        "service_completed_successfully, and blocks app+scheduler from ever starting. "
        "This looks unnecessary. It is not. Do not remove it."
    )
