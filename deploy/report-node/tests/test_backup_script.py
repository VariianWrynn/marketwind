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


def _env_with_stubs(tmp_path, *, pg_dump_rc=0, ossutil_rc=0, bark=True):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "ossutil_args.txt"
    curl_file = tmp_path / "curl_args.txt"
    _make_stub(bin_dir / "pg_dump", f'echo "FAKE DUMP"\nexit {pg_dump_rc}\n')
    _make_stub(bin_dir / "ossutil", f'echo "$@" > "{args_file}"\nexit {ossutil_rc}\n')
    _make_stub(bin_dir / "curl", f'echo "$@" >> "{curl_file}"\nexit 0\n')
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}" + env["PATH"]
    env["DATABASE_URL"] = "postgresql://u:p@postgres:5432/marketwind"
    env["OSS_BUCKET"] = "testbucket"
    env["OSSUTIL_AUTH_ARGS"] = "-e endpoint --mode EcsRamRole --ecs-role-name r"
    if bark:
        env["BARK_BASE_URL"] = "https://api.day.app"
        env["BARK_KEY"] = "TESTKEY"
    return env, args_file, curl_file


def _run(env):
    return subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True)


def test_uploads_to_dated_oss_key(tmp_path):
    env, args_file, _ = _env_with_stubs(tmp_path)
    result = _run(env)
    assert result.returncode == 0, result.stderr
    today = datetime.date.today().isoformat()
    assert f"oss://testbucket/backups/pg/marketwind-{today}.sql.gz" in args_file.read_text()


def test_pg_dump_failure_exits_nonzero(tmp_path):
    env, _, _ = _env_with_stubs(tmp_path, pg_dump_rc=1)
    assert _run(env).returncode != 0


def test_upload_failure_exits_nonzero(tmp_path):
    env, _, _ = _env_with_stubs(tmp_path, ossutil_rc=1)
    assert _run(env).returncode != 0


def test_bark_alert_sent_on_failure(tmp_path):
    env, _, curl_file = _env_with_stubs(tmp_path, pg_dump_rc=1)
    result = _run(env)
    assert result.returncode != 0
    assert curl_file.exists(), "expected a Bark alert (curl) on backup failure"
    assert "TESTKEY" in curl_file.read_text()


def test_no_bark_alert_on_success(tmp_path):
    env, _, curl_file = _env_with_stubs(tmp_path)
    result = _run(env)
    assert result.returncode == 0
    assert not curl_file.exists(), "no Bark alert should be sent on success"
