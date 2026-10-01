"""lazy-claude-herdr — find a Claude Code session from any herdr space and resume
it where it started.

usage:
  lazy-claude-herdr [keywords...]   pick from recent sessions (fuzzy filter preset)
  lazy-claude-herdr -a [keywords]   all retained sessions
  lazy-claude-herdr -l [keywords]   print the list and exit
  lazy-claude-herdr -s env          sort: recent | env | live   (ctrl-s cycles in the picker)
  lazy-claude-herdr --do <action> <session-id>
                                    run one action without the picker (e.g. resume, open-pr)
  lazy-claude-herdr -h              this help

In the picker: type to filter, type a number to jump, Enter to resume, ctrl-o for
the action menu. Config: ~/.config/lazy-claude-herdr/config.toml
"""
import re
import sys

from . import actions, config, herdr, picker, render, sessions


def _list(cfg, items, lm, query):
    tty = sys.stdout.isatty()
    for i, s in picker.matching(cfg, items, lm, query):
        line = f"{render.DIM}{i:>3}{render.RESET} {render.row(s, lm.get(s['id']), cfg.envs)}"
        print(line if tty else re.sub(r"\033\[[0-9;]*m", "", line))


# Sub-commands used by fzf bindings and the popup (not part of the public CLI),
# with the number of arguments each takes.
_INTERNAL = {"--preview": 1, "--ui": 2, "--menu": 2, "--act": 3, "--focus-after": 3}


def _internal(cfg, cmd, args):
    if len(args) != _INTERNAL[cmd]:
        print(f"lazy-claude-herdr: {cmd} takes {_INTERNAL[cmd]} arguments", file=sys.stderr)
        return 2
    if cmd == "--preview":
        s = sessions.find(args[0])
        if s:
            print(render.preview(s, herdr.live_map(herdr.state()).get(s["id"]), cfg.envs))
    elif cmd == "--ui":
        picker.ui_command(cfg, *args)
    elif cmd == "--menu":
        picker.menu(cfg, *args)
    elif cmd == "--act":
        picker.run_now(cfg, *args)
    else:
        herdr.focus_after(*args)
    return 0


def _run(cfg, action_id, session_id, st=None) -> int:
    try:
        message = actions.run_checked(cfg, action_id, session_id, st)
    except actions.Unavailable as e:
        print(e, file=sys.stderr)
        return 1
    if message:
        print(message)
    return 0


def _do(cfg, args) -> int:
    """Run one action on one session without the picker (scripting / key bindings)."""
    if len(args) != 2:
        print("usage: lazy-claude-herdr --do <action> <session-id>", file=sys.stderr)
        return 2
    ids = [a.id for a in actions.all_actions(cfg)]
    if args[0] not in ids:
        print(f"unknown action {args[0]!r} (one of: {', '.join(ids)})", file=sys.stderr)
        return 2
    return _run(cfg, *args)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        cfg = config.load()
        actions.all_actions(cfg)  # validate key collisions up front
    except config.ConfigError as e:
        print(f"lazy-claude-herdr: config error: {e}", file=sys.stderr)
        return 2
    if argv and argv[0] in _INTERNAL:
        return _internal(cfg, argv[0], argv[1:])
    if argv[:1] == ["--do"]:
        return _do(cfg, argv[1:])

    days, sort, list_only, words = cfg.days, cfg.sort, False, []
    it = iter(argv)
    for a in it:
        if a == "-a":
            days = None
        elif a == "-l":
            list_only = True
        elif a == "-s":
            sort = next(it, "")
            if sort not in config.SORTS:
                print(f"-s must be one of {', '.join(config.SORTS)}", file=sys.stderr)
                return 2
        elif a in ("-h", "--help"):
            print(__doc__.strip())
            return 0
        else:
            words.append(a)

    st = herdr.state()
    items, lm = picker.listing(cfg, days, sort, st)
    if list_only:
        _list(cfg, items, lm, " ".join(words))
        return 0
    session_id, action_id = picker.choose(cfg, items, lm, " ".join(words), days, sort)
    if not session_id:
        return 0
    # Exit actions chosen by a direct key never went through the menu's availability
    # filter, so this goes through the same check as --do.
    return _run(cfg, action_id, session_id, st)


def run():
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.stderr.close()
    except KeyboardInterrupt:
        sys.exit(130)
