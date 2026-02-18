"""Shared helpers for Minerva CLI tools."""
from __future__ import annotations


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
