"""Command line entry point for listing todo items stored in session notes."""
from __future__ import annotations

import argparse
import os
from collections.abc import Iterable, Mapping
from datetime import datetime

from google.auth.credentials import AnonymousCredentials
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import firestore
from google.cloud.firestore import Client
from rich.console import Console
from rich.table import Table

from .config import FirebaseConfig
from .todos import TodoList, fetch_todo_lists

console = Console()


def build_client(project_id: str, credentials_path: str | None = None) -> Client:
    """Create a Firestore client using the preferred credentials strategy."""
    if credentials_path:
        return firestore.Client.from_service_account_json(credentials_path, project=project_id)

    try:
        return firestore.Client(project=project_id)
    except DefaultCredentialsError:
        # Fall back to anonymous access when no credentials are available. This
        # allows read-only access to publicly readable Firestore instances or
        # local emulators without requiring service account credentials.
        return firestore.Client(project=project_id, credentials=AnonymousCredentials())


def _render_value(value: object) -> str:
    if isinstance(value, Mapping):
        items = ", ".join(f"{key}={val!r}" for key, val in sorted(value.items()))
        return items or "<empty mapping>"
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return ", ".join(map(str, value))
    return str(value)


def format_todo_list(todo_list: TodoList) -> Table:
    """Build a ``rich`` table describing the metadata of a todo list."""

    table = Table(title=f"Session: {todo_list.display_title}")
    table.add_column("Field")
    table.add_column("Value", overflow="fold")

    if not todo_list.data:
        table.add_row("<empty>", "<no fields>")
        return table

    for key, value in sorted(todo_list.data.items()):
        table.add_row(key, _render_value(value))

    return table


def build_todos_table(todo_list: TodoList) -> Table | None:
    """Return a table with the todos for ``todo_list`` if any are present."""

    if not todo_list.todos:
        return None

    table = Table(title=f"Todos for session {todo_list.id}")
    table.add_column("#")
    table.add_column("Title", overflow="fold")
    table.add_column("Due", overflow="fold")
    table.add_column("Status", overflow="fold")
    table.add_column("Metadata", overflow="fold")

    for index, todo in enumerate(todo_list.todos, start=1):
        due = todo.due_date.isoformat(timespec="minutes") if isinstance(todo.due_date, datetime) else "—"
        metadata_items = [f"id={todo.id}"] + [
            f"{key}={value!r}"
            for key, value in sorted(todo.metadata.items())
        ]
        metadata = ", ".join(metadata_items) or "<no metadata>"
        table.add_row(str(index), todo.title, due, todo.status, metadata)

    return table


def list_todos(client: Client, collection: str) -> None:
    """Fetch todo lists from Firestore and print them along with their items."""

    todo_lists = fetch_todo_lists(client, collection)
    if not todo_lists:
        console.print(f"[yellow]No documents found in collection '{collection}'.")
        return

    console.print(f"[green]Found {len(todo_lists)} session(s) in collection '{collection}'.")

    for todo_list in todo_lists:
        console.print(format_todo_list(todo_list))
        todos_table = build_todos_table(todo_list)
        if todos_table:
            console.print(todos_table)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List todo items stored in session notes.")
    parser.add_argument(
        "--config",
        default="google-services.json",
        help="Path to the google-services.json file shipped with Diana.",
    )
    parser.add_argument(
        "--collection",
        default="sessions",
        help="Name of the Firestore collection that stores the sessions.",
    )
    parser.add_argument(
        "--credentials",
        default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
        help=(
            "Optional path to a Google Cloud service account JSON file. "
            "Defaults to the GOOGLE_APPLICATION_CREDENTIALS environment variable."
        ),
    )
    return parser.parse_args(argv)



def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = FirebaseConfig.from_google_services(args.config)
    client = build_client(config.project_id, args.credentials)
    list_todos(client, args.collection)


if __name__ == "__main__":  # pragma: no cover - manual execution
    main()
