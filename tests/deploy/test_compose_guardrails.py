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


def test_prod_binds_postgres_and_redis_to_loopback():
    services = _load(PROD).get("services", {})
    for name in ("postgres", "redis"):
        published = services.get(name, {}).get("ports", []) or []
        assert published, f"{name} must republish on loopback in the prod override"
        assert all(str(p).startswith("127.0.0.1:") for p in published), (
            f"{name} is published on all interfaces by the base file with guessable "
            f"credentials; the prod override must narrow it to loopback (SSH tunnel "
            f"is already the documented access pattern)"
        )


def test_scheduler_healthcheck_also_exercises_the_venv_interpreter():
    sched = _load(PROD).get("services", {}).get("scheduler", {})
    probe = " ".join(str(p) for p in (sched.get("healthcheck", {}).get("test", []) or []))
    assert "HERMES_BIN" in probe, (
        "the scheduler must continuously prove its delivery path; the deploying agent "
        "is the same hermes install the scheduler invokes, and it has host root"
    )
    assert "python" in probe, (
        "testing HERMES_BIN alone cannot see a dangling uv interpreter - the actual "
        "ADR-0001 failure mode. Do not simplify this to `test -x $HERMES_BIN`."
    )


def test_env_example_ships_compose_file_commented_and_correctly_ordered():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    hits = [ln for ln in lines if "COMPOSE_FILE=" in ln]
    assert hits, "COMPOSE_FILE must be present in .env.example for the node to uncomment"
    line = hits[0]
    assert line.lstrip().startswith("#"), (
        "must ship COMMENTED OUT - active it breaks the Windows dev box three ways "
        "(path separator, `make dev` launching the prod stack, ${OSS_BUCKET:?} "
        "hard-failing every compose command). DEPLOY.md makes uncommenting an explicit step."
    )
    assert line.split("COMPOSE_FILE=", 1)[1].strip() == (
        "docker-compose.yml:deploy/report-node/docker-compose.prod.yml"
    ), "base file first, prod override second - the override must win"
    assert any(ln.startswith("COMPOSE_PROJECT_NAME=marketwind") for ln in lines), (
        "pin the project name: the pgdata volume is <project>_pgdata, and the project "
        "otherwise derives from the directory - a re-clone into marketwind-1 would "
        "silently attach a different, empty volume"
    )
