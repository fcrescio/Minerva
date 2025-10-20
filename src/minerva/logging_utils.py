"""Logging helpers for the Minerva CLI tools."""
from __future__ import annotations

import logging
import os

_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def _normalise_level(level: str | int | None) -> int:
    """Return ``level`` as a logging level integer.

    Accepts case-insensitive level names (e.g. ``"debug"``) as well as
    integers. Falls back to ``logging.INFO`` when ``level`` is ``None``.
    """

    if level is None:
        return logging.INFO

    if isinstance(level, int):
        return level

    if isinstance(level, str):
        candidate = getattr(logging, level.upper(), None)
        if isinstance(candidate, int):
            return candidate

    raise ValueError(f"Unsupported log level: {level!r}")


def configure_logging(level: str | int | None = None, *, env_var: str = "MINERVA_LOG_LEVEL") -> None:
    """Initialise application logging.

    Parameters
    ----------
    level:
        Desired logging level. When ``None`` the value is obtained from the
        environment variable identified by ``env_var``. If that environment
        variable is unset, ``INFO`` is used by default.
    env_var:
        Name of the environment variable that may contain a desired log level.
    """

    if level is None:
        level = os.environ.get(env_var)

    numeric_level = _normalise_level(level)

    # ``basicConfig`` only has an effect the first time it is called. We still
    # invoke it so scripts that use ``configure_logging`` in isolation behave
    # predictably when executed directly.
    logging.basicConfig(level=numeric_level, format=_LOG_FORMAT)

    # Ensure the library logger follows the configured verbosity.
    logging.getLogger("minerva").setLevel(numeric_level)
