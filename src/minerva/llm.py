"""LLM provider integrations for todo summarization and podcast generation."""
from __future__ import annotations

import json
import logging
import os
from typing import Iterable

import httpx
from groq import Groq

from .prompts import (
    PODCAST_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_prompt,
    load_podcast_user_prompt_template,
    render_podcast_user_prompt,
)
from .todos import TodoList

logger = logging.getLogger(__name__)

DEFAULT_MODELS = {
    "openrouter": "mistralai/mistral-nemo",
    "groq": "mixtral-8x7b-32768",
}


def summarize_with_openrouter(
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


def summarize_with_groq(
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


def generate_random_podcast_script(
    *,
    model: str,
    temperature: float = 0.7,
    max_output_tokens: int | None = 800,
    language: str | None = None,
    previous_topic_summaries: Iterable[str] | None = None,
    user_prompt_template_path: str | None = None,
) -> str:
    """Return a short podcast script generated with OpenRouter."""

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY environment variable is not set.")

    language_clause = f"Write the entire script in {language}. " if language else ""
    previous_topics = [topic.strip() for topic in (previous_topic_summaries or []) if topic.strip()]
    previous_topics_clause = ""
    if previous_topics:
        formatted_topics = "\n".join(f"- {topic}" for topic in previous_topics)
        previous_topics_clause = (
            "Do not reuse any of these previously generated topics:\n"
            f"{formatted_topics}\n"
        )

    user_prompt_template = load_podcast_user_prompt_template(user_prompt_template_path)
    user_prompt = render_podcast_user_prompt(
        user_prompt_template,
        language=language,
        language_clause=language_clause,
        previous_topics=previous_topics,
        previous_topics_clause=previous_topics_clause,
    )

    payload: dict[str, object] = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": PODCAST_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }

    if max_output_tokens is not None:
        payload["max_output_tokens"] = max_output_tokens
        logger.debug("Set OpenRouter max_output_tokens to %s", max_output_tokens)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("OPENROUTER_APP_URL", "https://github.com/fcrescio/Minerva"),
        "X-Title": os.environ.get("OPENROUTER_APP_TITLE", "Minerva Random Podcast"),
    }

    logger.debug(
        "Requesting random podcast script with model=%s temperature=%s", model, temperature
    )
    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            content=json.dumps(payload),
        )
        response.raise_for_status()
        logger.debug("OpenRouter podcast request completed with status %s", response.status_code)

    data = response.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:  # pragma: no cover - defensive fallback
        raise RuntimeError("Unexpected response from OpenRouter") from exc


__all__ = [
    "DEFAULT_MODELS",
    "generate_random_podcast_script",
    "summarise_with_groq",
    "summarise_with_openrouter",
    "summarize_with_groq",
    "summarize_with_openrouter",
]


# Backward-compatible aliases.
summarise_with_openrouter = summarize_with_openrouter
summarise_with_groq = summarize_with_groq
