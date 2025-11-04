"""Publish summaries to Telegram as voice notes or plain text messages."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..logging_utils import configure_logging
from ..pipeline import post_summary_to_telegram, post_text_to_telegram, synthesise_speech

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish summaries to Telegram as voice notes or plain text messages.",
    )
    parser.add_argument(
        "--summary",
        default="todo_summary.txt",
        help="Path to the text file containing the summary to narrate.",
    )
    parser.add_argument(
        "--speech-output",
        default="todo-summary.wav",
        help="Path to the audio file that will store the generated narration.",
    )
    parser.add_argument(
        "--existing-audio",
        default=None,
        help="Use an existing audio file instead of synthesising a new narration.",
    )
    parser.add_argument(
        "--voice",
        dest="voice",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Generate speech from the summary and send it as a voice message. Disable "
            "with --no-voice to send the summary as a text message instead."
        ),
    )
    parser.add_argument(
        "--telegram",
        dest="telegram",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Post the generated audio to Telegram. Disable with --no-telegram.",
    )
    parser.add_argument(
        "--telegram-token",
        default=os.environ.get("TELEGRAM_BOT_TOKEN"),
        help="Telegram bot token. Defaults to the TELEGRAM_BOT_TOKEN environment variable.",
    )
    parser.add_argument(
        "--telegram-chat-id",
        default=os.environ.get("TELEGRAM_CHAT_ID"),
        help="Telegram chat or channel ID where the audio should be posted.",
    )
    parser.add_argument(
        "--caption",
        default=None,
        help="Optional caption to include with the Telegram voice message.",
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

    if args.voice:
        if args.existing_audio:
            speech_path = Path(args.existing_audio)
            if not speech_path.exists():
                print(f"Existing audio file not found: {speech_path}", file=sys.stderr)
                return
            logger.info("Using existing audio file %s", speech_path)
        else:
            summary_path = Path(args.summary)
            try:
                summary_text = summary_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                print(f"Summary file not found: {summary_path}", file=sys.stderr)
                return

            speech_path = synthesise_speech(summary_text, output_filename=args.speech_output)
            if not speech_path:
                logger.info("Speech synthesis skipped or failed; no audio generated")
                return
            logger.info("Speech saved to %s", speech_path)

        if not args.telegram:
            logger.debug("Telegram upload disabled via CLI option")
            return

        if not args.telegram_token or not args.telegram_chat_id:
            print("Telegram bot token or chat ID missing; skipping Telegram upload.", file=sys.stderr)
            return

        caption = args.caption or datetime.now(timezone.utc).isoformat()

        try:
            post_summary_to_telegram(
                speech_path,
                token=args.telegram_token,
                chat_id=args.telegram_chat_id,
                caption=caption,
            )
        except Exception as exc:  # pragma: no cover - network call
            print(f"Failed to upload summary to Telegram: {exc}", file=sys.stderr)
            return

        print("Telegram upload completed successfully.")
        return

    if args.existing_audio:
        logger.warning(
            "--existing-audio provided but --no-voice selected; the audio file will be ignored."
        )

    if not args.telegram:
        logger.debug("Telegram upload disabled via CLI option")
        return

    summary_path = Path(args.summary)
    try:
        summary_text = summary_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"Summary file not found: {summary_path}", file=sys.stderr)
        return

    message_parts = [summary_text.strip()]
    if args.caption:
        message_parts.insert(0, args.caption.strip())
    message_text = "\n\n".join(part for part in message_parts if part)

    if not message_text:
        print("Summary text is empty; nothing to send to Telegram.", file=sys.stderr)
        return

    if not args.telegram_token or not args.telegram_chat_id:
        print("Telegram bot token or chat ID missing; skipping Telegram upload.", file=sys.stderr)
        return

    try:
        post_text_to_telegram(
            message_text,
            token=args.telegram_token,
            chat_id=args.telegram_chat_id,
        )
    except Exception as exc:  # pragma: no cover - network call
        print(f"Failed to send summary text to Telegram: {exc}", file=sys.stderr)
        return

    print("Telegram text message sent successfully.")


if __name__ == "__main__":  # pragma: no cover - manual execution
    main()
