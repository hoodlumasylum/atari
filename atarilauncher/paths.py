"""Where Atari keeps its files (overridable via env vars, handy for tests)."""
from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    override = os.environ.get("ATARI_CONFIG_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "atari"


def data_dir() -> Path:
    override = os.environ.get("ATARI_DATA_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "atari"


def config_file() -> Path:
    return config_dir() / "config.toml"


def state_file() -> Path:
    return data_dir() / "state.json"


def log_file() -> Path:
    return data_dir() / "launch.log"


def covers_dir() -> Path:
    """Older location (0.1.0): ~/.config/atari/covers/<system>/<file name>.png"""
    return config_dir() / "covers"


def user_covers_dir() -> Path:
    """Preferred place for your own box art: ~/.local/share/atari/covers/<game name>.png"""
    return data_dir() / "covers"


def metadata_file() -> Path:
    """Optional hand-written details (genre, players, release, rating): ~/.local/share/atari/metadata.json"""
    return data_dir() / "metadata.json"
