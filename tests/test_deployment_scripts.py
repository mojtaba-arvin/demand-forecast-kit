# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Basic syntax checks for host-side deployment scripts."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_restic_scripts_have_valid_bash_syntax() -> None:
    root = Path(__file__).resolve().parents[1]
    for name in ("backup-restic.sh", "restore-restic.sh", "smoke-restored-deployment.sh"):
        script = root / "scripts" / name
        subprocess.run(["bash", "-n", str(script)], check=True, capture_output=True, text=True)


def test_compose_profile_resolves_with_example_environment() -> None:
    root = Path(__file__).resolve().parents[1]
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI is not installed")
    compose_version = subprocess.run(
        [docker, "compose", "version"],
        check=False,
        capture_output=True,
        text=True,
    )
    if compose_version.returncode != 0:
        pytest.skip("Docker Compose plugin is not installed")

    env_file = root / ".env"
    previous = env_file.read_bytes() if env_file.exists() else None
    try:
        env_file.write_bytes((root / ".env.example").read_bytes())
        subprocess.run(
            [docker, "compose", "config", "--quiet"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        if previous is None:
            env_file.unlink(missing_ok=True)
        else:
            env_file.write_bytes(previous)
