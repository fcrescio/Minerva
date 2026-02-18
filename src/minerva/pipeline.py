"""Compatibility façade re-exporting pipeline helpers from split modules."""

from .llm import (
    DEFAULT_MODELS,
    generate_random_podcast_script,
    summarize_with_groq,
    summarize_with_openrouter,
)
from .media import convert_audio_to_ogg_opus, extract_audio_urls, synthesise_speech
from .notifications import post_summary_to_telegram, post_text_to_telegram
from .persistence import (
    compute_run_markers,
    deserialise_todo,
    deserialise_todo_list,
    normalise_metadata_value,
    read_run_markers,
    serialise_todo,
    serialise_todo_list,
    write_run_markers,
)
from .prompts import (
    PODCAST_SYSTEM_PROMPT,
    PODCAST_USER_PROMPT_TEMPLATE,
    SYSTEM_PROMPT,
    build_prompt,
    format_todo_for_prompt,
    load_podcast_user_prompt_template,
    load_system_prompt,
    render_podcast_user_prompt,
)

__all__ = [
    "DEFAULT_MODELS",
    "PODCAST_SYSTEM_PROMPT",
    "PODCAST_USER_PROMPT_TEMPLATE",
    "SYSTEM_PROMPT",
    "build_prompt",
    "compute_run_markers",
    "convert_audio_to_ogg_opus",
    "deserialise_todo",
    "deserialise_todo_list",
    "extract_audio_urls",
    "format_todo_for_prompt",
    "generate_random_podcast_script",
    "load_podcast_user_prompt_template",
    "load_system_prompt",
    "normalise_metadata_value",
    "post_summary_to_telegram",
    "post_text_to_telegram",
    "read_run_markers",
    "render_podcast_user_prompt",
    "serialise_todo",
    "serialise_todo_list",
    "summarize_with_groq",
    "summarize_with_openrouter",
    "synthesise_speech",
    "write_run_markers",
]
