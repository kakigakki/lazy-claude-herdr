"""User configuration (TOML). Everything is optional; with no file the tool runs
with English UI, basename environment labels and the built-in actions only."""
import os
import re
import tomllib
from dataclasses import dataclass, field

from . import i18n, paths

SORTS = ("recent", "env", "live")
COLORS = {
    "black": "1;30", "red": "1;31", "green": "1;32", "yellow": "1;33", "blue": "1;34",
    "magenta": "1;35", "cyan": "1;36", "white": "1;37", "gray": "37",
}
MODES = ("background", "pane", "pager")
VARIABLES = ("id", "cwd", "branch", "pr", "pr_url", "pr_repo", "title")
DEFAULT_REVIEW_TEMPLATE = "Please review: {title}\n{url}"
DEFAULT_DAYS = 14
# fzf key names we accept for `direct`: ctrl-x, alt-x, f1..f12
DIRECT_KEY_RE = re.compile(r"^(?:(?:ctrl|alt)-[a-z0-9]|f(?:[1-9]|1[0-2]))$")


class ConfigError(Exception):
    pass


@dataclass
class Env:
    match: str
    label: str
    color: str  # ANSI SGR parameters


@dataclass
class CustomAction:
    key: str
    label: str
    run: str
    mode: str = "background"
    requires: list = field(default_factory=list)
    when: str | None = None
    direct: str | None = None
    close: bool = False


@dataclass
class Config:
    language: str = "en"
    days: int | None = DEFAULT_DAYS
    sort: str = "recent"
    review_template: str = DEFAULT_REVIEW_TEMPLATE
    envs: list = field(default_factory=list)
    actions: list = field(default_factory=list)

    @property
    def recent_days(self) -> int:
        """Period ctrl-d switches to (the default period, or 14 if that is "all")."""
        return self.days or DEFAULT_DAYS


def _color(value, where):
    if isinstance(value, str) and value.startswith("ansi:"):
        return value[5:]
    if value not in COLORS:
        raise ConfigError(f"{where}: unknown color {value!r} (use one of {', '.join(COLORS)} or 'ansi:<SGR>')")
    return COLORS[value]


def parse(data: dict) -> Config:
    cfg = Config()
    if "language" in data:
        cfg.language = data["language"]
        try:
            i18n.set_language(cfg.language)
        except ValueError as e:
            raise ConfigError(str(e)) from None
    defaults = data.get("defaults", {})
    if "days" in defaults:
        days = defaults["days"]
        if days != 0 and (not isinstance(days, int) or days < 0):
            raise ConfigError("defaults.days must be a positive integer (0 = all periods)")
        cfg.days = days or None
    if "sort" in defaults:
        if defaults["sort"] not in SORTS:
            raise ConfigError(f"defaults.sort must be one of {', '.join(SORTS)}")
        cfg.sort = defaults["sort"]
    if "template" in data.get("review_request", {}):
        cfg.review_template = data["review_request"]["template"]
    for i, env in enumerate(data.get("envs", [])):
        where = f"envs[{i}]"
        if "match" not in env or "label" not in env:
            raise ConfigError(f"{where}: 'match' and 'label' are required")
        cfg.envs.append(Env(os.path.expanduser(env["match"]).rstrip("/"), env["label"],
                            _color(env.get("color", "gray"), where)))
    for i, a in enumerate(data.get("actions", [])):
        where = f"actions[{i}]"
        missing = [k for k in ("key", "label", "run") if k not in a]
        if missing:
            raise ConfigError(f"{where}: missing {', '.join(missing)}")
        mode = a.get("mode", "background")
        if mode not in MODES:
            raise ConfigError(f"{where}: mode must be one of {', '.join(MODES)}")
        requires = a.get("requires", [])
        if not isinstance(requires, list) or not all(isinstance(v, str) for v in requires):
            raise ConfigError(f"{where}: requires must be a list of variable names")
        unknown = [v for v in requires if v not in VARIABLES]
        if unknown:
            raise ConfigError(f"{where}: unknown variable in requires: {', '.join(unknown)}")
        key = a["key"]
        if not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z]", key):
            raise ConfigError(f"{where}: key must be a single letter")
        direct = a.get("direct")
        if direct is not None and (not isinstance(direct, str) or not DIRECT_KEY_RE.match(direct)):
            raise ConfigError(f"{where}: direct must look like ctrl-x, alt-x or f5")
        for name in ("label", "run", "when"):
            if name in a and not isinstance(a[name], str):
                raise ConfigError(f"{where}: {name} must be a string")
        cfg.actions.append(CustomAction(key, a["label"], a["run"], mode, list(requires),
                                        a.get("when"), direct, bool(a.get("close", False))))
    return cfg


def load() -> Config:
    path = paths.config_file()
    if not path.exists():
        return Config()
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from None
    try:
        return parse(data)
    except ConfigError as e:
        raise ConfigError(f"{path}: {e}") from None
