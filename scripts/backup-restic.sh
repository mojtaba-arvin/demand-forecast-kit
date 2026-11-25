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

mkdir -p backups
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive="backups/demand-forecast-kit-state-${timestamp}.tar.gz"
restart_services() {
  docker compose start api worker >/dev/null
}
trap restart_services EXIT

docker compose stop api worker
tar -czf "$archive" -C state .
restic backup "$archive" --tag demand-forecast-kit
restic forget --tag demand-forecast-kit \
  --keep-daily 7 --keep-weekly 5 --keep-monthly 12 --prune
rm -f "$archive"

restart_services
trap - EXIT
printf 'Encrypted off-host backup completed: %s\n' "$archive"
