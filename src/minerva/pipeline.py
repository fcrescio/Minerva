"""Processing pipeline that summarises todos using an LLM provider."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable, Iterator

import httpx
from groq import Groq

from .config import FirebaseConfig
from .main import build_client
from .todos import Todo, TodoList, fetch_todo_lists

DEFAULT_MODELS = {
    "openrouter": "mistralai/mistral-nemo",
    "groq": "mixtral-8x7b-32768",
}

SYSTEM_PROMPT = (
    "You are a helpful assistant that generates concise summaries of todo lists. "
    "Highlight overdue or upcoming items and mention items lacking due dates when relevant. "
    "Provide the answer in natural speech to be read out loud. Do not use characters or text structures that can't be read out loud. "
    "Answer in italian language"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarise todos with an LLM via OpenRouter or Groq."
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
        "--credentials",
        default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
        help=(
            "Optional path to a Google Cloud service account JSON file. "
            "Defaults to the GOOGLE_APPLICATION_CREDENTIALS environment variable."
        ),
    )
    parser.add_argument(
        "--provider",
        choices=sorted(DEFAULT_MODELS),
        default="openrouter",
        help="LLM provider to use for summarisation.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model identifier to use for summarisation. Defaults depend on the provider.",
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
            {"role": "system", "content": SYSTEM_PROMPT},
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


def summarise_with_groq(
    todos: Iterable[TodoList],
    *,
    model: str,
    temperature: float = 0.2,
    max_output_tokens: int | None = None,
) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY environment variable is not set.")

    prompt = _build_prompt(todos)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    client = Groq(api_key=api_key)
    kwargs: dict[str, object] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "top_p": 1,
        "stream": True,
    }
    if max_output_tokens is not None:
        kwargs["max_completion_tokens"] = max_output_tokens

    completion = client.chat.completions.create(**kwargs)
    parts: list[str] = []
    for chunk in completion:
        delta = chunk.choices[0].delta.content
        if delta:
            parts.append(delta)

    return "".join(parts).strip()


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


def synthesise_speech(summary: str, *, output_filename: str = "todo-summary.wav") -> Path | None:
    """Generate a spoken rendition of ``summary`` using fal.ai.

    When the ``FAL_KEY`` environment variable or the ``fal-client`` dependency are
    missing, the function returns ``None`` without raising so the CLI keeps
    working as a text-only tool. The generated audio is stored in
    ``output_filename`` relative to the current working directory.
    """

    api_key = os.environ.get("FAL_KEY")
    if not api_key:
        print(
            "FAL_KEY environment variable is not set; skipping speech synthesis.",
            file=sys.stderr,
        )
        return None

    try:
        import fal_client
    except ImportError:  # pragma: no cover - optional dependency guard
        print(
            "fal-client is not installed; skipping speech synthesis.",
            file=sys.stderr,
        )
        return None

    if hasattr(fal_client, "api_key"):
        try:
            fal_client.api_key = api_key  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - defensive fallback
            pass

    def on_queue_update(update: object) -> None:
        if isinstance(update, fal_client.InProgress):  # type: ignore[attr-defined]
            for log in getattr(update, "logs", []) or []:
                message = log.get("message") if isinstance(log, dict) else None
                if message:
                    print(message, file=sys.stderr)

    try:
        result = fal_client.subscribe(  # type: ignore[call-arg]
            "fal-ai/vibevoice/7b",
            arguments={
                "script": summary,
                "speakers": [{"preset": "Anchen [ZH] (Background Music)"}],
                "cfg_scale": 1.3,
            },
            with_logs=True,
            on_queue_update=on_queue_update,
        )
    except Exception as exc:  # pragma: no cover - network call
        print(f"Failed to synthesise speech with fal.ai: {exc}", file=sys.stderr)
        return None

    audio_urls = list(_extract_audio_urls(result))
    if not audio_urls:
        print(
            "fal.ai response did not contain audio URLs; skipping speech synthesis.",
            file=sys.stderr,
        )
        return None

    output_path = Path(output_filename)
    audio_url = audio_urls[0]
    try:
        with httpx.Client(timeout=120.0) as client:  # pragma: no cover - network call
            response = client.get(audio_url)
            response.raise_for_status()
        output_path.write_bytes(response.content)
    except Exception as exc:  # pragma: no cover - network call
        print(f"Unable to download fal.ai audio: {exc}", file=sys.stderr)
        return None

    return output_path


def _extract_audio_urls(payload: object) -> Iterator[str]:
    """Yield audio URLs from the fal.ai response payload."""

    if isinstance(payload, dict):
        for key in ("audio", "audios"):
            if key in payload:
                yield from _extract_audio_urls(payload[key])
        for value in payload.values():
            if isinstance(value, (dict, list)):
                yield from _extract_audio_urls(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _extract_audio_urls(item)
    elif isinstance(payload, str):
        if payload.startswith("http"):
            yield payload
    elif isinstance(payload, tuple):  # pragma: no cover - defensive branch
        for item in payload:
            yield from _extract_audio_urls(item)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = FirebaseConfig.from_google_services(args.config)
    client = build_client(config.project_id, args.credentials)
    todo_lists = fetch_todo_lists(client, args.collection)
    if not todo_lists:
        print("No todo lists found; nothing to summarise.")
        return

    model = args.model or DEFAULT_MODELS[args.provider]

    if args.provider == "groq":
        summary = summarise_with_groq(
            todo_lists,
            model=model,
            temperature=args.temperature,
            max_output_tokens=args.max_output_tokens,
        )
    else:
        summary = summarise_with_openrouter(
            todo_lists,
            model=model,
            temperature=args.temperature,
            max_output_tokens=args.max_output_tokens,
        )
    print(summary)

    speech_path = synthesise_speech(summary)
    if speech_path:
        print(f"\nSpeech saved to: {speech_path}")


if __name__ == "__main__":  # pragma: no cover - manual execution
    main()
