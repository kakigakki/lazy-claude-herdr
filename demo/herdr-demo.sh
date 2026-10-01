#!/bin/sh
# Starts an isolated herdr session ("lch-demo") on fixture data for demo/herdr.tape.
# Two spaces get a "live" Claude pane, reported the way herdr's Claude integration would.
D=${1:?usage: herdr-demo.sh <demo-dir>}
REPO=$(cd "$(dirname "$0")/.." && pwd)
SOCK="$HOME/.config/herdr/sessions/lch-demo/herdr.sock"
unset HERDR_ENV HERDR_SOCKET_PATH HERDR_PANE_ID HERDR_TAB_ID HERDR_WORKSPACE_ID
herdr session delete lch-demo >/dev/null 2>&1
export LAZY_CLAUDE_HERDR_PROJECTS=$D/projects LAZY_CLAUDE_HERDR_CONFIG=$D/config.toml LAZY_CLAUDE_HERDR_CACHE=$D/cache
export PATH="$D/bin:$PATH" PS1='$ ' SHELL="$D/bin/demo-shell"
(
  sleep 3
  h() { HERDR_SOCKET_PATH="$SOCK" herdr "$@"; }
  h plugin link "$REPO" >/dev/null
  for spec in "shop-api:a2:Rate limit the search endpoint" "shop-web-alt1:a1:Checkout: apply coupon codes"; do
    dir=${spec%%:*}; rest=${spec#*:}; sid=${rest%%:*}; title=${rest#*:}
    pane=$(h workspace create --cwd "$D/code/$dir" --label "$dir" --no-focus |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["root_pane"]["pane_id"])')
    for _ in 1 2 3 4 5 6 7 8 9 10; do  # wait for the pane's shell prompt
      [ -n "$(h pane read "$pane" --lines 3 --source visible | tr -d '[:space:]')" ] && break
      sleep 0.5
    done
    h pane run "$pane" "claude -r $sid" >/dev/null
    sleep 1
    h pane rename "$pane" "$title" >/dev/null
    h pane report-agent-session "$pane" --source herdr:claude --agent claude --agent-session-id "$sid" >/dev/null
  done
) &
cd "$D/code/shop-web" && exec herdr --session lch-demo
