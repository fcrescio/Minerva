"""Utilities for retrieving and ordering todo lists and items from Firestore."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from google.cloud.firestore import Client, DocumentSnapshot


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

    documents = list(client.collection(collection).stream())
    todo_lists: list[TodoList] = []
    for document in documents:
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

    todos = _fetch_todos(document)
    return TodoList(id=document.id, display_title=str(title), data=data, todos=todos)


def _fetch_todos(document: DocumentSnapshot) -> list[Todo]:
    notes_collection = document.reference.collection("notes")
    snapshots = list(notes_collection.stream())
    todos: list[Todo] = []
    for snapshot in snapshots:
        data = snapshot.to_dict() or {}
        if not _is_todo_data(data):
            continue
        todos.append(_build_todo(snapshot, data))
    todos.sort(key=_todo_sort_key)
    return todos


def _is_todo_data(data: dict[str, Any]) -> bool:
    todo_type = data.get("type")
    if isinstance(todo_type, str):
        return todo_type.lower() == "todo"
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

    return Todo(
        id=snapshot.id,
        title=str(title),
        due_date=due_date,
        status=status,
        metadata=metadata,
    )


def _todo_sort_key(todo: Todo) -> tuple[int, datetime, str]:
    due_date = todo.due_date or datetime.max.replace(tzinfo=timezone.utc)
    return (0 if todo.due_date else 1, due_date, todo.title.lower())


def _normalise_due_date(value: Any) -> datetime | None:
    """Return ``value`` as an aware ``datetime`` instance when possible."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if hasattr(value, "to_datetime"):
        dt = value.to_datetime()
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        for parser in (_parse_isoformat, _parse_rfc2822):
            parsed = parser(value)
            if parsed:
                return parsed
        return None
    return None


def _parse_isoformat(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_rfc2822(value: str) -> datetime | None:
    try:
        from email.utils import parsedate_to_datetime
    except ImportError:  # pragma: no cover - stdlib import guard
        return None

    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _determine_status(data: dict[str, Any]) -> str:
    status = data.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()

    for key in ("completed", "done"):
        if key in data:
            return "completed" if bool(data[key]) else "pending"

    return "unknown"
