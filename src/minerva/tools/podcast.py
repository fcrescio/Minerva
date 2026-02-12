"""Generate a short, random podcast script and optional narration audio."""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path

from ..logging_utils import configure_logging
from ..pipeline import (
    DEFAULT_MODELS,
    generate_random_podcast_script,
    post_summary_to_telegram,
    post_text_to_telegram,
    synthesise_speech,
)

logger = logging.getLogger(__name__)


DEFAULT_TEXT_OUTPUT = "random_podcast.txt"
DEFAULT_AUDIO_OUTPUT = "random-podcast.wav"
DEFAULT_TOPIC_HISTORY_OUTPUT = "random_podcast_topics.txt"


def normalize_topic_summary(text: str, *, max_length: int = 160) -> str:
    """Return a compact, one-line topic summary suitable for history tracking."""

    clean = re.sub(r"\s+", " ", text).strip(" -:\t")
    if len(clean) <= max_length:
        return clean
    return clean[: max_length - 1].rstrip() + "…"


def summarize_generated_topic(script_text: str) -> str:
    """Extract a one-line topic summary from a generated podcast script."""

    lines = [line.strip() for line in script_text.splitlines() if line.strip()]
    if not lines:
        return "Untitled topic"

    first_line = lines[0]
    lowered = first_line.lower()
    if lowered.startswith("title:"):
        title = first_line.split(":", 1)[1].strip()
        if title:
            return normalize_topic_summary(title)

    return normalize_topic_summary(first_line)


def load_topic_history(path: Path, *, max_entries: int) -> list[str]:
    """Read previously generated one-line topic summaries from disk."""

    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    except FileNotFoundError:
        return []

    topics = [line for line in lines if line]
    if max_entries <= 0:
        return topics
    return topics[-max_entries:]


def save_topic_history(path: Path, topics: list[str]) -> None:
    """Persist one-line topic summaries to disk."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(topics) + "\n", encoding="utf-8")


def resolve_telegram_chat_ids(raw_values: list[str] | None) -> list[str]:
    """Return cleaned Telegram chat IDs parsed from CLI flags or env vars."""

    if not raw_values:
        return []

    chat_ids: list[str] = []
    for raw_value in raw_values:
        for value in raw_value.split(","):
            chat_id = value.strip()
            if chat_id:
                chat_ids.append(chat_id)
    return chat_ids


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a short podcast on a random topic using OpenRouter and fal.ai.",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_TEXT_OUTPUT,
        help="Path to the text file where the generated script will be stored.",
    )
    parser.add_argument(
        "--speech-output",
        default=DEFAULT_AUDIO_OUTPUT,
        help="Path to the audio file that will store the narrated script.",
    )
    parser.add_argument(
        "--speech",
        dest="speech",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable or disable speech synthesis via fal.ai.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="OpenRouter model identifier to use. Defaults to the configured provider default.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.7,
        help="Sampling temperature supplied to the chat completion request.",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=800,
        help="Maximum number of tokens the model is allowed to generate.",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Optional language to write and narrate the podcast in (e.g. italian, french).",
    )
    parser.add_argument(
        "--topic-history-file",
        default=DEFAULT_TOPIC_HISTORY_OUTPUT,
        help="Path to the file that stores one-line summaries of previous podcast topics.",
    )
    parser.add_argument(
        "--topic-history-limit",
        type=int,
        default=25,
        help="Number of recent topics to include in the next generation prompt.",
    )
    parser.add_argument(
        "--telegram",
        dest="telegram",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Post the generated podcast to Telegram (voice if available, otherwise text).",
    )
    parser.add_argument(
        "--telegram-token",
        default=None,
        help="Telegram bot token. Defaults to the TELEGRAM_BOT_TOKEN environment variable.",
    )
    parser.add_argument(
        "--telegram-chat-id",
        action="append",
        default=None,
        help=(
            "Telegram chat or channel ID where the podcast should be posted. "
            "Pass the flag multiple times or provide a comma-separated list "
            "to post to multiple channels."
        ),
    )
    parser.add_argument(
        "--caption",
        default=None,
        help="Optional caption to include with the Telegram message.",
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


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    configure_logging(args.log_level)
    logger.debug("CLI arguments: %s", args)

    model = args.model or DEFAULT_MODELS["openrouter"]
    logger.info("Generating random podcast script using model %s", model)

    telegram_token = args.telegram_token or os.environ.get("TELEGRAM_BOT_TOKEN")
    raw_chat_ids = args.telegram_chat_id or [os.environ.get("TELEGRAM_CHAT_ID", "")]
    telegram_chat_ids = resolve_telegram_chat_ids(raw_chat_ids)

    topic_history_path = Path(args.topic_history_file)
    previous_topics = load_topic_history(
        topic_history_path,
        max_entries=max(args.topic_history_limit, 0),
    )

    try:
        script_text = generate_random_podcast_script(
            model=model,
            temperature=args.temperature,
            max_output_tokens=args.max_output_tokens,
            language=args.language,
            previous_topic_summaries=previous_topics,
        )
    except RuntimeError as exc:
        logger.error("Failed to generate podcast script: %s", exc)
        print(str(exc), file=sys.stderr)
        return

    output_path = Path(args.output)
    output_path.write_text(script_text, encoding="utf-8")
    logger.info("Podcast script written to %s", output_path)

    topic_summary = summarize_generated_topic(script_text)
    updated_topics = previous_topics + [topic_summary]
    save_topic_history(topic_history_path, updated_topics)
    logger.info("Saved topic summary to %s: %s", topic_history_path, topic_summary)

    print(script_text)

    speech_path: Path | None = None
    if args.speech:
        speech_path = synthesise_speech(script_text, output_filename=args.speech_output)
        if speech_path:
            logger.info("Podcast narration saved to %s", speech_path)
        else:
            logger.info("Speech synthesis skipped or failed; no audio generated")
    else:
        logger.debug("Speech synthesis disabled via CLI option")

    if not args.telegram:
        logger.debug("Telegram posting disabled via CLI option")
        return

    if not telegram_token or not telegram_chat_ids:
        logger.warning("Telegram credentials missing; skipping Telegram upload")
        return

    caption = args.caption or "Random podcast"
    try:
        if speech_path:
            for chat_id in telegram_chat_ids:
                post_summary_to_telegram(
                    speech_path,
                    token=telegram_token,
                    chat_id=chat_id,
                    caption=caption,
                )
        else:
            for chat_id in telegram_chat_ids:
                post_text_to_telegram(
                    script_text,
                    token=telegram_token,
                    chat_id=chat_id,
                )
    except Exception as exc:  # pragma: no cover - network call
        logger.exception("Failed to post podcast to Telegram")
        print(f"Failed to send podcast to Telegram: {exc}", file=sys.stderr)
        return

    logger.info("Podcast posted to %d Telegram chat(s)", len(telegram_chat_ids))


if __name__ == "__main__":  # pragma: no cover - manual execution
    main()
