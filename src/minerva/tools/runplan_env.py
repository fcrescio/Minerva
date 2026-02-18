from __future__ import annotations

import argparse
import re
import shlex
import sys
import tomllib
from pathlib import Path
from typing import Any, Mapping

from minerva.runplan import RunPlanValidationError, default_plan, load_run_plan, render_cron


_PATHS_MAP = {
    "data_dir": "MINERVA_DATA_DIR",
    "state_dir": "MINERVA_STATE_DIR",
    "unit_state_dir": "MINERVA_UNIT_STATE_DIR",
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

_OPTIONS_MAP = {
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


class UnitLookupError(ValueError):
    pass


def _table(cfg: Mapping[str, object], key: str) -> dict[str, object]:
    value = cfg.get(key, {})
    return dict(value) if isinstance(value, Mapping) else {}


def _merge_dicts(a: Mapping[str, object], b: Mapping[str, object]) -> dict[str, object]:
    result = dict(a)
    result.update(b)
    return result


def sanitize_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()


def _emit(name: str, value: object) -> str:
    return f"apply_if_unset {shlex.quote(name)} {shlex.quote(str(value))}"


def _load_raw_plan(plan_file: str | Path) -> dict[str, object]:
    plan_path = Path(plan_file)
    if not plan_path.exists():
        return default_plan()
    with plan_path.open("rb") as handle:
        parsed = tomllib.load(handle)
    return parsed if isinstance(parsed, dict) else default_plan()


def _selected_raw_unit(raw_plan: Mapping[str, object], unit_name: str) -> dict[str, object]:
    units_raw = raw_plan.get("unit", [])
    if not isinstance(units_raw, list):
        return {}
    for item in units_raw:
        if isinstance(item, Mapping) and str(item.get("name", "")).strip() == unit_name:
            return dict(item)
    return {}


def _merge_action_tables(a: Mapping[str, object], b: Mapping[str, object]) -> dict[str, object]:
    merged_table = dict(a)
    for key, value in b.items():
        key_text = str(key).strip()
        if not key_text:
            continue
        global_entry = merged_table.get(key_text, {})
        global_args: list[str] = []
        if isinstance(global_entry, Mapping):
            global_raw = global_entry.get("args", [])
            if isinstance(global_raw, list):
                global_args = [str(item).strip() for item in global_raw if str(item).strip()]
        unit_args: list[str] = []
        if isinstance(value, Mapping):
            unit_raw = value.get("args", [])
            if isinstance(unit_raw, list):
                unit_args = [str(item).strip() for item in unit_raw if str(item).strip()]
        merged_table[key_text] = {"args": [*global_args, *unit_args]}
    return merged_table


def derive_unit_exports(plan_file: str | Path, unit_name: str) -> list[str]:
    plan = load_run_plan(plan_file)
    selected = next((unit for unit in plan.units if unit.name == unit_name), None)
    if selected is None:
        raise UnitLookupError(f"Run unit {unit_name!r} not found in plan {str(plan_file)!r}")

    raw = _load_raw_plan(plan_file)
    global_cfg = raw.get("global", {}) if isinstance(raw, Mapping) else {}
    if not isinstance(global_cfg, Mapping):
        global_cfg = {}
    selected_raw = _selected_raw_unit(raw, unit_name)

    merged = plan.merged_unit(selected)
    merged_env = _merge_dicts(_table(global_cfg, "env"), _table(selected_raw, "env"))
    merged_paths = _merge_dicts(_table(global_cfg, "paths"), _table(selected_raw, "paths"))
    merged_options = _merge_dicts(_table(global_cfg, "options"), _table(selected_raw, "options"))
    merged_providers = _merge_dicts(_table(global_cfg, "providers"), _table(selected_raw, "providers"))
    merged_tokens = _merge_dicts(_table(global_cfg, "tokens"), _table(selected_raw, "tokens"))
    merged_action_cfg = _merge_action_tables(_table(global_cfg, "action"), _table(selected_raw, "action"))

    if "config_path" in merged_options:
        merged_paths["config_path"] = merged_options.pop("config_path")

    mode = merged.mode or merged.name
    actions = merged.actions
    if not actions:
        actions = ["fetch", "summarize", "publish", "podcast"] if str(mode) == "daily" else ["fetch", "summarize", "publish"]

    lines: list[str] = []
    for key, value in merged_env.items():
        key_text = str(key)
        env_name = key_text if key_text.isupper() else sanitize_key(key_text)
        lines.append(_emit(env_name, value))

    for key, value in merged_paths.items():
        key_text = str(key)
        env_name = _PATHS_MAP.get(key_text, f"MINERVA_{sanitize_key(key_text)}")
        lines.append(_emit(env_name, value))

    for key, value in merged_options.items():
        key_text = str(key)
        env_name = _OPTIONS_MAP.get(
            key_text,
            key_text if key_text.startswith("MINERVA_") else f"MINERVA_{sanitize_key(key_text)}",
        )
        lines.append(_emit(env_name, value))

    for key, value in merged_providers.items():
        lines.append(_emit(f"MINERVA_PROVIDER_{sanitize_key(str(key))}", value))

    for key, value in merged_tokens.items():
        lines.append(_emit(f"MINERVA_TOKEN_{sanitize_key(str(key))}", value))

    lines.append(f"export MINERVA_SELECTED_ACTIONS={shlex.quote(' '.join(str(item).strip() for item in actions if str(item).strip()))}")

    for action_name, action_cfg in merged_action_cfg.items():
        if not isinstance(action_cfg, Mapping):
            continue
        args_raw = action_cfg.get("args", [])
        if not isinstance(args_raw, list):
            continue
        normalized = [str(item).strip() for item in args_raw if str(item).strip()]
        if normalized:
            lines.append(_emit(f"MINERVA_ACTION_{sanitize_key(str(action_name))}_ARGS", " ".join(normalized)))

    lines.append(f"export MINERVA_SELECTED_MODE={shlex.quote(str(mode))}")
    lines.append(f"export MINERVA_SELECTED_UNIT={shlex.quote(unit_name)}")
    return lines


def _print_generic_error(exc: Exception) -> int:
    if isinstance(exc, tomllib.TOMLDecodeError):
        print(f"TOML parse error: {exc}", file=sys.stderr)
    else:
        print(str(exc), file=sys.stderr)
    return 2


def _print_validation_error(plan_file: str, exc: RunPlanValidationError) -> int:
    print(f"Run plan validation failed for {plan_file}", file=sys.stderr)
    for issue in exc.issues:
        print(f" - {issue}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m minerva.tools.runplan_env")
    parser.add_argument("command", choices=["load-unit", "list-units", "validate", "render-cron"])
    parser.add_argument("--plan", required=True)
    parser.add_argument("--unit")
    parser.add_argument("--system-cron", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "render-cron":
        try:
            print(render_cron(args.plan, system_cron=args.system_cron))
        except RunPlanValidationError as exc:
            return _print_validation_error(args.plan, exc)
        except Exception as exc:
            return _print_generic_error(exc)
        return 0

    try:
        plan = load_run_plan(args.plan)
    except RunPlanValidationError as exc:
        if args.command == "load-unit":
            print(f"echo {shlex.quote('Run plan validation failed')} >&2")
            for issue in exc.issues:
                print(f"echo {shlex.quote(f' - {issue}')} >&2")
            print("exit 2")
            return 0
        return _print_validation_error(args.plan, exc)
    except Exception as exc:
        if args.command == "load-unit":
            print(f"echo {shlex.quote('Run plan validation failed')} >&2")
            print(f"echo {shlex.quote(f' - {exc}')} >&2")
            print("exit 2")
            return 0
        return _print_generic_error(exc)

    if args.command == "list-units":
        print("name\tschedule\tenabled\tmode")
        for unit in plan.units:
            mode = unit.mode or plan.global_config.mode or unit.name
            print(f"{unit.name}\t{unit.schedule}\t{unit.enabled}\t{mode}")
        return 0

    if args.command == "validate":
        print("Run plan is valid")
        return 0

    if not args.unit:
        parser.error("--unit is required for load-unit")

    try:
        print("\n".join(derive_unit_exports(args.plan, args.unit)))
    except UnitLookupError as exc:
        print(f"echo {shlex.quote(str(exc))} >&2")
        print("exit 2")
    except RunPlanValidationError as exc:
        print(f"echo {shlex.quote('Run plan validation failed')} >&2")
        for issue in exc.issues:
            print(f"echo {shlex.quote(f' - {issue}')} >&2")
        print("exit 2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
