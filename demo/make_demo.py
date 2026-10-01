#!/usr/bin/env python3
"""Build a fake world for the demo recording: Claude projects, worktrees, a config
and a herdr state served by the test suite's fake herdr. Nothing real is shown.

usage: make_demo.py <out-dir>
"""
import json
import os
import sys
import time
from pathlib import Path

out = Path(os.path.abspath(sys.argv[1]))  # no realpath: keep /tmp, not /private/tmp
code = out / "code"
projects = out / "projects"
now = time.time()

WORKTREES = ["shop-api", "shop-web", "shop-web-alt1", "shop-web-alt2", "infra"]
SESSIONS = [
    # id, worktree, minutes ago, title, branch, pr, last prompt
    ("a1", "shop-web-alt1", 3, "Checkout: apply coupon codes", "feat/coupons", 812,
     "Coupons should stack with the member discount, but only one coupon per order."),
    ("a2", "shop-api", 9, "Rate limit the search endpoint", "fix/search-rate-limit", 809,
     "Add a token bucket per API key and return 429 with Retry-After."),
    ("a3", "shop-web", 25, "決済フローのリファクタ", "refactor/payment-flow", None,
     "Split the payment step into its own component and keep the tests green."),
    ("a4", "shop-web-alt2", 70, "Dark mode for the order history", "feat/dark-orders", 805,
     "Use the design tokens; no hard-coded colours."),
    ("a5", "infra", 180, "Upgrade Postgres to 17", "chore/pg17", 798,
     "Plan the upgrade with zero downtime; check extensions first."),
    ("a6", "shop-api", 60 * 26, "Flaky test in orders spec", "fix/flaky-orders", 801,
     "The spec fails about one run in ten on CI. Find out why."),
    ("a7", "shop-web", 60 * 30, "Explain the cart state machine", "main", None,
     "Draw the states and transitions of the cart."),
    ("a8", "shop-web-alt1", 60 * 50, "Image lazy loading on PLP", "perf/plp-images", 790,
     "LCP is 3.1s on the product list page."),
]
LIVE = {"a1": ("W2", "W2:p2"), "a2": ("W1", "W1:p2")}

for name in WORKTREES:
    (code / name).mkdir(parents=True, exist_ok=True)

for sid, wt, minutes, title, branch, pr, prompt in SESSIONS:
    cwd = str(code / wt)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - minutes * 60))
    rows = [
        {"type": "user", "cwd": cwd, "gitBranch": branch, "entrypoint": "cli", "sessionId": sid,
         "timestamp": stamp, "message": {"role": "user", "content": prompt}},
        {"type": "assistant", "timestamp": stamp, "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Sure — let me look at the relevant code first."}]}},
        {"type": "user", "cwd": cwd, "gitBranch": branch, "timestamp": stamp,
         "message": {"role": "user", "content": "Looks good, go ahead."}},
        {"type": "assistant", "timestamp": stamp, "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Done. Tests pass; I opened a PR with the changes."}]}},
        {"type": "ai-title", "aiTitle": title, "sessionId": sid},
        {"type": "last-prompt", "lastPrompt": prompt, "sessionId": sid},
    ]
    if pr:
        rows.append({"type": "pr-link", "sessionId": sid, "prNumber": pr,
                     "prUrl": f"https://github.com/acme/shop/pull/{pr}", "prRepository": "acme/shop"})
    proj = projects / ("-" + cwd.strip("/").replace("/", "-"))
    proj.mkdir(parents=True, exist_ok=True)
    path = proj / f"{sid}.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows) + "\n")
    os.utime(path, (now - minutes * 60, now - minutes * 60))

(out / "config.toml").write_text(f'''
[[envs]]
match = "{code}/shop-api"
label = "api"
color = "blue"

[[envs]]
match = "{code}/shop-web"
label = "web"
color = "green"

[[envs]]
match = "{code}/shop-web-alt*"
label = "web-alt"
color = "cyan"

[[actions]]
key = "e"
label = "Open the app in browser"
run = "open http://localhost:3000/"
''')

(out / "herdr-state.json").write_text(json.dumps({
    "agents": [{"agent_session": {"value": sid}, "workspace_id": ws, "pane_id": pane,
                "name": next(s[3] for s in SESSIONS if s[0] == sid),
                "terminal_id": f"term-{sid}", "cwd": str(code / next(s[1] for s in SESSIONS if s[0] == sid))}
               for sid, (ws, pane) in LIVE.items()],
    "workspaces": [{"workspace_id": "W1", "label": "shop-api", "active_tab_id": "W1:t1"},
                   {"workspace_id": "W2", "label": "shop-web-alt1", "active_tab_id": "W2:t1"}],
}))
# A stand-in for `claude` so the herdr demo can "resume" without Claude Code. It ends
# in a process literally named `claude` (a tiny C program that just waits), which is
# what herdr's agent detection looks at. Copying a system binary doesn't work on macOS:
# the copy loses its signature and is killed.
import subprocess  # noqa: E402
(out / "bin").mkdir(exist_ok=True)
(out / "libexec").mkdir(exist_ok=True)
(out / "libexec" / "stub.c").write_text("#include <unistd.h>\nint main(void){for(;;)pause();}\n")
subprocess.run(["cc", "-o", str(out / "libexec" / "claude"), str(out / "libexec" / "stub.c")], check=True)
fake = out / "bin" / "claude"
fake.write_text('#!/bin/sh\nclear\nprintf "\\033[1;35m✻ Claude Code\\033[0m  (demo stand-in)\\n\\nresumed session %s\\n\\n> " "$2"\n'
                f'exec "{out}/libexec/claude"\n')
fake.chmod(0o755)
# herdr spawns $SHELL for every pane; this one skips all rc/profile files so the
# demo shows neither the host's prompt (user/host names) nor its PATH.
shell = out / "bin" / "demo-shell"
# fzf also runs its preview / bindings through `$SHELL -c`, so pass those through.
shell.write_text(f'#!/bin/bash\nexport PATH="{out}/bin:$PATH" PS1="$ " BASH_SILENCE_DEPRECATION_WARNING=1\n'
                 'if [ "$1" = "-c" ]; then shift; exec /bin/bash --norc --noprofile -c "$@"; fi\n'
                 'exec /bin/bash --norc --noprofile -i\n')
shell.chmod(0o755)
print(out)
