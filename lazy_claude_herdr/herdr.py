"""Thin adapter over the `herdr` CLI (socket API wrapped as JSON on stdout).

Tests replace it by putting a fake `herdr` executable first on PATH.
"""
import json
import os
import shutil
import subprocess
import sys
import time

from . import system

PLUGIN_ID = "lazy-claude-herdr"


class HerdrError(RuntimeError):
    pass


def call(*args, raw=False):
    """Run `herdr <args>`; returns the JSON `result`, or stdout as text when `raw`."""
    out = subprocess.run(["herdr", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise HerdrError(f"herdr {' '.join(args)}: {out.stderr.strip() or out.stdout.strip()}")
    if raw:
        return out.stdout
    try:
        return json.loads(out.stdout)["result"]
    except (ValueError, KeyError):
        raise HerdrError(f"herdr {' '.join(args)}: unexpected output") from None


def available() -> bool:
    return bool(shutil.which("herdr") and os.environ.get("HERDR_SOCKET_PATH"))


def overlay_pane() -> str | None:
    """Our own overlay pane id when running as the plugin's popup."""
    if os.environ.get("HERDR_PLUGIN_ID") == PLUGIN_ID:
        return os.environ.get("HERDR_PANE_ID")
    return None


def state():
    """Snapshot of agents and workspaces, or None outside herdr."""
    if not available():
        return None
    try:
        agents = call("agent", "list")["agents"]
        workspaces = call("workspace", "list")["workspaces"]
    except (HerdrError, ValueError, KeyError):
        return None
    # herdr's Claude integration reports the session id of each Claude pane.
    live = {a["agent_session"]["value"]: a for a in agents
            if (a.get("agent_session") or {}).get("value")}
    return {"agents": agents, "workspaces": workspaces, "live": live}


def live_map(st) -> dict:
    return st["live"] if st else {}


def find_workspace(cwd: str, st) -> str | None:
    for w in st["workspaces"]:
        if (w.get("worktree") or {}).get("checkout_path") == cwd:
            return w["workspace_id"]
    for a in st["agents"]:
        if a.get("cwd") == cwd:
            return a["workspace_id"]
    base = os.path.basename(cwd.rstrip("/"))
    for w in st["workspaces"]:
        if w.get("label") == base:
            return w["workspace_id"]
    return None


def split_largest_pane(ws: str, cwd: str) -> str:
    """Split the widest-area pane of the workspace's active tab along its long side."""
    overlay = overlay_pane()
    active_tab = next((w["active_tab_id"] for w in call("workspace", "list")["workspaces"]
                       if w["workspace_id"] == ws), None)
    panes = [p for p in call("pane", "list", "--workspace", ws)["panes"]
             if p["tab_id"] == active_tab and p["pane_id"] != overlay]
    if not panes:
        raise HerdrError(f"no pane to split in workspace {ws}")
    layout = call("pane", "layout", "--pane", panes[0]["pane_id"])["layout"]
    target = max((p for p in layout["panes"] if p["pane_id"] != overlay),
                 key=lambda p: p["rect"]["width"] * p["rect"]["height"])
    r = target["rect"]
    # Terminal cells are roughly twice as tall as wide.
    direction = "right" if r["width"] > r["height"] * 2.2 else "down"
    return call("pane", "split", target["pane_id"], "--direction", direction,
                "--cwd", cwd, "--no-focus")["pane"]["pane_id"]


def wait_shell_ready(pane: str, timeout=8.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if call("pane", "read", pane, "--lines", "3", "--source", "visible", raw=True).strip():
                return
        except HerdrError:
            pass
        time.sleep(0.3)


def open_pane(cwd: str, st, command: str | None, label: str) -> None:
    """Run `command` (or just a shell) in a new pane of the space matching `cwd`."""
    ws = find_workspace(cwd, st)
    pane = None
    if ws is not None:
        try:
            pane = split_largest_pane(ws, cwd)
        except HerdrError:
            pane = None  # the space vanished or has nothing to split: make a new one
    if pane is None:
        # A new workspace comes with its own root pane; use it instead of splitting.
        created = call("workspace", "create", "--cwd", cwd, "--label",
                       os.path.basename(cwd.rstrip("/")), "--no-focus")
        ws, pane = created["workspace"]["workspace_id"], created["root_pane"]["pane_id"]
    wait_shell_ready(pane)
    if command:
        call("pane", "run", pane, command)
    call("pane", "rename", pane, label[:24])
    focus(ws, pane)


def focus(ws: str, target: str) -> None:
    """herdr restores the previous focus when an overlay closes, which would undo a
    focus done from inside the popup. So from the popup, hand the focus to a detached
    process that waits for the overlay to disappear first."""
    overlay = overlay_pane()
    if not overlay:
        _focus_now(ws, target)
        return
    system.spawn_detached([sys.executable, "-m", "lazy_claude_herdr", "--focus-after", overlay, ws, target],
                          cwd=system.PKG_ROOT)


def _focus_now(ws, target):
    call("workspace", "focus", ws)
    call("agent", "focus", target)


def focus_after(overlay: str, ws: str, target: str) -> None:
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            call("pane", "get", overlay)
        except HerdrError:
            break
        time.sleep(0.1)
    time.sleep(0.2)  # let herdr finish restoring the previous focus
    _focus_now(ws, target)


def notify(title: str, body: str) -> None:
    if available():
        subprocess.run(["herdr", "notification", "show", title, "--body", body], capture_output=True)
