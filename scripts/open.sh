#!/bin/sh
# Do not pass --cwd: relative pane commands resolve against the plugin directory.
exec "${HERDR_BIN_PATH:-herdr}" plugin pane open --plugin lazy-claude-herdr --entrypoint picker --placement overlay
