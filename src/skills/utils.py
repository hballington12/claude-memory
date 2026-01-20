"""Utility functions for skills."""

import json
from pathlib import Path


def get_settings_path(scope: str) -> Path:
    """Get the settings file path based on scope."""
    if scope == "user":
        return Path.home() / ".claude" / "settings.json"
    elif scope == "local":
        return Path(".claude") / "settings.local.json"
    else:  # project (default)
        return Path(".claude") / "settings.json"


def load_settings(path: Path) -> dict:
    """Load existing settings or return empty dict."""
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_settings(path: Path, settings: dict) -> None:
    """Save settings to file, creating directories if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(settings, f, indent=2)
