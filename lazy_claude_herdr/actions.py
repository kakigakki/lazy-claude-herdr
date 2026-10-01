"""What can be done to a session: built-in actions plus actions defined in config.

kind:
  exit   - closes the picker, then runs (resume, fork, open a pane ...)
  inline - runs and returns to the picker with a one-line confirmation
  pager  - takes over the screen to show output, then returns to the picker
"""
import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Callable

from . import herdr, render, sessions, system
from .config import VARIABLES, ConfigError
from .i18n import t

# Keys the picker already uses (fzf defaults, our bindings, and keys herdr commonly
# takes such as its ctrl-b prefix and ctrl-h/j/k/l pane navigation).
RESERVED_DIRECT = {"enter", "esc", "ctrl-c", "ctrl-g", "ctrl-s", "ctrl-a", "ctrl-d", "ctrl-o",
                   "ctrl-r", "ctrl-y", "ctrl-t", "ctrl-j", "ctrl-k", "ctrl-n", "ctrl-p", "up",
                   "down", "ctrl-b", "ctrl-h", "ctrl-l"}
RESERVED_MENU = set("jkq0123456789")


@dataclass
class Ctx:
    cfg: object
    st: dict | None  # herdr state, None outside herdr

    def live(self, s):
        return herdr.live_map(self.st).get(s["id"])

    def title(self, s):
        return render.title_of(s, self.live(s))

    def env_label(self, s):
        return render.env_of(s["cwd"], self.cfg.envs)[0]


@dataclass
class Action:
    id: str
    key: str
    label: str
    kind: str
    run: Callable
    available: Callable = lambda ctx, s: True
    direct: str | None = None


# --- running things in a pane, or here when outside herdr --------------------

def _exec_here(cwd, argv):
    os.chdir(cwd)
    os.execvp(argv[0], argv)


def _shell():
    return os.environ.get("SHELL") or "/bin/sh"


def open_pane(ctx, s, command, label):
    if ctx.st is None:
        _exec_here(s["cwd"], [_shell(), "-ic", command] if command else [_shell(), "-i"])
    herdr.open_pane(s["cwd"], ctx.st, command, label)
    print(t("opened", env=ctx.env_label(s), title=label))


def resume(ctx, s):
    if ctx.st is None:
        _exec_here(s["cwd"], ["claude", "-r", s["id"]])
    live = ctx.live(s)
    if live:
        herdr.focus(live["workspace_id"], live["terminal_id"])
        print(t("moved_live", env=ctx.env_label(s), title=ctx.title(s)))
        return
    open_pane(ctx, s, f"claude -r {s['id']}", ctx.title(s))


def fork(ctx, s):
    if ctx.st is None:
        _exec_here(s["cwd"], ["claude", "-r", s["id"], "--fork-session"])
    open_pane(ctx, s, f"claude -r {s['id']} --fork-session", f"{ctx.title(s)} {t('fork_suffix')}")


# --- built-in inline / pager actions -----------------------------------------

def _has_pr(ctx, s):
    return bool(s.get("pr_url"))


def open_pr(ctx, s):
    if not system.open_url(s["pr_url"]):
        return t("f_failed", label=t("a_open_pr"), error="no `open` / `xdg-open`")
    return t("f_opened_pr", pr=s["pr"])


def review_message(template, pr):
    return (template.replace("{title}", pr.get("title", "")).replace("{url}", pr.get("url", ""))
            .replace("{number}", str(pr.get("number", ""))))


def copy_review(ctx, s):
    out = subprocess.run(["gh", "pr", "view", s["pr_url"], "--json", "title,url,number"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return t("f_pr_fetch_failed", pr=s["pr"], error=(out.stderr.strip() or "gh failed")[:80])
    msg = review_message(ctx.cfg.review_template, json.loads(out.stdout))
    if not system.copy(msg):
        return _no_clipboard(t("a_copy_review"))
    herdr.notify(t("notify_review"), msg)
    return t("f_copied_review", pr=s["pr"])


def _no_clipboard(label):
    return t("f_failed", label=label, error="no pbcopy / wl-copy / xclip / xsel")


def pr_status(ctx, s):
    env = {**os.environ, "GH_FORCE_TTY": "100%"}
    view = subprocess.run(["gh", "pr", "view", s["pr_url"]], capture_output=True, text=True, env=env)
    checks = subprocess.run(["gh", "pr", "checks", s["pr_url"]], capture_output=True, text=True, env=env)
    system.page(f"{view.stdout or view.stderr}\n{render.BOLD}── CI ──{render.RESET}\n"
                f"{checks.stdout or checks.stderr}")


def conversation_log(ctx, s):
    from datetime import datetime
    out = [f"{render.BOLD}{ctx.title(s)}{render.RESET}  {render.DIM}{s['cwd']}{render.RESET}\n"]
    for role, ts, text in sessions.transcript(s):
        try:
            when = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%m/%d %H:%M")
        except (AttributeError, ValueError):
            when = ""
        who = (f"{render.GREEN}{render.BOLD}{t('log_you')}{render.RESET}" if role == "user"
               else f"{render.CYAN}{render.BOLD}{t('log_claude')}{render.RESET}")
        out.append(f"{who} {render.DIM}{when}{render.RESET}\n{text}\n")
    system.page("\n".join(out), start_at_end=True)


def _copier(text_fn, flash_key, label_key, **flash_fields):
    def run(ctx, s):
        if not system.copy(text_fn(s)):
            return _no_clipboard(t(label_key))
        return t(flash_key, **{k: f(s) for k, f in flash_fields.items()})
    return run


def builtins():
    return [
        Action("resume", "r", t("a_resume"), "exit", resume, direct="enter"),
        Action("fork", "f", t("a_fork"), "exit", fork, direct="ctrl-t"),
        Action("open-pr", "p", t("a_open_pr"), "inline", open_pr, _has_pr, direct="ctrl-r"),
        Action("copy-review", "y", t("a_copy_review"), "inline", copy_review, _has_pr, direct="ctrl-y"),
        Action("pr-status", "s", t("a_pr_status"), "pager", pr_status, _has_pr),
        Action("log", "l", t("a_log"), "pager", conversation_log),
        Action("shell", "n", t("a_shell"), "exit",
               lambda ctx, s: open_pane(ctx, s, None, ctx.env_label(s))),
        Action("copy-cmd", "c", t("a_copy_cmd"), "inline",
               _copier(lambda s: f"cd {shlex.quote(s['cwd'])} && claude -r {s['id']}", "f_copied_cmd",
                       "a_copy_cmd")),
        Action("copy-branch", "b", t("a_copy_branch"), "inline",
               _copier(lambda s: s["branch"], "f_copied_branch", "a_copy_branch", branch=lambda s: s["branch"]),
               lambda ctx, s: bool(s.get("branch"))),
        Action("copy-id", "i", t("a_copy_id"), "inline",
               _copier(lambda s: s["id"], "f_copied_id", "a_copy_id")),
    ]


# --- config-defined actions --------------------------------------------------

def variables(ctx, s) -> dict:
    return {"id": s["id"], "cwd": s["cwd"], "branch": s.get("branch") or "",
            "pr": str(s.get("pr") or ""), "pr_url": s.get("pr_url") or "",
            "pr_repo": s.get("pr_repo") or "", "title": ctx.title(s)}


_VAR_RE = re.compile(r"\{(" + "|".join(VARIABLES) + r")\}")


def expand(command: str, values: dict) -> str:
    """Substitute known `{var}`s, shell-quoted. Other braces (awk, ${VAR}) are left alone."""
    return _VAR_RE.sub(lambda m: shlex.quote(values[m.group(1)]), command)


def _env(values):
    return {**os.environ, **{f"LCH_{k.upper()}": v for k, v in values.items()}}


def _custom(ca, index):
    # `close = true` turns a background action into one that also closes the picker.
    kind = "exit" if ca.mode == "pane" or ca.close else {"background": "inline", "pager": "pager"}[ca.mode]

    def available(ctx, s):
        values = variables(ctx, s)
        if any(not values[v] for v in ca.requires):
            return False
        if not ca.when:
            return True
        try:
            r = subprocess.run(expand(ca.when, values), shell=True, cwd=s["cwd"], env=_env(values),
                               capture_output=True, timeout=3)
            return r.returncode == 0
        except subprocess.TimeoutExpired:
            return False

    def run(ctx, s):
        values = variables(ctx, s)
        command = expand(ca.run, values)
        if ca.mode == "pane":
            return open_pane(ctx, s, command, ca.label)
        if ca.mode == "pager":
            r = subprocess.run(command, shell=True, cwd=s["cwd"], env=_env(values),
                               capture_output=True, text=True)
            system.page(r.stdout + r.stderr)
            return None
        system.spawn_detached(command, shell=True, cwd=s["cwd"], env=_env(values))
        return t("f_started", label=ca.label)

    return Action(f"custom-{index}", ca.key, ca.label, kind, run, available, ca.direct)


def all_actions(cfg) -> list[Action]:
    acts = builtins()
    menu_keys = {a.key for a in acts}
    direct_keys = set(RESERVED_DIRECT)
    for i, ca in enumerate(cfg.actions):
        if ca.key in menu_keys or ca.key in RESERVED_MENU:
            raise ConfigError(f"actions[{i}]: menu key {ca.key!r} is already used")
        if ca.direct and ca.direct in direct_keys:
            raise ConfigError(f"actions[{i}]: direct key {ca.direct!r} is reserved or already used")
        menu_keys.add(ca.key)
        if ca.direct:
            direct_keys.add(ca.direct)
        acts.append(_custom(ca, i))
    return acts


def by_id(cfg, action_id) -> Action:
    return next(a for a in all_actions(cfg) if a.id == action_id)


def available_for(ctx, s) -> list[Action]:
    return [a for a in all_actions(ctx.cfg) if a.available(ctx, s)]


class Unavailable(Exception):
    pass


def run_checked(cfg, action_id, session_id, st=None):
    """Look the session up, check the action applies to it, run it.
    Returns the action's confirmation message (or None); raises Unavailable."""
    s = sessions.find(session_id)
    if not s:
        raise Unavailable(f"session not found: {session_id}")
    if not os.path.isdir(s["cwd"]):
        raise Unavailable(t("missing_cwd", cwd=s["cwd"]))
    ctx = Ctx(cfg, st if st is not None else herdr.state())
    act = by_id(cfg, action_id)
    if not act.available(ctx, s):
        raise Unavailable(t("f_unavailable"))
    return act.run(ctx, s)
