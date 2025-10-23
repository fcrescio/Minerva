#!/usr/bin/env bash
set -euo pipefail

export MINERVA_DATA_DIR="${MINERVA_DATA_DIR:-/data}"
export MINERVA_STATE_DIR="${MINERVA_STATE_DIR:-$MINERVA_DATA_DIR/state}"
export MINERVA_PROMPTS_DIR="${MINERVA_PROMPTS_DIR:-$MINERVA_DATA_DIR/prompts}"
export MINERVA_RUN_CACHE_FILE="${MINERVA_RUN_CACHE_FILE:-$MINERVA_STATE_DIR/summary_run_marker.txt}"

mkdir -p "$MINERVA_STATE_DIR" "$MINERVA_PROMPTS_DIR"

DEFAULT_PROMPTS_DIR="/usr/local/share/minerva/prompts"
for prompt in hourly daily; do
  target="$MINERVA_PROMPTS_DIR/${prompt}.txt"
  if [[ ! -f "$target" ]]; then
    cp "$DEFAULT_PROMPTS_DIR/${prompt}.txt" "$target"
  fi
done

CONFIG_TARGET="${MINERVA_CONFIG_FILE:-$MINERVA_DATA_DIR/google-services.json}"
mkdir -p "$(dirname "$CONFIG_TARGET")"
if [[ -n "${GOOGLE_SERVICES_JSON:-}" ]]; then
  printf '%s' "$GOOGLE_SERVICES_JSON" >"$CONFIG_TARGET"
  export MINERVA_CONFIG_PATH="$CONFIG_TARGET"
elif [[ -n "${GOOGLE_SERVICES_JSON_BASE64:-}" ]]; then
  printf '%s' "$GOOGLE_SERVICES_JSON_BASE64" | base64 -d >"$CONFIG_TARGET"
  export MINERVA_CONFIG_PATH="$CONFIG_TARGET"
elif [[ -n "${GOOGLE_SERVICES_PATH:-}" ]]; then
  if [[ -f "$GOOGLE_SERVICES_PATH" ]]; then
    export MINERVA_CONFIG_PATH="$GOOGLE_SERVICES_PATH"
  else
    echo "[warning] GOOGLE_SERVICES_PATH '$GOOGLE_SERVICES_PATH' does not exist" >&2
  fi
elif [[ -f /config/google-services.json ]]; then
  export MINERVA_CONFIG_PATH="/config/google-services.json"
fi

CRON_FILE="${MINERVA_CRON_FILE:-/etc/minerva.cron}"
cat >"$CRON_FILE" <<'CRONTAB'
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SHELL=/bin/bash

0 * * * * /usr/local/bin/minerva-run hourly
0 6 * * * /usr/local/bin/minerva-run daily
CRONTAB

if [[ $# -gt 0 ]]; then
  exec "$@"
fi

exec /usr/local/bin/supercronic "$CRON_FILE"
