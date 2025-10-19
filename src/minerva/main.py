"""Command line entry point for listing todo lists stored in Firestore."""
from __future__ import annotations

import argparse
import os
from collections.abc import Iterable

from google.auth.exceptions import DefaultCredentialsError
from google.cloud import firestore
from google.cloud.firestore import Client, DocumentSnapshot
from rich.console import Console
from rich.table import Table

from .config import FirebaseConfig

console = Console()


def build_client(project_id: str, credentials_path: str | None = None) -> Client:
    """Create a Firestore client using the preferred credentials strategy."""
    if credentials_path:
        return firestore.Client.from_service_account_json(credentials_path, project=project_id)

    try:
        return firestore.Client(project=project_id)
    except DefaultCredentialsError as exc:  # pragma: no cover - informative path
        hint = (
            "No Google Cloud credentials were found. Set the "
            "GOOGLE_APPLICATION_CREDENTIALS environment variable to a service "
            "account JSON file or pass --credentials."
        )
        raise RuntimeError(hint) from exc


def format_todo_list(doc: DocumentSnapshot) -> Table:
    """Build a ``rich`` table representing a todo list document."""
    data = doc.to_dict() or {}
    title = data.get("name") or data.get("title") or doc.id

    table = Table(title=f"Todo list: {title}")
    table.add_column("Field")
    table.add_column("Value", overflow="fold")

    if not data:
        table.add_row("<empty>", "<no fields>")
    else:
        for key, value in sorted(data.items()):
            if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
                rendered = ", ".join(map(str, value))
            else:
                rendered = str(value)
            table.add_row(key, rendered)

    return table


def stream_subcollections(doc: DocumentSnapshot) -> Iterable[Table]:
    """Yield tables for all nested todo items subcollections, if any."""
    for subcollection in doc.reference.collections():
        items = list(subcollection.stream())
        if not items:
            continue

        table = Table(title=f"Items in {subcollection.id} for list {doc.id}")
        table.add_column("Item ID")
        table.add_column("Fields", overflow="fold")

        for item in items:
            item_data = item.to_dict() or {}
            description = ", ".join(f"{k}={v!r}" for k, v in sorted(item_data.items())) or "<empty>"
            table.add_row(item.id, description)

        yield table


def list_todo_lists(client: Client, collection: str) -> None:
    """Fetch todo lists from Firestore and print them."""
    documents = list(client.collection(collection).stream())
    if not documents:
        console.print(f"[yellow]No documents found in collection '{collection}'.")
        return

    console.print(f"[green]Found {len(documents)} todo list(s) in collection '{collection}'.")

    for document in documents:
        console.print(format_todo_list(document))
        for table in stream_subcollections(document):
            console.print(table)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List todo lists stored in Firestore.")
    parser.add_argument(
        "--config",
        default="google-services.json",
        help="Path to the google-services.json file shipped with Diana.",
    )
    parser.add_argument(
        "--collection",
        default="todoLists",
        help="Name of the Firestore collection that stores todo lists.",
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
    list_todo_lists(client, args.collection)


if __name__ == "__main__":  # pragma: no cover - manual execution
    main()
