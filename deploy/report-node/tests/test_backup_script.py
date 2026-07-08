# deploy/report-node/tests/test_backup_script.py
import datetime
import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "backup.sh"


def _make_stub(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _env_with_stubs(tmp_path, *, pg_dump_rc=0, ossutil_rc=0):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "ossutil_args.txt"
    _make_stub(bin_dir / "pg_dump", f'echo "FAKE DUMP"\nexit {pg_dump_rc}\n')
    _make_stub(bin_dir / "ossutil", f'echo "$@" > "{args_file}"\nexit {ossutil_rc}\n')
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}" + env["PATH"]
    env["DATABASE_URL"] = "postgresql://u:p@postgres:5432/marketwind"
    env["OSS_BUCKET"] = "testbucket"
    env["OSSUTIL_AUTH_ARGS"] = "-e endpoint --mode EcsRamRole --ecs-role-name r"
    return env, args_file


def test_uploads_to_dated_oss_key(tmp_path):
    env, args_file = _env_with_stubs(tmp_path)
    result = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    today = datetime.date.today().isoformat()
    assert f"oss://testbucket/backups/pg/marketwind-{today}.sql.gz" in args_file.read_text()


def test_pg_dump_failure_exits_nonzero(tmp_path):
    env, _ = _env_with_stubs(tmp_path, pg_dump_rc=1)
    result = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert result.returncode != 0


def test_upload_failure_exits_nonzero(tmp_path):
    env, _ = _env_with_stubs(tmp_path, ossutil_rc=1)
    result = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert result.returncode != 0
