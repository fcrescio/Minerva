"""Configuration helpers for connecting to Firebase/Firestore."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


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
        if not config_path.exists():
            msg = f"google-services.json not found at {config_path}"
            raise FileNotFoundError(msg)

        with config_path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)

        project_info: Mapping[str, Any] | None = data.get("project_info")
        if not project_info:
            raise ValueError("google-services.json is missing 'project_info'")

        project_id = project_info.get("project_id")
        if not project_id:
            raise ValueError("google-services.json is missing 'project_id'")

        return cls(project_id=project_id)
