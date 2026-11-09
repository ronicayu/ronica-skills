import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))

from fake_gh import Fake  # noqa: E402


@pytest.fixture
def fake(tmp_path, monkeypatch):
    # One fake GitHub repository o/demo; every `gh` call of this process goes to it.
    fake = Fake.create(tmp_path / "gh.json", repo="o/demo")
    monkeypatch.setenv("FAKE_GH_STATE", str(fake.path))
    monkeypatch.setenv("TASKGRAPH_GH", f"{sys.executable} -I {HERE / 'fake_gh.py'}")
    monkeypatch.setenv("TASKGRAPH_GH_PACE", "0")
    return fake
