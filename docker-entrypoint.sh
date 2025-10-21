#!/usr/bin/env bash
set -euo pipefail

# Default to running once every 24 hours (86400 seconds) unless overridden.
INTERVAL="${SCHEDULE_INTERVAL_SECONDS:-86400}"

ARGS=("$@")

CONFIG_FILE=""

cleanup() {
  if [[ -n "$CONFIG_FILE" && -f "$CONFIG_FILE" ]]; then
    rm -f "$CONFIG_FILE"
  fi
}
trap cleanup EXIT

has_config_arg=0
for arg in "${ARGS[@]}"; do
  if [[ "$arg" == "--config" ]]; then
    has_config_arg=1
    break
  fi
done

if [[ "$has_config_arg" -eq 0 ]]; then
  if [[ -n "${GOOGLE_SERVICES_JSON:-}" ]]; then
    CONFIG_FILE="${GOOGLE_SERVICES_FILE:-$(mktemp)}"
    printf '%s' "$GOOGLE_SERVICES_JSON" >"$CONFIG_FILE"
    ARGS=("--config" "$CONFIG_FILE" "${ARGS[@]}")
  elif [[ -n "${GOOGLE_SERVICES_JSON_BASE64:-}" ]]; then
    CONFIG_FILE="${GOOGLE_SERVICES_FILE:-$(mktemp)}"
    printf '%s' "$GOOGLE_SERVICES_JSON_BASE64" | base64 -d >"$CONFIG_FILE"
    ARGS=("--config" "$CONFIG_FILE" "${ARGS[@]}")
  elif [[ -n "${GOOGLE_SERVICES_PATH:-}" ]]; then
    if [[ -f "$GOOGLE_SERVICES_PATH" ]]; then
      ARGS=("--config" "$GOOGLE_SERVICES_PATH" "${ARGS[@]}")
    else
      echo "[warning] GOOGLE_SERVICES_PATH '$GOOGLE_SERVICES_PATH' does not exist" >&2
    fi
  elif [[ -f /config/google-services.json ]]; then
    ARGS=("--config" "/config/google-services.json" "${ARGS[@]}")
  fi
fi

run_service() {
  echo "[$(date --iso-8601=seconds)] Starting todo summary run" >&2
  summarize-todos "${ARGS[@]}"
  echo "[$(date --iso-8601=seconds)] Completed todo summary run" >&2
}

# Run immediately on container start, then sleep for the configured interval.
while true; do
  run_service
  sleep "$INTERVAL"
done
