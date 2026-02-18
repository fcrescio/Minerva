"""Audio synthesis and conversion helpers."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterator

import httpx

logger = logging.getLogger(__name__)


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
    "convert_audio_to_ogg_opus",
    "extract_audio_urls",
    "synthesise_speech",
]
