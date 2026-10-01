# lazy-claude-herdr

**English** · [日本語](README.ja.md) · [中文](README.zh.md)

Find any Claude Code session from any [herdr](https://herdr.dev) space and resume it **where it started**.

If you run Claude Code in several herdr spaces (one per git worktree, say), `claude --resume` only shows the sessions of the directory you're in. The next day you've forgotten which space a task lived in. lazy-claude-herdr pops up one list of every session, and Enter takes you back:

- **live session** → focuses the pane it's running in, in whatever space that is
- **stopped session** → splits a pane in the space that matches its directory and runs `claude -r` there (creates the space if there is none)

![herdr popup](demo/herdr.gif)

## Features

- One key from anywhere in herdr opens it as an overlay popup
- Every row: live marker, environment, last activity, title, PR, branch — aligned, coloured per environment
- Type to fuzzy-filter; **type a number to jump** to that row
- `ctrl-s` cycles the sort: recent / by environment / live first; `ctrl-a` / `ctrl-d` switch between all retained sessions and the last N days
- Preview: status, path, branch, PR, last prompt
- `ctrl-o` opens an action menu for the row: fork into a new pane, open the PR, copy a review-request message, PR status and CI, read the conversation log, open a shell pane, copy the resume command / branch / ID — plus your own actions from config
- Direct keys: `ctrl-r` open PR · `ctrl-y` copy review request · `ctrl-t` fork
- UI in English, Japanese or Chinese
- Works as a plain CLI outside herdr, too

![picker](demo/demo.gif)

## Requirements

- herdr ≥ 0.7, with the Claude integration installed (`herdr integration install claude`) — without it everything works except the live marker
- [fzf](https://github.com/junegunn/fzf)
- Python ≥ 3.11 (standard library only)
- Optional: [`gh`](https://cli.github.com/) for PR status and the review-request title
- macOS or Linux

## Install

```sh
herdr plugin install kakigakki/lazy-claude-herdr
```

Bind a key in `~/.config/herdr/config.toml`, then `herdr server reload-config`:

```toml
[[keys.command]]
key = "prefix+f"
type = "plugin_action"
command = "lazy-claude-herdr.open"
```

To use it as a command as well, link the entry point into your PATH:

```sh
root=$(herdr plugin list --json | python3 -c 'import json,sys; print(next(p["plugin_root"] for p in json.load(sys.stdin)["result"]["plugins"] if p["plugin_id"] == "lazy-claude-herdr"))')
ln -s "$root/bin/lazy-claude-herdr" ~/.local/bin/
```

## Usage

| In the list | |
|---|---|
| type text | fuzzy filter (title, environment, branch, `#PR`) |
| type a number | jump to that row (digits never filter — search a PR as `#123`) |
| `Enter` | resume |
| `ctrl-o` | action menu (letters or numbers run an item) |
| `ctrl-s` | cycle sort |
| `ctrl-a` / `ctrl-d` | all retained sessions / last N days |
| `ctrl-r` / `ctrl-y` / `ctrl-t` | open PR / copy review request / fork |
| `esc` | close |

Command line:

```sh
lazy-claude-herdr [keywords]       # open the picker, pre-filtered
lazy-claude-herdr -a               # all retained sessions
lazy-claude-herdr -l [keywords]    # print the list
lazy-claude-herdr -s env           # sort: recent | env | live
lazy-claude-herdr --do resume <id> # run one action without the picker
```

## Configuration

`~/.config/lazy-claude-herdr/config.toml` (or `$XDG_CONFIG_HOME/...`, or `$LAZY_CLAUDE_HERDR_CONFIG`). Everything is optional; see [examples/config.toml](examples/config.toml).

```toml
language = "en"                 # en | ja | zh

[defaults]
days = 14                       # 0 = all retained sessions
sort = "recent"                 # recent | env | live

[review_request]
template = "Please review: {title}\n{url}"   # {title} {url} {number}

[[envs]]                        # how directories are labelled; order = "by environment" order
match = "~/code/shop-*"         # path or glob, subdirectories match too
label = "shop-wt"
color = "cyan"                  # or "ansi:38;5;208"

[[actions]]                     # your own menu items
key = "g"
label = "Open lazygit here"
run = "lazygit"                 # {id} {cwd} {branch} {pr} {pr_url} {pr_repo} {title}
mode = "pane"                   # background (default) | pane | pager
requires = []                   # hide when any of these variables is empty
when = "test -d .git"           # hide unless this exits 0 (runs in the session's directory)
direct = "ctrl-g"               # optional key in the list
close = false                   # true: a background action also closes the picker
```

Variables are shell-quoted when substituted and also exported as `LCH_ID`, `LCH_CWD`, `LCH_BRANCH`, … Commands run with `/bin/sh` in the session's directory (`pane` mode runs them in your shell inside the new pane).

## How it works

- Sessions are read from Claude Code's transcripts under `~/.claude/projects` (`$CLAUDE_CONFIG_DIR` is respected), indexed with a small cache keyed by file size and mtime. Non-interactive (`claude -p`) sessions and sessions whose directory is gone are hidden.
- herdr is driven through its CLI: the Claude integration's `agent_session` tells which pane runs which session; a space is matched by worktree path, then by pane directory, then by label.
- In the popup, focus changes are handed to a detached process that waits for the overlay to close, because herdr restores the previous focus when an overlay closes.

## Caveats

- **Claude Code's transcript format is not a public API.** Titles, PR links and other fields can change with any Claude Code release. Missing fields degrade (for example an empty PR column) instead of failing, but expect occasional breakage.
- Relies on herdr 0.7 APIs (plugin overlay panes, `agent_session`); tested with herdr 0.7.3.
- Claude Code deletes sessions after `cleanupPeriodDays` (30 by default), so "all periods" reaches back about that far.

## Development

```sh
python3 -m unittest discover -s tests   # stdlib only; fakes for herdr, gh, clipboard on PATH
vhs demo/demo.tape                      # regenerate demo/demo.gif (fixture data)
vhs demo/herdr.tape                     # regenerate demo/herdr.gif (isolated herdr session)
herdr session stop lch-demo && herdr session delete lch-demo
```

## License

MIT
