"""Generate a summary for previously dumped todo lists."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..logging_utils import configure_logging
from ..llm import DEFAULT_MODELS, summarize_with_groq, summarize_with_openrouter
from ..persistence import deserialise_todo_list, read_run_markers, write_run_markers
from ..prompts import load_system_prompt
from ..todos import TodoList

logger = logging.getLogger(__name__)


@dataclass
class TodoDump:
    todo_lists: list[TodoList]
    run_markers: dict[str, str]
    metadata: dict[str, Any]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a natural language summary for dumped todo lists.",
    )
    parser.add_argument(
        "--todos",
        default="todo_dump.json",
        help="Path to the JSON dump produced by fetch-todos.",
    )
    parser.add_argument(
        "--output",
        default="todo_summary.txt",
        help="Path to the file where the generated summary will be stored.",
    )
    parser.add_argument(
        "--provider",
        choices=sorted(DEFAULT_MODELS),
        default="openrouter",
        help="LLM provider to use for summarization.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model identifier to use for summarization. Defaults depend on the provider.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="Sampling temperature supplied to the chat completion request.",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=1024,
        help="Maximum number of tokens the model is allowed to generate.",
    )
    parser.add_argument(
        "--system-prompt-file",
        default=None,
        help="Path to a text file that overrides the default system prompt.",
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


def _load_dump(path: Path) -> TodoDump:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RuntimeError(f"Todo dump file not found: {path}")

    if not isinstance(payload, Mapping):
        raise RuntimeError("Todo dump file does not contain a JSON object")

    todos_payload = payload.get("todo_lists", [])
    todo_lists = []
    if isinstance(todos_payload, list):
        for item in todos_payload:
            if isinstance(item, Mapping):
                todo_lists.append(deserialise_todo_list(item))

    run_markers_payload = payload.get("run_markers", {})
    run_markers = (
        {str(key): str(value) for key, value in run_markers_payload.items()}
        if isinstance(run_markers_payload, Mapping)
        else {}
    )

    metadata_payload = payload.get("metadata", {})
    metadata = dict(metadata_payload) if isinstance(metadata_payload, Mapping) else {}

    return TodoDump(todo_lists=todo_lists, run_markers=run_markers, metadata=metadata)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    configure_logging(args.log_level)
    logger.debug("CLI arguments: %s", args)

    dump_path = Path(args.todos)
    dump = _load_dump(dump_path)
    if not dump.todo_lists:
        logger.info("Todo dump %s does not contain any lists to summarize", dump_path)
        print("Todo dump does not contain any lists to summarize.")
        return

    model = args.model or DEFAULT_MODELS[args.provider]
    logger.debug("Using provider %s with model %s", args.provider, model)

    try:
        system_prompt = load_system_prompt(args.system_prompt_file)
    except RuntimeError as exc:
        logger.error("Unable to load system prompt: %s", exc)
        print(str(exc), file=sys.stderr)
        return

    if args.provider == "groq":
        summary = summarize_with_groq(
            dump.todo_lists,
            model=model,
            temperature=args.temperature,
            max_output_tokens=args.max_output_tokens,
            system_prompt=system_prompt,
        )
    else:
        summary = summarize_with_openrouter(
            dump.todo_lists,
            model=model,
            temperature=args.temperature,
            max_output_tokens=args.max_output_tokens,
            system_prompt=system_prompt,
        )

    output_path = Path(args.output)
    output_path.write_text(summary, encoding="utf-8")
    logger.info("Summary written to %s", output_path)
    print(summary)

    run_cache_file = dump.metadata.get("run_cache_file")
    if run_cache_file and dump.run_markers:
        cache_path = Path(run_cache_file)
        existing_markers: dict[str, str] = {}
        if cache_path.exists():
            try:
                existing_markers = read_run_markers(cache_path)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Unable to read existing run markers from %s: %s", cache_path, exc)
        merged_markers = {**existing_markers, **dump.run_markers}
        write_run_markers(merged_markers, cache_path)
        logger.debug(
            "Persisted %d run markers to %s", len(merged_markers), cache_path
        )


if __name__ == "__main__":  # pragma: no cover - manual execution
    main()
