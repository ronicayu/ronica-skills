import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tgstore.base import StoreError  # noqa: E402
from tgstore.config import cache_path, checkout_id, find_config, load_config, project_entry  # noqa: E402

GOOD = """
version = 1

[projects."demo"]
backend = "github"
repo = "acme/plan"

[projects."demo".meta]
local = ["sessions", "session"]
deferred = ["tokens"]

[projects."other"]
backend = "github"
repo = "acme/other"
label = "tasks"
cache_ttl = 5
full_every = 60
cache = "~/c/other.db"
claimant = "me"
"""


def write(folder, text=GOOD):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ".taskgraph.toml"
    path.write_text(text, encoding="utf-8")
    return path


def git(*args, cwd):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd, check=True, capture_output=True)


def test_load_config_reads_every_key(tmp_path):
    config = load_config(write(tmp_path))
    demo, other = project_entry(config, "demo"), project_entry(config, "other")
    assert (demo.backend, demo.repo, demo.label, demo.cache_ttl, demo.full_every) == ("github", "acme/plan", "taskgraph", 30, 600)
    assert demo.local == ("sessions", "session") and demo.deferred == ("tokens",)
    assert (other.label, other.cache_ttl, other.full_every, other.cache, other.claimant) == ("tasks", 5, 60, "~/c/other.db", "me")
    assert project_entry(config, "unmapped") is None


def test_cache_path_default_and_override(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    config = load_config(write(tmp_path / "x"))
    assert cache_path(config.projects["demo"]) == tmp_path / ".taskgraph" / "cache" / "github" / "acme" / "plan.db"
    assert cache_path(config.projects["other"]) == tmp_path / "c" / "other.db"


def test_find_config_walks_up_from_a_subfolder(tmp_path, monkeypatch):
    monkeypatch.delenv("TASKGRAPH_CONFIG", raising=False)
    path = write(tmp_path / "repo")
    deep = tmp_path / "repo" / ".claude" / "worktrees" / "task-12" / "src"
    deep.mkdir(parents=True)
    assert find_config(deep) == path.resolve()


def test_find_config_nearest_file_wins(tmp_path, monkeypatch):
    monkeypatch.delenv("TASKGRAPH_CONFIG", raising=False)
    write(tmp_path)
    near = write(tmp_path / "a" / "b")
    (tmp_path / "a" / "b" / "c").mkdir()
    assert find_config(tmp_path / "a" / "b" / "c") == near.resolve()


def test_find_config_uses_the_main_checkout_of_a_worktree(tmp_path, monkeypatch):
    monkeypatch.delenv("TASKGRAPH_CONFIG", raising=False)
    main = tmp_path / "main"
    main.mkdir()
    git("init", "-q", cwd=main)
    git("commit", "-q", "--allow-empty", "-m", "x", cwd=main)
    path = write(main)  # not committed
    git("worktree", "add", "-q", str(tmp_path / "wt"), cwd=main)
    sub = tmp_path / "wt" / "sub"
    sub.mkdir()
    assert find_config(sub) == path.resolve()
    assert checkout_id(sub) == checkout_id(main)


def test_find_config_none_without_a_file(tmp_path, monkeypatch):
    monkeypatch.delenv("TASKGRAPH_CONFIG", raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    folder = tmp_path / "plain"
    folder.mkdir()
    assert find_config(folder) is None


def test_env_path_wins_and_empty_turns_the_config_off(tmp_path, monkeypatch):
    write(tmp_path / "near")
    elsewhere = write(tmp_path / "elsewhere", GOOD.replace("acme/plan", "acme/else"))
    monkeypatch.setenv("TASKGRAPH_CONFIG", str(elsewhere))
    assert find_config(tmp_path / "near") == elsewhere
    monkeypatch.setenv("TASKGRAPH_CONFIG", "")
    assert find_config(tmp_path / "near") is None
    monkeypatch.setenv("TASKGRAPH_CONFIG", str(tmp_path / "missing.toml"))
    with pytest.raises(StoreError, match="is not a file"):
        find_config(tmp_path)


CASES = {
    "unknown backend": GOOD.replace('backend = "github"', 'backend = "gitlab"', 1),
    "repo must be owner/name": GOOD.replace('repo = "acme/plan"', 'repo = "acme"'),
    "cache_ttl must be at least 0": GOOD.replace("cache_ttl = 5", "cache_ttl = -1"),
    "full_every must be at least 60": GOOD.replace("full_every = 60", "full_every = 59"),
    "tokens is in both local and deferred": GOOD.replace('local = ["sessions", "session"]', 'local = ["sessions", "tokens"]'),
    "version must be 1": GOOD.replace("version = 1", "version = 2"),
    "unknown key colour": GOOD.replace('label = "tasks"', 'colour = "red"'),
    "meta takes only local and deferred": GOOD.replace('deferred = ["tokens"]', 'shared = ["tokens"]'),
}


@pytest.mark.parametrize("message", CASES)
def test_validation_errors(tmp_path, message):
    with pytest.raises(StoreError, match=message):
        load_config(write(tmp_path, CASES[message]))


def test_broken_toml_and_unreadable_file(tmp_path):
    with pytest.raises(StoreError, match="taskgraph.toml"):
        load_config(write(tmp_path, "version = "))
    with pytest.raises(StoreError, match="cannot read"):
        load_config(tmp_path / "nope.toml")


def test_python_before_3_11_gets_one_clear_message(tmp_path, monkeypatch):
    path = write(tmp_path)
    monkeypatch.setitem(sys.modules, "tomllib", None)  # makes `import tomllib` raise ImportError
    with pytest.raises(StoreError) as caught:
        load_config(path)
    assert str(caught.value) == ".taskgraph.toml needs Python 3.11 or later"


def test_importing_tgstore_does_not_import_tomllib():
    code = "import sys; sys.path.insert(0, sys.argv[1]); import tgstore, tgstore.config; assert 'tomllib' not in sys.modules"
    scripts = str(Path(__file__).resolve().parents[1] / "scripts")
    assert subprocess.run([sys.executable, "-c", code, scripts]).returncode == 0
