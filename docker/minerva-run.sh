#!/usr/bin/env bash
set -euo pipefail

# User-configurable environment variables
# ---------------------------------------
#   MINERVA_LOG_PATH              File to tee script output to.
#   MINERVA_DATA_DIR              Root data directory (defaults to /data).
#   MINERVA_STATE_DIR             Directory to store generated state.
#   MINERVA_UNIT_STATE_DIR        Directory to store state for the selected unit.
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

if [[ -f /etc/container.env ]]; then
  # shellcheck disable=SC1091
  source /etc/container.env
fi

INITIAL_SUBCOMMAND="${1:-}"
if [[ "$INITIAL_SUBCOMMAND" == "unit" || "$INITIAL_SUBCOMMAND" == "hourly" || "$INITIAL_SUBCOMMAND" == "daily" ]]; then
  if [[ -n "${MINERVA_LOG_PATH:-}" ]]; then
    exec >>"$MINERVA_LOG_PATH" 2>&1
  elif [[ -e /proc/1/fd/1 && -w /proc/1/fd/1 ]]; then
    exec >>/proc/1/fd/1 2>&1
  else
    exec >>/dev/stdout 2>&1
  fi
fi

log() {
  local unit_tag="${MINERVA_SELECTED_UNIT:-}"
  if [[ -n "$unit_tag" ]]; then
    printf '[%s] [minerva-run:%s] %s\n' "$(date --iso-8601=seconds)" "$unit_tag" "$*"
  else
    printf '[%s] [minerva-run] %s\n' "$(date --iso-8601=seconds)" "$*"
  fi
}

usage() {
  cat <<'USAGE'
Usage:
  minerva-run unit <name> [--plan <path>] [-- <summary args...>]
  minerva-run list-units [--plan <path>]
  minerva-run validate [--plan <path>]
  minerva-run render-cron [--system-cron] [--plan <path>]

Legacy compatibility:
  minerva-run hourly [--plan <path>] [-- <summary args...>]
  minerva-run daily [--plan <path>] [-- <summary args...>]
USAGE
}

apply_if_unset() {
  local name="$1"
  local value="$2"
  if [[ -z "${!name+x}" || -z "${!name}" ]]; then
    printf -v "$name" '%s' "$value"
    export "$name"
  fi
}

run_plan_command() {
  local command="$1"
  local plan_file="$2"
  local unit_name="${3:-}"

  local args=("$command" --plan "$plan_file")
  if [[ "$command" == "load-unit" && -n "$unit_name" ]]; then
    args+=(--unit "$unit_name")
  elif [[ "$command" == "render-cron" && "$unit_name" == "true" ]]; then
    args+=(--system-cron)
  fi

  python3 -m minerva.tools.runplan_env "${args[@]}"
}

SUBCOMMAND="${1:-}"
if [[ -z "$SUBCOMMAND" ]]; then
  usage
  exit 2
fi
shift || true

PLAN_FILE="${MINERVA_RUN_PLAN_FILE:-${MINERVA_DATA_DIR:-/data}/minerva-run-plan.toml}"
UNIT_NAME=""

if [[ "$SUBCOMMAND" == "hourly" || "$SUBCOMMAND" == "daily" ]]; then
  UNIT_NAME="$SUBCOMMAND"
  SUBCOMMAND="unit"
fi

case "$SUBCOMMAND" in
  list-units)
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
        *)
          log "Unknown argument for list-units: $1"
          usage
          exit 2
          ;;
      esac
    done
    run_plan_command "list-units" "$PLAN_FILE"
    exit 0
    ;;
  validate)
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
        *)
          log "Unknown argument for validate: $1"
          usage
          exit 2
          ;;
      esac
    done
    run_plan_command "validate" "$PLAN_FILE"
    exit $?
    ;;
  render-cron)
    SYSTEM_CRON="false"
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
        --system-cron)
          SYSTEM_CRON="true"
          shift
          ;;
        *)
          log "Unknown argument for render-cron: $1"
          usage
          exit 2
          ;;
      esac
    done
    run_plan_command "render-cron" "$PLAN_FILE" "$SYSTEM_CRON"
    exit $?
    ;;
  unit)
    if [[ -z "$UNIT_NAME" ]]; then
      UNIT_NAME="${1:-}"
      shift || true
    fi
    if [[ -z "$UNIT_NAME" ]]; then
      usage
      exit 2
    fi

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
    eval "$(run_plan_command "load-unit" "$PLAN_FILE" "$UNIT_NAME")"
    set -- "${EXTRA_ARGS[@]}"
    ;;
  *)
    usage
    exit 2
    ;;
esac

MODE="${MINERVA_SELECTED_MODE:-$UNIT_NAME}"
DATA_DIR="${MINERVA_DATA_DIR:-/data}"
STATE_DIR="${MINERVA_STATE_DIR:-$DATA_DIR/state}"
UNIT_STATE_DIR="${MINERVA_UNIT_STATE_DIR:-$STATE_DIR/units/${MINERVA_SELECTED_UNIT:-$UNIT_NAME}}"
PROMPTS_DIR="${MINERVA_PROMPTS_DIR:-$DATA_DIR/prompts}"
RUN_CACHE_FILE="${MINERVA_RUN_CACHE_FILE:-$UNIT_STATE_DIR/summary_run_marker.txt}"
TODO_DUMP_FILE="${MINERVA_TODO_DUMP_FILE:-$UNIT_STATE_DIR/todo_dump.json}"
SUMMARY_FILE="${MINERVA_SUMMARY_FILE:-$UNIT_STATE_DIR/todo_summary.txt}"
SPEECH_FILE="${MINERVA_SPEECH_FILE:-$UNIT_STATE_DIR/todo-summary.wav}"
PODCAST_TEXT_FILE="${MINERVA_PODCAST_TEXT_FILE:-$UNIT_STATE_DIR/random_podcast.txt}"
PODCAST_AUDIO_FILE="${MINERVA_PODCAST_AUDIO_FILE:-$UNIT_STATE_DIR/random-podcast.wav}"
PODCAST_TOPIC_FILE="${MINERVA_PODCAST_TOPIC_FILE:-$UNIT_STATE_DIR/random_podcast_topics.txt}"
PODCAST_PROMPT_TEMPLATE_FILE="${MINERVA_PODCAST_PROMPT_TEMPLATE_FILE:-}"

mkdir -p "$STATE_DIR"
mkdir -p "$UNIT_STATE_DIR"
mkdir -p   "$(dirname "$RUN_CACHE_FILE")"   "$(dirname "$TODO_DUMP_FILE")"   "$(dirname "$SUMMARY_FILE")"   "$(dirname "$SPEECH_FILE")"   "$(dirname "$PODCAST_TEXT_FILE")"   "$(dirname "$PODCAST_AUDIO_FILE")"   "$(dirname "$PODCAST_TOPIC_FILE")"

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
  local _target_name=$1
  local -n _target="$_target_name"
  local _env_name=$2
  local _env_value="${!_env_name:-}"
  if [[ -n "$_env_value" ]]; then
    read -r -a _extra <<< "$_env_value"
    _target+=("${_extra[@]}")
  fi
}

sanitize_key() {
  local value="$1"
  value="${value//[^[:alnum:]]/_}"
  value="${value##_}"
  value="${value%%_}"
  printf '%s' "${value^^}"
}

append_action_args() {
  local _target_name=$1
  local -n _target="$_target_name"
  local _action_name="$2"
  local _canonical_action
  _canonical_action="$(normalize_action_token "$_action_name")"
  local _env_name="MINERVA_ACTION_$(sanitize_key "$_canonical_action")_ARGS"
  append_args_from_env "$_target_name" "$_env_name"
}

append_sources_from_spec() {
  local _target_name=$1
  local -n _target="$_target_name"
  local _spec="$2"
  local _source

  if [[ -z "$_spec" ]]; then
    return
  fi

  for _source in $_spec; do
    if [[ "$_source" == ACTION:* ]]; then
      append_action_args "$_target_name" "${_source#ACTION:}"
    else
      append_args_from_env "$_target_name" "$_source"
    fi
  done
}

build_action_args() {
  local _action="$1"
  local -n _target=$2
  local _base_ref="${ACTION_BASE_REFS[$_action]}"
  local _mode_ref="${ACTION_MODE_REFS[$_action]}"
  local -n _base="$_base_ref"
  local -n _mode="$_mode_ref"

  _target=("${_base[@]}")
  _target+=("${_mode[@]}")
  append_sources_from_spec _target "${ACTION_GLOBAL_ENV_SOURCES[$_action]}"
  append_sources_from_spec _target "${ACTION_OVERRIDE_ENV_SOURCES[$_action]}"
}

normalize_action_token() {
  local _action="$1"
  if [[ "$_action" == "summarise" ]]; then
    printf 'summarize'
  else
    printf '%s' "$_action"
  fi
}

check_action_inputs() {
  local _action="$1"
  local _missing=false
  local _input

  for _input in ${ACTION_REQUIRED_INPUTS[$_action]}; do
    if [[ ! -f "$_input" ]]; then
      log "Skipping $_action: missing required input at $_input"
      _missing=true
      break
    fi
  done

  if [[ "$_missing" == "true" ]]; then
    return 1
  fi

  return 0
}

remove_action_outputs() {
  local _action="$1"
  local _output

  for _output in ${ACTION_CLEAN_OUTPUTS[$_action]}; do
    rm -f "$_output"
  done
}

check_action_outputs() {
  local _action="$1"
  local _output

  for _output in ${ACTION_REQUIRED_OUTPUTS[$_action]}; do
    if [[ ! -f "$_output" ]]; then
      log "$_action output not created at $_output; skipping downstream actions"
      return 1
    fi
  done

  return 0
}

if [[ "$MODE" == "hourly" ]]; then
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
elif [[ "$MODE" == "daily" ]]; then
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
fi

FETCH_ARGS=("--output" "$TODO_DUMP_FILE" "--run-cache-file" "$RUN_CACHE_FILE")
SUMMARY_ARGS=("--todos" "$TODO_DUMP_FILE" "--output" "$SUMMARY_FILE")
PUBLISH_ARGS=("--summary" "$SUMMARY_FILE" "--speech-output" "$SPEECH_FILE")
PODCAST_ARGS=("--output" "$PODCAST_TEXT_FILE" "--speech-output" "$PODCAST_AUDIO_FILE" "--topic-history-file" "$PODCAST_TOPIC_FILE")

if [[ -n "$CONFIG_PATH" ]]; then
  FETCH_ARGS=("--config" "$CONFIG_PATH" "${FETCH_ARGS[@]}")
fi

declare -A ACTION_COMMANDS=()
declare -A ACTION_BASE_REFS=()
declare -A ACTION_MODE_REFS=()
declare -A ACTION_REQUIRED_INPUTS=()
declare -A ACTION_CLEAN_OUTPUTS=()
declare -A ACTION_REQUIRED_OUTPUTS=()
declare -A ACTION_GLOBAL_ENV_SOURCES=()
declare -A ACTION_OVERRIDE_ENV_SOURCES=()
declare -A ACTION_LOG_MESSAGES=()

ACTION_COMMANDS[fetch]="fetch-todos"
ACTION_BASE_REFS[fetch]="FETCH_ARGS"
ACTION_MODE_REFS[fetch]="FETCH_MODE_ARGS"
ACTION_REQUIRED_INPUTS[fetch]=""
ACTION_CLEAN_OUTPUTS[fetch]="$TODO_DUMP_FILE"
ACTION_REQUIRED_OUTPUTS[fetch]="$TODO_DUMP_FILE"
ACTION_GLOBAL_ENV_SOURCES[fetch]="MINERVA_FETCH_ARGS"
ACTION_OVERRIDE_ENV_SOURCES[fetch]="ACTION:fetch"
ACTION_LOG_MESSAGES[fetch]="Fetching todos"

ACTION_COMMANDS[summarize]="summarize-todos"
ACTION_BASE_REFS[summarize]="SUMMARY_ARGS"
ACTION_MODE_REFS[summarize]="SUMMARY_MODE_ARGS"
ACTION_REQUIRED_INPUTS[summarize]="$TODO_DUMP_FILE"
ACTION_CLEAN_OUTPUTS[summarize]="$SUMMARY_FILE"
ACTION_REQUIRED_OUTPUTS[summarize]="$SUMMARY_FILE"
ACTION_GLOBAL_ENV_SOURCES[summarize]="MINERVA_SUMMARY_ARGS MINERVA_SHARED_ARGS"
ACTION_OVERRIDE_ENV_SOURCES[summarize]="ACTION:summarize"
ACTION_LOG_MESSAGES[summarize]="Generating summary"

ACTION_COMMANDS[publish]="publish-summary"
ACTION_BASE_REFS[publish]="PUBLISH_ARGS"
ACTION_MODE_REFS[publish]="PUBLISH_MODE_ARGS"
ACTION_REQUIRED_INPUTS[publish]="$SUMMARY_FILE"
ACTION_CLEAN_OUTPUTS[publish]=""
ACTION_REQUIRED_OUTPUTS[publish]=""
ACTION_GLOBAL_ENV_SOURCES[publish]="MINERVA_PUBLISH_ARGS"
ACTION_OVERRIDE_ENV_SOURCES[publish]="ACTION:publish"
ACTION_LOG_MESSAGES[publish]="Publishing summary"

ACTION_COMMANDS[podcast]="generate-podcast"
ACTION_BASE_REFS[podcast]="PODCAST_ARGS"
ACTION_MODE_REFS[podcast]="PODCAST_MODE_ARGS"
ACTION_REQUIRED_INPUTS[podcast]=""
ACTION_CLEAN_OUTPUTS[podcast]=""
ACTION_REQUIRED_OUTPUTS[podcast]=""
ACTION_GLOBAL_ENV_SOURCES[podcast]="MINERVA_PODCAST_ARGS MINERVA_PODCAST_TELEGRAM_ARGS"
ACTION_OVERRIDE_ENV_SOURCES[podcast]="ACTION:podcast"
ACTION_LOG_MESSAGES[podcast]="Generating random podcast"

if [[ -n "${MINERVA_PODCAST_LANGUAGE:-}" ]]; then
  PODCAST_ARGS+=("--language" "$MINERVA_PODCAST_LANGUAGE")
fi

if [[ -n "$PODCAST_PROMPT_TEMPLATE_FILE" ]]; then
  PODCAST_ARGS+=("--prompt-template-file" "$PODCAST_PROMPT_TEMPLATE_FILE")
fi

if [[ $# -gt 0 ]]; then
  SUMMARY_ARGS+=("$@")
fi

if [[ -n "${MINERVA_SELECTED_ACTIONS:-}" ]]; then
  read -r -a ACTIONS <<< "$MINERVA_SELECTED_ACTIONS"
else
  ACTIONS=("fetch" "summarize" "publish")
  if [[ "$MODE" == "daily" ]]; then
    ACTIONS+=("podcast")
  fi
fi

log "Starting unit run with mode=$MODE actions=${ACTIONS[*]}"

for action in "${ACTIONS[@]}"; do
  canonical_action="$(normalize_action_token "$action")"
  if [[ -z "${ACTION_COMMANDS[$canonical_action]+x}" ]]; then
    log "Unknown action '$action' for unit '${MINERVA_SELECTED_UNIT:-$UNIT_NAME}'"
    exit 2
  fi

  if ! check_action_inputs "$canonical_action"; then
    break
  fi

  log "${ACTION_LOG_MESSAGES[$canonical_action]}"
  remove_action_outputs "$canonical_action"

  action_command="${ACTION_COMMANDS[$canonical_action]}"
  action_args=()
  build_action_args "$canonical_action" action_args
  "$action_command" "${action_args[@]}"

  if ! check_action_outputs "$canonical_action"; then
    break
  fi
done

log "Completed unit run"
