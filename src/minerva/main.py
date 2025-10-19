"""Command line entry point for listing sessions and notes stored in Firestore."""
from __future__ import annotations

import argparse
import os
from collections.abc import Iterable

from google.auth.credentials import AnonymousCredentials
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
    except DefaultCredentialsError:
        # Fall back to anonymous access when no credentials are available. This
        # allows read-only access to publicly readable Firestore instances or
        # local emulators without requiring service account credentials.
        return firestore.Client(project=project_id, credentials=AnonymousCredentials())


def format_session(doc: DocumentSnapshot) -> Table:
    """Build a ``rich`` table representing a session document."""
    data = doc.to_dict() or {}
    title = (
        data.get("name")
        or data.get("title")
        or data.get("startedAt")
        or data.get("createdAt")
        or doc.id
    )

    table = Table(title=f"Session: {title}")
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


def build_notes_table(doc: DocumentSnapshot) -> Table | None:
    """Return a table with the notes for ``doc`` if any are present."""

    notes_collection = doc.reference.collection("notes")
    notes = list(notes_collection.stream())
    if not notes:
        return None

    table = Table(title=f"Notes for session {doc.id}")
    table.add_column("Note ID")
    table.add_column("Content", overflow="fold")
    table.add_column("Metadata", overflow="fold")

    for note in notes:
        data = note.to_dict() or {}
        content = data.get("content") or data.get("text") or data.get("note") or "<empty>"
        metadata_items = [
            f"{key}={value!r}"
            for key, value in sorted(data.items())
            if key not in {"content", "text", "note"}
        ]
        metadata = ", ".join(metadata_items) or "<no metadata>"
        table.add_row(note.id, str(content), metadata)

    return table


def list_sessions(client: Client, collection: str) -> None:
    """Fetch sessions from Firestore and print them along with their notes."""
    documents = list(client.collection(collection).stream())
    if not documents:
        console.print(f"[yellow]No documents found in collection '{collection}'.")
        return

    console.print(f"[green]Found {len(documents)} session(s) in collection '{collection}'.")

    for document in documents:
        console.print(format_session(document))
        notes_table = build_notes_table(document)
        if notes_table:
            console.print(notes_table)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List sessions stored in Firestore.")
    parser.add_argument(
        "--config",
        default="google-services.json",
        help="Path to the google-services.json file shipped with Diana.",
    )
    parser.add_argument(
        "--collection",
        default="sessions",
        help="Name of the Firestore collection that stores sessions.",
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
    list_sessions(client, args.collection)


if __name__ == "__main__":  # pragma: no cover - manual execution
    main()
