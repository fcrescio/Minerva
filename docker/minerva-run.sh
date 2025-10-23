#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-}"
if [[ -z "$MODE" ]]; then
  echo "Usage: minerva-run <hourly|daily>" >&2
  exit 2
fi
shift || true

DATA_DIR="${MINERVA_DATA_DIR:-/data}"
STATE_DIR="${MINERVA_STATE_DIR:-$DATA_DIR/state}"
PROMPTS_DIR="${MINERVA_PROMPTS_DIR:-$DATA_DIR/prompts}"
RUN_CACHE_FILE="${MINERVA_RUN_CACHE_FILE:-$STATE_DIR/summary_run_marker.txt}"

mkdir -p "$STATE_DIR"

CONFIG_PATH="${MINERVA_CONFIG_PATH:-}"
if [[ -z "$CONFIG_PATH" ]]; then
  if [[ -n "${GOOGLE_SERVICES_PATH:-}" && -f "$GOOGLE_SERVICES_PATH" ]]; then
    CONFIG_PATH="$GOOGLE_SERVICES_PATH"
  elif [[ -f /config/google-services.json ]]; then
    CONFIG_PATH="/config/google-services.json"
  fi
fi

ARGS=()
if [[ -n "$CONFIG_PATH" ]]; then
  ARGS+=("--config" "$CONFIG_PATH")
fi

case "$MODE" in
  hourly)
    PROMPT_FILE="$PROMPTS_DIR/hourly.txt"
    if [[ ! -f "$PROMPT_FILE" ]]; then
      echo "Hourly system prompt not found at $PROMPT_FILE" >&2
      exit 1
    fi
    ARGS+=("--system-prompt-file" "$PROMPT_FILE" "--run-cache-file" "$RUN_CACHE_FILE" "--skip-if-run")
    if [[ -n "${MINERVA_HOURLY_ARGS:-}" ]]; then
      read -r -a EXTRA <<< "${MINERVA_HOURLY_ARGS}"
      ARGS+=("${EXTRA[@]}")
    fi
    ;;
  daily)
    PROMPT_FILE="$PROMPTS_DIR/daily.txt"
    if [[ ! -f "$PROMPT_FILE" ]]; then
      echo "Daily system prompt not found at $PROMPT_FILE" >&2
      exit 1
    fi
    ARGS+=("--system-prompt-file" "$PROMPT_FILE" "--run-cache-file" "$RUN_CACHE_FILE" "--no-skip-if-run")
    if [[ -n "${MINERVA_DAILY_ARGS:-}" ]]; then
      read -r -a EXTRA <<< "${MINERVA_DAILY_ARGS}"
      ARGS+=("${EXTRA[@]}")
    fi
    ;;
  *)
    echo "Unknown run mode: $MODE" >&2
    exit 2
    ;;
esac

if [[ -n "${MINERVA_SHARED_ARGS:-}" ]]; then
  read -r -a EXTRA <<< "${MINERVA_SHARED_ARGS}"
  ARGS+=("${EXTRA[@]}")
fi

if [[ $# -gt 0 ]]; then
  ARGS+=("$@")
fi

printf '[%s] Starting %s summary run\n' "$(date --iso-8601=seconds)" "$MODE" >&2
summarize-todos "${ARGS[@]}"
printf '[%s] Completed %s summary run\n' "$(date --iso-8601=seconds)" "$MODE" >&2
