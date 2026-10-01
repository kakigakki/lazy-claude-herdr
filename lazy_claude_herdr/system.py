"""Platform helpers: clipboard, opening URLs, pager, detached processes."""
import os
import shutil
import subprocess
import sys

PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _first(*cmds):
    for cmd in cmds:
        if shutil.which(cmd[0]):
            return cmd
    return None


def copy(text: str) -> bool:
    cmd = _first(["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"])
    if not cmd:
        return False
    subprocess.run(cmd, input=text, text=True)
    return True


def open_url(url: str) -> bool:
    cmd = _first(["open"] if sys.platform == "darwin" else ["xdg-open"], ["xdg-open"], ["open"])
    if not cmd:
        return False
    subprocess.run([*cmd, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def spawn_detached(args, **kw) -> None:
    """Start a process that outlives us (and the herdr overlay we may be running in)."""
    subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, **kw)


def page(text: str, start_at_end=False) -> None:
    args = ["less", "-R"] + (["+G"] if start_at_end else [])
    if shutil.which("less") and sys.stdout.isatty():
        subprocess.run(args, input=text, text=True)
    else:
        sys.stdout.write(text + "\n")
