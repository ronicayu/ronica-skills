#!/usr/bin/env python3
"""Read the Agentic Team project config.

Usage:
    config.py [--root DIR] get <dotted.key> [--json]
    config.py [--root DIR] show [--json]
    config.py [--root DIR] check
    config.py [--root DIR] model <tier|override key>

Merges <root>/.agentic-team.toml with the optional, gitignored
<root>/.agentic-team.local.toml (local keys win; local lists replace tracked
lists), fills in defaults from SCHEMA, and validates the result. A value of
kind "choice:a,b" must be one of the listed strings. `check` reads no git
state and makes no network call; run.py detects the code host from [merge].

    get     print one value: a scalar plainly, a table or list as JSON
    show    print the merged config with defaults, as TOML-like text or JSON
    check   list every problem, or print `ok`
    model   resolve a tier or a models.overrides key to
            {"model": ..., "effort": ...}; a tier that names Claude
            profiles adds "profile": a name or a list of names

[profiles] is optional: name = the CLAUDE_CONFIG_DIR of a second Claude profile.
`check` also runs `claude plugin list --json` under each profile and fails
when agentic-team is not installed there. Without [profiles] nothing changes.

Exit 0 OK, 2 config problem, 1 unexpected error. `get` and `model` refuse to
answer while `check` reports problems.

[messaging] sets how the Manager and a worker message each other: the asks per
attempt, the minutes before an unanswered ask is due and before an unacked
message counts as undelivered, the doorbell ("socket" posts to the receiver's
inbox socket and falls back to stop plus resume; "resume" only stops and
resumes), and the seconds between two reads of Taskgraph in `run.py wait`.

Python callers (run.py) may import load(root), problems(config),
resolve_model(config, name) and profile_path(config, name).
"""

import argparse
import datetime
import difflib
import json
import os
import subprocess
import sys

try:
    import tomllib
except ImportError:  # Python < 3.11
    print("config.py: needs Python 3.11 or later. Run scripts/python-path.sh to find one, "
          "or set AGENTIC_TEAM_PYTHON to its path.", file=sys.stderr)
    sys.exit(2)

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKED = ".agentic-team.toml"
LOCAL = ".agentic-team.local.toml"
TODO = "TODO"
TIERS = ("mechanical", "implementation", "judgement", "verifier")
PROFILES = "profiles"  # an optional table: profile name -> CLAUDE_CONFIG_DIR; the names are free, so it is not in SCHEMA
DEFAULT_PROFILE = "default"  # the Manager's own environment; reserved, never defined in [profiles]
PLUGIN_NAME = "agentic-team"

# Ignored paths that run.py may delete with a merged worktree: dependencies, environments, caches, build output
# and operating-system files that a command rebuilds. Nothing that can be data (an .env file, logs, a database).
# [merge] disposable adds patterns; an entry "!<pattern>" there turns off one of these.
DISPOSABLE_DEFAULT = (
    # dependencies
    "node_modules/", "bower_components/", ".pnpm-store/",
    # Python environments, caches and build output
    ".venv/", "venv/", ".tox/", ".nox/", "__pycache__/", "*.pyc", "*.pyo", ".pytest_cache/", ".mypy_cache/",
    ".ruff_cache/", ".hypothesis/", ".coverage", ".coverage.*", "htmlcov/", "*.egg-info/", ".eggs/",
    # JavaScript caches and build output
    ".next/", "next-env.d.ts", ".nuxt/", ".svelte-kit/", ".turbo/", ".parcel-cache/", ".eslintcache",
    "*.tsbuildinfo", "coverage/",
    # other build output and caches
    ".cache/", "dist/", "build/", "target/", ".gradle/",
    # operating system files
    ".DS_Store", "Thumbs.db",
    # the session report files of agentic-team; each report is in Taskgraph
    ".agentic-team/",
)


def system_timezone():
    try:
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in target:
            name = target.split("zoneinfo/", 1)[1]
            ZoneInfo(name)
            return name
    except (OSError, ValueError, ZoneInfoNotFoundError):
        pass
    return "UTC"


# Every project setting: section -> key -> (type, default). Merge,
# validation, defaults, and `show` all read this table; add new keys here.
# A default of None means "unset"; callables are evaluated at load time.
# A type "choice:a,b" holds one of the listed strings.
# A type "patterns" is a list of path patterns; pattern_problems checks each one.
SCHEMA: dict[str, dict[str, tuple[str, object]]] = {
    "taskgraph": {"project": ("str", "")},
    "constraints": {"forbidden": ("list", [])},
    "autonomy": {
        "grant": ("str", ""),
        "always_pause": ("list", []),
    },
    "sessions": {
        "max_parallel": ("posint", 2),
        "permission_mode": ("nonempty", "auto"),
        "timezone": ("timezone", system_timezone),
        "timezone_label": ("str", ""),
    },
    "models": {
        "mechanical": ("model", {"model": "haiku", "effort": None}),
        "implementation": ("model", {"model": "sonnet", "effort": "high"}),
        "judgement": ("model", {"model": "opus", "effort": None}),
        "verifier": ("model?", None),
        "overrides": ("overrides", {}),
    },
    "merge": {
        "mode": ("choice:local,pr", "local"),
        "host": ("choice:auto,github,gitlab", "auto"),
        "remote": ("nonempty", "origin"),
        "base": ("str", ""),
        "method": ("choice:merge,squash,rebase", "merge"),
        "catch_up": ("choice:host,local", "host"),
        "draft": ("bool", False),
        "remove_worktrees": ("bool", True),
        "disposable": ("patterns", []),
    },
    "verify": {"kind": ("choice:code,schema,design-doc", "code")},
    "roles": {"default": ("str", "")},
    "messaging": {
        "asks_per_attempt": ("nonneg", 3),
        "ask_due_minutes": ("posint", 60),
        "pending_minutes": ("posint", 10),
        "doorbell": ("choice:socket,resume", "socket"),
        "tg_poll_seconds": ("posint", 5),
    },
    "notifications": {"skill": ("str", "")},
}

TYPE_NAMES = {
    "str": "a string",
    "nonempty": "a non-empty string",
    "list": "a list of strings",
    "patterns": "a list of path patterns",
    "posint": "a positive integer",
    "nonneg": "an integer that is 0 or more",
    "bool": "true or false",
    "timezone": "an IANA time zone name",
    "model": 'a model id or { model = "...", effort = "...", profile = "..." }',
    "model?": 'a model id or { model = "...", effort = "...", profile = "..." }',
    "overrides": 'a table of "work type" = model',
}



def type_name(kind):
    if kind.startswith("choice:"):
        return "one of " + ", ".join(f'"{c}"' for c in kind[7:].split(","))
    return TYPE_NAMES[kind]


ALL_KEYS = [f"{s}.{k}" for s, keys in SCHEMA.items() for k in keys]


class ConfigError(Exception):
    pass


class Config(dict):
    """The merged config, plus the file-level problems found while loading."""

    def __init__(self, data, root, errors, missing=False):
        super().__init__(data)
        self.root = root
        self.errors = errors
        self.missing = missing  # the tracked file does not exist


# ---------------------------------------------------------------- loading

def deep_merge(base, override):
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def read_toml(path, errors):
    name = os.path.basename(path)
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        errors.append(f"{name}: TOML syntax error: {exc}")
    except OSError as exc:
        errors.append(f"{name}: cannot read: {exc.strerror}")
    return {}


def suggest(name, choices):
    close = difflib.get_close_matches(name, choices, n=1, cutoff=0.6)
    return f" (did you mean {close[0]}?)" if close else ""


def unknown_keys(raw, source):
    """Problems for sections and keys in one file that SCHEMA lacks."""
    found = []
    for section, body in raw.items():
        if section == PROFILES:
            if not isinstance(body, dict):
                found.append(f"{source}: {section} must be a table ([{section}])")
            continue
        if section not in SCHEMA:
            if isinstance(body, dict):
                found.append(f"{source}: unknown section [{section}]{suggest(section, list(SCHEMA))}")
            else:
                found.append(f"{source}: unknown top-level key {section}{suggest(section, ALL_KEYS)}")
            continue
        if not isinstance(body, dict):
            found.append(f"{source}: {section} must be a table ([{section}])")
            continue
        for key in body:
            if key not in SCHEMA[section]:
                dotted = f"{section}.{key}"
                found.append(f"{source}: unknown key {dotted}{suggest(dotted, ALL_KEYS)}")
    return found


def normalize_profile(value):
    """A profile name or a non-empty list of names, else None."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list) and value and all(isinstance(v, str) and v.strip() for v in value):
        return [v.strip() for v in value]
    return None


def normalize_model(value):
    """Return {"model", "effort"} for a string or table, else None. A table may add "profile" (a name or a list of
    names); the key is there only when the table sets it, so a config without profiles reads as it always did."""
    if isinstance(value, str) and value.strip():
        return {"model": value.strip(), "effort": None}
    if isinstance(value, dict) and isinstance(value.get("model"), str) and value["model"].strip():
        effort = value.get("effort")
        if effort is None or isinstance(effort, str):
            found = {"model": value["model"].strip(), "effort": effort or None}
            if "profile" in value:
                profile = normalize_profile(value["profile"])
                if profile is None:
                    return None
                found["profile"] = profile
            return found
    return None


def zone_label(zone):
    try:
        return datetime.datetime.now(ZoneInfo(zone)).strftime("%Z")
    except (ValueError, ZoneInfoNotFoundError):
        return ""


def load(root="."):
    """Return the merged Config with defaults filled in. Never raises for a
    bad config; problems(config) reports what is wrong."""
    root = os.path.abspath(root)
    errors = []
    tracked_path = os.path.join(root, TRACKED)
    local_path = os.path.join(root, LOCAL)

    missing = not os.path.isfile(tracked_path)
    if missing:
        errors.append(f"{TRACKED} not found in {root}; run /agentic-team:setup, or pass --root <repository root>")
        tracked = {}
    else:
        tracked = read_toml(tracked_path, errors)
    local = read_toml(local_path, errors) if os.path.isfile(local_path) else {}
    errors += unknown_keys(tracked, TRACKED) + unknown_keys(local, LOCAL)

    merged = deep_merge(tracked, local)
    data = {}
    for section, keys in SCHEMA.items():
        given = merged.get(section) if isinstance(merged.get(section), dict) else {}
        data[section] = {}
        for key, (kind, default) in keys.items():
            if key in given:
                value = given[key]
            else:
                value = default() if callable(default) else json.loads(json.dumps(default))
            if kind in ("model", "model?") and value is not None:
                value = normalize_model(value) or value
            elif kind == "overrides" and isinstance(value, dict):
                value = {k: normalize_model(v) or v for k, v in value.items()}
            data[section][key] = value

    if isinstance(merged.get(PROFILES), dict):  # present only when the project sets it
        data[PROFILES] = dict(merged[PROFILES])
    sessions = data["sessions"]
    if sessions["timezone"] == "":
        sessions["timezone"] = system_timezone()
    if not sessions["timezone_label"] and isinstance(sessions["timezone"], str):
        sessions["timezone_label"] = zone_label(sessions["timezone"])
    return Config(data, root, errors, missing)


# ------------------------------------------------------------- validation

def is_todo(value):
    if value == TODO:
        return True
    if isinstance(value, list):
        return any(is_todo(v) for v in value)
    if isinstance(value, dict):
        return any(is_todo(v) for v in value.values())
    return False


def type_ok(kind, value):
    if kind.startswith("choice:"):
        return isinstance(value, str) and value in kind[7:].split(",")
    if kind == "str":
        return isinstance(value, str)
    if kind == "nonempty":
        return isinstance(value, str) and bool(value.strip())
    if kind == "list":
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    if kind == "patterns":
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    if kind == "posint":
        return isinstance(value, int) and not isinstance(value, bool) and value > 0
    if kind == "nonneg":
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "timezone":
        return isinstance(value, str)
    if kind == "model":
        return normalize_model(value) == value
    if kind == "model?":
        return value is None or normalize_model(value) == value
    if kind == "overrides":
        return isinstance(value, dict) and all(normalize_model(v) == v for v in value.values())
    raise ValueError(kind)


def pattern_problems(dotted, patterns):
    """Problems in a list of disposable path patterns. A pattern names files or folders; an entry "!<pattern>"
    turns off one pattern of DISPOSABLE_DEFAULT."""
    found = []
    for pattern in patterns:
        name = pattern[1:] if pattern.startswith("!") else pattern
        if pattern != pattern.strip() or not name.strip("/") or set(name) <= set("*?/"):
            found.append(f"{dotted}: {json.dumps(pattern)} is not a usable pattern; name files or folders, "
                         f'for example "*.sqlite-journal" or "generated/"')
        elif pattern.startswith("!") and name not in DISPOSABLE_DEFAULT:
            found.append(f"{dotted}: {json.dumps(pattern)} turns off nothing: {json.dumps(name)} is not a default pattern")
    return found


def problems(config):
    """Every problem in a loaded Config, one string each."""
    found = list(getattr(config, "errors", []))
    if getattr(config, "missing", False):
        return found  # a missing file makes every other line noise
    for section, keys in SCHEMA.items():
        for key, (kind, _) in keys.items():
            dotted = f"{section}.{key}"
            value = config[section][key]
            if is_todo(value):
                found.append(f"{dotted} is TODO; set it, or \"\" / [] if it does not apply")
                continue
            if not type_ok(kind, value):
                found.append(f"{dotted} must be {type_name(kind)}, not {json.dumps(value)}")
                continue
            if kind == "timezone":
                try:
                    ZoneInfo(value)
                except (ValueError, ZoneInfoNotFoundError):
                    found.append(f"{dotted}: {value!r} is not an IANA time zone, for example \"Asia/Singapore\"")
            if kind == "patterns":
                found += pattern_problems(dotted, value)
    project = config["taskgraph"]["project"]
    if isinstance(project, str) and not project.strip():
        found.append("taskgraph.project is empty; `tg projects` lists names")
    return found + profile_problems(config)


def tier_profiles(value):
    """The profile names a tier value lists: [] for none (the Manager's own profile)."""
    profile = value.get("profile") if isinstance(value, dict) else None
    return [profile] if isinstance(profile, str) else list(profile or [])


def profile_problems(config):
    """Problems with [profiles] and with the tiers that name a profile. Reads the file system, runs nothing."""
    defined = config.get(PROFILES) or {}
    found = []
    for name, path in defined.items():
        dotted = f"profiles.{name}"
        if name == DEFAULT_PROFILE:
            found.append(f'{dotted}: "{DEFAULT_PROFILE}" is the Manager\'s own profile and is reserved; '
                         "remove it from [profiles]")
        elif not isinstance(path, str) or not path.strip():
            found.append(f"{dotted} must be the CLAUDE_CONFIG_DIR of the profile, a non-empty string, not {json.dumps(path)}")
        elif not os.path.isdir(os.path.expanduser(path)):
            found.append(f"{dotted}: directory {path} does not exist; run claude once with "
                         f"CLAUDE_CONFIG_DIR={path} to create it, or fix the path")
    tiers = [(f"models.{tier}", config["models"][tier]) for tier in TIERS]
    tiers += [(f"models.overrides.{key}", value) for key, value in config["models"]["overrides"].items()]
    for dotted, value in tiers:
        for name in tier_profiles(value):
            if name != DEFAULT_PROFILE and name not in defined:
                found.append(f"{dotted} uses profile {name!r}, which [profiles] does not define"
                             + (suggest(name, list(defined)) if defined else
                                f'; add {name} = "<CLAUDE_CONFIG_DIR>" under [profiles]'))
    return found


def profile_path(config, name):
    """The expanded CLAUDE_CONFIG_DIR of a profile, or None for the Manager's own (`default`, or no name)."""
    if not name or name == DEFAULT_PROFILE:
        return None
    path = (config.get(PROFILES) or {}).get(name)
    if not isinstance(path, str) or not path.strip():
        raise ConfigError(f"no profile named {name!r} in [profiles]"
                          + suggest(name, list(config.get(PROFILES) or {})))
    return os.path.abspath(os.path.expanduser(path))


def manager_version():
    try:
        with open(os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            return json.load(fh).get("version")
    except (OSError, ValueError):
        return None


def installed_plugin(listing):
    """The entry for agentic-team in the output of `claude plugin list --json`, or None. The shape is read loosely:
    any object in the JSON whose name or id is agentic-team or agentic-team@<marketplace> is the entry, and so is the
    value under a key of that name (the shape of the plugin registry file, installed_plugins.json: a list of
    entries per plugin)."""
    stack = [listing]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key in ("name", "id"):
                label = item.get(key)
                if isinstance(label, str) and label.split("@", 1)[0] == PLUGIN_NAME:
                    return item
            for key, value in item.items():
                if isinstance(key, str) and key.split("@", 1)[0] == PLUGIN_NAME:
                    entries = [v for v in value if isinstance(v, dict)] if isinstance(value, list) else [value]
                    entries = [v for v in entries if isinstance(v, dict)]
                    return next((v for v in entries if v.get("version")), entries[0] if entries else {})
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return None


def manager_bypasses(config):
    """True when a settings file that the Manager's session reads sets permissions.defaultMode to bypassPermissions:
    the project's .claude/settings.json and settings.local.json, and the user settings of CLAUDE_CONFIG_DIR (else
    ~/.claude). A session started with a flag is not visible here. Only a hint for `check`."""
    user = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    for path in (os.path.join(config.root, ".claude", "settings.json"),
                 os.path.join(config.root, ".claude", "settings.local.json"), os.path.join(user, "settings.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                mode = (json.load(fh).get("permissions") or {}).get("defaultMode")
        except (OSError, ValueError, AttributeError):
            continue
        if mode == "bypassPermissions":
            return True
    return False


def messaging_warnings(config):
    """Warnings for [messaging]. A Manager in bypassPermissions holds a peer message for approval, so the socket
    doorbell cannot wake it (workers still reach it through `run.py wait`)."""
    if config["messaging"]["doorbell"] == "socket" and manager_bypasses(config):
        return ["messaging.doorbell is \"socket\" but the Manager runs in bypassPermissions, which holds a peer "
                "message for approval; workers' doorbells will not wake it, run.py wait still does"]
    return []


def plugin_problems(config):
    """(problems, warnings) from `claude plugin list --json` under each profile in [profiles]. A profile needs the
    agentic-team plugin for `--agent agentic-team:worker`; the brief holds absolute paths to the Manager's run.py
    and tg.py, so no other plugin is needed."""
    found, warnings = [], []
    mine = manager_version()
    for name in (config.get(PROFILES) or {}):
        try:
            directory = profile_path(config, name)
        except ConfigError:
            continue
        if name == DEFAULT_PROFILE or not os.path.isdir(directory):
            continue  # profile_problems said so
        install = (f"CLAUDE_CONFIG_DIR={directory} claude plugin marketplace add ronicayu/ronica-skills; "
                   f"CLAUDE_CONFIG_DIR={directory} claude plugin install {PLUGIN_NAME}@ronica-skills")
        try:
            out = subprocess.run(["claude", "plugin", "list", "--json"], capture_output=True, text=True,
                                 env={**os.environ, "CLAUDE_CONFIG_DIR": directory})
        except FileNotFoundError:
            found.append(f"profiles.{name}: cannot run claude to check its plugins; put claude on PATH")
            continue
        try:
            entry = installed_plugin(json.loads(out.stdout)) if out.returncode == 0 else None
        except ValueError:
            entry = None
        if entry is None:
            found.append(f"profiles.{name}: the {PLUGIN_NAME} plugin is not installed in {directory}; run: {install}")
            continue
        version = entry.get("version")
        if mine and version and version != mine:
            warnings.append(f"profiles.{name}: {PLUGIN_NAME} {version} is installed there, the Manager runs {mine}")
    return found, warnings


# ------------------------------------------------------------------ lookup

def lookup(config, dotted):
    section, _, rest = dotted.partition(".")
    if section == PROFILES and PROFILES in config:
        if not rest:
            return config[PROFILES]
        if rest not in config[PROFILES]:
            raise ConfigError(f"unknown key {dotted}{suggest(rest, list(config[PROFILES]))}")
        return config[PROFILES][rest]
    if section not in SCHEMA:
        raise ConfigError(f"unknown key {dotted}{suggest(dotted, ALL_KEYS + list(SCHEMA))}")
    value = config[section]
    if not rest:
        return value
    key, _, sub = rest.partition(".")
    if key not in SCHEMA[section]:
        raise ConfigError(f"unknown key {dotted}{suggest(dotted, ALL_KEYS)}")
    value = value[key]
    if sub:
        if not isinstance(value, dict) or sub not in value:
            raise ConfigError(f"unknown key {dotted}")
        value = value[sub]
    return value


def resolve_model(config, name):
    wanted = name.strip().lower()
    for work_type, value in config["models"]["overrides"].items():
        if work_type.strip().lower() == wanted:
            return value
    if wanted in TIERS:
        value = config["models"][wanted]
        return value if value is not None else {"model": None, "effort": None}
    choices = list(TIERS) + list(config["models"]["overrides"])
    raise ConfigError(f"no tier or models.overrides entry named {name!r}; choose from: {', '.join(choices)}")


# ------------------------------------------------------------------ output

def scalar_text(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def toml_value(value):
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{toml_key(k)} = {toml_value(v)}" for k, v in value.items()
                                if v is not None) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value, ensure_ascii=False)


def toml_key(key):
    return key if key.replace("_", "").replace("-", "").isalnum() else json.dumps(key)


def show_text(config):
    lines = []
    for section, keys in SCHEMA.items():
        lines.append(f"[{section}]")
        nested = []
        for key, (kind, _) in keys.items():
            value = config[section][key]
            if kind == "overrides" and isinstance(value, dict):
                nested.append((f"{section}.{key}", value))
            elif value is None:
                lines.append(f"# {key} = (unset)")
            else:
                lines.append(f"{key} = {toml_value(value)}")
        for name, table in nested:
            lines.append(f"\n[{name}]")
            lines += [f"{toml_key(k)} = {toml_value(v)}" for k, v in table.items()]
        lines.append("")
    if config.get(PROFILES):
        lines.append(f"[{PROFILES}]")
        lines += [f"{toml_key(k)} = {toml_value(v)}" for k, v in config[PROFILES].items()]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def fail(message, code=2):
    print(f"config.py: {message}", file=sys.stderr)
    sys.exit(code)


def refuse_if_broken(config):
    found = problems(config)
    if found:
        fail("config has problems; run `config.py check`, or /agentic-team:setup:\n  " + "\n  ".join(found))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", help="repository root holding .agentic-team.toml (default: .)")
    sub = parser.add_subparsers(dest="command", required=True)
    get = sub.add_parser("get", help="print one value")
    get.add_argument("key", help="dotted key, for example sessions.max_parallel")
    get.add_argument("--json", action="store_true", help="always print JSON")
    show = sub.add_parser("show", help="print the merged config with defaults")
    show.add_argument("--json", action="store_true")
    sub.add_parser("check", help="list problems, or print ok")
    model = sub.add_parser("model", help="resolve a tier or a models.overrides key")
    model.add_argument("name", help="mechanical, implementation, judgement, verifier, or a models.overrides key")
    args = parser.parse_args(argv)

    config = load(args.root)
    try:
        if args.command == "check":
            found = problems(config)
            warnings = messaging_warnings(config)
            if config.get(PROFILES) and not getattr(config, "missing", False):
                more, extra = plugin_problems(config)
                found += more
                warnings += extra
            for warning in warnings:
                print(f"config.py: warning: {warning}", file=sys.stderr)
            if found:
                print("\n".join(found))
                sys.exit(2)
            print("ok")
        elif args.command == "show":
            for problem in problems(config):
                print(f"config.py: warning: {problem}", file=sys.stderr)
            print(json.dumps(config, indent=2) if args.json else show_text(config), end="\n" if args.json else "")
        elif args.command == "get":
            refuse_if_broken(config)
            value = lookup(config, args.key)
            print(json.dumps(value) if args.json else scalar_text(value))
        elif args.command == "model":
            refuse_if_broken(config)
            print(json.dumps(resolve_model(config, args.name)))
    except ConfigError as exc:
        fail(str(exc))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - report, then exit 1
        fail(f"unexpected error: {exc}", 1)
