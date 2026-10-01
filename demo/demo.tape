# Regenerate the README GIF:  vhs demo/demo.tape   (run from the repository root)
# Everything shown comes from demo/make_demo.py; no real sessions are used.

Output demo/demo.gif

Require fzf
Set Shell "bash"
Set FontSize 14
Set Width 1800
Set Height 640
Set Padding 16
Set Theme "Catppuccin Mocha"
Set TypingSpeed 60ms

Hide
Type "export D=/tmp/lch-demo && rm -rf $D && python3 demo/make_demo.py $D >/dev/null"
Enter
Type "export LAZY_CLAUDE_HERDR_PROJECTS=$D/projects LAZY_CLAUDE_HERDR_CONFIG=$D/config.toml LAZY_CLAUDE_HERDR_CACHE=$D/cache"
Enter
Type "export FAKE_HERDR_STATE=$D/herdr-state.json FAKE_HERDR_LOG=$D/herdr.log FAKE_CLIP=$D/clip FAKE_OPEN_LOG=$D/open.log HERDR_SOCKET_PATH=$D/sock"
Enter
Type "export PATH=$PWD/tests/fakes/bin:$PWD/bin:$PATH PS1='$ ' && clear"
Enter
Show

Type "lazy-claude-herdr"
Sleep 400ms
Enter
Sleep 2s

# move around: the preview follows
Down
Sleep 900ms
Down
Sleep 900ms

# fuzzy filter
Type "coupon"
Sleep 1.5s
Ctrl+U
Sleep 500ms

# jump by number
Type "5"
Sleep 1.5s
Backspace
Sleep 500ms

# sort: by environment, then live first
Ctrl+S
Sleep 1.8s
Ctrl+S
Sleep 1.8s
Ctrl+S
Sleep 1s

# action menu on a row, copy a review request
Down
Sleep 600ms
Ctrl+O
Sleep 2s
Type "y"
Sleep 2s

# read the conversation log
Ctrl+O
Sleep 1s
Type "l"
Sleep 2.5s
Type "q"
Sleep 1s

# resume: in herdr this jumps to (or opens a pane in) the session's space
Up
Sleep 600ms
Enter
Sleep 2.5s
