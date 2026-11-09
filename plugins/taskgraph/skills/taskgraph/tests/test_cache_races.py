"""Two tg processes on one cache and one fake repository."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import tg

SCRIPT = Path(tg.__file__).resolve()

pytestmark = pytest.mark.skipif(sys.version_info < (3, 11), reason="a config file needs Python 3.11")


class Proc:
    """tg.py as a child process of project demo, on the cache in tmp_path."""

    def __init__(self, fake, tmp_path, *, claimant="me", name="cache"):
        config = tmp_path / f"{name}.toml"
        config.write_text(
            f'version = 1\n[projects.demo]\nbackend = "github"\nrepo = "o/demo"\ncache = "{tmp_path / name}.db"\ncache_ttl = 3600\nclaimant = "{claimant}"\n'
            '[projects.demo.meta]\nlocal = ["session"]\ndeferred = ["tokens"]\n',
            encoding="utf-8",
        )
        self.env = {**os.environ, "TASKGRAPH_TODAY": "2026-10-13", "TASKGRAPH_CONFIG": str(config), "TASKGRAPH_PROJECT": "demo", "TASKGRAPH_CLAIMANT": claimant}
        self.fake = fake

    def start(self, *args):
        return subprocess.Popen([sys.executable, str(SCRIPT), "--json", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env)

    def run(self, *args):
        p = self.start(*args)
        out, err = p.communicate()
        return p.returncode, out, err

    def ok(self, *args):
        code, out, err = self.run(*args)
        assert code == 0, err
        return json.loads(out) if out.strip() else None


def titles(fake):
    return [i["title"] for i in fake.state()["issues"].values()]


def wait_for(fake, method, suffix):
    end = time.time() + 20
    while time.time() < end:
        if any(c["method"] == method and c["path"].endswith(suffix) for c in fake.calls()):
            return
        time.sleep(0.02)
    raise AssertionError(f"no {method} {suffix} within 20 s")


def test_a_write_that_commits_while_another_waits_for_the_lock_is_not_pushed_twice(fake, tmp_path):
    proc = Proc(fake, tmp_path)
    proc.ok("add", "one")
    fake.fault(delay_ms=1500)  # every call of B is slow; B holds the cache write lock meanwhile
    fake.clear_log()
    b = proc.start("add", "B")
    wait_for(fake, "POST", "/issues")
    fake.fault(delay_ms=0)
    a = proc.start("edit", "1", "--meta", "session=x")  # a local-only key: no remote call of its own, but it waits for B's commit
    out_b, err_b = b.communicate()
    out_a, err_a = a.communicate()
    assert (b.returncode, a.returncode) == (0, 0), (err_b, err_a)
    assert sorted(titles(fake)) == ["B", "one"]
    assert sorted(t["title"] for t in proc.ok("ls")) == ["B", "one"]


def test_an_edit_that_waits_for_the_lock_does_not_undo_the_write_that_committed_first(fake, tmp_path):
    proc = Proc(fake, tmp_path)
    proc.ok("add", "one")
    fake.fault(delay_ms=1500)
    fake.clear_log()
    b = proc.start("edit", "1", "--title", "X")
    wait_for(fake, "PATCH", "/issues/1")
    fake.fault(delay_ms=0)
    a = proc.start("edit", "1", "--meta", "session=x")  # reads task 1 before B commits, writes after
    out_b, err_b = b.communicate()
    out_a, err_a = a.communicate()
    assert (b.returncode, a.returncode) == (0, 0), (err_b, err_a)
    assert fake.issue(1)["title"] == "X"
    assert proc.ok("--fresh", "show", "1")["title"] == "X"
