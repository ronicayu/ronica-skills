import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))

from fake_gh import Fake  # noqa: E402

CONFIG = """version = 1

[projects.demo]
backend = "github"
repo = "o/demo"
cache = "{cache}"

[projects.demo.meta]
local = ["sessions", "session", "cleanup_kept", "host_rebase"]
deferred = ["tokens", "model", "started_at"]
"""


def pytest_addoption(parser):
    parser.addoption("--backend", default="sqlite", choices=("sqlite", "github-fake"), help="the store that tests/test_tg.py runs against")


def pytest_configure(config):
    config.addinivalue_line("markers", "sqlite_only(reason): the test needs something only the local SQLite store has; skipped on --backend=github-fake")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--backend") != "github-fake":
        return
    for item in items:
        mark = item.get_closest_marker("sqlite_only")
        if mark:
            item.add_marker(pytest.mark.skip(reason=f"sqlite_only: {mark.args[0] if mark.args else ''}"))


@pytest.fixture
def fake(tmp_path, monkeypatch):
    # One fake GitHub repository o/demo; every `gh` call of this process goes to it.
    fake = Fake.create(tmp_path / "gh.json", repo="o/demo")
    monkeypatch.setenv("FAKE_GH_STATE", str(fake.path))
    monkeypatch.setenv("TASKGRAPH_GH", f"{sys.executable} -I {HERE / 'fake_gh.py'}")
    monkeypatch.setenv("TASKGRAPH_GH_PACE", "0")
    return fake


@pytest.fixture(autouse=True)
def backend(request, tmp_path, monkeypatch):
    # No test is routed by a stray .taskgraph.toml. On --backend=github-fake, tests/test_tg.py runs against a fake repository: project demo is mapped to it.
    monkeypatch.setenv("TASKGRAPH_CONFIG", "")
    if request.config.getoption("--backend") != "github-fake" or request.module.__name__ != "test_tg":
        return
    state = Fake.create(tmp_path / "github-fake.json", repo="o/demo")
    config = tmp_path / "github-fake.toml"
    config.write_text(CONFIG.format(cache=tmp_path / "t.db"), encoding="utf-8")  # the cache is where tests/test_tg.py looks for its database
    monkeypatch.setenv("TASKGRAPH_CONFIG", str(config))
    monkeypatch.setenv("FAKE_GH_STATE", str(state.path))
    monkeypatch.setenv("TASKGRAPH_GH", f"{sys.executable} -I {HERE / 'fake_gh.py'}")
    monkeypatch.setenv("TASKGRAPH_GH_PACE", "0")
