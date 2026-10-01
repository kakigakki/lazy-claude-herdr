"""Turning sessions into aligned, coloured terminal rows, header and preview."""
import fnmatch
import os
import unicodedata
from datetime import datetime
from pathlib import Path

from .i18n import t

RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
GREEN, YELLOW, CYAN = "\033[32m", "\033[33m", "\033[36m"
NEUTRAL = "37"
HERDR_WORKTREES = str(Path.home() / ".herdr" / "worktrees") + "/"


def sgr(code: str, text: str) -> str:
    return f"\033[{code}m{text}{RESET}"


# --- environments -----------------------------------------------------------

def env_of(cwd: str, envs) -> tuple[str, str, int]:
    """(label, colour, sort index) for a session directory."""
    cwd = cwd.rstrip("/")
    for i, env in enumerate(envs):
        if fnmatch.fnmatchcase(cwd, env.match) or fnmatch.fnmatchcase(cwd, env.match + "/*"):
            return env.label, env.color, i
    name = os.path.basename(cwd) or cwd
    if cwd.startswith(HERDR_WORKTREES):
        name = "herdr:" + name
    return name, NEUTRAL, len(envs)


# --- width-aware text -------------------------------------------------------

def _cw(c: str) -> int:
    return 2 if unicodedata.east_asian_width(c) in "WF" else 1


def cell_width(text: str) -> int:
    return sum(_cw(c) for c in text)


def fit(text: str, width: int) -> str:
    """Truncate to `width` terminal cells (CJK counts as 2) and right-pad."""
    if cell_width(text) <= width:
        return text + " " * (width - cell_width(text))
    out, w = "", 0
    for c in text:
        if w + _cw(c) > width - 1:
            break
        out += c
        w += _cw(c)
    return out + "…" + " " * (width - w - 1)


def when_label(ts: float) -> str:
    d = datetime.fromtimestamp(ts)
    days = (datetime.now().date() - d.date()).days
    day = t("today") if days == 0 else t("yesterday") if days == 1 else d.strftime("%m/%d")
    return f"{day} {d:%H:%M}"


# --- rows -------------------------------------------------------------------

def title_of(s: dict, live: dict | None) -> str:
    return (s.get("custom_title") or (live or {}).get("name") or s.get("ai_title")
            or (s.get("last_prompt") or "").replace("\n", " ")[:60] or t("untitled"))


def row(s: dict, live: dict | None, envs, title_width=46) -> str:
    label, color, _ = env_of(s["cwd"], envs)
    mark = f"{GREEN}●{RESET}" if live else f"{DIM}·{RESET}"
    pr = f"{YELLOW}{fit('#' + str(s['pr']), 7)}{RESET}" if s.get("pr") else " " * 7
    return (f"{mark} {sgr(color, fit(label, 14))} {DIM}{fit(when_label(s['mtime']), 11)}{RESET} "
            f"{BOLD}{fit(title_of(s, live), title_width)}{RESET} {pr} {DIM}{s.get('branch') or ''}{RESET}")


def numbered_lines(sessions, live_map, envs) -> list[str]:
    """`<id>\\t<number>\\t<row>`: fzf hides field 1 and searches only field 3."""
    return [f"{s['id']}\t{DIM}{i:>3}{RESET}\t{row(s, live_map.get(s['id']), envs)}"
            for i, s in enumerate(sessions, 1)]


def search_text(s: dict, live: dict | None, envs) -> str:
    label = env_of(s["cwd"], envs)[0]
    parts = (label, title_of(s, live), s.get("branch"), s.get("pr") and f"#{s['pr']}", s["id"])
    return " ".join(str(p) for p in parts if p).lower()


def header(period_days, count, sort, flash=None, default_days=14) -> str:
    period = t("period_days", days=period_days) if period_days else t("period_all")
    lines = []
    if flash:
        lines.append(f"{YELLOW}{BOLD}✔ {flash}{RESET}")
    lines.append(f"{period} · {t('count', n=count)} · {t('sort_' + sort)}   {GREEN}●{RESET} {t('live_legend')}")
    lines.append(t("help_line"))
    lines.append(f"{DIM}{t('direct_line', days=default_days)}{RESET}")
    return "\n".join(lines)


def preview(s: dict, live: dict | None, envs) -> str:
    label = env_of(s["cwd"], envs)[0]
    status = (f"{GREEN}{t('p_live', pane=live.get('name') or live.get('pane_id'))}{RESET}"
              if live else t("p_stopped"))
    rows = [
        (t("p_status"), status),
        (t("p_env"), f"{label}  {DIM}{s['cwd']}{RESET}"),
        (t("p_branch"), s.get("branch") or "-"),
        (t("p_pr"), f"#{s['pr']}  {DIM}{s.get('pr_url') or ''}{RESET}" if s.get("pr") else "-"),
        (t("p_last"), datetime.fromtimestamp(s["mtime"]).strftime("%Y-%m-%d %H:%M")),
        (t("p_id"), f"{DIM}{s['id']}{RESET}"),
    ]
    width = max(cell_width(k) for k, _ in rows) + 1
    out = [f"{BOLD}{title_of(s, live)}{RESET}", ""]
    out += [f"{DIM}{fit(k, width)}{RESET} {v}" for k, v in rows]
    if s.get("last_prompt"):
        out += ["", f"{DIM}{t('p_last_prompt')}{RESET}", s["last_prompt"][:600]]
    return "\n".join(out)
