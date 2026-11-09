from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from tgstore.base import StoreError

NAME = ".taskgraph.toml"
BACKENDS = ("github",)
KEYS = {"backend", "repo", "label", "cache_ttl", "full_every", "cache", "claimant", "meta"}


@dataclass(frozen=True)
class Entry:
    name: str
    backend: str
    repo: str
    label: str = "taskgraph"
    cache_ttl: float = 30
    full_every: float = 600
    cache: str | None = None
    claimant: str | None = None
    local: tuple = ()
    deferred: tuple = ()


@dataclass(frozen=True)
class Config:
    path: Path
    projects: dict


def git_common_dir(cwd):
    try:
        out = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True, cwd=cwd, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return (Path(cwd) / out).resolve() if out else None


def find_config(cwd=None, env=None):
    env = os.environ if env is None else env
    given = env.get("TASKGRAPH_CONFIG")
    if given is not None:
        if given == "":
            return None  # an empty value turns the config off
        path = Path(given).expanduser()
        if not path.is_file():
            raise StoreError(f"TASKGRAPH_CONFIG {given} is not a file")
        return path
    here = Path(cwd or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        if (folder / NAME).is_file():
            return folder / NAME
    common = git_common_dir(here)
    if common is not None:
        root = common.parent if common.name == ".git" else common
        if (root / NAME).is_file():
            return root / NAME
    return None


def checkout_id(cwd=None):
    common = git_common_dir(Path(cwd or Path.cwd()).resolve())
    return hashlib.sha1(str(common or Path(cwd or Path.cwd()).resolve()).encode()).hexdigest()[:8]


def bad(name, message):
    raise StoreError(f"{NAME}: project {name}: {message}")


def number(name, table, key, default, minimum):
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad(name, f"{key} must be a number of seconds")
    if value < minimum:
        bad(name, f"{key} must be at least {minimum}")
    return value


def words(name, meta, key):
    value = meta.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        bad(name, f"meta.{key} must be a list of keys")
    return tuple(value)


def entry_from(name, table):
    if not isinstance(table, dict):
        bad(name, "must be a table")
    unknown = sorted(set(table) - KEYS)
    if unknown:
        bad(name, f"unknown key {unknown[0]}")
    backend = table.get("backend")
    if backend not in BACKENDS:
        bad(name, f"unknown backend {backend!r} (expected one of {', '.join(BACKENDS)})")
    repo = table.get("repo")
    if not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        bad(name, f"repo must be owner/name: {repo!r}")
    for key in ("label", "cache", "claimant"):
        if key in table and (not isinstance(table[key], str) or not table[key]):
            bad(name, f"{key} must be a non-empty string")
    meta = table.get("meta", {})
    if not isinstance(meta, dict) or set(meta) - {"local", "deferred"}:
        bad(name, "meta takes only local and deferred")
    local, deferred = words(name, meta, "local"), words(name, meta, "deferred")
    both = sorted(set(local) & set(deferred))
    if both:
        bad(name, f"meta key {both[0]} is in both local and deferred")
    return Entry(
        name, backend, repo, table.get("label", "taskgraph"), number(name, table, "cache_ttl", 30, 0), number(name, table, "full_every", 600, 60),
        table.get("cache"), table.get("claimant"), local, deferred,
    )


def load_config(path):
    try:
        import tomllib  # only here: tg must run without a config on Python 3.9 and 3.10
    except ImportError:
        raise StoreError(f"{NAME} needs Python 3.11 or later")
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        raise StoreError(f"cannot read {path}: {e}")
    except tomllib.TOMLDecodeError as e:
        raise StoreError(f"{path}: {e}")
    if data.get("version") != 1:
        raise StoreError(f"{NAME}: version must be 1")
    projects = data.get("projects", {})
    if not isinstance(projects, dict):
        raise StoreError(f"{NAME}: projects must be a table")
    return Config(path, {name: entry_from(name, table) for name, table in projects.items()})


def project_entry(config, project):
    return config.projects.get(project)


def cache_path(entry):
    if entry.cache:
        return Path(entry.cache).expanduser()
    owner, repo = entry.repo.split("/")
    return Path.home() / ".taskgraph" / "cache" / entry.backend / owner / f"{repo}.db"
