import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from contextlib import closing, contextmanager
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "tg.py"


@pytest.fixture
def db(tmp_path):
    return tmp_path / "t.db"


@pytest.fixture
def raw(db):
    def run(*args, cwd=None, env=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--db", str(db), *args],
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env,
        )

    return run


@pytest.fixture
def tg(raw):
    def run(*args):
        p = raw("--project", "demo", "--json", *args)
        assert p.returncode == 0, p.stderr
        return json.loads(p.stdout)

    return run


@pytest.fixture
def fail(raw):
    def run(*args):
        p = raw("--project", "demo", "--json", *args)
        assert p.returncode == 1
        assert p.stderr.startswith("error:")
        return p

    return run


def ids(tasks):
    return [t["id"] for t in tasks]


def test_add_returns_task_with_defaults(tg):
    t = tg("add", "Ship v1")
    assert t["id"] == 1
    assert t["title"] == "Ship v1"
    assert t["project"] == "demo"
    assert t["status"] == "open"
    assert t["derived_status"] == "ready"
    assert t["notes"] == ""
    assert t["meta"] == {}
    assert t["depends_on"] == [] and t["blocks"] == []
    assert t["done_at"] is None
    assert t["created_at"].endswith("Z")


def test_add_with_notes_and_meta(tg):
    t = tg("add", "A", "--notes", "why", "--meta", "estimate=3", "owner=ronica")
    assert t["notes"] == "why"
    assert t["meta"] == {"estimate": 3, "owner": "ronica"}


def test_depends_and_blocks_create_edges(tg):
    goal = tg("add", "goal")["id"]
    pre = tg("add", "pre", "--blocks", str(goal))["id"]
    leaf = tg("add", "leaf", "--depends", str(pre))
    assert leaf["depends_on"] == [pre]
    shown = tg("show", str(goal))
    assert [d["id"] for d in shown["depends_on"]] == [pre]
    assert [b["id"] for b in tg("show", str(pre))["blocks"]] == [goal, leaf["id"]]


def test_cycle_rejected(tg, fail):
    a = tg("add", "A")["id"]
    b = tg("add", "B", "--depends", str(a))["id"]
    c = tg("add", "C", "--depends", str(b))["id"]
    p = fail("dep", "add", str(a), str(c))
    assert "cycle" in p.stderr
    fail("dep", "add", str(a), str(a))
    assert tg("show", str(a))["depends_on"] == []


def test_add_with_cycle_creating_edges_rolls_back(tg, fail):
    a = tg("add", "A")["id"]
    b = tg("add", "B", "--depends", str(a))["id"]
    fail("add", "C", "--depends", str(b), "--blocks", str(a))
    assert ids(tg("ls", "--all-projects")) == [a, b]


def test_unknown_id_and_bad_meta(tg, fail):
    fail("show", "99")
    fail("done", "99")
    fail("dep", "add", "1", "2")
    t = tg("add", "A")["id"]
    fail("edit", str(t), "--meta", "novalue")


def test_ready_blocked_derivation(tg):
    a = tg("add", "A")["id"]
    b = tg("add", "B", "--depends", str(a))["id"]
    by_id = {t["id"]: t for t in tg("ls")}
    assert by_id[a]["derived_status"] == "ready"
    assert by_id[b]["derived_status"] == "blocked"
    assert by_id[b]["blocked_by"] == 1
    assert ids(tg("ready")) == [a]
    assert ids(tg("ls", "--status", "blocked")) == [b]
    assert ids(tg("ls", "--status", "open")) == [a, b]


def test_done_unblocks_and_reopen_reblocks(tg):
    a = tg("add", "A")["id"]
    b = tg("add", "B", "--depends", str(a))["id"]
    done = tg("done", str(a))
    assert done["status"] == "done" and done["done_at"]
    assert ids(tg("ready")) == [b]
    reopened = tg("reopen", str(a))
    assert reopened["status"] == "open" and reopened["done_at"] is None
    assert ids(tg("ready")) == [a]
    assert tg("show", str(b))["derived_status"] == "blocked"


def test_start_and_in_progress_not_ready(tg):
    a = tg("add", "A")["id"]
    assert tg("start", str(a))["derived_status"] == "in_progress"
    assert tg("ready") == []
    assert ids(tg("ls", "--status", "in_progress")) == [a]


def test_done_on_blocked_warns(tg, raw):
    a = tg("add", "A")["id"]
    b = tg("add", "B", "--depends", str(a))["id"]
    p = raw("--project", "demo", "--json", "done", str(b))
    assert p.returncode == 0
    assert "warning" in p.stderr and f"#{a}" in p.stderr
    assert json.loads(p.stdout)["status"] == "done"


def test_edit_meta_merge_and_unset(tg):
    t = tg("add", "A", "--meta", "owner=x")["id"]
    e = tg("edit", str(t), "--meta", "estimate=3", "link=http://a.b", 'tags=["a","b"]', "flag=true")
    assert e["meta"] == {"owner": "x", "estimate": 3, "link": "http://a.b", "tags": ["a", "b"], "flag": True}
    assert isinstance(e["meta"]["estimate"], int)
    e = tg("edit", str(t), "--unset-meta", "owner", "flag", "--title", "B", "--notes", "n")
    assert e["meta"] == {"estimate": 3, "link": "http://a.b", "tags": ["a", "b"]}
    assert e["title"] == "B" and e["notes"] == "n"


def test_why_returns_path_to_goal(tg):
    goal = tg("add", "goal")["id"]
    mid = tg("add", "mid", "--blocks", str(goal))["id"]
    leaf = tg("add", "leaf", "--blocks", str(mid))["id"]
    other = tg("add", "other goal")["id"]
    tg("dep", "add", str(other), str(leaf))
    paths = tg("why", str(leaf))
    assert sorted([[n["id"] for n in p] for p in paths]) == [[leaf, mid, goal], [leaf, other]]
    assert paths[0][0]["title"] == "leaf"
    assert tg("why", str(goal)) == [[{"id": goal, "title": "goal"}]]


def test_tree_downward(tg):
    goal = tg("add", "goal")["id"]
    a = tg("add", "a", "--blocks", str(goal))["id"]
    tg("add", "b", "--blocks", str(goal))
    tree = tg("tree")
    assert [n["id"] for n in tree] == [goal]
    assert [c["id"] for c in tree[0]["children"]] == [a, a + 1]
    assert tg("tree", str(a))[0]["children"] == []


def test_ls_default_excludes_done(tg):
    a = tg("add", "A")["id"]
    b = tg("add", "B")["id"]
    tg("done", str(a))
    assert ids(tg("ls")) == [b]
    assert ids(tg("ls", "--status", "done")) == [a]


def test_rm_cascades_deps(tg, db):
    a = tg("add", "A")["id"]
    b = tg("add", "B", "--depends", str(a))["id"]
    assert tg("rm", str(a)) == {"deleted": a}
    assert tg("show", str(b))["depends_on"] == []
    assert tg("show", str(b))["derived_status"] == "ready"
    import sqlite3

    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM deps").fetchone()[0] == 0


def test_dep_rm(tg, fail):
    a = tg("add", "A")["id"]
    b = tg("add", "B", "--depends", str(a))["id"]
    tg("dep", "rm", str(b), str(a))
    assert tg("show", str(b))["depends_on"] == []
    fail("dep", "rm", str(b), str(a))


def test_graph_writes_html(tg, tmp_path):
    a = tg("add", "Unique </script> title")["id"]
    tg("add", "B", "--blocks", str(a))
    out = tmp_path / "g.html"
    r = tg("graph", "--no-open", "--out", str(out))
    assert r["path"] == str(out) and r["nodes"] == 2 and r["edges"] == 1
    html = out.read_text()
    assert "Unique <\\/script> title" in html
    assert "__DATA__" not in html
    assert "cytoscape" in html
    assert '"live": false' in html


def test_projects_counts(raw, tg):
    a = tg("add", "A")["id"]
    tg("add", "B", "--depends", str(a))
    tg("add", "C")
    tg("done", "3")
    p = raw("--project", "other", "--json", "add", "X")
    assert p.returncode == 0
    rows = {r["project"]: r for r in tg("projects")}
    assert rows["demo"]["total"] == 3
    assert rows["demo"]["done"] == 1
    assert rows["demo"]["ready"] == 1
    assert rows["demo"]["blocked"] == 1
    assert rows["other"]["total"] == 1 and rows["other"]["ready"] == 1


def test_all_projects_scope(raw, tg):
    tg("add", "A")
    raw("--project", "other", "--json", "add", "X")
    assert len(tg("ls")) == 1
    assert len(tg("ls", "--all-projects")) == 2
    assert len(tg("ready", "--all-projects")) == 2


def test_default_project_is_cwd_basename(raw, tmp_path):
    work = tmp_path / "myproj"
    work.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "TASKGRAPH_PROJECT"}
    env["GIT_CEILING_DIRECTORIES"] = str(tmp_path)
    p = raw("--json", "add", "A", cwd=work, env=env)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["project"] == "myproj"


def test_env_project_and_flag_precedence(raw, tmp_path):
    env = {**os.environ, "TASKGRAPH_PROJECT": "fromenv"}
    assert json.loads(raw("--json", "add", "A", env=env).stdout)["project"] == "fromenv"
    assert json.loads(raw("--project", "flag", "--json", "add", "B", env=env).stdout)["project"] == "flag"


def test_human_output(raw):
    assert raw("--project", "demo", "add", "A").stdout.strip() == "1"
    out = raw("--project", "demo", "ls").stdout
    assert "ready" in out and "A" in out


def test_global_flags_after_subcommand(raw):
    p = raw("add", "A", "--project", "demo", "--json")
    assert json.loads(p.stdout)["project"] == "demo"


def free_port():
    with closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def fetch(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return r.read().decode()


@pytest.fixture
def serve(db):
    procs = []

    def start(port, *extra, other_db=None, project="demo"):
        p = subprocess.Popen(
            [sys.executable, str(SCRIPT), "--db", str(other_db or db), "--project", project, "serve", "--no-open", "--port", str(port), *extra],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        procs.append(p)
        return p

    yield start
    for p in procs:
        p.terminate()
        p.communicate(timeout=5)


def test_serve_live_updates(serve, tg):
    a = tg("add", "Write the spec")["id"]
    b = tg("add", "Review the spec", "--depends", str(a))["id"]
    port = free_port()
    p = serve(port)
    assert p.stdout.readline().strip() == f"http://127.0.0.1:{port}/?project=demo"
    page = fetch(port, "/")
    assert "Write the spec" in page and '"live": true' in page and "__DATA__" not in page
    v1 = json.loads(fetch(port, "/version"))
    assert v1["app"] == "taskgraph"
    nodes = {n["id"]: n for n in json.loads(fetch(port, "/data.json"))["nodes"]}
    assert nodes[a]["derived_status"] == "ready" and nodes[b]["derived_status"] == "blocked"
    tg("done", str(a))
    v2 = json.loads(fetch(port, "/version"))
    assert v2["version"] != v1["version"]
    data = json.loads(fetch(port, "/data.json"))
    nodes = {n["id"]: n for n in data["nodes"]}
    assert nodes[a]["derived_status"] == "done" and nodes[b]["derived_status"] == "ready"
    assert data["live"] is True and data["version"] == v2["version"]
    with pytest.raises(urllib.error.HTTPError) as e:
        fetch(port, "/nope")
    assert e.value.code == 404


def test_serve_already_running(serve, raw):
    port = free_port()
    p = serve(port)
    p.stdout.readline()
    second = raw("--project", "demo", "serve", "--no-open", "--port", str(port))
    assert second.returncode == 0
    assert f"already running at http://127.0.0.1:{port}/?project=demo" in second.stdout
    as_json = json.loads(raw("--project", "demo", "--json", "serve", "--no-open", "--port", str(port)).stdout)
    assert as_json == {"url": f"http://127.0.0.1:{port}/?project=demo", "already_running": True}


def test_serve_other_project_reuses_server(serve, raw):
    port = free_port()
    p = serve(port)
    p.stdout.readline()
    other = raw("--project", "elsewhere", "serve", "--no-open", "--port", str(port))
    assert other.returncode == 0
    assert f"already running at http://127.0.0.1:{port}/?project=elsewhere" in other.stdout


def test_serve_port_taken_by_other_db(serve, raw, tmp_path):
    port = free_port()
    p = serve(port, other_db=tmp_path / "other.db")
    p.stdout.readline()
    other = raw("--project", "demo", "serve", "--no-open", "--port", str(port))
    assert other.returncode == 1
    assert "pass --port" in other.stderr


def test_serve_ignores_query_string(serve, db):
    port = free_port()
    p = serve(port)
    p.stdout.readline()
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/version?t=1", timeout=5) as r:
        info = json.load(r)
    assert info["app"] == "taskgraph" and info["db"] == str(db) and "scope" not in info


def test_serve_serves_all_projects_and_url_picks_view(serve, raw, tg):
    demo = tg("add", "Demo task")["id"]
    other = json.loads(raw("--project", "other", "--json", "add", "Other task").stdout)["id"]
    port = free_port()
    p = serve(port)
    assert p.stdout.readline().strip() == f"http://127.0.0.1:{port}/?project=demo"
    data = json.loads(fetch(port, "/data.json"))
    assert {n["id"] for n in data["nodes"]} == {demo, other}
    assert data["projects"] == ["demo", "other"]
    port = free_port()
    p = serve(port, "--all-projects")
    assert p.stdout.readline().strip() == f"http://127.0.0.1:{port}/"
    port = free_port()
    p = serve(port, project="my proj/x")
    assert p.stdout.readline().strip() == f"http://127.0.0.1:{port}/?project=my%20proj%2Fx"


def test_serve_port_taken_by_other_service(raw):
    with closing(socket.socket()) as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        port = blocker.getsockname()[1]
        p = raw("--project", "demo", "serve", "--no-open", "--port", str(port))
    assert p.returncode == 1
    assert f"port {port} in use" in p.stderr
