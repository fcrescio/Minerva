"""Processing pipeline that summarises todos using an LLM provider."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Mapping

import httpx
from groq import Groq
from telegram import Bot, InputFile
from telegram.error import TelegramError

from .config import FirebaseConfig
from .logging_utils import configure_logging
from .main import build_client
from .todos import Todo, TodoList, fetch_todo_lists

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
        "--summary-group",
        default=None,
        help="Only summarise sessions whose summaryGroup field matches this value.",
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
    parser.add_argument(
        "--speech",
        dest="speech",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Generate an audio narration of the summary using fal.ai. "
            "Disable with --no-speech."
        ),
    )
    parser.add_argument(
        "--telegram",
        dest="telegram",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Post the generated speech track to Telegram. Requires a bot token "
            "and target chat ID. Disable with --no-telegram."
        ),
    )
    parser.add_argument(
        "--skip-summary",
        dest="skip_summary",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Skip LLM summarisation and reuse an existing audio file when "
            "uploading to Telegram."
        ),
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
            "Skip summary generation when the run cache file already contains the "
            "hash for today's todos. Disable with --no-skip-if-run."
        ),
    )
    parser.add_argument(
        "--existing-audio",
        default="todo_summary.ogg",
        help=(
            "Path to an existing audio file to upload when --skip-summary is "
            "enabled."
        ),
    )
    parser.add_argument(
        "--telegram-token",
        default=os.environ.get("TELEGRAM_BOT_TOKEN"),
        help=(
            "Telegram bot token. Defaults to the TELEGRAM_BOT_TOKEN environment "
            "variable."
        ),
    )
    parser.add_argument(
        "--telegram-chat-id",
        default=os.environ.get("TELEGRAM_CHAT_ID"),
        help=(
            "Telegram chat or channel ID where the audio should be posted. "
            "Defaults to the TELEGRAM_CHAT_ID environment variable."
        ),
    )
    return parser.parse_args(argv)


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

    prompt = _build_prompt(todos)
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

    prompt = _build_prompt(todos)
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

def _load_system_prompt(path: str | None) -> str:
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


def _build_prompt(todo_lists: Iterable[TodoList]) -> str:
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
    logger.debug(
        "Formatted todo %s for prompt: headline=%r details=%r",
        todo.id,
        headline,
        details,
    )
    return f"{headline} ({details})"


def _compute_run_markers(todo_lists: Iterable[TodoList]) -> dict[str, str]:
    """Return hashes that uniquely identify today's todos per session."""

    today = datetime.now(timezone.utc).date().isoformat()
    markers: dict[str, str] = {}
    for todo_list in todo_lists:
        todos_payload = [_serialise_todo(todo) for todo in todo_list.todos]
        payload = json.dumps(
            {"date": today, "document": todo_list.id, "todos": todos_payload},
            separators=(",", ":"),
            sort_keys=True,
        )
        markers[todo_list.id] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return markers


def _serialise_todo(todo: Todo) -> dict[str, object]:
    """Return a JSON-serialisable representation of ``todo``."""

    return {
        "id": todo.id,
        "title": todo.title,
        "due_date": todo.due_date.isoformat(timespec="minutes") if todo.due_date else None,
        "status": todo.status,
        "metadata": {
            key: _normalise_metadata_value(value)
            for key, value in sorted(todo.metadata.items())
        },
    }


def _normalise_metadata_value(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, datetime):
        return value.isoformat(timespec="minutes")
    return str(value)


def _write_run_markers(markers: Mapping[str, str], path: Path) -> None:
    """Persist per-session run markers to ``path`` ensuring the directory exists."""

    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{session_id}\t{marker}" for session_id, marker in sorted(markers.items())]
    contents = "\n".join(lines)
    if lines:
        contents += "\n"
    path.write_text(contents, encoding="utf-8")


def _read_run_markers(path: Path) -> dict[str, str]:
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

    audio_urls = list(_extract_audio_urls(result))
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
            voice_file = open(voice_path,"rb")
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


def _extract_audio_urls(payload: object) -> Iterator[str]:
    """Yield audio URLs from the fal.ai response payload."""

    if isinstance(payload, dict):
        logger.debug("Inspecting dict payload keys: %s", list(payload))
        for key in ("audio", "url"):
            if key in payload:
                yield from _extract_audio_urls(payload[key])
        for value in payload.values():
            if isinstance(value, (dict, list)):
                yield from _extract_audio_urls(value)
    elif isinstance(payload, list):
        logger.debug("Inspecting list payload with %d elements", len(payload))
        for item in payload:
            yield from _extract_audio_urls(item)
    elif isinstance(payload, str):
        if payload.startswith("http"):
            logger.debug("Found audio URL candidate: %s", payload)
            yield payload
        else:
            logger.debug("Ignoring non-http string payload: %s", payload)
    elif isinstance(payload, tuple):  # pragma: no cover - defensive branch
        logger.debug("Inspecting tuple payload with %d elements", len(payload))
        for item in payload:
            yield from _extract_audio_urls(item)
    else:
        logger.debug("Ignoring payload of type %s", type(payload))


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    configure_logging(args.log_level)
    logger.debug("CLI arguments: %s", args)
    summary: str | None = None
    summary_timestamp: datetime | None = None
    speech_path: Path | None
    run_markers: dict[str, str] | None = None
    cache_path: Path | None = None

    if args.skip_summary:
        speech_path = Path(args.existing_audio)
        logger.debug("Skipping summary generation; using audio file %s", speech_path)
        if not speech_path.exists():
            print(
                f"Existing audio file not found: {speech_path}",
                file=sys.stderr,
            )
            return
    else:
        config = FirebaseConfig.from_google_services(args.config)
        client = build_client(config.project_id, args.credentials)
        todo_lists = fetch_todo_lists(
            client,
            args.collection,
            summary_group=args.summary_group,
        )
        logger.debug("Fetched %d todo lists for summarisation", len(todo_lists))
        if not todo_lists:
            if args.summary_group:
                print(
                    "No todo lists found for summary group "
                    f"'{args.summary_group}'; nothing to summarise."
                )
            else:
                print("No todo lists found; nothing to summarise.")
            return

        if args.run_cache_file:
            cache_path = Path(args.run_cache_file)
            run_markers = _compute_run_markers(todo_lists)
            logger.debug(
                "Computed run markers for %d session(s)",
                len(run_markers),
            )
            if args.skip_if_run and cache_path.exists():
                existing_markers = _read_run_markers(cache_path)
                logger.debug(
                    "Loaded %d existing run marker(s) from %s",
                    len(existing_markers),
                    cache_path,
                )
                unchanged_sessions = {
                    session_id
                    for session_id, marker in run_markers.items()
                    if existing_markers.get(session_id) == marker
                }
                if unchanged_sessions:
                    logger.info(
                        "Skipping %d unchanged session(s): %s",
                        len(unchanged_sessions),
                        ", ".join(sorted(unchanged_sessions)),
                    )
                todo_lists = [
                    todo_list
                    for todo_list in todo_lists
                    if run_markers.get(todo_list.id)
                    != existing_markers.get(todo_list.id)
                ]
                if not todo_lists:
                    logger.info(
                        "Run markers already present for all sessions; skipping summary generation"
                    )
                    print("Summary already generated for today's todos; skipping.")
                    return
                if unchanged_sessions:
                    print(
                        "Skipping sessions with unchanged todos: "
                        + ", ".join(sorted(unchanged_sessions))
                    )

        model = args.model or DEFAULT_MODELS[args.provider]
        logger.debug("Using provider %s with model %s", args.provider, model)

        try:
            system_prompt = _load_system_prompt(args.system_prompt_file)
        except RuntimeError as exc:
            logger.error("Unable to load system prompt: %s", exc)
            print(str(exc), file=sys.stderr)
            return

        if args.provider == "groq":
            summary = summarise_with_groq(
                todo_lists,
                model=model,
                temperature=args.temperature,
                max_output_tokens=args.max_output_tokens,
                system_prompt=system_prompt,
            )
        else:
            summary = summarise_with_openrouter(
                todo_lists,
                model=model,
                temperature=args.temperature,
                max_output_tokens=args.max_output_tokens,
                system_prompt=system_prompt,
            )
        summary_timestamp = datetime.now(timezone.utc)
        logger.debug("Generated summary with %d characters", len(summary))
        print(summary)

        if cache_path and run_markers:
            _write_run_markers(run_markers, cache_path)
            logger.debug("Persisted run markers to %s", cache_path)

        if args.speech:
            speech_path = synthesise_speech(summary)
            if speech_path:
                logger.debug("Speech synthesis successful: %s", speech_path)
                print(f"\nSpeech saved to: {speech_path}")
            else:
                logger.debug("Speech synthesis skipped or failed")
        else:
            logger.debug("Speech synthesis disabled via CLI option")
            speech_path = None

    if args.telegram:
        if not speech_path:
            logger.debug("Telegram upload requested but no speech file is available")
            print(
                "Telegram upload requested but no speech file was generated.",
                file=sys.stderr,
            )
        elif not args.telegram_token or not args.telegram_chat_id:
            logger.debug("Telegram credentials are missing; skipping upload")
            print(
                "Telegram bot token or chat ID missing; skipping Telegram upload.",
                file=sys.stderr,
            )
        else:
            try:
                post_summary_to_telegram(
                    speech_path,
                    token=args.telegram_token,
                    chat_id=args.telegram_chat_id,
                    caption=(
                        summary_timestamp.isoformat()
                        if summary_timestamp
                        else datetime.now(timezone.utc).isoformat()
                    ),
                )
                print("Telegram upload completed successfully.")
            except TelegramError as exc:
                print(f"Failed to upload summary to Telegram: {exc}", file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover - manual execution
    main()
