"""The fzf picker and the small sub-commands its key bindings call back into.

One run keeps its UI state (period, sort, pending exit action, flash message) in a
JSON file, so that fzf's `reload` / `transform-header` / `execute` processes can
share it.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import shlex

from . import actions, herdr, paths, render, sessions, system
from .config import SORTS
from .i18n import t

# fzf runs bindings through this shell; pin it so users of fish/dash get the same
# behaviour (the digit-jump binding uses bash's [[ =~ ]]).
FZF_SHELL = "--with-shell=bash -c"


def _self_cmd() -> str:
    """Shell command fzf uses to call back into us (must work from any cwd)."""
    return f"cd {shlex.quote(system.PKG_ROOT)} && {shlex.quote(sys.executable)} -m lazy_claude_herdr"


# --- ordering ------------------------------------------------------------------

def sort_sessions(items, mode, live_map, envs):
    by_recent = sorted(items, key=lambda s: s["mtime"], reverse=True)
    if mode == "env":
        def key(s):
            label, _, index = render.env_of(s["cwd"], envs)
            return (index, label if index == len(envs) else "")
        return sorted(by_recent, key=key)  # stable: newest first within an environment
    if mode == "live":
        return sorted(by_recent, key=lambda s: s["id"] not in live_map)
    return by_recent


def listing(cfg, days, sort, st=None):
    st = st if st is not None else herdr.state()
    lm = herdr.live_map(st)
    return sort_sessions(sessions.load(days), sort, lm, cfg.envs), lm


# --- UI state file -------------------------------------------------------------

def ui_read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def ui_write(path, ui):
    # reload (async) and transform-header (sync) can run at the same time; never let
    # one of them read a half-written file.
    tmp = Path(f"{path}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(ui))
    os.replace(tmp, path)


def ui_command(cfg, path, action):
    """Called from fzf bindings.

    sort / all / recent / header: update state *and* print the header. These run via
    `transform-header`, which is synchronous; `reload` is asynchronous, so updating
    state there would leave the header one step behind.
    emit: print the list for `reload`.
    after-menu: print `accept` if the menu chose an exit action.
    pend:<id>: remember an exit action chosen by a direct key.
    """
    ui = ui_read(path)
    if action == "emit":
        items, lm = listing(cfg, ui.get("days"), ui.get("sort", "recent"))
        print("\n".join(render.numbered_lines(items, lm, cfg.envs)))
        return
    if action == "after-menu":
        print("accept" if ui.get("pending") else "")
        return
    if action.startswith("pend:"):
        ui["pending"] = action[5:]
        ui_write(path, ui)
        return
    if action == "sort":
        ui["sort"] = SORTS[(SORTS.index(ui.get("sort", "recent")) + 1) % len(SORTS)]
    elif action == "all":
        ui["days"] = None
    elif action == "recent":
        ui["days"] = cfg.recent_days
    count = len(sessions.load(ui.get("days")))
    print(render.header(ui.get("days"), count, ui.get("sort", "recent"), ui.pop("flash", None),
                        cfg.recent_days))
    ui_write(path, ui)


def flash(path, message):
    if message:
        ui = ui_read(path)
        ui["flash"] = message
        ui_write(path, ui)


# --- actions invoked from the picker -------------------------------------------

def run_now(cfg, ui_path, action_id, session_id):
    """Run an inline or pager action for a session, leaving a flash message."""
    try:
        flash(ui_path, actions.run_checked(cfg, action_id, session_id))
    except actions.Unavailable as e:
        flash(ui_path, str(e))
    except Exception as e:  # keep the picker alive whatever an action does
        flash(ui_path, t("f_failed", label=action_id, error=str(e)[:80]))


def menu(cfg, ui_path, session_id):
    s = sessions.find(session_id)
    if not s:
        return
    ctx = actions.Ctx(cfg, herdr.state())
    acts = actions.available_for(ctx, s)
    lines, binds = [], []
    for i, a in enumerate(acts, 1):
        direct = f"  {render.DIM}{a.direct}{render.RESET}" if a.direct else ""
        lines.append(f"{a.id}\t{render.DIM}{i:>2}{render.RESET}  "
                     f"{render.YELLOW}{render.BOLD}{a.key}{render.RESET}  {a.label}{direct}")
        binds.append(f"--bind={a.key}:pos({i})+accept")
    binds += [f"--bind={i}:pos({i})+accept" for i in range(1, min(len(acts), 9) + 1)]
    r = subprocess.run(
        ["fzf", FZF_SHELL, "--ansi", "--delimiter=\t", "--with-nth=2..", "--no-input", "--layout=reverse",
         "--height=100%", "--border=rounded", "--pointer=▶", "--tabstop=1",
         f"--border-label= {ctx.title(s)[:40]} ", "--color=pointer:green,header:italic",
         f"--header={t('menu_header')}", "--bind=j:down,k:up,q:abort", *binds],
        input="\n".join(lines), stdout=subprocess.PIPE, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return
    act = actions.by_id(cfg, r.stdout.split("\t", 1)[0])
    if act.kind == "exit":
        ui_command(cfg, ui_path, f"pend:{act.id}")
    else:
        run_now(cfg, ui_path, act.id, session_id)


# --- the picker itself ---------------------------------------------------------

def _bindings(cfg, ui_path):
    me = _self_cmd()
    ui_path = shlex.quote(str(ui_path))
    ui = f"{me} --ui {ui_path}"
    reload_with = lambda act: f"transform-header({ui} {act})+reload({ui} emit)+first"
    header_refresh = f"transform-header({ui} header)"
    binds = [
        # Digits only: don't filter, jump to that row number instead.
        "change:transform-search([[ $FZF_QUERY =~ ^[0-9]+$ ]] || echo \"$FZF_QUERY\")"
        "+transform:[[ $FZF_QUERY =~ ^[0-9]+$ ]] && echo \"pos($FZF_QUERY)\"",
        f"ctrl-s:{reload_with('sort')}",
        f"ctrl-a:{reload_with('all')}",
        f"ctrl-d:{reload_with('recent')}",
        f"ctrl-o:execute({me} --menu {ui_path} {{1}})+transform({ui} after-menu)+{header_refresh}",
    ]
    for a in actions.all_actions(cfg):
        if not a.direct or a.direct == "enter":
            continue
        if a.kind == "exit":
            binds.append(f"{a.direct}:execute-silent({ui} pend:{a.id})+accept")
        elif a.kind == "pager":
            binds.append(f"{a.direct}:execute({me} --act {ui_path} {a.id} {{1}})+{header_refresh}")
        else:
            binds.append(f"{a.direct}:execute-silent({me} --act {ui_path} {a.id} {{1}})+{header_refresh}")
    return [f"--bind={b}" for b in binds]


def choose(cfg, items, lm, query, days, sort):
    """Returns (session id, action id) or (None, None)."""
    if not shutil.which("fzf"):
        return _choose_plain(cfg, items, lm, query)
    cache = paths.cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    for old in cache.glob("ui-*.json"):  # left behind by killed runs
        if time.time() - old.stat().st_mtime > 86400:
            old.unlink(missing_ok=True)
    ui_path = cache / f"ui-{os.getpid()}.json"
    ui_write(ui_path, {"days": days, "sort": sort})
    in_popup = herdr.overlay_pane() is not None
    try:
        r = subprocess.run(
            ["fzf", FZF_SHELL, "--ansi", "--delimiter=\t", "--with-nth=2..", "--nth=2", "--no-sort",
             "--tabstop=1",
             "--layout=reverse", "--height=100%" if in_popup else "--height=90%", "--border=rounded",
             "--info=inline", f"--prompt={t('prompt')}", "--pointer=▶",
             "--color=hl:yellow:bold,hl+:yellow:bold,pointer:green,header:italic",
             f"--header={render.header(days, len(items), sort, None, cfg.recent_days)}", f"--query={query}",
             f"--preview={_self_cmd()} --preview {{1}}",
             "--preview-window=right,38%,wrap,border-left,<50(down,9,wrap,border-top)",
             *_bindings(cfg, ui_path)],
            input="\n".join(render.numbered_lines(items, lm, cfg.envs)), stdout=subprocess.PIPE, text=True)
        pending = ui_read(ui_path).get("pending") or "resume"
    finally:
        ui_path.unlink(missing_ok=True)
    if r.returncode != 0 or not r.stdout.strip():
        return None, None
    return r.stdout.split("\t", 1)[0], pending


def matching(cfg, items, live_map, query):
    """(number, session) pairs whose text contains every word of `query`."""
    words = query.lower().split()
    return [(i, s) for i, s in enumerate(items, 1)
            if all(w in render.search_text(s, live_map.get(s["id"]), cfg.envs) for w in words)]


def _choose_plain(cfg, items, lm, query):
    shown = [s for _, s in matching(cfg, items, lm, query)][:30]
    if not shown:
        print(t("no_match"))
        return None, None
    for i, s in enumerate(shown, 1):
        print(f"{render.DIM}{i:>3}{render.RESET} {render.row(s, lm.get(s['id']), cfg.envs)}")
    try:
        ans = input(t("ask_number")).strip()
    except (EOFError, KeyboardInterrupt):
        return None, None
    if ans.isdigit() and 0 < int(ans) <= len(shown):
        return shown[int(ans) - 1]["id"], "resume"
    return None, None
