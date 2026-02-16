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
export MINERVA_RUN_PLAN_FILE="${MINERVA_RUN_PLAN_FILE:-$MINERVA_DATA_DIR/minerva-run-plan.toml}"

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

generate_cron_file() {
  local cron_file=$1
  local system_cron=$2

  python3 - "$MINERVA_RUN_PLAN_FILE" "$system_cron" >"$cron_file" <<'PY'
from __future__ import annotations

import os
import shlex
import sys
import tomllib

plan_path = sys.argv[1]
system_cron = sys.argv[2].lower() == "true"


def default_plan() -> dict[str, object]:
    return {
        "global": {},
        "unit": [
            {"name": "hourly", "schedule": "0 * * * *", "enabled": True},
            {"name": "daily", "schedule": "0 6 * * *", "enabled": True},
        ],
    }


if os.path.exists(plan_path):
    with open(plan_path, "rb") as handle:
        plan = tomllib.load(handle)
else:
    plan = default_plan()

units = plan.get("unit", []) if isinstance(plan, dict) else []
if not isinstance(units, list):
    units = []

lines = [
    "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "SHELL=/bin/bash",
    "",
    "# Redirect job output to the container log stream.",
]

for unit in units:
    if not isinstance(unit, dict):
        continue
    if unit.get("enabled", True) is False:
        continue

    name = str(unit.get("name", "")).strip()
    schedule = str(unit.get("schedule", "")).strip()
    if not name or not schedule:
        continue

    command = (
        f"/usr/local/bin/minerva-run unit {shlex.quote(name)} "
        f"--plan {shlex.quote(plan_path)} >> /proc/1/fd/1 2>&1"
    )
    if system_cron:
        lines.append(f"{schedule} root {command}")
    else:
        lines.append(f"{schedule} {command}")

if len(lines) == 4:
    lines.append("# No enabled units found in run plan.")

print("\n".join(lines))
PY
}

CRON_FILE="${MINERVA_CRON_FILE:-/etc/cron.d/minerva}"
if [[ "$CRON_FILE" == /etc/cron.d/* ]]; then
  log "Writing system cron file to $CRON_FILE"
  generate_cron_file "$CRON_FILE" "true"
  chmod 0644 "$CRON_FILE"
else
  log "Writing user cron file to $CRON_FILE and installing with crontab"
  generate_cron_file "$CRON_FILE" "false"
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
