"""Telegram notification transport helpers."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telegram import Bot
from telegram.error import TelegramError

from .media import convert_audio_to_ogg_opus

logger = logging.getLogger(__name__)


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


__all__ = ["post_summary_to_telegram", "post_text_to_telegram"]
