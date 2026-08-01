#!/usr/bin/env python3
"""Preflight: verify the hermes WeChat delivery path resolves before the stack builds.

Run on the box AFTER populating .env and BEFORE `docker compose up`:

    python3 deploy/report-node/check_hermes.py            # reads ./.env
    python3 deploy/report-node/check_hermes.py /path/.env # explicit .env path

Without this, an ADR-0001 misconfiguration surfaces as `hermes: not found` in the
middle of the 07:00 report -- hours after deploy, with no named cause. It also
validates the premise of the scheduler healthcheck in docker-compose.prod.yml:
that healthcheck watches <venv>/bin/python, which is a symlink into a uv-managed
python tree living OUTSIDE ~/.hermes and mounted separately. This script proves
the tree is where the compose file will look for it.

Stdlib-only, no type hints, no __future__ -- same constraints as check_keys.py,
whose .env plumbing and PASS/FAIL table it reuses.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from check_keys import FAIL, PASS, load_env, summarize  # noqa: E402

DEFAULT_UV_PYTHON_DIR = "/root/.local/share/uv/python/cpython-3.11-linux-x86_64-gnu"


def venv_interpreter(hermes_bin):
    """The `python` sibling of the hermes entrypoint. No existence check."""
    return os.path.join(os.path.dirname(hermes_bin), "python")


def check_hermes_bin(env):
    name = "HERMES_BIN"
    path = env.get("HERMES_BIN", "")
    if not path:
        return (name, FAIL, "unset -- set it to <hermes venv>/bin/hermes in .env")
    if not os.path.isfile(path):
        return (name, FAIL, "not a file: %s" % path)
    if not os.access(path, os.X_OK):
        return (name, FAIL, "not executable: %s" % path)
    return (name, PASS, path)


def check_venv_interpreter(env):
    name = "venv interpreter"
    path = env.get("HERMES_BIN", "")
    if not path:
        return (name, FAIL, "HERMES_BIN unset")
    interp = venv_interpreter(path)
    # exists() must lead: it resolves the link, whereas os.access(X_OK) answers True
    # for a dangling one on Windows -- and a dangling link IS the failure being caught.
    if not os.path.exists(interp) or not os.access(interp, os.X_OK):
        return (name, FAIL,
                "not executable: %s (a dangling symlink fails this too -- check "
                "that its target exists)" % interp)
    return (name, PASS, "%s -> %s" % (interp, os.path.realpath(interp)))


def check_interpreter_mounted(env):
    name = "interpreter under mount"
    path = env.get("HERMES_BIN", "")
    if not path:
        return (name, FAIL, "HERMES_BIN unset")
    mount = env.get("HERMES_UV_PYTHON_DIR", DEFAULT_UV_PYTHON_DIR)
    real = os.path.realpath(venv_interpreter(path))
    # Trailing separator so a sibling like /uv/python-3.12 cannot prefix-match /uv/python.
    prefix = os.path.realpath(mount).rstrip(os.sep) + os.sep
    if not real.startswith(prefix):
        return (name, FAIL,
                "interpreter resolves to %s, outside HERMES_UV_PYTHON_DIR=%s -- "
                "the prod compose mounts that dir, so set it to %s"
                % (real, mount, os.path.dirname(os.path.dirname(real))))
    return (name, PASS, "under %s" % mount)


def main(argv):
    path = argv[1] if len(argv) > 1 else os.path.join(os.getcwd(), ".env")
    env = load_env(path)
    src = path if os.path.isfile(path) else "process env only"
    sys.stdout.write("Checking hermes delivery path (source: %s)\n\n" % src)
    results = [check_hermes_bin(env),
               check_venv_interpreter(env),
               check_interpreter_mounted(env)]
    report, code = summarize(results)
    sys.stdout.write(report + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
