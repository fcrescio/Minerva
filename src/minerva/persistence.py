"""Persistence and serialisation helpers for todo data and run markers."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from .todos import Todo, TodoList

logger = logging.getLogger(__name__)


def compute_run_markers(todo_lists: Iterable[TodoList]) -> dict[str, str]:
    """Return hashes that uniquely identify today's todos per session."""

    today = datetime.now(timezone.utc).date().isoformat()
    markers: dict[str, str] = {}
    for todo_list in todo_lists:
        todos_payload = [serialise_todo(todo) for todo in todo_list.todos]
        payload = json.dumps(
            {"date": today, "document": todo_list.id, "todos": todos_payload},
            separators=(",", ":"),
            sort_keys=True,
        )
        markers[todo_list.id] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return markers


def serialise_todo(todo: Todo) -> dict[str, object]:
    """Return a JSON-serialisable representation of ``todo``."""

    return {
        "id": todo.id,
        "title": todo.title,
        "due_date": todo.due_date.isoformat(timespec="minutes") if todo.due_date else None,
        "status": todo.status,
        "metadata": {
            key: normalise_metadata_value(value)
            for key, value in sorted(todo.metadata.items())
        },
    }


def serialise_todo_list(todo_list: TodoList) -> dict[str, object]:
    """Return a serialisable mapping representing ``todo_list``."""

    return {
        "id": todo_list.id,
        "display_title": todo_list.display_title,
        "todos": [serialise_todo(todo) for todo in todo_list.todos],
    }


def deserialise_todo(payload: Mapping[str, object]) -> Todo:
    """Reconstruct a :class:`Todo` instance from ``payload``."""

    raw_due_date = payload.get("due_date")
    due_date: datetime | None
    if isinstance(raw_due_date, str) and raw_due_date:
        try:
            parsed = datetime.fromisoformat(raw_due_date)
        except ValueError:
            logger.debug("Unable to parse todo due date %r", raw_due_date)
            due_date = None
        else:
            due_date = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    else:
        due_date = None

    metadata = payload.get("metadata")
    metadata_mapping = dict(metadata) if isinstance(metadata, Mapping) else {}

    return Todo(
        id=str(payload.get("id", "")),
        title=str(payload.get("title", "")),
        due_date=due_date,
        status=str(payload.get("status", "")),
        metadata={str(key): value for key, value in metadata_mapping.items()},
    )


def deserialise_todo_list(payload: Mapping[str, object]) -> TodoList:
    """Reconstruct a :class:`TodoList` instance from ``payload``."""

    todos_payload = payload.get("todos")
    todos: list[Todo] = []
    if isinstance(todos_payload, Iterable):
        for item in todos_payload:
            if isinstance(item, Mapping):
                todos.append(deserialise_todo(item))

    return TodoList(
        id=str(payload.get("id", "")),
        display_title=str(payload.get("display_title", "")),
        data=dict(payload.get("data", {})) if isinstance(payload.get("data"), Mapping) else {},
        todos=todos,
    )


def normalise_metadata_value(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, datetime):
        return value.isoformat(timespec="minutes")
    return str(value)


def write_run_markers(markers: Mapping[str, str], path: Path) -> None:
    """Persist per-session run markers to ``path`` ensuring the directory exists."""

    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{session_id}\t{marker}" for session_id, marker in sorted(markers.items())]
    contents = "\n".join(lines)
    if lines:
        contents += "\n"
    path.write_text(contents, encoding="utf-8")


def read_run_markers(path: Path) -> dict[str, str]:
    """Return previously stored per-session run markers.

    Older single-marker files result in an empty mapping so that a fresh run
    regenerates the cache using the new format.
    """

    markers: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "\t" in line:
            session_id, marker = line.split("\t", 1)
        elif " " in line:
            session_id, marker = line.split(None, 1)
        else:
            logger.debug("Ignoring legacy run marker line without delimiter: %s", line)
            return {}
        markers[session_id] = marker.strip()
    return markers


__all__ = [
    "compute_run_markers",
    "deserialise_todo",
    "deserialise_todo_list",
    "normalise_metadata_value",
    "read_run_markers",
    "serialise_todo",
    "serialise_todo_list",
    "write_run_markers",
]
