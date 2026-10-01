"""End-to-end tests: the CLI runs as a subprocess against fixture sessions, with
fake herdr / clipboard / opener / gh executables first on PATH."""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAKES = Path(__file__).resolve().parent / "fakes"
ANSI = re.compile(r"\033\[[0-9;]*m")


def strip(text):
    return ANSI.sub("", text)


def cells(text):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


class Fixture:
    """A temporary home with Claude projects, config, cache and fake-tool logs."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.projects = self.root / "projects"
        self.workdirs = self.root / "work"
        self.config = self.root / "config.toml"
        self.state = self.root / "herdr-state.json"
        self.herdr_log = self.root / "herdr.log"
        self.clip = self.root / "clip"
        self.open_log = self.root / "open.log"
        self.projects.mkdir()
        self.workdirs.mkdir()
        self.set_herdr({"agents": [], "workspaces": []})

    def workdir(self, name):
        d = self.workdirs / name
        d.mkdir(exist_ok=True)
        return str(d)

    def session(self, sid, cwd, *, age_min=5, branch="main", title=None, pr=None,
                prompt=None, entrypoint="cli", extra=()):
        lines = [{"type": "user", "cwd": cwd, "gitBranch": branch, "entrypoint": entrypoint,
                  "sessionId": sid, "timestamp": "2026-09-30T01:00:00Z",
                  "message": {"role": "user", "content": prompt or "hello"}},
                 {"type": "assistant", "timestamp": "2026-09-30T01:01:00Z",
                  "message": {"role": "assistant", "content": [{"type": "text", "text": "hi there"}]}}]
        if title:
            lines.append({"type": "ai-title", "aiTitle": title, "sessionId": sid})
        if prompt:
            lines.append({"type": "last-prompt", "lastPrompt": prompt, "sessionId": sid})
        if pr:
            lines.append({"type": "pr-link", "sessionId": sid, "prNumber": pr,
                          "prUrl": f"https://github.com/acme/app/pull/{pr}", "prRepository": "acme/app"})
        lines += list(extra)
        proj = self.projects / ("-" + cwd.strip("/").replace("/", "-"))
        proj.mkdir(exist_ok=True)
        path = proj / f"{sid}.jsonl"
        path.write_text("\n".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) for x in lines) + "\n")
        mtime = time.time() - age_min * 60
        os.utime(path, (mtime, mtime))
        return path

    def set_config(self, text):
        self.config.write_text(text)

    def set_herdr(self, state):
        self.state.write_text(json.dumps(state))

    def env(self, herdr=True, path=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("HERDR_", "LAZY_CLAUDE_HERDR_"))}
        env.update({
            "LAZY_CLAUDE_HERDR_PROJECTS": str(self.projects),
            "LAZY_CLAUDE_HERDR_CONFIG": str(self.config),
            "LAZY_CLAUDE_HERDR_CACHE": str(self.root / "cache"),
            "FAKE_HERDR_STATE": str(self.state), "FAKE_HERDR_LOG": str(self.herdr_log),
            "FAKE_CLIP": str(self.clip), "FAKE_OPEN_LOG": str(self.open_log),
            "PATH": path or f"{FAKES / 'bin'}:{os.environ['PATH']}",
        })
        if herdr:
            env["HERDR_SOCKET_PATH"] = str(self.root / "herdr.sock")
        return env

    def run(self, *args, herdr=True, path=None):
        return subprocess.run([sys.executable, "-m", "lazy_claude_herdr", *args], cwd=ROOT,
                              env=self.env(herdr, path), capture_output=True, text=True, timeout=30)

    def herdr_calls(self):
        if not self.herdr_log.exists():
            return []
        return [json.loads(line) for line in self.herdr_log.read_text().splitlines()]

    def mutating_calls(self):
        return [c for c in self.herdr_calls() if c[:2] not in (["agent", "list"], ["workspace", "list"])]


class Base(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.addCleanup(self.f.tmp.cleanup)

    def lines(self, *args, **kw):
        r = self.f.run("-l", *args, **kw)
        self.assertEqual(r.returncode, 0, r.stderr)
        return [strip(line) for line in r.stdout.splitlines()]


class ListingTest(Base):
    def test_lists_resumable_sessions_newest_first_with_numbers(self):
        app = self.f.workdir("app")
        self.f.session("old", app, age_min=60, title="Older task")
        self.f.session("new", app, age_min=1, title="Newer task", pr=42, branch="feat/x")
        self.f.session("printmode", app, entrypoint="sdk-cli", title="claude -p run")
        self.f.session("gone", str(self.f.root / "deleted"), title="Removed worktree")
        lines = self.lines()
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[0], r"^\s+1 · app\s+today \d\d:\d\d\s+Newer task\s+#42\s+feat/x$")
        self.assertRegex(lines[1], r"^\s+2 · app\s+.*Older task")

    def test_missing_fields_degrade_to_last_prompt_or_untitled(self):
        app = self.f.workdir("app")
        self.f.session("a", app, prompt="please fix the login bug")
        self.f.session("b", app, age_min=10)
        lines = self.lines()
        self.assertIn("please fix the login bug", lines[0])
        self.assertIn("(untitled)", lines[1])

    def test_period_filter_and_all(self):
        app = self.f.workdir("app")
        self.f.session("recent", app, title="Recent")
        self.f.session("ancient", app, age_min=60 * 24 * 20, title="Ancient")
        self.assertEqual(len(self.lines()), 1)
        self.assertEqual(len(self.lines("-a")), 2)

    def test_cache_picks_up_changed_files(self):
        app = self.f.workdir("app")
        path = self.f.session("s", app, title="First title")
        self.assertIn("First title", self.lines()[0])
        with path.open("a") as fh:
            fh.write(json.dumps({"type": "ai-title", "aiTitle": "Second title"}, separators=(",", ":")) + "\n")
        self.assertIn("Second title", self.lines()[0])

    def test_keyword_filter(self):
        app = self.f.workdir("app")
        self.f.session("a", app, title="Payment flow", branch="feat/pay")
        self.f.session("b", app, title="Search box", branch="feat/search")
        self.assertEqual(len(self.lines("pay")), 1)
        self.assertEqual(len(self.lines("search")), 1)

    def test_cjk_titles_keep_columns_aligned(self):
        app = self.f.workdir("app")
        self.f.session("a", app, title="日本語のタイトルとても長いタイトルですよ本当に長いです", pr=1, branch="b1")
        self.f.session("b", app, age_min=10, title="ascii title", pr=2, branch="b2")
        first, second = self.lines()
        self.assertEqual(cells(first[:first.index("#1")]), cells(second[:second.index("#2")]))


class ConfigTest(Base):
    def test_env_labels_and_env_sort_order(self):
        a, b, c = self.f.workdir("alpha"), self.f.workdir("beta"), self.f.workdir("zeta")
        self.f.set_config(f'''
[[envs]]
match = "{b}"
label = "B-env"
color = "cyan"
[[envs]]
match = "{self.f.workdirs}/alp*"
label = "A-env"
''')
        self.f.session("s1", c, age_min=1, title="z")
        self.f.session("s2", a, age_min=2, title="a")
        self.f.session("s3", b, age_min=3, title="b")
        labels = [line.split()[2] for line in self.lines("-s", "env")]
        self.assertEqual(labels, ["B-env", "A-env", "zeta"])
        raw = self.f.run("-l").stdout
        self.assertNotIn("\033[1;36m", raw)  # not a tty: colours stripped

    def test_invalid_config_is_reported(self):
        self.f.set_config('[[envs]]\nmatch = "/x"\nlabel = "x"\ncolor = "purple"\n')
        r = self.f.run("-l")
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown color 'purple'", r.stderr)

    def test_language_switch(self):
        self.f.session("s", self.f.workdir("app"), title="t")
        self.f.set_config('language = "ja"\n')
        self.assertIn("今日", self.lines()[0])
        self.f.set_config('language = "zh"\n')
        self.assertIn("今天", self.lines()[0])
        self.f.set_config('language = "fr"\n')
        self.assertIn("unknown language", self.f.run("-l").stderr)

    def test_defaults_section(self):
        app = self.f.workdir("app")
        self.f.session("recent", app, title="Recent")
        self.f.session("ancient", app, age_min=60 * 24 * 20, title="Ancient")
        self.f.set_config("[defaults]\ndays = 0\n")
        self.assertEqual(len(self.lines()), 2)

    def test_custom_action_validation(self):
        cases = {
            'key = ","': "key must be a single letter",
            'key = 1': "key must be a single letter",
            'key = "z"\ndirect = "ctrl+x"': "direct must look like",
            'key = "z"\nrequires = "pr"': "requires must be a list",
        }
        for body, message in cases.items():
            self.f.set_config(f'[[actions]]\nlabel = "x"\nrun = "true"\n{body}\n')
            r = self.f.run("-l")
            self.assertEqual(r.returncode, 2, body)
            self.assertIn(message, r.stderr, body)

    def test_custom_action_key_collisions(self):
        self.f.set_config('[[actions]]\nkey = "p"\nlabel = "x"\nrun = "true"\n')
        self.assertIn("menu key 'p' is already used", self.f.run("-l").stderr)
        self.f.set_config('[[actions]]\nkey = "z"\nlabel = "x"\nrun = "true"\ndirect = "ctrl-s"\n')
        self.assertIn("direct key 'ctrl-s' is reserved", self.f.run("-l").stderr)


class HerdrTest(Base):
    def live_state(self, cwd, sid):
        return {"agents": [{"agent_session": {"value": sid}, "name": "pane name", "pane_id": "W1:p1",
                            "terminal_id": "term_1", "workspace_id": "W1", "cwd": cwd}],
                "workspaces": [{"workspace_id": "W1", "label": "app", "active_tab_id": "W1:t1"}]}

    def test_live_marker_and_pane_name_title(self):
        app = self.f.workdir("app")
        self.f.session("live", app, title="ai title")
        self.f.set_herdr(self.live_state(app, "live"))
        self.assertRegex(self.lines()[0], r"^\s+1 ● app .*pane name")
        self.assertRegex(self.lines(herdr=False)[0], r"^\s+1 · app .*ai title")

    def test_resume_live_session_focuses_its_pane(self):
        app = self.f.workdir("app")
        self.f.session("live", app, title="t")
        self.f.set_herdr(self.live_state(app, "live"))
        r = self.f.run("--do", "resume", "live")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.f.mutating_calls(), [["workspace", "focus", "W1"], ["agent", "focus", "term_1"]])

    def test_resume_stopped_session_splits_matching_space(self):
        app = self.f.workdir("app")
        self.f.session("stopped", app, title="My task")
        self.f.set_herdr({
            "agents": [{"cwd": app, "workspace_id": "W1", "pane_id": "W1:p1", "terminal_id": "t"}],
            "workspaces": [{"workspace_id": "W1", "label": "app", "active_tab_id": "W1:t1"}],
            "panes": [{"pane_id": "W1:p1", "tab_id": "W1:t1"}],
            "layout": {"panes": [{"pane_id": "W1:p1", "rect": {"width": 200, "height": 50}}]},
        })
        r = self.f.run("--do", "resume", "stopped")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.f.mutating_calls()
        self.assertIn(["pane", "split", "W1:p1", "--direction", "right", "--cwd", app, "--no-focus"], calls)
        self.assertIn(["pane", "run", "NEW_PANE", "claude -r stopped"], calls)
        self.assertIn(["pane", "rename", "NEW_PANE", "My task"], calls)
        self.assertEqual(calls[-1], ["agent", "focus", "NEW_PANE"])

    def test_resume_without_matching_space_creates_one(self):
        app = self.f.workdir("app")
        self.f.session("s", app, title="t")
        r = self.f.run("--do", "resume", "s")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.f.mutating_calls()
        self.assertEqual(calls[0][:2], ["workspace", "create"])
        self.assertIn(["pane", "run", "NEW_WS:p1", "claude -r s"], calls)

    def test_space_without_splittable_pane_falls_back_to_new_space(self):
        app = self.f.workdir("app")
        self.f.session("s", app, title="t")
        self.f.set_herdr({"agents": [], "panes": [],
                          "workspaces": [{"workspace_id": "W1", "label": "app", "active_tab_id": "W1:t1"}]})
        r = self.f.run("--do", "resume", "s")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(["pane", "run", "NEW_WS:p1", "claude -r s"], self.f.mutating_calls())

    def test_resume_refuses_missing_directory(self):
        gone = self.f.workdir("gone")
        self.f.session("s", gone, title="t")
        os.rmdir(gone)
        r = self.f.run("--do", "resume", "s")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.f.mutating_calls(), [])

    def test_fork_runs_fork_session_in_new_pane(self):
        app = self.f.workdir("app")
        self.f.session("s", app, title="t")
        self.f.run("--do", "fork", "s")
        self.assertIn(["pane", "run", "NEW_WS:p1", "claude -r s --fork-session"], self.f.mutating_calls())

    def test_resume_outside_herdr_execs_claude_here(self):
        app = self.f.workdir("app")
        self.f.session("s", app, title="t")
        bin_dir = self.f.root / "bin"
        bin_dir.mkdir()
        claude = bin_dir / "claude"
        claude.write_text(f'#!/bin/sh\necho "$PWD $*" > {self.f.root}/claude.out\n')
        claude.chmod(0o755)
        r = self.f.run("--do", "resume", "s", herdr=False, path=f"{bin_dir}:{os.environ['PATH']}")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.f.root / "claude.out").read_text().split(),
                         [os.path.realpath(app), "-r", "s"])
        self.assertEqual(self.f.herdr_calls(), [])


class ActionTest(Base):
    def setUp(self):
        super().setUp()
        self.app = self.f.workdir("my app")
        self.f.session("s", self.app, title="Task", pr=42, branch="feat/it's")
        self.f.session("nopr", self.app, age_min=10, title="No PR")

    def test_copy_actions(self):
        self.f.run("--do", "copy-id", "s")
        self.assertEqual(self.f.clip.read_text(), "s")
        self.f.run("--do", "copy-branch", "s")
        self.assertEqual(self.f.clip.read_text(), "feat/it's")
        self.f.run("--do", "copy-cmd", "s")
        self.assertEqual(self.f.clip.read_text(), f"cd '{self.app}' && claude -r s")

    def test_review_request_default_and_custom_template(self):
        r = self.f.run("--do", "copy-review", "s")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.f.clip.read_text(), "Please review: Add widget\nhttps://github.com/acme/app/pull/42")
        self.assertIn(["notification", "show", "review request (copied)", "--body",
                       "Please review: Add widget\nhttps://github.com/acme/app/pull/42"], self.f.herdr_calls())
        self.f.set_config('[review_request]\ntemplate = "{title}\\nのレビューお願いします🙏\\n{url} (#{number})"\n')
        self.f.run("--do", "copy-review", "s")
        self.assertEqual(self.f.clip.read_text(),
                         "Add widget\nのレビューお願いします🙏\nhttps://github.com/acme/app/pull/42 (#42)")

    def test_pr_actions_unavailable_without_pr(self):
        r = self.f.run("--do", "open-pr", "nopr")
        self.assertEqual(r.returncode, 1)
        self.f.run("--do", "open-pr", "s")
        self.assertIn("https://github.com/acme/app/pull/42", self.f.open_log.read_text())

    def test_custom_background_action_quotes_variables_and_runs_in_cwd(self):
        out = self.f.root / "out.txt"
        self.f.set_config(f'''
[[actions]]
key = "x"
label = "Write vars"
run = "printf '%s|%s|%s|%s' {{branch}} {{pr}} \\"$PWD\\" \\"$LCH_ID\\" > {out}; awk 'BEGIN{{print}}' >/dev/null"
''')
        r = self.f.run("--do", "custom-0", "s")
        self.assertEqual(r.returncode, 0, r.stderr)
        for _ in range(50):
            if out.exists() and out.read_text():
                break
            time.sleep(0.05)
        self.assertEqual(out.read_text(), f"feat/it's|42|{os.path.realpath(self.app)}|s")

    def test_custom_action_requires_and_when(self):
        self.f.set_config('''
[[actions]]
key = "x"
label = "Needs PR"
run = "true"
requires = ["pr_url"]
[[actions]]
key = "z"
label = "Needs .env"
run = "true"
when = "test -f .env"
''')
        self.assertEqual(self.f.run("--do", "custom-0", "nopr").returncode, 1)
        self.assertEqual(self.f.run("--do", "custom-0", "s").returncode, 0)
        self.assertEqual(self.f.run("--do", "custom-1", "s").returncode, 1)
        Path(self.app, ".env").write_text("APP_PORT=1\n")
        self.assertEqual(self.f.run("--do", "custom-1", "s").returncode, 0)

    def test_custom_pane_action_opens_pane(self):
        self.f.set_config('[[actions]]\nkey = "g"\nlabel = "lazygit"\nrun = "lazygit"\nmode = "pane"\n')
        self.f.run("--do", "custom-0", "s")
        self.assertIn(["pane", "run", "NEW_WS:p1", "lazygit"], self.f.mutating_calls())

    def _path_with(self, *tool_dirs):
        """A PATH with only the given fake tools plus the shell and Python (no pbcopy/open)."""
        hidden = self.f.root / "tools"
        hidden.mkdir(exist_ok=True)
        for tool in ("herdr", "gh"):
            if not (hidden / tool).exists():
                os.symlink(FAKES / "bin" / tool, hidden / tool)
        return ":".join([*map(str, tool_dirs), str(hidden), "/bin", os.path.dirname(sys.executable)])

    def test_linux_clipboard_and_opener(self):
        self.f.run("--do", "copy-id", "s", path=self._path_with(FAKES / "linux-bin"))
        self.assertEqual(self.f.clip.read_text(), "s")
        self.f.run("--do", "open-pr", "s", path=self._path_with(FAKES / "linux-bin"))
        self.assertIn("xdg-open https://github.com/acme/app/pull/42", self.f.open_log.read_text())

    def test_missing_clipboard_tool_is_reported_not_claimed(self):
        r = self.f.run("--do", "copy-id", "s", path=self._path_with())
        self.assertIn("Failed", r.stdout)
        self.assertFalse(self.f.clip.exists())


class PickerPlumbingTest(Base):
    def test_ui_state_transitions_drive_header_and_list(self):
        a, b = self.f.workdir("a"), self.f.workdir("b")
        self.f.session("s1", a, age_min=1, title="one")
        self.f.session("s2", b, age_min=2, title="two")
        self.f.session("old", a, age_min=60 * 24 * 30, title="old")
        ui = self.f.root / "ui.json"
        ui.write_text(json.dumps({"days": 14, "sort": "recent"}))
        header = strip(self.f.run("--ui", str(ui), "sort").stdout)
        self.assertIn("by environment", header)
        header = strip(self.f.run("--ui", str(ui), "all").stdout)
        self.assertIn("all periods · 3 sessions", header)
        emitted = strip(self.f.run("--ui", str(ui), "emit").stdout).splitlines()
        self.assertEqual([line.split("\t")[0] for line in emitted], ["s1", "old", "s2"])
        self.assertEqual(emitted[0].split("\t")[1].strip(), "1")

    def test_flash_message_is_shown_once(self):
        self.f.session("s", self.f.workdir("a"), title="t")
        ui = self.f.root / "ui.json"
        ui.write_text(json.dumps({"days": 14, "sort": "recent"}))
        self.f.run("--act", str(ui), "copy-id", "s")
        self.assertIn("✔ Copied session ID", strip(self.f.run("--ui", str(ui), "header").stdout))
        self.assertNotIn("✔", strip(self.f.run("--ui", str(ui), "header").stdout))

    def test_all_periods_default_still_offers_a_recent_period(self):
        self.f.set_config("[defaults]\ndays = 0\n")
        ui = self.f.root / "ui.json"
        ui.write_text(json.dumps({"days": None, "sort": "recent"}))
        header = strip(self.f.run("--ui", str(ui), "recent").stdout)
        self.assertIn("last 14 days", header)
        self.assertNotIn("None", header)

    def test_internal_commands_check_argument_count(self):
        r = self.f.run("--ui", "only-one")
        self.assertEqual(r.returncode, 2)
        self.assertIn("takes 2 arguments", r.stderr)

    def test_pending_exit_action_from_direct_key(self):
        ui = self.f.root / "ui.json"
        ui.write_text("{}")
        self.assertEqual(self.f.run("--ui", str(ui), "after-menu").stdout.strip(), "")
        self.f.run("--ui", str(ui), "pend:fork")
        self.assertEqual(self.f.run("--ui", str(ui), "after-menu").stdout.strip(), "accept")

    def test_preview(self):
        app = self.f.workdir("app")
        self.f.session("s", app, title="Task", pr=7, branch="feat/p", prompt="do the thing")
        out = strip(self.f.run("--preview", "s").stdout)
        for expected in ("Task", app, "feat/p", "#7", "do the thing", "stopped"):
            self.assertIn(expected, out)


class I18nTest(unittest.TestCase):
    def test_every_language_has_every_key(self):
        sys.path.insert(0, str(ROOT))
        from lazy_claude_herdr.i18n import MESSAGES
        reference = set(MESSAGES["en"])
        for lang, catalogue in MESSAGES.items():
            self.assertEqual(set(catalogue), reference, lang)
            for key, text in catalogue.items():
                fields = set(re.findall(r"\{(\w+)\}", text))
                self.assertEqual(fields, set(re.findall(r"\{(\w+)\}", MESSAGES["en"][key])), f"{lang}.{key}")


if __name__ == "__main__":
    unittest.main()
