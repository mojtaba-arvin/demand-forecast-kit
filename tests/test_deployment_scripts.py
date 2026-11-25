# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Basic syntax checks for host-side deployment scripts."""

import subprocess
from pathlib import Path


def test_restic_scripts_have_valid_bash_syntax() -> None:
    root = Path(__file__).resolve().parents[1]
    for name in ("backup-restic.sh", "restore-restic.sh"):
        script = root / "scripts" / name
        subprocess.run(["bash", "-n", str(script)], check=True, capture_output=True, text=True)
