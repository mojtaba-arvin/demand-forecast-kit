#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY must point to an initialized remote Restic repository}"
: "${RESTIC_PASSWORD_FILE:?RESTIC_PASSWORD_FILE must point to a protected password file}"
command -v restic >/dev/null
command -v docker >/dev/null
test -r "$RESTIC_PASSWORD_FILE"
test -d state

running_services="$(docker compose ps --services --status running)"
for service in api worker; do
  if ! grep -Fxq "$service" <<<"$running_services"; then
    printf 'Refusing backup: Compose service %s is not running\n' "$service" >&2
    exit 1
  fi
done

umask 077
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
temporary="$(mktemp -d "${TMPDIR:-/var/tmp}/demand-forecast-kit-backup.XXXXXX")"
archive="$temporary/demand-forecast-kit-state-${timestamp}.tar.gz"
cleanup() {
  rm -rf "$temporary"
  docker compose start api worker >/dev/null || true
}
trap cleanup EXIT

docker compose stop api worker
tar -czf "$archive" -C state .
restic backup "$archive" --tag demand-forecast-kit

# Restore service availability before the potentially slow repository prune.
docker compose start api worker
trap - EXIT
rm -rf "$temporary"

restic forget --tag demand-forecast-kit \
  --keep-daily 7 --keep-weekly 5 --keep-monthly 12 --prune
printf 'Encrypted off-host backup completed; services are running.\n'
