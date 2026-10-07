"""Index of Claude Code sessions, built from the JSONL transcripts Claude Code
keeps under its projects directory.

The transcript format is not a public API. Everything here is best effort: a
missing or renamed field leaves the corresponding value empty instead of failing.
"""
import json
import os
import re
import time
from pathlib import Path

from . import paths

CACHE_VERSION = 1
FIELDS = ("cwd", "branch", "ai_title", "custom_title", "last_prompt",
          "pr", "pr_url", "pr_repo", "entrypoint")

_CWD_RE = re.compile(r'"cwd":"((?:[^"\\]|\\.)*)"')
_BRANCH_RE = re.compile(r'"gitBranch":"((?:[^"\\]|\\.)*)"')
_ENTRY_RE = re.compile(r'"entrypoint":"([^"]*)"')
_TYPED = ('"ai-title"', '"custom-title"', '"last-prompt"', '"pr-link"')


def _unescape(raw: str) -> str:
    try:
        return json.loads(f'"{raw}"')
    except ValueError:
        return raw


def _update_meta(line: str, meta: dict) -> None:
    if not any(k in line[:80] for k in _TYPED):
        # Message lines can carry megabytes of tool output; only regex them.
        if '"type":"user"' in line[:400] or '"cwd":' in line[:600]:
            if m := _CWD_RE.search(line):
                meta["cwd"] = _unescape(m.group(1))
            if m := _BRANCH_RE.search(line):
                meta["branch"] = _unescape(m.group(1))
            if not meta["entrypoint"] and (m := _ENTRY_RE.search(line)):
                meta["entrypoint"] = m.group(1)
        return
    try:
        d = json.loads(line)
    except ValueError:
        return
    kind = d.get("type")
    if kind == "ai-title":
        meta["ai_title"] = d.get("aiTitle")
    elif kind == "custom-title":
        meta["custom_title"] = d.get("customTitle") or d.get("title")
    elif kind == "last-prompt":
        meta["last_prompt"] = d.get("lastPrompt")
    elif kind == "pr-link":
        meta["pr"] = d.get("prNumber")
        meta["pr_url"] = d.get("prUrl")
        meta["pr_repo"] = d.get("prRepository")


def scan_file(path: Path, start: int = 0, base: dict | None = None) -> dict:
    """Extract session metadata. `start`>0 scans only bytes appended since a prior
    scan (seek is a line boundary: JSONL flushes whole lines), merging onto `base`
    (the cached meta). This keeps active multi-MB transcripts from being re-read in
    full every launch — the main source of picker lag."""
    meta = dict(base) if base else dict.fromkeys(FIELDS)
    with path.open("r", encoding="utf-8", errors="replace") as f:
        if start:
            f.seek(start)
        for line in f:
            _update_meta(line, meta)
    return meta


def _cache_path() -> Path:
    return paths.cache_dir() / f"index-v{CACHE_VERSION}.json"


def _read_cache() -> dict:
    try:
        return json.loads(_cache_path().read_text())
    except (OSError, ValueError):
        return {}


def load(max_age_days=None) -> list[dict]:
    """Resumable sessions, newest first. `max_age_days=None` means everything kept."""
    cache_file = _cache_path()
    cache = _read_cache()
    now = time.time()
    too_old = (lambda mtime: now - mtime > max_age_days * 86400) if max_age_days else (lambda mtime: False)
    sessions, new_cache = [], {}
    for path in paths.projects_dir().glob("*/*.jsonl"):
        try:
            st = path.stat()
        except OSError:
            continue
        key = str(path)
        hit = cache.get(key)
        if hit and hit["mtime"] == st.st_mtime and hit["size"] == st.st_size:
            meta = hit["meta"]
        elif too_old(st.st_mtime):
            if hit:  # keep the stale entry so a later "all periods" run can refresh it
                new_cache[key] = hit
            continue
        elif hit and st.st_size > hit["size"] and hit["meta"].get("cwd"):
            # Appended since last scan: read only the new bytes, merge onto cached meta.
            meta = scan_file(path, start=hit["size"], base=hit["meta"])
        else:
            meta = scan_file(path)
        new_cache[key] = {"mtime": st.st_mtime, "size": st.st_size, "meta": meta}
        if too_old(st.st_mtime):
            continue
        # `claude -p` runs (e.g. other tools' helpers) can't be resumed interactively,
        # and a session whose directory is gone (removed worktree) can't be resumed either.
        if not meta.get("cwd") or meta.get("entrypoint") == "sdk-cli" or not os.path.isdir(meta["cwd"]):
            continue
        sessions.append({"id": path.stem, "mtime": st.st_mtime, "path": key,
                         **{k: meta.get(k) for k in FIELDS}})
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    # fzf runs preview/reload processes concurrently; replace atomically.
    tmp = cache_file.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(new_cache))
    os.replace(tmp, cache_file)
    sessions.sort(key=lambda s: s["mtime"], reverse=True)
    return sessions


def find(session_id: str):
    """One session by id, without scanning every transcript (preview runs per keystroke)."""
    if not session_id or "/" in session_id:
        return None
    for path in paths.projects_dir().glob(f"*/{session_id}.jsonl"):
        st = path.stat()
        hit = _read_cache().get(str(path))
        if hit and hit["mtime"] == st.st_mtime and hit["size"] == st.st_size:
            meta = hit["meta"]
        else:
            meta = scan_file(path)
        if meta.get("cwd"):
            return {"id": session_id, "mtime": st.st_mtime, "path": str(path),
                    **{k: meta.get(k) for k in FIELDS}}
    return None


def transcript(session: dict):
    """(role, local timestamp ISO string, text) for human and assistant text only."""
    with open(session["path"], encoding="utf-8", errors="replace") as f:
        for line in f:
            if '"type":"user"' not in line[:400] and '"type":"assistant"' not in line[:400]:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("isSidechain") or d.get("isMeta"):
                continue
            content = (d.get("message") or {}).get("content")
            texts = [content] if isinstance(content, str) else [
                c.get("text", "") for c in content or [] if isinstance(c, dict) and c.get("type") == "text"]
            # Skip injected blocks such as <command-name>, <system-reminder>.
            text = "\n".join(t for t in texts if t and not t.lstrip().startswith("<")).strip()
            if text:
                yield d.get("type"), d.get("timestamp"), text
