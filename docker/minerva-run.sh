#!/usr/bin/env bash
set -euo pipefail

# User-configurable environment variables
# ---------------------------------------
#   MINERVA_LOG_PATH              File to tee script output to.
#   MINERVA_DATA_DIR              Root data directory (defaults to /data).
#   MINERVA_STATE_DIR             Directory to store generated state.
#   MINERVA_PROMPTS_DIR           Directory containing prompt templates.
#   MINERVA_CONFIG_PATH           Explicit path to google-services.json.
#   MINERVA_RUN_PLAN_FILE         Run-plan file path (defaults to /data/minerva-run-plan.toml).
#   MINERVA_FETCH_ARGS            Extra arguments for every fetch invocation.
#   MINERVA_SUMMARY_ARGS          Extra arguments for every summary invocation.
#   MINERVA_PUBLISH_ARGS          Extra arguments for every publish invocation.
#   MINERVA_SHARED_ARGS           Extra arguments appended to summary invocations.
#   MINERVA_HOURLY_FETCH_ARGS     Extra fetch arguments for hourly runs.
#   MINERVA_HOURLY_SUMMARY_ARGS   Extra summary arguments for hourly runs.
#   MINERVA_HOURLY_PUBLISH_ARGS   Extra publish arguments for hourly runs.
#   MINERVA_DAILY_FETCH_ARGS      Extra fetch arguments for daily runs.
#   MINERVA_DAILY_SUMMARY_ARGS    Extra summary arguments for daily runs.
#   MINERVA_DAILY_PUBLISH_ARGS    Extra publish arguments for daily runs.
#   MINERVA_PODCAST_ARGS          Extra arguments for podcast generation runs.
#   MINERVA_DAILY_PODCAST_ARGS    Extra podcast arguments for daily runs.
#   MINERVA_PODCAST_PROMPT_TEMPLATE_FILE
#                                 Optional path to a custom podcast prompt template.
#   MINERVA_DAILY_PODCAST_PROMPT_TEMPLATE_FILE
#                                 Daily-mode override for the podcast prompt template path.
#   MINERVA_PODCAST_TELEGRAM_ARGS Extra Telegram arguments for podcast runs.
#   MINERVA_PODCAST_TEXT_FILE     Override the default podcast script output file.
#   MINERVA_PODCAST_AUDIO_FILE    Override the default podcast audio output file.
#   MINERVA_PODCAST_TOPIC_FILE    Override the default podcast topic history file.
#   MINERVA_PODCAST_LANGUAGE      Language to request for the generated podcast script.

source /etc/container.env

if [[ -n "${MINERVA_LOG_PATH:-}" ]]; then
  exec >>"$MINERVA_LOG_PATH" 2>&1
elif [[ -e /proc/1/fd/1 && -w /proc/1/fd/1 ]]; then
  exec >>/proc/1/fd/1 2>&1
else
  exec >>/dev/stdout 2>&1
fi

log() {
  printf '[%s] [minerva-run] %s\n' "$(date --iso-8601=seconds)" "$*"
}

load_unit_overrides() {
  local unit_name="$1"
  local plan_file="$2"

  python3 - "$unit_name" "$plan_file" <<'PY'
from __future__ import annotations

import os
import re
import shlex
import sys
import tomllib

unit_name = sys.argv[1]
plan_file = sys.argv[2]


def default_plan() -> dict[str, object]:
    return {
        "global": {},
        "unit": [
            {"name": "hourly", "schedule": "0 * * * *", "enabled": True, "mode": "hourly"},
            {"name": "daily", "schedule": "0 6 * * *", "enabled": True, "mode": "daily"},
        ],
    }


if os.path.exists(plan_file):
    with open(plan_file, "rb") as handle:
        plan = tomllib.load(handle)
else:
    plan = default_plan()

if not isinstance(plan, dict):
    print("echo 'Invalid run plan format' >&2")
    print("exit 2")
    raise SystemExit

global_cfg = plan.get("global", {})
if not isinstance(global_cfg, dict):
    global_cfg = {}

units = plan.get("unit", [])
if not isinstance(units, list):
    units = []

selected: dict[str, object] | None = None
for unit in units:
    if isinstance(unit, dict) and str(unit.get("name", "")).strip() == unit_name:
        selected = unit
        break

if selected is None:
    print(f"echo {shlex.quote(f'Run unit {unit_name!r} not found in plan {plan_file!r}')} >&2")
    print("exit 2")
    raise SystemExit


def table(cfg: dict[str, object], key: str) -> dict[str, object]:
    value = cfg.get(key, {})
    return value if isinstance(value, dict) else {}


def merge_dicts(a: dict[str, object], b: dict[str, object]) -> dict[str, object]:
    result = dict(a)
    result.update(b)
    return result


def sanitize_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()


paths_map = {
    "data_dir": "MINERVA_DATA_DIR",
    "state_dir": "MINERVA_STATE_DIR",
    "prompts_dir": "MINERVA_PROMPTS_DIR",
    "run_cache_file": "MINERVA_RUN_CACHE_FILE",
    "todo_dump_file": "MINERVA_TODO_DUMP_FILE",
    "summary_file": "MINERVA_SUMMARY_FILE",
    "speech_file": "MINERVA_SPEECH_FILE",
    "podcast_text_file": "MINERVA_PODCAST_TEXT_FILE",
    "podcast_audio_file": "MINERVA_PODCAST_AUDIO_FILE",
    "podcast_topic_file": "MINERVA_PODCAST_TOPIC_FILE",
    "podcast_prompt_template_file": "MINERVA_PODCAST_PROMPT_TEMPLATE_FILE",
    "daily_podcast_prompt_template_file": "MINERVA_DAILY_PODCAST_PROMPT_TEMPLATE_FILE",
    "config_path": "MINERVA_CONFIG_PATH",
}

options_map = {
    "fetch_args": "MINERVA_FETCH_ARGS",
    "summary_args": "MINERVA_SUMMARY_ARGS",
    "publish_args": "MINERVA_PUBLISH_ARGS",
    "shared_args": "MINERVA_SHARED_ARGS",
    "hourly_fetch_args": "MINERVA_HOURLY_FETCH_ARGS",
    "hourly_summary_args": "MINERVA_HOURLY_SUMMARY_ARGS",
    "hourly_publish_args": "MINERVA_HOURLY_PUBLISH_ARGS",
    "daily_fetch_args": "MINERVA_DAILY_FETCH_ARGS",
    "daily_summary_args": "MINERVA_DAILY_SUMMARY_ARGS",
    "daily_publish_args": "MINERVA_DAILY_PUBLISH_ARGS",
    "podcast_args": "MINERVA_PODCAST_ARGS",
    "daily_podcast_args": "MINERVA_DAILY_PODCAST_ARGS",
    "podcast_telegram_args": "MINERVA_PODCAST_TELEGRAM_ARGS",
    "podcast_language": "MINERVA_PODCAST_LANGUAGE",
}

merged_env = merge_dicts(table(global_cfg, "env"), table(selected, "env"))
merged_paths = merge_dicts(table(global_cfg, "paths"), table(selected, "paths"))
merged_options = merge_dicts(table(global_cfg, "options"), table(selected, "options"))
merged_providers = merge_dicts(table(global_cfg, "providers"), table(selected, "providers"))
merged_tokens = merge_dicts(table(global_cfg, "tokens"), table(selected, "tokens"))

if "config_path" in merged_options:
    merged_paths["config_path"] = merged_options.pop("config_path")

mode = selected.get("mode") or global_cfg.get("mode") or selected.get("name")


def emit(name: str, value: object) -> None:
    print(f"export {name}={shlex.quote(str(value))}")

for key, value in merged_env.items():
    key_text = str(key)
    env_name = key_text if key_text.isupper() else sanitize_key(key_text)
    emit(env_name, value)

for key, value in merged_paths.items():
    key_text = str(key)
    env_name = paths_map.get(key_text, f"MINERVA_{sanitize_key(key_text)}")
    emit(env_name, value)

for key, value in merged_options.items():
    key_text = str(key)
    env_name = options_map.get(key_text, key_text if key_text.startswith("MINERVA_") else f"MINERVA_{sanitize_key(key_text)}")
    emit(env_name, value)

for key, value in merged_providers.items():
    emit(f"MINERVA_PROVIDER_{sanitize_key(str(key))}", value)

for key, value in merged_tokens.items():
    emit(f"MINERVA_TOKEN_{sanitize_key(str(key))}", value)

print(f"MODE={shlex.quote(str(mode))}")
PY
}

MODE="${1:-}"
if [[ -z "$MODE" ]]; then
  log "Usage: minerva-run <hourly|daily|unit <name> --plan <file>>"
  exit 2
fi
shift || true

if [[ "$MODE" == "unit" ]]; then
  UNIT_NAME="${1:-}"
  if [[ -z "$UNIT_NAME" ]]; then
    log "Usage: minerva-run unit <unit-name> --plan <file>"
    exit 2
  fi
  shift || true

  PLAN_FILE="${MINERVA_RUN_PLAN_FILE:-${MINERVA_DATA_DIR:-/data}/minerva-run-plan.toml}"
  EXTRA_ARGS=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --plan)
        if [[ $# -lt 2 ]]; then
          log "Missing value for --plan"
          exit 2
        fi
        PLAN_FILE="$2"
        shift 2
        ;;
      --)
        shift
        EXTRA_ARGS+=("$@")
        break
        ;;
      *)
        EXTRA_ARGS+=("$1")
        shift
        ;;
    esac
  done

  # shellcheck disable=SC1090
  eval "$(load_unit_overrides "$UNIT_NAME" "$PLAN_FILE")"
  set -- "${EXTRA_ARGS[@]}"
fi

DATA_DIR="${MINERVA_DATA_DIR:-/data}"
STATE_DIR="${MINERVA_STATE_DIR:-$DATA_DIR/state}"
PROMPTS_DIR="${MINERVA_PROMPTS_DIR:-$DATA_DIR/prompts}"
RUN_CACHE_FILE="${MINERVA_RUN_CACHE_FILE:-$STATE_DIR/summary_run_marker.txt}"
TODO_DUMP_FILE="${MINERVA_TODO_DUMP_FILE:-$STATE_DIR/todo_dump.json}"
SUMMARY_FILE="${MINERVA_SUMMARY_FILE:-$STATE_DIR/todo_summary.txt}"
SPEECH_FILE="${MINERVA_SPEECH_FILE:-$STATE_DIR/todo-summary.wav}"
PODCAST_TEXT_FILE="${MINERVA_PODCAST_TEXT_FILE:-$STATE_DIR/random_podcast.txt}"
PODCAST_AUDIO_FILE="${MINERVA_PODCAST_AUDIO_FILE:-$STATE_DIR/random-podcast.wav}"
PODCAST_TOPIC_FILE="${MINERVA_PODCAST_TOPIC_FILE:-$STATE_DIR/random_podcast_topics.txt}"
PODCAST_PROMPT_TEMPLATE_FILE="${MINERVA_PODCAST_PROMPT_TEMPLATE_FILE:-}"

mkdir -p "$STATE_DIR"
mkdir -p \
  "$(dirname "$RUN_CACHE_FILE")" \
  "$(dirname "$TODO_DUMP_FILE")" \
  "$(dirname "$SUMMARY_FILE")" \
  "$(dirname "$SPEECH_FILE")" \
  "$(dirname "$PODCAST_TEXT_FILE")" \
  "$(dirname "$PODCAST_AUDIO_FILE")" \
  "$(dirname "$PODCAST_TOPIC_FILE")"

CONFIG_PATH="${MINERVA_CONFIG_PATH:-}"
if [[ -z "$CONFIG_PATH" ]]; then
  if [[ -n "${GOOGLE_SERVICES_PATH:-}" && -f "$GOOGLE_SERVICES_PATH" ]]; then
    CONFIG_PATH="$GOOGLE_SERVICES_PATH"
  elif [[ -f /config/google-services.json ]]; then
    CONFIG_PATH="/config/google-services.json"
  fi
fi

PROMPT_FILE=""
FETCH_MODE_ARGS=()
SUMMARY_MODE_ARGS=()
PUBLISH_MODE_ARGS=()
PODCAST_MODE_ARGS=()

append_args_from_env() {
  local -n _target=$1
  local _env_name=$2
  local _env_value="${!_env_name:-}"
  if [[ -n "$_env_value" ]]; then
    read -r -a _extra <<< "$_env_value"
    _target+=("${_extra[@]}")
  fi
}

case "$MODE" in
  hourly)
    PROMPT_FILE="$PROMPTS_DIR/hourly.txt"
    if [[ ! -f "$PROMPT_FILE" ]]; then
      log "Hourly system prompt not found at $PROMPT_FILE"
      exit 1
    fi
    FETCH_MODE_ARGS+=("--skip-if-run")
    SUMMARY_MODE_ARGS+=("--system-prompt-file" "$PROMPT_FILE")
    append_args_from_env FETCH_MODE_ARGS MINERVA_HOURLY_FETCH_ARGS
    append_args_from_env SUMMARY_MODE_ARGS MINERVA_HOURLY_SUMMARY_ARGS
    append_args_from_env PUBLISH_MODE_ARGS MINERVA_HOURLY_PUBLISH_ARGS
    ;;
  daily)
    PROMPT_FILE="$PROMPTS_DIR/daily.txt"
    if [[ ! -f "$PROMPT_FILE" ]]; then
      log "Daily system prompt not found at $PROMPT_FILE"
      exit 1
    fi
    SUMMARY_MODE_ARGS+=("--system-prompt-file" "$PROMPT_FILE")
    append_args_from_env FETCH_MODE_ARGS MINERVA_DAILY_FETCH_ARGS
    append_args_from_env SUMMARY_MODE_ARGS MINERVA_DAILY_SUMMARY_ARGS
    append_args_from_env PUBLISH_MODE_ARGS MINERVA_DAILY_PUBLISH_ARGS
    append_args_from_env PODCAST_MODE_ARGS MINERVA_DAILY_PODCAST_ARGS

    if [[ -n "${MINERVA_DAILY_PODCAST_PROMPT_TEMPLATE_FILE:-}" ]]; then
      PODCAST_PROMPT_TEMPLATE_FILE="$MINERVA_DAILY_PODCAST_PROMPT_TEMPLATE_FILE"
    fi
    ;;
  *)
    log "Unknown run mode: $MODE"
    exit 2
    ;;
esac

FETCH_ARGS=("--output" "$TODO_DUMP_FILE" "--run-cache-file" "$RUN_CACHE_FILE")
SUMMARY_ARGS=("--todos" "$TODO_DUMP_FILE" "--output" "$SUMMARY_FILE")
PUBLISH_ARGS=("--summary" "$SUMMARY_FILE" "--speech-output" "$SPEECH_FILE")
PODCAST_ARGS=("--output" "$PODCAST_TEXT_FILE" "--speech-output" "$PODCAST_AUDIO_FILE" "--topic-history-file" "$PODCAST_TOPIC_FILE")

if [[ -n "$CONFIG_PATH" ]]; then
  FETCH_ARGS=("--config" "$CONFIG_PATH" "${FETCH_ARGS[@]}")
fi

FETCH_ARGS+=("${FETCH_MODE_ARGS[@]}")
SUMMARY_ARGS+=("${SUMMARY_MODE_ARGS[@]}")
PUBLISH_ARGS+=("${PUBLISH_MODE_ARGS[@]}")

append_args_from_env FETCH_ARGS MINERVA_FETCH_ARGS
append_args_from_env SUMMARY_ARGS MINERVA_SUMMARY_ARGS
append_args_from_env SUMMARY_ARGS MINERVA_SHARED_ARGS
append_args_from_env PUBLISH_ARGS MINERVA_PUBLISH_ARGS
append_args_from_env PODCAST_ARGS MINERVA_PODCAST_ARGS
append_args_from_env PODCAST_ARGS MINERVA_PODCAST_TELEGRAM_ARGS

PODCAST_ARGS+=("${PODCAST_MODE_ARGS[@]}")

if [[ -n "${MINERVA_PODCAST_LANGUAGE:-}" ]]; then
  PODCAST_ARGS+=("--language" "$MINERVA_PODCAST_LANGUAGE")
fi

if [[ -n "$PODCAST_PROMPT_TEMPLATE_FILE" ]]; then
  PODCAST_ARGS+=("--prompt-template-file" "$PODCAST_PROMPT_TEMPLATE_FILE")
fi

if [[ $# -gt 0 ]]; then
  SUMMARY_ARGS+=("$@")
fi

log "Starting $MODE summary run"

log "Fetching todos"
rm -f "$TODO_DUMP_FILE"
fetch-todos "${FETCH_ARGS[@]}"

if [[ ! -f "$TODO_DUMP_FILE" ]]; then
  log "Todo dump not created; skipping summarisation and publication"
  exit 0
fi

log "Generating summary"
rm -f "$SUMMARY_FILE"
summarize-todos "${SUMMARY_ARGS[@]}"

if [[ ! -f "$SUMMARY_FILE" ]]; then
  log "Summary file not created; skipping publication"
  exit 0
fi

log "Publishing summary"
publish-summary "${PUBLISH_ARGS[@]}"

if [[ "$MODE" == "daily" ]]; then
  log "Generating random podcast"
  generate-podcast "${PODCAST_ARGS[@]}"
fi

log "Completed $MODE summary run"
