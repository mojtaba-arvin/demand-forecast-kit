#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
set -Eeuo pipefail

base_url="${DEMAND_FORECAST_API_URL:-http://127.0.0.1:8000}"
token="${DEMAND_FORECAST_API_TOKEN:?DEMAND_FORECAST_API_TOKEN must be an ops:read bearer token}"
stale_after_seconds="${DEMAND_FORECAST_WORKER_STALE_AFTER_SECONDS:-90}"

if [[ ! "$stale_after_seconds" =~ ^[0-9]+$ ]] || (( stale_after_seconds < 5 || stale_after_seconds > 3600 )); then
  printf 'DEMAND_FORECAST_WORKER_STALE_AFTER_SECONDS must be between 5 and 3600\\n' >&2
  exit 2
fi

command -v curl >/dev/null
command -v python3 >/dev/null

curl --fail --silent --show-error --max-time 10 \
  "${base_url%/}/health/ready" >/dev/null

worker_status="$(curl --fail --silent --show-error --max-time 10 \
  --header "Authorization: Bearer ${token}" \
  "${base_url%/}/v1/ops/worker/status?stale_after_seconds=${stale_after_seconds}")"

python3 -c '
import json
import sys

payload = json.load(sys.stdin)
workers = payload.get("workers", [])
if payload.get("healthy") is not True or not any(
    worker.get("status") == "running" and worker.get("healthy") is True
    for worker in workers
):
    raise SystemExit("restore smoke check failed: no healthy worker heartbeat")
' <<<"$worker_status"

printf 'Restore smoke check passed: API readiness and tenant-scoped worker heartbeat are healthy.\n'
