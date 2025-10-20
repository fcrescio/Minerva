"""Configuration helpers for connecting to Firebase/Firestore."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FirebaseConfig:
    """Minimal configuration extracted from ``google-services.json``."""

    project_id: str

    @classmethod
    def from_google_services(cls, path: Path | str) -> "FirebaseConfig":
        """Load the Firebase project metadata from ``google-services.json``.

        Parameters
        ----------
        path:
            Location of the ``google-services.json`` file shipped with the
            mobile application.
        """

        config_path = Path(path)
        logger.debug("Loading Firebase configuration from %s", config_path)
        if not config_path.exists():
            msg = f"google-services.json not found at {config_path}"
            raise FileNotFoundError(msg)

        with config_path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
        logger.debug("Raw google-services.json keys: %s", sorted(data))

        project_info: Mapping[str, Any] | None = data.get("project_info")
        if not project_info:
            raise ValueError("google-services.json is missing 'project_info'")
        logger.debug("project_info keys: %s", sorted(project_info))

        project_id = project_info.get("project_id")
        if not project_id:
            raise ValueError("google-services.json is missing 'project_id'")
        logger.debug("Detected Firebase project id: %s", project_id)

        return cls(project_id=project_id)
