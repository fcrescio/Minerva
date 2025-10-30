"""Fetch todo lists from Firestore and dump them to a JSON file."""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import FirebaseConfig
from ..logging_utils import configure_logging
from ..main import build_client
from ..pipeline import compute_run_markers, read_run_markers, serialise_todo_list
from ..todos import fetch_todo_lists

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch todo lists from Firestore and store them in a JSON file.",
    )
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
        "--summary-group",
        default=None,
        help="Only include sessions whose summaryGroup field matches this value.",
    )
    parser.add_argument(
        "--credentials",
        default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
        help=(
            "Optional path to a Google Cloud service account JSON file. "
            "Defaults to the GOOGLE_APPLICATION_CREDENTIALS environment variable."
        ),
    )
    parser.add_argument(
        "--output",
        default="todo_dump.json",
        help="Path to the JSON file where the todo lists will be stored.",
    )
    parser.add_argument(
        "--run-cache-file",
        default="summary_run_marker.txt",
        help=(
            "Path to the file where the pipeline stores the hash of the current "
            "date and todo set."
        ),
    )
    parser.add_argument(
        "--skip-if-run",
        dest="skip_if_run",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Skip output when the run cache file already contains the hash for "
            "today's todos. Disable with --no-skip-if-run."
        ),
    )
    parser.add_argument(
        "--log-level",
        default=None,
        help=(
            "Logging level (e.g. DEBUG, INFO). Defaults to the MINERVA_LOG_LEVEL "
            "environment variable or INFO when unset."
        ),
    )
    return parser.parse_args(argv)


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, Path)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serialisable")


def _write_dump(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    configure_logging(args.log_level)
    logger.debug("CLI arguments: %s", args)

    config = FirebaseConfig.from_google_services(args.config)
    credentials_path = args.credentials or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    client = build_client(config.project_id, credentials_path)

    todo_lists = fetch_todo_lists(
        client,
        args.collection,
        summary_group=args.summary_group,
    )
    logger.debug("Fetched %d todo lists for dumping", len(todo_lists))

    if not todo_lists:
        logger.info("No todo lists matched the requested filters")
        print("No todo lists found; nothing to dump.")
        return

    run_markers = compute_run_markers(todo_lists)

    cache_path = Path(args.run_cache_file) if args.run_cache_file else None
    if args.skip_if_run and cache_path and cache_path.exists():
        existing_markers = read_run_markers(cache_path)
        logger.debug(
            "Loaded %d existing run marker(s) from %s",
            len(existing_markers),
            cache_path,
        )
        todo_lists = [
            todo_list
            for todo_list in todo_lists
            if run_markers.get(todo_list.id) != existing_markers.get(todo_list.id)
        ]
        run_markers = {
            todo_list.id: run_markers[todo_list.id]
            for todo_list in todo_lists
        }
        if not todo_lists:
            logger.info("All todo lists match cached markers; skipping dump")
            print("Summary already generated for today's todos; skipping dump.")
            return

    payload: dict[str, Any] = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "collection": args.collection,
            "summary_group": args.summary_group,
            "run_cache_file": str(cache_path) if cache_path else None,
        },
        "run_markers": run_markers,
        "todo_lists": [serialise_todo_list(todo_list) for todo_list in todo_lists],
    }

    output_path = Path(args.output)
    _write_dump(output_path, payload)
    logger.info("Wrote todo dump to %s", output_path)
    print(f"Todo lists saved to {output_path}")


if __name__ == "__main__":  # pragma: no cover - manual execution
    main()
