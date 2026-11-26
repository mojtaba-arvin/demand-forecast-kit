# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Exercise the real Restic scripts against an isolated local repository."""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

import pytest


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_restic_backup_restore_round_trip_and_service_recovery(tmp_path: Path) -> None:
    real_restic = shutil.which("restic")
    if real_restic is None:
        pytest.skip("Restic is not installed")

    project = Path(__file__).resolve().parents[1]
    deployment = tmp_path / "deployment"
    scripts = deployment / "scripts"
    scripts.mkdir(parents=True)
    for name in ("backup-restic.sh", "restore-restic.sh"):
        shutil.copy2(project / "scripts" / name, scripts / name)

    state = deployment / "state"
    state.mkdir()
    database = state / "operations.sqlite"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("CREATE TABLE marker (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO marker VALUES (7)")
    (state / "artifacts").mkdir()
    (state / "artifacts" / "forecast.json").write_text('{"run_id": 7}\n', encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_state = tmp_path / "docker-services"
    docker_state.write_text("api\nworker\n", encoding="utf-8")
    _write_executable(
        fake_bin / "docker",
        """#!/usr/bin/env bash
set -Eeuo pipefail
[[ "${1:-}" == "compose" ]] || exit 64
case "${2:-}" in
  ps) cat "$FAKE_DOCKER_STATE" ;;
  stop) : > "$FAKE_DOCKER_STATE" ;;
  start) printf 'api\\nworker\\n' > "$FAKE_DOCKER_STATE" ;;
  *) exit 64 ;;
esac
""",
    )
    _write_executable(
        fake_bin / "restic",
        """#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${1:-}" == "forget" ]]; then
  grep -Fxq api "$FAKE_DOCKER_STATE"
  grep -Fxq worker "$FAKE_DOCKER_STATE"
fi
if [[ "${1:-}" == "backup" && "${FAKE_RESTIC_FAIL_BACKUP:-0}" == "1" ]]; then
  exit 42
fi
exec "$REAL_RESTIC" "$@"
""",
    )
    _write_executable(fake_bin / "chown", "#!/usr/bin/env bash\nexit 0\n")

    repository = tmp_path / "restic-repository"
    password_file = tmp_path / "restic-password"
    password_file.write_text("test-only-password", encoding="utf-8")
    password_file.chmod(0o600)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_DOCKER_STATE": str(docker_state),
            "REAL_RESTIC": real_restic,
            "RESTIC_REPOSITORY": str(repository),
            "RESTIC_PASSWORD_FILE": str(password_file),
        }
    )
    subprocess.run([real_restic, "init"], env=env, check=True, capture_output=True, text=True)

    backup = subprocess.run(
        ["bash", str(scripts / "backup-restic.sh")],
        cwd=deployment,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert backup.returncode == 0, backup.stderr
    assert docker_state.read_text(encoding="utf-8") == "api\nworker\n"

    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE marker SET value=99")
    (state / "post-backup-only.txt").write_text("must be rolled back", encoding="utf-8")
    docker_state.write_text("", encoding="utf-8")

    restore = subprocess.run(
        ["bash", str(scripts / "restore-restic.sh"), "--confirm"],
        cwd=deployment,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert restore.returncode == 0, restore.stderr
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT value FROM marker").fetchone() == (7,)
    assert not (state / "post-backup-only.txt").exists()
    preserved = list(deployment.glob("state.pre-restore-*"))
    assert len(preserved) == 1
    assert (preserved[0] / "post-backup-only.txt").is_file()
    assert docker_state.read_text(encoding="utf-8") == ""


def test_backup_failure_attempts_to_restart_both_services(tmp_path: Path) -> None:
    real_restic = shutil.which("restic")
    if real_restic is None:
        pytest.skip("Restic is not installed")

    project = Path(__file__).resolve().parents[1]
    deployment = tmp_path / "deployment"
    scripts = deployment / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(project / "scripts" / "backup-restic.sh", scripts / "backup-restic.sh")
    (deployment / "state").mkdir()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_state = tmp_path / "docker-services"
    docker_state.write_text("api\nworker\n", encoding="utf-8")
    _write_executable(
        fake_bin / "docker",
        """#!/usr/bin/env bash
set -Eeuo pipefail
case "${2:-}" in
  ps) cat "$FAKE_DOCKER_STATE" ;;
  stop) : > "$FAKE_DOCKER_STATE" ;;
  start) printf 'api\\nworker\\n' > "$FAKE_DOCKER_STATE" ;;
  *) exit 64 ;;
esac
""",
    )
    _write_executable(
        fake_bin / "restic",
        """#!/usr/bin/env bash
if [[ "${1:-}" == "backup" ]]; then exit 42; fi
exec "$REAL_RESTIC" "$@"
""",
    )
    repository = tmp_path / "restic-repository"
    password_file = tmp_path / "restic-password"
    password_file.write_text("test-only-password", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_DOCKER_STATE": str(docker_state),
            "REAL_RESTIC": real_restic,
            "RESTIC_REPOSITORY": str(repository),
            "RESTIC_PASSWORD_FILE": str(password_file),
        }
    )
    result = subprocess.run(
        ["bash", str(scripts / "backup-restic.sh")],
        cwd=deployment,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 42
    assert docker_state.read_text(encoding="utf-8") == "api\nworker\n"
