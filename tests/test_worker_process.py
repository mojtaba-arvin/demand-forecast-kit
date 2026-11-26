# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Process-level worker shutdown and heartbeat lifecycle tests."""

from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name == "nt", reason="SIGTERM lifecycle is POSIX-specific")
def test_sigterm_records_worker_as_stopped(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    env = os.environ.copy()
    env["DEMAND_FORECAST_STATE_DIR"] = str(state_dir)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "demand_forecast_kit.operations_worker",
            "--tenant-id",
            "tenant-sigterm",
            "--poll-seconds",
            "1",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    database = state_dir / "operations.sqlite"
    deadline = time.monotonic() + 10
    heartbeat_seen = False
    while time.monotonic() < deadline and not heartbeat_seen:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            pytest.fail(f"worker exited before startup: {stdout}\n{stderr}")
        if database.exists():
            try:
                with sqlite3.connect(database) as connection:
                    row = connection.execute(
                        "SELECT 1 FROM worker_heartbeats WHERE tenant_id=?",
                        ("tenant-sigterm",),
                    ).fetchone()
                heartbeat_seen = row is not None
            except sqlite3.OperationalError:
                pass
        if not heartbeat_seen:
            time.sleep(0.05)

    assert heartbeat_seen, "worker did not publish its startup heartbeat"
    process.send_signal(signal.SIGTERM)
    try:
        stdout, stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        pytest.fail(f"worker did not stop after SIGTERM: {stdout}\n{stderr}")

    assert process.returncode == 0, f"worker failed during shutdown: {stdout}\n{stderr}"
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT status FROM worker_heartbeats WHERE tenant_id=?",
            ("tenant-sigterm",),
        ).fetchall()
    assert rows == [("stopped",)]
