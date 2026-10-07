"""Filesystem locations. Every one of them can be overridden by an environment
variable so tests, screenshots and the demo can run against fixture data."""
import os
from pathlib import Path

APP = "lazy-claude-herdr"


def _xdg(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / fallback)


def projects_dir() -> Path:
    if os.environ.get("LAZY_CLAUDE_HERDR_PROJECTS"):
        return Path(os.environ["LAZY_CLAUDE_HERDR_PROJECTS"])
    claude_home = os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude"
    return Path(claude_home) / "projects"


def config_file() -> Path:
    if os.environ.get("LAZY_CLAUDE_HERDR_CONFIG"):
        return Path(os.environ["LAZY_CLAUDE_HERDR_CONFIG"])
    return _xdg("XDG_CONFIG_HOME", ".config") / APP / "config.toml"


def cache_dir() -> Path:
    if os.environ.get("LAZY_CLAUDE_HERDR_CACHE"):
        return Path(os.environ["LAZY_CLAUDE_HERDR_CACHE"])
    return _xdg("XDG_CACHE_HOME", ".cache") / APP


def log_file() -> Path:
    return cache_dir() / "lazy-claude-herdr.log"
