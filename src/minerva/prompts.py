"""Prompt and template helpers for Minerva LLM interactions."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .todos import Todo, TodoList

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a helpful assistant that generates concise summaries of todo lists. "
    "Highlight overdue or upcoming items and mention items lacking due dates when relevant. "
    "Provide the summary as a podcast-like monologue . Be playful and creative with moderation."
    "Answer in italian language"
)

PODCAST_SYSTEM_PROMPT = (
    "You are a creative podcast host who can pick engaging, wholesome topics at random. "
    "Generate a concise script for a 2-3 minute episode that includes a title, a short "
    "intro hook, two or three key talking points, and a friendly sign-off. "
    "Keep the tone upbeat and curious, use clear language, and avoid sensitive subjects."
)

PODCAST_USER_PROMPT_TEMPLATE = (
    "Pick a surprising, family-friendly topic at random and craft a brief script "
    "for a 2-3 minute podcast episode. Include a catchy title, an inviting "
    "opening, a handful of vivid talking points, and a warm sign-off. Avoid "
    "reusing the same subject across runs. "
    "{previous_topics_clause}"
    "{language_clause}"
)


def load_podcast_user_prompt_template(path: str | None) -> str:
    """Return podcast user prompt template, optionally loaded from ``path``."""

    if not path:
        return PODCAST_USER_PROMPT_TEMPLATE

    template_path = Path(path)
    try:
        contents = template_path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - filesystem errors
        raise RuntimeError(
            f"Failed to read podcast prompt template file {template_path}: {exc}"
        ) from exc

    stripped = contents.strip()
    if not stripped:
        raise RuntimeError(
            f"Podcast prompt template file {template_path} is empty after stripping whitespace."
        )

    return stripped


def render_podcast_user_prompt(
    template: str,
    *,
    language: str | None,
    language_clause: str,
    previous_topics: Iterable[str],
    previous_topics_clause: str,
) -> str:
    """Render a podcast prompt template with supported placeholders."""

    placeholder_values = {
        "language": language or "",
        "language_clause": language_clause,
        "previous_topics": "\n".join(previous_topics),
        "previous_topics_clause": previous_topics_clause,
    }
    try:
        return template.format(**placeholder_values)
    except KeyError as exc:
        missing = exc.args[0]
        raise RuntimeError(
            "Unknown placeholder in podcast prompt template: "
            f"{{{missing}}}. Supported placeholders are: "
            "{language}, {language_clause}, {previous_topics}, {previous_topics_clause}."
        ) from exc


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
    lines = [f"The current date and time is {today}", "Provide a summary for the following todo lists:"]
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


__all__ = [
    "SYSTEM_PROMPT",
    "PODCAST_SYSTEM_PROMPT",
    "PODCAST_USER_PROMPT_TEMPLATE",
    "build_prompt",
    "format_todo_for_prompt",
    "load_podcast_user_prompt_template",
    "load_system_prompt",
    "render_podcast_user_prompt",
]
