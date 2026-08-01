"""Preflight for the hermes delivery path, tested against real files.

The failure this guards is a symlinked interpreter that resolves outside the
directory the prod compose mounts (ADR-0001), so the tests build actual files and
symlinks instead of mocking os.path — a mock cannot dangle.
"""

from __future__ import annotations

import importlib.util
import stat
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "check_hermes.py"
_spec = importlib.util.spec_from_file_location("check_hermes", _MODULE_PATH)
check_hermes = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(check_hermes)

PASS, FAIL = "PASS", "FAIL"


def _venv(tmp_path: Path, *, uv_dir_name="uv-python", interpreter=True):
    """A hermes-shaped venv: bin/hermes plus bin/python -> <uv_dir>/bin/python3.11."""
    bin_dir = tmp_path / "hermes-agent" / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    hermes = bin_dir / "hermes"
    hermes.write_text("#!/bin/sh\nexit 0\n")
    hermes.chmod(hermes.stat().st_mode | stat.S_IEXEC)
    uv_dir = tmp_path / uv_dir_name
    real = uv_dir / "bin" / "python3.11"
    if interpreter:
        real.parent.mkdir(parents=True)
        real.write_text("#!/bin/sh\nexit 0\n")
        real.chmod(real.stat().st_mode | stat.S_IEXEC)
    (bin_dir / "python").symlink_to(real)
    env = {"HERMES_BIN": str(hermes), "HERMES_UV_PYTHON_DIR": str(uv_dir)}
    return env, uv_dir


def test_all_three_pass_on_a_well_formed_venv(tmp_path):
    env, _ = _venv(tmp_path)
    for check in (check_hermes.check_hermes_bin,
                  check_hermes.check_venv_interpreter,
                  check_hermes.check_interpreter_mounted):
        _name, status, detail = check(env)
        assert status == PASS, detail


def test_unset_hermes_bin_fails():
    _name, status, _detail = check_hermes.check_hermes_bin({})
    assert status == FAIL


def test_dangling_interpreter_symlink_fails(tmp_path):
    # The ADR-0001 failure mode: HERMES_UV_PYTHON_DIR not mounted, so the venv's
    # python symlink points at nothing. HERMES_BIN itself is still fine.
    env, _ = _venv(tmp_path, interpreter=False)
    assert check_hermes.check_hermes_bin(env)[1] == PASS
    _name, status, _detail = check_hermes.check_venv_interpreter(env)
    assert status == FAIL


def test_interpreter_outside_the_mounted_dir_fails_and_names_the_real_dir(tmp_path):
    env, _ = _venv(tmp_path)
    env["HERMES_UV_PYTHON_DIR"] = str(tmp_path / "somewhere-else")
    _name, status, detail = check_hermes.check_interpreter_mounted(env)
    assert status == FAIL
    assert str(tmp_path / "uv-python") in detail, (
        "the detail must print the real resolved dir — that string is what the "
        "operator pastes into HERMES_UV_PYTHON_DIR"
    )


def test_main_exits_nonzero_when_hermes_is_missing(tmp_path, monkeypatch):
    # load_env merges the real process environment, so clear the key explicitly —
    # otherwise this test passes or fails depending on the runner's shell.
    monkeypatch.delenv("HERMES_BIN", raising=False)
    assert check_hermes.main(["check_hermes.py", str(tmp_path / "absent.env")]) != 0
