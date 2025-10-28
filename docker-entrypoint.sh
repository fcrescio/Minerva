#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[%s] [entrypoint] %s\n' "$(date --iso-8601=seconds)" "$*" >&2
}

log "Starting container entrypoint"

export MINERVA_DATA_DIR="${MINERVA_DATA_DIR:-/data}"
export MINERVA_STATE_DIR="${MINERVA_STATE_DIR:-$MINERVA_DATA_DIR/state}"
export MINERVA_PROMPTS_DIR="${MINERVA_PROMPTS_DIR:-$MINERVA_DATA_DIR/prompts}"
export MINERVA_RUN_CACHE_FILE="${MINERVA_RUN_CACHE_FILE:-$MINERVA_STATE_DIR/summary_run_marker.txt}"

log "Ensuring data directories exist (data: $MINERVA_DATA_DIR, state: $MINERVA_STATE_DIR, prompts: $MINERVA_PROMPTS_DIR)"
mkdir -p "$MINERVA_STATE_DIR" "$MINERVA_PROMPTS_DIR"

DEFAULT_PROMPTS_DIR="/usr/local/share/minerva/prompts"
for prompt in hourly daily; do
  target="$MINERVA_PROMPTS_DIR/${prompt}.txt"
  if [[ ! -f "$target" ]]; then
    log "Seeding default $prompt prompt into $target"
    cp "$DEFAULT_PROMPTS_DIR/${prompt}.txt" "$target"
  else
    log "Existing $prompt prompt found at $target"
  fi
done

CONFIG_TARGET="${MINERVA_CONFIG_FILE:-$MINERVA_DATA_DIR/google-services.json}"
mkdir -p "$(dirname "$CONFIG_TARGET")"
if [[ -n "${GOOGLE_SERVICES_JSON:-}" ]]; then
  log "Writing google-services.json from GOOGLE_SERVICES_JSON environment variable to $CONFIG_TARGET"
  printf '%s' "$GOOGLE_SERVICES_JSON" >"$CONFIG_TARGET"
  export MINERVA_CONFIG_PATH="$CONFIG_TARGET"
elif [[ -n "${GOOGLE_SERVICES_JSON_BASE64:-}" ]]; then
  log "Writing google-services.json from GOOGLE_SERVICES_JSON_BASE64 environment variable to $CONFIG_TARGET"
  printf '%s' "$GOOGLE_SERVICES_JSON_BASE64" | base64 -d >"$CONFIG_TARGET"
  export MINERVA_CONFIG_PATH="$CONFIG_TARGET"
elif [[ -n "${GOOGLE_SERVICES_PATH:-}" ]]; then
  if [[ -f "$GOOGLE_SERVICES_PATH" ]]; then
    log "Using google-services.json from GOOGLE_SERVICES_PATH=$GOOGLE_SERVICES_PATH"
    export MINERVA_CONFIG_PATH="$GOOGLE_SERVICES_PATH"
  else
    log "GOOGLE_SERVICES_PATH '$GOOGLE_SERVICES_PATH' does not exist"
  fi
elif [[ -f /config/google-services.json ]]; then
  log "Using google-services.json from /config/google-services.json"
  export MINERVA_CONFIG_PATH="/config/google-services.json"
else
  log "No google-services.json configuration provided"
fi

# Dump env as export statements, safely escaping double quotes
printenv | awk -F= '{
  k=$1; v=substr($0, index($0,$2));
  gsub(/"/, "\\\"", v);
  printf("export %s=\"%s\"\n", k, v);
}' > /etc/container.env

CRON_FILE="${MINERVA_CRON_FILE:-/etc/cron.d/minerva}"
if [[ "$CRON_FILE" == /etc/cron.d/* ]]; then
  log "Writing system cron file to $CRON_FILE"
  cat >"$CRON_FILE" <<'CRONTAB'
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SHELL=/bin/bash

# Redirect job output to the container log stream.
0 * * * * root /usr/local/bin/minerva-run hourly >> /proc/1/fd/1 2>&1
0 6 * * * root /usr/local/bin/minerva-run daily >> /proc/1/fd/1 2>&1
CRONTAB
  chmod 0644 "$CRON_FILE"
else
  log "Writing user cron file to $CRON_FILE and installing with crontab"
  cat >"$CRON_FILE" <<'CRONTAB'
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SHELL=/bin/bash

# Redirect job output to the container log stream.
0 * * * * /usr/local/bin/minerva-run hourly >> /proc/1/fd/1 2>&1
0 6 * * * /usr/local/bin/minerva-run daily >> /proc/1/fd/1 2>&1
CRONTAB
  crontab "$CRON_FILE"
fi

if [[ $# -gt 0 ]]; then
  log "Executing custom command: $*"
  exec "$@"
fi

# Dump env as export statements, safely escaping double quotes
printenv | awk -F= '{
  k=$1; v=substr($0, index($0,$2));
  gsub(/"/, "\\\"", v);
  printf("export %s=\"%s\"\n", k, v);
}' > /etc/container.env

log "Starting cron in foreground"
exec cron -f
