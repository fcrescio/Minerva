"""Processing pipeline that summarises todos using an LLM provider."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Mapping

import httpx
from groq import Groq
from telegram import Bot
from telegram.error import TelegramError

from .todos import Todo, TodoList

logger = logging.getLogger(__name__)

DEFAULT_MODELS = {
    "openrouter": "mistralai/mistral-nemo",
    "groq": "mixtral-8x7b-32768",
}

SYSTEM_PROMPT = (
    "You are a helpful assistant that generates concise summaries of todo lists. "
    "Highlight overdue or upcoming items and mention items lacking due dates when relevant. "
    "Provide the summary as a podcast-like monologue . Be playful and creative with moderation."
    "Answer in italian language"
)


def summarise_with_openrouter(
    todos: Iterable[TodoList],
    *,
    model: str,
    temperature: float = 0.2,
    max_output_tokens: int | None = None,
    system_prompt: str = SYSTEM_PROMPT,
) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY environment variable is not set.")

    prompt = build_prompt(todos)
    logger.debug(
        "Submitting OpenRouter request with model=%s temperature=%s max_output_tokens=%s",
        model,
        temperature,
        max_output_tokens,
    )
    payload: dict[str, object] = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    }

    if max_output_tokens is not None:
        payload["max_output_tokens"] = max_output_tokens
        logger.debug("Set OpenRouter max_output_tokens to %s", max_output_tokens)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("OPENROUTER_APP_URL", "https://github.com/fcrescio/Minerva"),
        "X-Title": os.environ.get("OPENROUTER_APP_TITLE", "Minerva Todo Summariser"),
    }

    with httpx.Client(timeout=60.0) as client:
        logger.debug("Sending POST request to OpenRouter")
        response = client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            content=json.dumps(payload),
        )
        response.raise_for_status()
        logger.debug("OpenRouter request completed with status %s", response.status_code)

    data = response.json()
    logger.debug("OpenRouter response keys: %s", list(data) if isinstance(data, dict) else type(data))
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
    system_prompt: str = SYSTEM_PROMPT,
) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY environment variable is not set.")

    prompt = build_prompt(todos)
    logger.debug(
        "Submitting Groq request with model=%s temperature=%s max_output_tokens=%s",
        model,
        temperature,
        max_output_tokens,
    )
    messages = [
        {"role": "system", "content": system_prompt},
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
        logger.debug("Set Groq max_completion_tokens to %s", max_output_tokens)

    completion = client.chat.completions.create(**kwargs)
    parts: list[str] = []
    for chunk in completion:
        delta = chunk.choices[0].delta.content
        if delta:
            parts.append(delta)
            logger.debug("Received Groq delta chunk with %d characters", len(delta))

    return "".join(parts).strip()

def load_system_prompt(path: str | None) -> str:
    """Return the system prompt, optionally loaded from ``path``."""

    if not path:
        return SYSTEM_PROMPT

    prompt_path = Path(path)
    try:
        contents = prompt_path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - filesystem errors
        raise RuntimeError(
            f"Failed to read system prompt file {prompt_path}: {exc}"
        ) from exc

    stripped = contents.strip()
    if not stripped:
        raise RuntimeError(
            f"System prompt file {prompt_path} is empty after stripping whitespace."
        )

    return stripped


def build_prompt(todo_lists: Iterable[TodoList]) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    lines = [f"The current date and time is {today}","Provide a summary for the following todo lists:"]
    for todo_list in todo_lists:
        logger.debug("Adding todo list %s to prompt", todo_list.id)
        lines.append(f"\nList: {todo_list.display_title} (id={todo_list.id})")
        if not todo_list.todos:
            logger.debug("Todo list %s has no todos", todo_list.id)
            lines.append("  - No todos recorded.")
            continue
        for todo in todo_list.todos:
            lines.append(format_todo_for_prompt(todo))
    return "\n".join(lines)


def format_todo_for_prompt(todo: Todo) -> str:
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
    logger.debug(
        "Formatted todo %s for prompt: headline=%r details=%r",
        todo.id,
        headline,
        details,
    )
    return f"{headline} ({details})"


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


def synthesise_speech(summary: str, *, output_filename: str = "todo-summary.wav") -> Path | None:
    """Generate a spoken rendition of ``summary`` using fal.ai.

    When the ``FAL_KEY`` environment variable or the ``fal-client`` dependency are
    missing, the function returns ``None`` without raising so the CLI keeps
    working as a text-only tool. The generated audio is stored in
    ``output_filename`` relative to the current working directory.
    """

    logger.debug("Starting speech synthesis for summary with %d characters", len(summary))
    api_key = os.environ.get("FAL_KEY")
    if not api_key:
        logger.debug("FAL_KEY environment variable is missing; skipping speech synthesis")
        print(
            "FAL_KEY environment variable is not set; skipping speech synthesis.",
            file=sys.stderr,
        )
        return None

    try:
        import fal_client
    except ImportError:  # pragma: no cover - optional dependency guard
        logger.debug("fal-client dependency not available; skipping speech synthesis")
        print(
            "fal-client is not installed; skipping speech synthesis.",
            file=sys.stderr,
        )
        return None

    if hasattr(fal_client, "api_key"):
        try:
            fal_client.api_key = api_key  # type: ignore[attr-defined]
            logger.debug("Configured fal_client.api_key attribute")
        except Exception:  # pragma: no cover - defensive fallback
            logger.debug("Unable to assign fal_client.api_key attribute", exc_info=True)
            pass

    def on_queue_update(update: object) -> None:
        logger.debug("Received fal.ai queue update: %s", type(update))
        if isinstance(update, fal_client.InProgress):  # type: ignore[attr-defined]
            for log in getattr(update, "logs", []) or []:
                message = log.get("message") if isinstance(log, dict) else None
                if message:
                    logger.debug("fal.ai log message: %s", message)
                    print(message, file=sys.stderr)

    try:
        logger.debug("Subscribing to fal.ai synthesis stream")
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
        logger.debug("fal.ai subscribe() returned payload of type %s", type(result))
    except Exception as exc:  # pragma: no cover - network call
        logger.exception("Failed to synthesise speech with fal.ai")
        print(f"Failed to synthesise speech with fal.ai: {exc}", file=sys.stderr)
        return None

    audio_urls = list(extract_audio_urls(result))
    logger.debug("Extracted %d audio URL(s) from fal.ai response", len(audio_urls))
    if not audio_urls:
        logger.debug("fal.ai response payload contained no audio URLs: %r", result)
        print(
            "fal.ai response did not contain audio URLs; skipping speech synthesis.",
            file=sys.stderr,
        )
        return None

    output_path = Path(output_filename)
    audio_url = audio_urls[0]
    logger.debug("Downloading audio from %s to %s", audio_url, output_path)
    try:
        with httpx.Client(timeout=120.0) as client:  # pragma: no cover - network call
            response = client.get(audio_url)
            response.raise_for_status()
        output_path.write_bytes(response.content)
        logger.debug("Audio download completed successfully; %d bytes written", output_path.stat().st_size)
    except Exception as exc:  # pragma: no cover - network call
        logger.exception("Unable to download fal.ai audio")
        print(f"Unable to download fal.ai audio: {exc}", file=sys.stderr)
        return None

    return output_path


def convert_audio_to_ogg_opus(audio_path: Path) -> Path:
    """Convert ``audio_path`` to an OGG/Opus voice note for Telegram."""

    if audio_path.suffix.lower() == ".ogg":
        logger.debug("Audio already in OGG format: %s", audio_path)
        return audio_path

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise RuntimeError(
            "ffmpeg is required to convert audio to Telegram voice message format."
        )

    output_path = audio_path.with_suffix(".ogg")
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(audio_path),
        "-c:a",
        "libopus",
        "-b:a",
        "64k",
        "-ac",
        "1",
        str(output_path),
    ]

    logger.debug("Running ffmpeg to convert %s to %s", audio_path, output_path)
    try:
        subprocess.run(command, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:  # pragma: no cover - external tool
        logger.exception("ffmpeg failed with exit code %s", exc.returncode)
        raise RuntimeError("Failed to convert audio to OGG/Opus with ffmpeg") from exc

    logger.debug("ffmpeg conversion succeeded; generated %s", output_path)
    return output_path


def post_summary_to_telegram(
    audio_path: Path,
    *,
    token: str,
    chat_id: str,
    caption: str | None = None,
) -> None:
    """Upload ``audio_path`` to a Telegram chat using the provided bot credentials."""

    logger.debug("Posting audio %s to Telegram chat %s", audio_path, chat_id)
    if not audio_path.exists():
        raise FileNotFoundError(audio_path)

    caption_text = caption or "Todo summary"
    if len(caption_text) > 1024:
        caption_text = f"{caption_text[:1021]}..."
        logger.debug("Truncated caption to 1024 characters for Telegram")

    try:
        voice_path = convert_audio_to_ogg_opus(audio_path)
    except Exception:
        logger.exception("Unable to prepare audio for Telegram voice message")
        raise

    async def _send_voice_async() -> None:
        async with Bot(token=token) as bot:
            with open(voice_path, "rb") as voice_file:
                await bot.send_voice(
                    chat_id=chat_id,
                    voice=voice_file,
                    caption=caption_text,
                )

    try:
        asyncio.run(_send_voice_async())
        logger.debug("Telegram upload completed successfully")
    except TelegramError:
        logger.exception("Failed to send audio to Telegram")
        raise


def post_text_to_telegram(
    message: str,
    *,
    token: str,
    chat_id: str,
) -> None:
    """Send ``message`` to a Telegram chat using the provided bot credentials."""

    logger.debug("Posting text message to Telegram chat %s", chat_id)
    trimmed_message = message.strip()
    if not trimmed_message:
        raise ValueError("Telegram message must not be empty")

    if len(trimmed_message) > 4096:
        trimmed_message = f"{trimmed_message[:4093]}..."
        logger.debug("Truncated message to 4096 characters for Telegram")

    async def _send_message_async() -> None:
        async with Bot(token=token) as bot:
            await bot.send_message(chat_id=chat_id, text=trimmed_message)

    try:
        asyncio.run(_send_message_async())
        logger.debug("Telegram text message sent successfully")
    except TelegramError:
        logger.exception("Failed to send text message to Telegram")
        raise


def extract_audio_urls(payload: object) -> Iterator[str]:
    """Yield audio URLs from the fal.ai response payload."""

    if isinstance(payload, dict):
        logger.debug("Inspecting dict payload keys: %s", list(payload))
        for key in ("audio", "url"):
            if key in payload:
                yield from extract_audio_urls(payload[key])
        for value in payload.values():
            if isinstance(value, (dict, list)):
                yield from extract_audio_urls(value)
    elif isinstance(payload, list):
        logger.debug("Inspecting list payload with %d elements", len(payload))
        for item in payload:
            yield from extract_audio_urls(item)
    elif isinstance(payload, str):
        if payload.startswith("http"):
            logger.debug("Found audio URL candidate: %s", payload)
            yield payload
        else:
            logger.debug("Ignoring non-http string payload: %s", payload)
    elif isinstance(payload, tuple):  # pragma: no cover - defensive branch
        logger.debug("Inspecting tuple payload with %d elements", len(payload))
        for item in payload:
            yield from extract_audio_urls(item)
    else:
        logger.debug("Ignoring payload of type %s", type(payload))


__all__ = [
    "DEFAULT_MODELS",
    "SYSTEM_PROMPT",
    "build_prompt",
    "compute_run_markers",
    "convert_audio_to_ogg_opus",
    "deserialise_todo",
    "deserialise_todo_list",
    "extract_audio_urls",
    "format_todo_for_prompt",
    "load_system_prompt",
    "normalise_metadata_value",
    "post_summary_to_telegram",
    "post_text_to_telegram",
    "read_run_markers",
    "serialise_todo",
    "serialise_todo_list",
    "summarise_with_groq",
    "summarise_with_openrouter",
    "synthesise_speech",
    "write_run_markers",
]


