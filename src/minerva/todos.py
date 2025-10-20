"""Utilities for retrieving and ordering todo lists and items from Firestore."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from google.cloud.firestore import Client, DocumentReference, DocumentSnapshot

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Todo:
    """Representation of a single todo item."""

    id: str
    title: str
    due_date: datetime | None
    status: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class TodoList:
    """Representation of a todo list document and its items."""

    id: str
    display_title: str
    data: dict[str, Any]
    todos: list[Todo]


def fetch_todo_lists(client: Client, collection: str) -> list[TodoList]:
    """Retrieve all todo lists from ``collection`` sorted by their natural order."""

    logger.debug("Fetching todo lists from collection '%s'", collection)
    documents = list(client.collection(collection).stream())
    logger.debug("Retrieved %d documents from Firestore", len(documents))
    todo_lists: list[TodoList] = []
    for document in documents:
        logger.debug("Processing document %s", document.id)
        todo_lists.append(_build_todo_list(document))
    return todo_lists


def _build_todo_list(document: DocumentSnapshot) -> TodoList:
    data = document.to_dict() or {}
    title = (
        data.get("name")
        or data.get("title")
        or data.get("label")
        or data.get("createdAt")
        or document.id
    )

    logger.debug("Normalised title for document %s: %s", document.id, title)
    todos = _fetch_todos(document)
    logger.debug("Document %s produced %d todos", document.id, len(todos))
    return TodoList(id=document.id, display_title=str(title), data=data, todos=todos)


def _fetch_todos(document: DocumentSnapshot) -> list[Todo]:
    notes_collection = document.reference.collection("notes")
    logger.debug("Streaming notes for document %s", document.id)
    snapshots = list(notes_collection.stream())
    logger.debug("Found %d notes in document %s", len(snapshots), document.id)
    todos: list[Todo] = []
    for snapshot in snapshots:
        data = snapshot.to_dict() or {}
        logger.debug("Inspecting note %s with keys %s", snapshot.id, sorted(data))
        if not _is_todo_data(data):
            logger.debug("Skipping note %s because it is not a todo", snapshot.id)
            continue
        todos.append(_build_todo(snapshot, data))
    todos.sort(key=_todo_sort_key)
    logger.debug("Sorted %d todos for document %s", len(todos), document.id)
    return todos


def _is_todo_data(data: dict[str, Any]) -> bool:
    todo_type = data.get("type")
    if isinstance(todo_type, str):
        match = todo_type.lower() == "todo"
        logger.debug("Todo type %r interpreted as todo=%s", todo_type, match)
        return match
    logger.debug("Todo type %r is not recognised as a todo", todo_type)
    return False


def _build_todo(snapshot: DocumentSnapshot, data: dict[str, Any] | None = None) -> Todo:
    if data is None:
        data = snapshot.to_dict() or {}
    title = (
        data.get("title")
        or data.get("name")
        or data.get("text")
        or data.get("content")
        or snapshot.id
    )
    due_date = _normalise_due_date(data.get("dueDate") or data.get("due_date"))
    status = _determine_status(data)
    metadata = {
        key: value
        for key, value in data.items()
        if key not in {"title", "name", "text", "content", "type"}
    }

    todo = Todo(
        id=snapshot.id,
        title=str(title),
        due_date=due_date,
        status=status,
        metadata=metadata,
    )
    logger.debug(
        "Built todo %s: title=%r due_date=%s status=%s metadata_keys=%s",
        snapshot.id,
        todo.title,
        todo.due_date,
        todo.status,
        sorted(todo.metadata),
    )
    return todo


def _todo_sort_key(todo: Todo) -> tuple[int, datetime, str]:
    due_date = todo.due_date or datetime.max.replace(tzinfo=timezone.utc)
    sort_key = (0 if todo.due_date else 1, due_date, todo.title.lower())
    logger.debug("Sort key for todo %s: %s", todo.id, sort_key)
    return sort_key


def _normalise_due_date(value: Any) -> datetime | None:
    """Return ``value`` as an aware ``datetime`` instance when possible."""

    if value is None:
        logger.debug("Normalising due date: value is None")
        return None
    if isinstance(value, datetime):
        normalised = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        logger.debug("Normalised datetime due date %s -> %s", value, normalised)
        return normalised
    if hasattr(value, "to_datetime"):
        dt = value.to_datetime()
        normalised = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        logger.debug("Normalised due date via to_datetime %s -> %s", value, normalised)
        return normalised
    if isinstance(value, (int, float)):
        normalised = datetime.fromtimestamp(value, tz=timezone.utc)
        logger.debug("Normalised numeric due date %s -> %s", value, normalised)
        return normalised
    if isinstance(value, str):
        for parser in (_parse_isoformat, _parse_rfc2822):
            parsed = parser(value)
            if parsed:
                logger.debug("Parsed string due date %r -> %s", value, parsed)
                return parsed
        logger.debug("Unable to parse string due date %r", value)
        return None
    logger.debug("Unsupported due date value %r", value)
    return None


def _parse_isoformat(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        logger.debug("Invalid ISO due date %r", value)
        return None
    normalised = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    logger.debug("Parsed ISO due date %r -> %s", value, normalised)
    return normalised


def _parse_rfc2822(value: str) -> datetime | None:
    try:
        from email.utils import parsedate_to_datetime
    except ImportError:  # pragma: no cover - stdlib import guard
        logger.debug("email.utils.parsedate_to_datetime not available")
        return None

    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        logger.debug("Invalid RFC2822 due date %r", value)
        return None
    if dt is None:
        logger.debug("parsedate_to_datetime returned None for %r", value)
        return None
    normalised = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    logger.debug("Parsed RFC2822 due date %r -> %s", value, normalised)
    return normalised


def _determine_status(data: dict[str, Any]) -> str:
    status = data.get("status")
    if isinstance(status, str) and status.strip():
        cleaned = status.strip()
        logger.debug("Determined status from explicit field: %r -> %s", status, cleaned)
        return cleaned

    for key in ("completed", "done"):
        if key in data:
            resolved = "completed" if bool(data[key]) else "pending"
            logger.debug("Determined status from %s=%r -> %s", key, data[key], resolved)
            return resolved

    logger.debug("Status could not be determined from data keys: %s", sorted(data))
    return "unknown"
