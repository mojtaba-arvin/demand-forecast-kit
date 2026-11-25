#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${1:-}" != "--confirm" ]]; then
  printf 'Usage: %s --confirm (stops must already be stopped)\n' "$0" >&2
  exit 2
fi

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY must point to the Restic repository}"
: "${RESTIC_PASSWORD_FILE:?RESTIC_PASSWORD_FILE must point to a protected password file}"
command -v restic >/dev/null
command -v docker >/dev/null
command -v python3 >/dev/null
test -r "$RESTIC_PASSWORD_FILE"

running_services="$(docker compose ps --services --status running)"
for service in api worker; do
  if grep -Fxq "$service" <<<"$running_services"; then
    printf 'Refusing restore: stop Compose service %s first\n' "$service" >&2
    exit 1
  fi
done

temporary="$(mktemp -d)"
trap 'rm -rf "$temporary"' EXIT
restic restore latest --tag demand-forecast-kit --target "$temporary"
archive="$(find "$temporary" -type f -name 'demand-forecast-kit-state-*.tar.gz' -print -quit)"
if [[ -z "$archive" ]]; then
  printf 'No tagged demand-forecast-kit state archive found in the latest snapshot\n' >&2
  exit 1
fi
tar -tzf "$archive" >/dev/null

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
previous_state="state.pre-restore-${timestamp}"
if [[ -d state ]]; then
  mv state "$previous_state"
fi
mkdir -p state
if ! tar -xzf "$archive" -C state; then
  rm -rf state
  if [[ -d "$previous_state" ]]; then mv "$previous_state" state; fi
  exit 1
fi
chown -R 10001:10001 state

if ! python3 - "$ROOT_DIR/state" <<'PY'
from pathlib import Path
import sqlite3
import sys

root = Path(sys.argv[1])
databases = sorted((*root.rglob("*.sqlite"), *root.rglob("*.db")))
if not databases:
    raise SystemExit("restore contains no SQLite databases")
for path in databases:
    connection = sqlite3.connect(path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != ("ok",) or foreign_key_errors:
            raise SystemExit(f"database verification failed: {path}")
    finally:
        connection.close()
    print(f"verified: {path.relative_to(root)}")
PY
then
  rm -rf state
  if [[ -d "$previous_state" ]]; then mv "$previous_state" state; fi
  exit 1
fi

if [[ -d "$previous_state" ]]; then
  printf 'Previous state preserved at %s.\n' "$previous_state"
else
  printf 'No previous state directory existed.\n'
fi
printf 'Services remain stopped. Start them and perform API/worker smoke checks before deleting any preserved state.\n'
