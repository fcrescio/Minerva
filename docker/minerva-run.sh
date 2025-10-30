#!/usr/bin/env bash
set -euo pipefail

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

mkdir -p "$STATE_DIR"
mkdir -p "$(dirname "$RUN_CACHE_FILE")" "$(dirname "$TODO_DUMP_FILE")" "$(dirname "$SUMMARY_FILE")" "$(dirname "$SPEECH_FILE")"

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

case "$MODE" in
  hourly)
    PROMPT_FILE="$PROMPTS_DIR/hourly.txt"
    if [[ ! -f "$PROMPT_FILE" ]]; then
      log "Hourly system prompt not found at $PROMPT_FILE"
      exit 1
    fi
    FETCH_MODE_ARGS+=("--skip-if-run")
    SUMMARY_MODE_ARGS+=("--system-prompt-file" "$PROMPT_FILE")
    if [[ -n "${MINERVA_HOURLY_ARGS:-}" ]]; then
      read -r -a EXTRA <<< "${MINERVA_HOURLY_ARGS}"
      SUMMARY_MODE_ARGS+=("${EXTRA[@]}")
    fi
    ;;
  daily)
    PROMPT_FILE="$PROMPTS_DIR/daily.txt"
    if [[ ! -f "$PROMPT_FILE" ]]; then
      log "Daily system prompt not found at $PROMPT_FILE"
      exit 1
    fi
    SUMMARY_MODE_ARGS+=("--system-prompt-file" "$PROMPT_FILE")
    if [[ -n "${MINERVA_DAILY_ARGS:-}" ]]; then
      read -r -a EXTRA <<< "${MINERVA_DAILY_ARGS}"
      SUMMARY_MODE_ARGS+=("${EXTRA[@]}")
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

if [[ -n "$CONFIG_PATH" ]]; then
  FETCH_ARGS=("--config" "$CONFIG_PATH" "${FETCH_ARGS[@]}")
fi

FETCH_ARGS+=("${FETCH_MODE_ARGS[@]}")
SUMMARY_ARGS+=("${SUMMARY_MODE_ARGS[@]}")

if [[ -n "${MINERVA_FETCH_ARGS:-}" ]]; then
  read -r -a EXTRA <<< "${MINERVA_FETCH_ARGS}"
  FETCH_ARGS+=("${EXTRA[@]}")
fi

if [[ -n "${MINERVA_SUMMARY_ARGS:-}" ]]; then
  read -r -a EXTRA <<< "${MINERVA_SUMMARY_ARGS}"
  SUMMARY_ARGS+=("${EXTRA[@]}")
fi

if [[ -n "${MINERVA_SHARED_ARGS:-}" ]]; then
  read -r -a EXTRA <<< "${MINERVA_SHARED_ARGS}"
  SUMMARY_ARGS+=("${EXTRA[@]}")
fi

if [[ -n "${MINERVA_PUBLISH_ARGS:-}" ]]; then
  read -r -a EXTRA <<< "${MINERVA_PUBLISH_ARGS}"
  PUBLISH_ARGS+=("${EXTRA[@]}")
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

log "Completed $MODE summary run"
