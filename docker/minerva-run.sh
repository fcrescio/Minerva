#!/usr/bin/env bash
set -euo pipefail

# User-configurable environment variables
# ---------------------------------------
#   MINERVA_LOG_PATH              File to tee script output to.
#   MINERVA_DATA_DIR              Root data directory (defaults to /data).
#   MINERVA_STATE_DIR             Directory to store generated state.
#   MINERVA_PROMPTS_DIR           Directory containing prompt templates.
#   MINERVA_CONFIG_PATH           Explicit path to google-services.json.
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

MODE="${1:-}"
if [[ -z "$MODE" ]]; then
  log "Usage: minerva-run <hourly|daily>"
  exit 2
fi
shift || true

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
