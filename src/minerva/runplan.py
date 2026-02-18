"""Run-plan dataclasses with merge and validation helpers.

Merge semantics
---------------
* Scalar values: unit values override global values when provided.
* List values (``args``/``actions``): lists are **appended** in order
  ``global + unit``.
* Secret/token maps: per-key merge where unit values override matching
  global keys.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import shlex
import tomllib
from typing import Any, Mapping

_CRON_FIELD = re.compile(r"^(\*|\d+|\d+-\d+|\*/\d+|\d+(,\d+)+)$")
_ACTION_ALIASES = {"summarise": "summarize"}


def normalize_action_token(action: object) -> str:
    """Normalize action names to internal canonical tokens."""

    token = str(action).strip().lower()
    return _ACTION_ALIASES.get(token, token)


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation issue scoped to a plan key."""

    file_path: str
    unit_name: str
    key: str
    message: str

    def __str__(self) -> str:
        return (
            f"{self.file_path}: unit={self.unit_name!r} key={self.key!r}: {self.message}"
        )


class RunPlanValidationError(ValueError):
    """Raised when a run plan contains one or more validation issues."""

    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        super().__init__("\n".join(str(issue) for issue in issues))


@dataclass(frozen=True)
class GlobalConfig:
    """Global defaults applied to each unit before unit overrides."""

    mode: str | None = None
    args: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    tokens: dict[str, str] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)
    action_args: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class UnitConfig:
    """Configuration for one scheduled unit."""

    name: str
    schedule: str
    mode: str | None = None
    enabled: bool = True
    args: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    tokens: dict[str, str] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)
    action_args: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class RunPlan:
    """A validated run plan loaded from TOML or a plain mapping."""

    global_config: GlobalConfig = field(default_factory=GlobalConfig)
    units: list[UnitConfig] = field(default_factory=list)
    file_path: str = "<memory>"

    @classmethod
    def from_toml(cls, path: str | Path) -> "RunPlan":
        plan_path = Path(path)
        data = tomllib.loads(plan_path.read_text(encoding="utf-8"))
        return cls.from_mapping(data, file_path=str(plan_path))

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], *, file_path: str = "<memory>") -> "RunPlan":
        global_raw = raw.get("global")
        global_cfg = _build_global_config(global_raw if isinstance(global_raw, Mapping) else {})

        units_raw = raw.get("unit", [])
        units: list[UnitConfig] = []
        if isinstance(units_raw, list):
            for item in units_raw:
                if isinstance(item, Mapping):
                    units.append(_build_unit_config(item))

        plan = cls(global_config=global_cfg, units=units, file_path=file_path)
        plan.validate()
        return plan

    def merged_unit(self, unit: UnitConfig) -> UnitConfig:
        """Return a resolved unit with global defaults merged in."""

        mode = unit.mode if unit.mode is not None else self.global_config.mode
        args = [*self.global_config.args, *unit.args]
        actions = [*self.global_config.actions, *unit.actions]
        tokens = {**self.global_config.tokens, **unit.tokens}
        secrets = {**self.global_config.secrets, **unit.secrets}
        action_args = _merge_action_args(self.global_config.action_args, unit.action_args)

        return UnitConfig(
            name=unit.name,
            schedule=unit.schedule,
            mode=mode,
            enabled=unit.enabled,
            args=args,
            actions=actions,
            tokens=tokens,
            secrets=secrets,
            action_args=action_args,
        )

    def validate(self) -> None:
        """Validate invariants and raise :class:`RunPlanValidationError` on error."""

        issues: list[ValidationIssue] = []
        seen_names: set[str] = set()

        for idx, unit in enumerate(self.units):
            unit_name = unit.name.strip() or f"<unit[{idx}]>"

            if unit_name in seen_names:
                issues.append(
                    ValidationIssue(
                        file_path=self.file_path,
                        unit_name=unit_name,
                        key="name",
                        message="duplicate unit name",
                    )
                )
            seen_names.add(unit_name)

            if not _is_valid_five_field_cron(unit.schedule):
                issues.append(
                    ValidationIssue(
                        file_path=self.file_path,
                        unit_name=unit_name,
                        key="schedule",
                        message=(
                            "invalid cron expression; expected 5 fields "
                            "(minute hour day month weekday)"
                        ),
                    )
                )

            merged = self.merged_unit(unit)
            if not merged.actions:
                issues.append(
                    ValidationIssue(
                        file_path=self.file_path,
                        unit_name=unit_name,
                        key="actions",
                        message="must include at least one action",
                    )
                )

        if issues:
            raise RunPlanValidationError(issues)


def default_plan() -> dict[str, object]:
    """Return the built-in run plan used when no plan file exists."""

    return {
        "global": {},
        "unit": [
            {
                "name": "hourly",
                "schedule": "0 * * * *",
                "enabled": True,
                "mode": "hourly",
                "actions": ["fetch", "summarize", "publish"],
            },
            {
                "name": "daily",
                "schedule": "0 6 * * *",
                "enabled": True,
                "mode": "daily",
                "actions": ["fetch", "summarize", "publish", "podcast"],
            },
        ],
    }


def load_run_plan(path: str | Path) -> RunPlan:
    """Load and validate a run plan from TOML, or use the built-in default."""

    plan_path = Path(path)
    if plan_path.exists():
        return RunPlan.from_toml(plan_path)
    return RunPlan.from_mapping(default_plan(), file_path=str(plan_path))


def render_cron(plan_path: str | Path, *, system_cron: bool) -> str:
    """Render cron file contents for a validated run plan."""

    plan = load_run_plan(plan_path)
    lines = [
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "SHELL=/bin/bash",
        "",
        "# Redirect job output to the container log stream.",
    ]

    enabled_count = 0
    plan_path_text = str(plan_path)
    for unit in plan.units:
        if not unit.enabled:
            continue

        command = (
            f"/usr/local/bin/minerva-run unit {shlex.quote(unit.name)} "
            f"--plan {shlex.quote(plan_path_text)} >> /proc/1/fd/1 2>&1"
        )
        lines.append(f"# unit: {unit.name}")
        if system_cron:
            lines.append(f"{unit.schedule} root {command}")
        else:
            lines.append(f"{unit.schedule} {command}")
        enabled_count += 1

    if enabled_count == 0:
        lines.append("# No enabled units found in run plan.")

    return "\n".join(lines)


def _build_global_config(raw: Mapping[str, Any]) -> GlobalConfig:
    return GlobalConfig(
        mode=_as_optional_str(raw.get("mode")),
        args=_as_string_list(raw.get("args")),
        actions=_as_action_list(raw.get("actions")),
        tokens=_as_string_map(raw.get("tokens")),
        secrets=_as_string_map(raw.get("secrets")),
        action_args=_as_action_args_map(raw.get("action")),
    )


def _build_unit_config(raw: Mapping[str, Any]) -> UnitConfig:
    return UnitConfig(
        name=str(raw.get("name", "")).strip(),
        schedule=str(raw.get("schedule", "")).strip(),
        mode=_as_optional_str(raw.get("mode")),
        enabled=bool(raw.get("enabled", True)),
        args=_as_string_list(raw.get("args")),
        actions=_as_action_list(raw.get("actions")),
        tokens=_as_string_map(raw.get("tokens")),
        secrets=_as_string_map(raw.get("secrets")),
        action_args=_as_action_args_map(raw.get("action")),
    )


def _as_action_args_map(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, Mapping):
        return {}

    result: dict[str, list[str]] = {}
    for key, item in value.items():
        normalized_key = normalize_action_token(key)
        if not normalized_key:
            continue
        if isinstance(item, Mapping):
            result[normalized_key] = _as_string_list(item.get("args"))
    return result


def _merge_action_args(
    global_args: Mapping[str, list[str]], unit_args: Mapping[str, list[str]]
) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {
        key: [*values]
        for key, values in global_args.items()
    }
    for key, values in unit_args.items():
        merged[key] = [*merged.get(key, []), *values]
    return merged


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_action_list(value: Any) -> list[str]:
    return [normalize_action_token(item) for item in _as_string_list(value)]


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _as_string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for key, item in value.items():
        normalized_key = str(key).strip()
        normalized_value = str(item).strip()
        if normalized_key and normalized_value:
            result[normalized_key] = normalized_value
    return result


def _is_valid_five_field_cron(expr: str) -> bool:
    parts = expr.split()
    if len(parts) != 5:
        return False
    return all(_CRON_FIELD.match(part) for part in parts)
