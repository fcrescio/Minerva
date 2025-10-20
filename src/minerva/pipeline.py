"""Processing pipeline that summarises todos using an OpenRouter-hosted LLM."""
from __future__ import annotations

import argparse
import json
import os
from typing import Iterable

import httpx

from .config import FirebaseConfig
from .main import build_client
from .todos import Todo, TodoList, fetch_todo_lists

DEFAULT_MODEL = "mistralai/mistral-nemo"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarise todos with an LLM via OpenRouter.")
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
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Fully qualified OpenRouter model identifier to use for summarisation.",
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
        help=(
            "Maximum number of tokens the model is allowed to generate. "
            "OpenRouter requires this for some providers such as Anthropic."
        ),
    )
    return parser.parse_args(argv)


def summarise_with_openrouter(
    todos: Iterable[TodoList],
    *,
    model: str,
    temperature: float = 0.2,
    max_output_tokens: int | None = None,
) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY environment variable is not set.")

    prompt = _build_prompt(todos)
    payload: dict[str, object] = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant that generates concise summaries of todo lists. "
                    "Highlight overdue or upcoming items and mention items lacking due dates when relevant."
                    "Provide the answer in natural speech to be read out loud. Do not use characters or text structures that can't be read out loud."
                    "Answer in italian language"
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }

    if max_output_tokens is not None:
        payload["max_output_tokens"] = max_output_tokens

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("OPENROUTER_APP_URL", "https://github.com/fcrescio/Minerva"),
        "X-Title": os.environ.get("OPENROUTER_APP_TITLE", "Minerva Todo Summariser"),
    }

    print(headers)
    print(payload)
    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            content=json.dumps(payload),
        )
        response.raise_for_status()

    data = response.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:  # pragma: no cover - defensive fallback
        raise RuntimeError("Unexpected response from OpenRouter") from exc


def _build_prompt(todo_lists: Iterable[TodoList]) -> str:
    lines = ["Provide a summary for the following todo lists:"]
    for todo_list in todo_lists:
        lines.append(f"\nList: {todo_list.display_title} (id={todo_list.id})")
        if not todo_list.todos:
            lines.append("  - No todos recorded.")
            continue
        for todo in todo_list.todos:
            lines.append(_format_todo_for_prompt(todo))
    return "\n".join(lines)


def _format_todo_for_prompt(todo: Todo) -> str:
    headline = f"  - {todo.title}"
    parts: list[str] = []
    if todo.due_date:
        parts.append(f"due {todo.due_date.isoformat(timespec='minutes')}")
    else:
        parts.append("no due date")
    if todo.status:
        parts.append(f"status: {todo.status}")
    if todo.metadata:
        meta = ", ".join(f"{key}={value!r}" for key, value in sorted(todo.metadata.items()))
        parts.append(f"details: {meta}")
    details = ", ".join(parts)
    return f"{headline} ({details})"


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = FirebaseConfig.from_google_services(args.config)
    client = build_client(config.project_id, args.credentials)
    todo_lists = fetch_todo_lists(client, args.collection)
    if not todo_lists:
        print("No todo lists found; nothing to summarise.")
        return

    summary = summarise_with_openrouter(
        todo_lists,
        model=args.model,
        temperature=args.temperature,
        max_output_tokens=args.max_output_tokens,
    )
    print(summary)


if __name__ == "__main__":  # pragma: no cover - manual execution
    main()
