#!/usr/bin/env bash
set -euo pipefail

# Default to running once every 24 hours (86400 seconds) unless overridden.
INTERVAL="${SCHEDULE_INTERVAL_SECONDS:-86400}"

run_service() {
  echo "[$(date --iso-8601=seconds)] Starting todo summary run" >&2
  summarize-todos "$@"
  echo "[$(date --iso-8601=seconds)] Completed todo summary run" >&2
}

# Run immediately on container start, then sleep for the configured interval.
while true; do
  run_service "$@"
  sleep "$INTERVAL"
done
