"""Lightweight always-on diagnostic log.

The focus flow runs partly in a detached process with no terminal, so an
intermittent "didn't jump to the space" leaves no visible trace. This appends a
few timestamped lines per run to a bounded file you can tail:

    tail -f ~/.cache/lazy-claude-herdr/lazy-claude-herdr.log

Logging must never break the tool, so every failure here is swallowed. Set
LCH_NO_LOG=1 to disable.
"""
import os
import time

from . import paths

_MAX_BYTES = 1_000_000  # truncate when the log grows past ~1 MB


def log(msg: str) -> None:
    if os.environ.get("LCH_NO_LOG"):
        return
    try:
        path = paths.log_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if path.stat().st_size > _MAX_BYTES:
                path.write_text("")  # simple reset; this is debug data, not history
        except OSError:
            pass
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{ts} [{os.getpid()}] {msg}\n")
    except Exception:
        pass
