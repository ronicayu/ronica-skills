import json
import os
import socket
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from contextlib import closing, contextmanager
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "tg.py"


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setenv("TASKGRAPH_TODAY", "2026-10-13")


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
    assert sorted([[n["via"] for n in p] for p in paths], key=len) == [[None, "blocks"], [None, "blocks", "blocks"]]
    assert tg("why", str(goal)) == [[{"id": goal, "title": "goal", "via": None}]]


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


def add(tg, title, *args):
    return tg("add", title, *args)["id"]


def test_type_add_edit_and_validation(tg, fail):
    assert tg("add", "plain")["type"] == "task"
    m = tg("add", "M", "--type", "milestone", "--meta", "date=2026-12-01")
    assert m["type"] == "milestone" and m["meta"] == {"type": "milestone", "date": "2026-12-01"}
    e = tg("edit", str(m["id"]), "--type", "decision")
    assert e["type"] == "decision" and e["meta"]["type"] == "decision"
    e = tg("edit", str(m["id"]), "--type", "task")
    assert e["type"] == "task" and "type" not in e["meta"]
    e = tg("edit", str(m["id"]), "--meta", "type=external")
    assert e["type"] == "external"
    e = tg("edit", str(m["id"]), "--meta", "type=task")
    assert "type" not in e["meta"]
    fail("add", "X", "--type", "epic")
    fail("add", "X", "--meta", "type=epic")
    fail("edit", str(m["id"]), "--type", "epic")
    fail("edit", str(m["id"]), "--meta", "type=1")
    assert ids(tg("ls", "--all-projects")) == [1, m["id"]]


def test_ls_filters_by_type(tg):
    a = add(tg, "A")
    d = add(tg, "D", "--type", "decision")
    e = add(tg, "E", "--type", "external")
    assert ids(tg("ls", "--type", "decision")) == [d]
    assert ids(tg("ls", "--type", "decision", "external")) == [d, e]
    assert ids(tg("ls", "--type", "task")) == [a]


def test_date_meta_validation(tg, fail):
    for key in ("date", "decide_by", "needed_by", "chase"):
        fail("add", "X", "--meta", f"{key}=tomorrow")
        fail("add", "X", "--meta", f"{key}=2026-13-01")
        fail("add", "X", "--meta", f"{key}=20261013")
        assert tg("add", "X", "--meta", f"{key}=2026-10-13")["meta"][key] == "2026-10-13"
    t = add(tg, "Y")
    fail("edit", str(t), "--meta", "date=nope")
    assert "date" not in tg("show", str(t))["meta"]


def test_parent_add_edit_no_parent(tg, raw, fail):
    p = add(tg, "P")
    c = tg("add", "C", "--parent", str(p))
    assert c["parent"] == p and c["children"] == []
    assert tg("show", str(p))["children"] == [c["id"]]
    other = add(tg, "Q")
    assert tg("edit", str(c["id"]), "--parent", str(other))["parent"] == other
    assert tg("show", str(p))["children"] == []
    assert tg("edit", str(c["id"]), "--no-parent")["parent"] is None
    fail("edit", str(c["id"]), "--parent", str(p), "--no-parent")
    fail("add", "X", "--parent", "99")
    assert ids(tg("ls", "--parent", str(p))) == []
    tg("edit", str(c["id"]), "--parent", str(p))
    kid2 = add(tg, "C2", "--parent", str(p))
    assert ids(tg("ls", "--parent", str(p))) == [c["id"], kid2]
    out = raw("--project", "demo", "tree", "--children").stdout
    assert out.splitlines()[0].endswith("P")
    assert "  [ready] #2 C" in out
    tree = tg("tree", "--children")
    assert [n["id"] for n in tree] == [p, other]
    assert [n["id"] for n in tree[0]["children"]] == [c["id"], kid2]
    assert tg("tree", "--children", str(c["id"]))[0]["children"] == []


def test_parent_cycle_rejected(tg, fail):
    a = add(tg, "A")
    b = add(tg, "B", "--parent", str(a))
    c = add(tg, "C", "--parent", str(b))
    p = fail("edit", str(a), "--parent", str(c))
    assert "cycle" in p.stderr
    fail("edit", str(a), "--parent", str(a))
    assert tg("show", str(a))["parent"] is None


def test_parent_type_rules(tg, fail):
    task = add(tg, "T")
    obj = add(tg, "O", "--type", "objective")
    for kind in ("milestone", "decision", "external"):
        k = add(tg, kind, "--type", kind)
        fail("add", "X", "--parent", str(k))
        fail("edit", str(task), "--parent", str(k))
    fail("edit", str(obj), "--parent", str(task))
    fail("add", "X", "--type", "objective", "--parent", str(task))
    sub = tg("add", "Sub", "--type", "objective", "--parent", str(obj))
    assert sub["parent"] == obj
    assert tg("add", "T2", "--parent", str(obj))["parent"] == obj
    add(tg, "child", "--parent", str(task))
    for kind in ("milestone", "decision", "external"):
        fail("edit", str(task), "--type", kind)
    assert tg("edit", str(task), "--type", "objective")["type"] == "objective"
    fail("edit", str(obj), "--type", "task")


def test_dependency_between_ancestor_and_descendant_rejected(tg, fail):
    a = add(tg, "A")
    b = add(tg, "B", "--parent", str(a))
    c = add(tg, "C", "--parent", str(b))
    sibling = add(tg, "S", "--parent", str(a))
    other = add(tg, "O")
    for x, y in ((a, b), (b, a), (a, c), (c, a)):
        assert "ancestor" in fail("dep", "add", str(x), str(y)).stderr
    fail("add", "N", "--parent", str(a), "--depends", str(a))
    fail("add", "N", "--parent", str(a), "--blocks", str(a))
    tg("dep", "add", str(b), str(sibling))
    tg("dep", "add", str(other), str(a))
    fail("edit", str(other), "--parent", str(a))
    assert tg("show", str(other))["parent"] is None
    fail("edit", str(sibling), "--parent", str(b))


def test_child_inherits_parent_dependencies(tg):
    gate = add(tg, "gate")
    parent = add(tg, "P", "--depends", str(gate))
    child = add(tg, "C", "--parent", str(parent))
    grandchild = add(tg, "G", "--parent", str(child))
    nodes = {t["id"]: t for t in tg("ls")}
    assert nodes[grandchild]["derived_status"] == "blocked" and nodes[grandchild]["blocked_by"] == 1
    assert ids(tg("ready")) == [gate]
    tg("done", str(gate))
    assert ids(tg("ready")) == [grandchild]
    assert tg("show", str(child))["derived_status"] == "blocked"


def test_summary_status_rollup(tg, fail):
    p = add(tg, "P")
    a = add(tg, "A", "--parent", str(p))
    b = add(tg, "B", "--parent", str(p), "--depends", str(a))
    assert tg("show", str(p))["derived_status"] == "blocked"
    tg("start", str(a))
    assert tg("show", str(p))["derived_status"] == "in_progress"
    tg("done", str(a))
    assert tg("show", str(p))["derived_status"] == "in_progress"
    tg("done", str(b))
    shown = tg("show", str(p))
    assert shown["derived_status"] == "done"
    tg("reopen", str(b))
    assert tg("show", str(p))["derived_status"] == "in_progress"
    for cmd in ("start", "done", "reopen"):
        assert f"status of #{p} is derived from its children" in fail(cmd, str(p)).stderr
    assert ids(tg("ls")) == [p, b]


def test_nested_summary_rollup(tg):
    top = add(tg, "top", "--type", "objective")
    mid = add(tg, "mid", "--parent", str(top))
    leaf = add(tg, "leaf", "--parent", str(mid))
    assert tg("show", str(top))["derived_status"] == "blocked"
    tg("start", str(leaf))
    assert tg("show", str(top))["derived_status"] == "in_progress"
    tg("done", str(leaf))
    assert tg("show", str(mid))["derived_status"] == "done"
    assert tg("show", str(top))["derived_status"] == "done"


def test_dependency_on_summary_waits_for_all_children(tg):
    p = add(tg, "P")
    c1 = add(tg, "C1", "--parent", str(p))
    c2 = add(tg, "C2", "--parent", str(p))
    after = add(tg, "after", "--depends", str(p))
    tg("done", str(c1))
    assert tg("show", str(after))["derived_status"] == "blocked"
    assert tg("show", str(after))["blocked_by"] == 1
    tg("done", str(c2))
    assert tg("show", str(after))["derived_status"] == "ready"


def test_milestone_derived_from_dependencies(tg, fail):
    a = add(tg, "A")
    b = add(tg, "B")
    m = add(tg, "M", "--type", "milestone", "--depends", str(a), str(b))
    assert tg("show", str(m))["derived_status"] == "blocked"
    assert tg("show", str(m))["blocked_by"] == 2
    tg("done", str(a))
    assert tg("show", str(m))["blocked_by"] == 1
    assert tg("show", str(m))["derived_status"] == "blocked"
    tg("done", str(b))
    assert tg("show", str(m))["derived_status"] == "done"
    for cmd in ("start", "done", "reopen"):
        assert f"status of #{m} is derived from its dependencies" in fail(cmd, str(m)).stderr
    lone = add(tg, "lone", "--type", "milestone")
    assert tg("show", str(lone))["derived_status"] == "blocked"
    after = add(tg, "after", "--depends", str(m))
    assert tg("show", str(after))["derived_status"] == "ready"


def test_ready_excludes_milestone_objective_and_summary(tg):
    obj = add(tg, "O", "--type", "objective")
    parent = add(tg, "P", "--parent", str(obj))
    leaf = add(tg, "L", "--parent", str(parent))
    add(tg, "M", "--type", "milestone")
    plain = add(tg, "plain")
    decision = add(tg, "D", "--type", "decision")
    assert ids(tg("ready")) == [leaf, plain, decision]
    assert leaf in ids(tg("ls", "--status", "ready"))
    assert obj not in ids(tg("ls", "--status", "ready"))


def test_rollup_counts(tg):
    obj = add(tg, "O", "--type", "objective")
    assert tg("show", str(obj))["rollup"] == {"done": 0, "total": 0}
    p = add(tg, "P", "--parent", str(obj))
    a = add(tg, "A", "--parent", str(p))
    b = add(tg, "B", "--parent", str(p))
    c = add(tg, "C", "--parent", str(obj))
    lone = add(tg, "lone")
    tg("done", str(a))
    tg("done", str(c))
    nodes = {t["id"]: t for t in tg("ls", "--all-projects", "--status", "open", "ready", "blocked", "in_progress", "done")}
    assert nodes[obj]["rollup"] == {"done": 2, "total": 3}
    assert nodes[p]["rollup"] == {"done": 1, "total": 2}
    assert nodes[b]["rollup"] is None and nodes[lone]["rollup"] is None


def test_late_and_chase_per_type(tg):
    m = add(tg, "M", "--type", "milestone", "--meta", "date=2026-10-01")
    mf = add(tg, "Mf", "--type", "milestone", "--meta", "date=2026-10-13")
    d = add(tg, "D", "--type", "decision", "--meta", "decide_by=2026-10-01")
    e = add(tg, "E", "--type", "external", "--meta", "needed_by=2026-10-10", "chase=2026-10-13")
    ef = add(tg, "Ef", "--type", "external", "--meta", "needed_by=2026-11-10", "chase=2026-10-14")
    t = add(tg, "T", "--meta", "date=2026-01-01", "decide_by=2026-01-01")
    nodes = {n["id"]: n for n in tg("ls")}
    assert nodes[m]["late_days"] == 12
    assert nodes[mf]["late_days"] is None
    assert nodes[d]["late_days"] == 12 and nodes[d]["chase_due"] is False
    assert nodes[e]["late_days"] == 3 and nodes[e]["chase_due"] is True
    assert nodes[ef]["late_days"] is None and nodes[ef]["chase_due"] is False
    assert nodes[t]["late_days"] is None and nodes[t]["chase_due"] is False
    tg("done", str(d))
    tg("done", str(e))
    done = {n["id"]: n for n in tg("ls", "--status", "done")}
    assert done[d]["late_days"] is None
    assert done[e]["late_days"] is None and done[e]["chase_due"] is False


def test_milestone_late_clears_when_derived_done(tg):
    a = add(tg, "A")
    m = add(tg, "M", "--type", "milestone", "--meta", "date=2026-10-01", "--depends", str(a))
    assert tg("show", str(m))["late_days"] == 12
    tg("done", str(a))
    assert tg("show", str(m))["late_days"] is None


def test_human_output_type_and_late(raw):
    raw("--project", "demo", "add", "Wave 1 date", "--type", "decision", "--meta", "decide_by=2026-10-01")
    out = raw("--project", "demo", "ls").stdout.rstrip("\n")
    assert out == "   1  ready       [decision] Wave 1 date — due 2026-10-01  (late 12d)"
    shown = raw("--project", "demo", "show", "1").stdout
    assert "type:    decision" in shown and "late:    12d" in shown


def test_show_human_parent_children_rollup(raw, tg):
    p = add(tg, "P")
    c = add(tg, "C", "--parent", str(p))
    shown = raw("--project", "demo", "show", str(p)).stdout
    assert f"children: #{c}" in shown and "rollup:  0/1" in shown
    assert f"parent:  #{p} P" in raw("--project", "demo", "show", str(c)).stdout


def test_rm_with_children_requires_recursive(tg, fail):
    p = add(tg, "P")
    c = add(tg, "C", "--parent", str(p))
    g = add(tg, "G", "--parent", str(c))
    keep = add(tg, "keep", "--depends", str(g))
    assert "--recursive" in fail("rm", str(p)).stderr
    assert ids(tg("ls", "--all-projects")) == [p, c, g, keep]
    assert tg("rm", str(p), "--recursive") == {"deleted": p, "descendants": [c, g]}
    assert ids(tg("ls", "--all-projects")) == [keep]
    assert tg("show", str(keep))["depends_on"] == []
    leaf = add(tg, "leaf")
    assert tg("rm", str(leaf)) == {"deleted": leaf}


def test_migration_from_old_schema(db, raw, tg):
    old = sqlite3.connect(db)
    old.executescript(
        """
        CREATE TABLE tasks (
          id INTEGER PRIMARY KEY,
          project TEXT NOT NULL,
          title TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','done')),
          notes TEXT NOT NULL DEFAULT '',
          meta TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(meta)),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          done_at TEXT
        );
        CREATE TABLE deps (
          task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
          depends_on INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
          PRIMARY KEY (task_id, depends_on),
          CHECK (task_id <> depends_on)
        );
        INSERT INTO tasks (id, project, title, notes, meta, created_at, updated_at)
          VALUES (1, 'demo', 'Legacy', 'kept', '{"owner": "x"}', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """
    )
    old.commit()
    old.close()
    legacy = tg("show", "1")
    assert legacy["title"] == "Legacy" and legacy["notes"] == "kept" and legacy["meta"] == {"owner": "x"}
    assert legacy["parent"] is None and legacy["children"] == [] and legacy["type"] == "task"
    child = tg("add", "New", "--parent", "1")
    assert child["parent"] == 1
    assert tg("show", "1")["children"] == [child["id"]]
    cols = [r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(tasks)")]
    assert cols.count("parent_id") == 1


def test_payload_fields_in_graph_and_serve(serve, tg, raw, tmp_path):
    p = add(tg, "P", "--type", "objective")
    c = add(tg, "C", "--parent", str(p))
    m = add(tg, "M", "--type", "milestone", "--meta", "date=2026-10-01", "--depends", str(c))
    out = tmp_path / "g.html"
    tg("graph", "--no-open", "--out", str(out))
    html = out.read_text()
    assert '"rollup": {"done": 0, "total": 1}' in html and '"late_days": 12' in html
    port = free_port()
    proc = serve(port)
    proc.stdout.readline()
    nodes = {n["id"]: n for n in json.loads(fetch(port, "/data.json"))["nodes"]}
    expected = {"id", "title", "status", "derived_status", "project", "notes", "meta", "depends_on", "blocks", "created_at", "done_at", "type", "parent", "children", "rollup", "late_days", "chase_due", "start", "due", "span", "conflicts", "outlook", "threats", "baseline"}
    assert set(nodes[p]) == expected
    assert nodes[p]["type"] == "objective" and nodes[p]["children"] == [c] and nodes[p]["parent"] is None
    assert nodes[c]["parent"] == p and nodes[c]["rollup"] is None
    assert nodes[m]["late_days"] == 12 and nodes[m]["depends_on"] == [c] and nodes[p]["rollup"] == {"done": 0, "total": 1}
    assert nodes[m]["chase_due"] is False


def test_payload_scoped_drops_outside_parent_refs(raw, tg, tmp_path, db):
    p = add(tg, "P")
    inside = add(tg, "Inside", "--parent", str(p))
    outside = json.loads(raw("--project", "other", "--json", "add", "Kid").stdout)["id"]
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE tasks SET parent_id=? WHERE id=?", (p, outside))
    out = tmp_path / "g.html"
    tg("graph", "--no-open", "--out", str(out))
    data = json.loads(out.read_text().split("let DATA = ", 1)[1].split(";\n", 1)[0])
    nodes = {n["id"]: n for n in data["nodes"]}
    assert set(nodes) == {p, inside}
    assert nodes[p]["children"] == [inside]
    assert nodes[p]["rollup"] == {"done": 0, "total": 2}
    raw("--project", "other", "--json", "graph", "--no-open", "--out", str(out))
    data = json.loads(out.read_text().split("let DATA = ", 1)[1].split(";\n", 1)[0])
    assert [n["id"] for n in data["nodes"]] == [outside] and data["nodes"][0]["parent"] is None


def test_deadlock_via_dep_add(tg, fail):
    s = add(tg, "S")
    l2 = add(tg, "L2", "--parent", str(s))
    l1 = add(tg, "L1")
    tg("dep", "add", str(l2), str(l1))
    p = fail("dep", "add", str(l1), str(s))
    assert p.stderr.startswith("error: deadlock: ")
    assert f"#{l1} waits for #{s}" in p.stderr
    assert f"#{s} waits for #{l2} (its child)" in p.stderr
    assert f"#{l2} waits for #{l1}" in p.stderr
    assert tg("show", str(l1))["depends_on"] == []


def test_deadlock_via_edit_parent(tg, fail):
    s = add(tg, "S")
    l1 = add(tg, "L1", "--depends", str(s))
    l2 = add(tg, "L2", "--depends", str(l1))
    p = fail("edit", str(l2), "--parent", str(s))
    assert "deadlock" in p.stderr and f"#{s} waits for #{l2} (its child)" in p.stderr
    assert tg("show", str(l2))["parent"] is None


def test_deadlock_via_add_parent(tg, fail):
    s = add(tg, "S")
    l1 = add(tg, "L1", "--depends", str(s))
    assert "deadlock" in fail("add", "X", "--parent", str(s), "--depends", str(l1)).stderr
    assert ids(tg("ls", "--all-projects")) == [s, l1]
    gate = add(tg, "gate", "--depends", str(l1))
    p = fail("add", "Y", "--parent", str(gate), "--blocks", str(s))
    assert "deadlock" in p.stderr
    assert ids(tg("ls", "--all-projects")) == [s, l1, gate]


def test_deadlock_through_inherited_dependency(tg, fail):
    gate = add(tg, "gate")
    parent = add(tg, "P", "--depends", str(gate))
    child = add(tg, "C", "--parent", str(parent))
    p = fail("dep", "add", str(gate), str(child))
    assert "deadlock" in p.stderr and f"(dependency of ancestor #{parent})" in p.stderr


def test_no_deadlock_for_siblings_and_cross_subtree_deps(tg):
    p = add(tg, "P")
    a = add(tg, "A", "--parent", str(p))
    b = add(tg, "B", "--parent", str(p))
    q = add(tg, "Q")
    c = add(tg, "C", "--parent", str(q))
    tg("dep", "add", str(b), str(a))
    tg("dep", "add", str(c), str(a))
    tg("dep", "add", str(q), str(p))


def test_summary_waits_for_own_dependencies(tg):
    gate = add(tg, "gate")
    parent = add(tg, "P", "--depends", str(gate))
    child = add(tg, "C", "--parent", str(parent))
    after = add(tg, "after", "--type", "milestone", "--depends", str(parent))
    tg("done", str(child))
    assert tg("show", str(parent))["derived_status"] == "in_progress"
    assert tg("show", str(after))["derived_status"] == "blocked"
    tg("done", str(gate))
    assert tg("show", str(parent))["derived_status"] == "done"
    assert tg("show", str(after))["derived_status"] == "done"


def test_why_follows_parent_links(tg, raw):
    milestone = add(tg, "launch", "--type", "milestone")
    parent = add(tg, "workstream", "--blocks", str(milestone))
    child = add(tg, "child", "--parent", str(parent))
    paths = tg("why", str(child))
    assert [[(n["id"], n["via"]) for n in p] for p in paths] == [[(child, None), (parent, "parent"), (milestone, "blocks")]]
    out = raw("--project", "demo", "why", str(child)).stdout.splitlines()
    assert "(part of)" not in out[0] and "(part of)" in out[1] and "(part of)" not in out[2]
    assert "#" + str(milestone) in out[2]


def test_ls_repeated_flags_accumulate(tg):
    a = add(tg, "A")
    b = add(tg, "B", "--depends", str(a))
    c = add(tg, "C", "--type", "decision")
    tg("done", str(c))
    assert ids(tg("ls", "--status", "ready", "--status", "done")) == [a, c]
    assert ids(tg("ls", "--status", "blocked", "--status", "ready")) == [a, b]
    assert ids(tg("ls", "--status", "ready", "--status", "done", "--type", "task", "--type", "decision")) == [a, c]


def test_date_command_maps_due_per_type(tg):
    keys = {"task": "due", "objective": "due", "milestone": "date", "decision": "decide_by", "external": "needed_by"}
    for kind, key in keys.items():
        t = add(tg, kind, "--type", kind)
        r = tg("date", str(t), "--due", "2026-12-01")
        assert r["meta"][key] == "2026-12-01" and r["due"] == "2026-12-01"
    t = add(tg, "plain")
    r = tg("date", str(t), "--start", "2026-11-01", "--due", "2026-12-01")
    assert r["meta"] == {"start": "2026-11-01", "due": "2026-12-01"} and r["start"] == "2026-11-01"
    r = tg("date", str(t), "--clear", "start", "due")
    assert r["meta"] == {} and r["start"] is None and r["due"] is None


def test_date_command_relative_and_validation(tg, fail, raw):
    t = add(tg, "T")
    assert tg("date", str(t), "--due", "today")["due"] == "2026-10-13"
    assert tg("date", str(t), "--due", "+3d")["due"] == "2026-10-16"
    assert tg("date", str(t), "--due", "+2w")["due"] == "2026-10-27"
    assert tg("date", str(t), "--due", "-1w")["due"] == "2026-10-06"
    assert tg("date", str(t), "--start", "-2w")["start"] == "2026-09-29"
    assert "YYYY-MM-DD" in fail("date", str(t), "--due", "tomorrow").stderr
    fail("date", str(t), "--due", "2026-13-01")
    fail("date", str(t))
    fail("date", "99", "--due", "today")
    assert "same date" in fail("date", str(t), "--due", "today", "--clear", "due").stderr
    assert tg("show", str(t))["due"] == "2026-10-06"
    human = raw("--project", "demo", "date", str(t), "--due", "+1d").stdout.strip()
    assert human == f"#{t} start 2026-09-29 due 2026-10-14"


def test_date_start_after_due_rejected(tg, fail):
    t = add(tg, "T", "--start", "2026-11-01", "--due", "2026-11-05")
    assert "after due" in fail("date", str(t), "--start", "2026-11-06").stderr
    assert "after due" in fail("date", str(t), "--due", "2026-10-30").stderr
    assert "after due" in fail("add", "X", "--start", "2026-11-06", "--due", "2026-11-05").stderr
    assert tg("show", str(t))["start"] == "2026-11-01"
    tg("date", str(t), "--start", "2026-11-05")
    m = add(tg, "M", "--type", "milestone")
    r = tg("date", str(m), "--start", "2026-12-31", "--due", "2026-12-01")
    assert r["start"] is None and r["due"] == "2026-12-01" and r["meta"]["start"] == "2026-12-31"


def test_promised_only_for_externals(tg, fail):
    e = add(tg, "E", "--type", "external")
    r = tg("date", str(e), "--start", "2026-10-01", "--due", "2026-11-01", "--promised", "2026-10-20")
    assert r["meta"] == {"type": "external", "start": "2026-10-01", "needed_by": "2026-11-01", "promised": "2026-10-20"}
    assert tg("date", str(e), "--clear", "promised")["meta"].get("promised") is None
    t = add(tg, "T")
    assert "external" in fail("date", str(t), "--promised", "2026-10-20").stderr
    fail("date", str(t), "--clear", "promised")


def test_add_with_start_and_due(tg):
    assert tg("add", "T", "--start", "+1d", "--due", "+1w")["meta"] == {"start": "2026-10-14", "due": "2026-10-20"}
    m = tg("add", "M", "--type", "milestone", "--due", "2026-12-01")
    assert m["meta"]["date"] == "2026-12-01" and m["due"] == "2026-12-01"
    d = tg("add", "D", "--type", "decision", "--due", "2026-12-01", "--start", "2026-11-01")
    assert d["meta"]["decide_by"] == "2026-12-01" and d["start"] is None


def test_load_normalizes_start_and_due(tg, db):
    t = add(tg, "T", "--meta", "due=2026-11-01", "start=2026-10-20")
    bad = add(tg, "Bad")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE tasks SET meta=? WHERE id=?", (json.dumps({"due": "soon", "start": 5}), bad))
    nodes = {n["id"]: n for n in tg("ls")}
    assert (nodes[t]["start"], nodes[t]["due"]) == ("2026-10-20", "2026-11-01")
    assert (nodes[bad]["start"], nodes[bad]["due"]) == (None, None)
    assert nodes[t]["conflicts"] == [] and nodes[t]["span"] is None


def test_tasks_can_be_late_objectives_cannot(tg):
    t = add(tg, "T", "--due", "2026-10-01")
    o = add(tg, "O", "--type", "objective", "--due", "2026-10-01")
    nodes = {n["id"]: n for n in tg("ls")}
    assert nodes[t]["late_days"] == 12 and nodes[o]["late_days"] is None
    tg("done", str(t))
    assert tg("show", str(t))["late_days"] is None


def test_summary_span(tg):
    p = add(tg, "P", "--type", "objective")
    assert tg("show", str(p))["span"] is None
    a = add(tg, "A", "--parent", str(p), "--start", "2026-11-01", "--due", "2026-11-10")
    sub = add(tg, "Sub", "--parent", str(p))
    b = add(tg, "B", "--parent", str(sub), "--due", "2026-12-05")
    c = add(tg, "C", "--parent", str(sub), "--start", "2026-10-20")
    add(tg, "undated", "--parent", str(sub))
    assert tg("show", str(p))["span"] == {"start": "2026-10-20", "end": "2026-12-05"}
    assert tg("show", str(sub))["span"] == {"start": "2026-10-20", "end": "2026-12-05"}
    assert tg("show", str(a))["span"] is None
    tg("date", str(c), "--clear", "start")
    tg("date", str(b), "--clear", "due")
    assert tg("show", str(sub))["span"] is None
    assert tg("show", str(p))["span"] == {"start": "2026-11-01", "end": "2026-11-10"}


def test_dependency_conflict(tg, raw):
    a = add(tg, "A", "--due", "2027-02-01")
    b = add(tg, "B", "--depends", str(a), "--start", "2027-01-15", "--due", "2027-03-01")
    ca, cb = tg("show", str(a))["conflicts"], tg("show", str(b))["conflicts"]
    message = f"#{a} due 2027-02-01 after #{b} needs it 2027-01-15"
    common = {"kind": "dependency", "from": a, "to": b, "due": "2027-02-01", "need": "2027-01-15", "gap": -17, "message": message}
    assert ca == [dict(common, **{"with": b})]
    assert cb == [dict(common, **{"with": a})]
    out = raw("--project", "demo", "ls").stdout
    assert out.count("(conflict)") == 2
    assert message in raw("--project", "demo", "show", str(a)).stdout
    tg("date", str(b), "--start", "2027-02-01")
    assert tg("show", str(a))["conflicts"] == [] and tg("show", str(b))["conflicts"] == []
    tg("date", str(b), "--clear", "start", "--due", "2027-01-31")
    assert tg("show", str(b))["conflicts"][0]["with"] == a
    tg("done", str(a))
    assert tg("show", str(b))["conflicts"] == []


def test_dependency_conflict_uses_milestone_date_and_inherited_deps(tg):
    gate = add(tg, "gate", "--due", "2026-12-20")
    m = add(tg, "M", "--type", "milestone", "--depends", str(gate), "--meta", "date=2026-12-01")
    assert tg("show", str(m))["conflicts"][0]["with"] == gate
    parent = add(tg, "P", "--depends", str(gate))
    child = add(tg, "C", "--parent", str(parent), "--due", "2026-12-10")
    shown = tg("show", str(child))["conflicts"]
    assert [c["kind"] for c in shown] == ["dependency"] and shown[0]["with"] == gate
    assert {c["with"] for c in tg("show", str(gate))["conflicts"]} == {m, child}


def test_parent_due_conflict(tg):
    p = add(tg, "P", "--due", "2026-12-01")
    ok = add(tg, "ok", "--parent", str(p), "--due", "2026-12-01")
    late = add(tg, "late", "--parent", str(p), "--due", "2026-12-02")
    free = add(tg, "free", "--parent", str(p))
    assert tg("show", str(ok))["conflicts"] == [] and tg("show", str(free))["conflicts"] == []
    c = tg("show", str(late))["conflicts"]
    assert [(x["kind"], x["with"]) for x in c] == [("parent", p)]
    assert tg("show", str(p))["conflicts"] == []


def test_promised_conflict(tg):
    e = add(tg, "E", "--type", "external", "--due", "2026-12-01")
    tg("date", str(e), "--promised", "2026-12-01")
    assert tg("show", str(e))["conflicts"] == []
    tg("date", str(e), "--promised", "2026-12-15")
    c = tg("show", str(e))["conflicts"]
    assert [(x["kind"], x["with"]) for x in c] == [("promised", None)]
    assert "2026-12-15" in c[0]["message"]


def agenda_fixture(tg):
    late_small = add(tg, "late small", "--due", "2026-10-10")
    late_big = add(tg, "late big", "--due", "2026-09-01", "--meta", "owner=ana")
    soon = add(tg, "soon", "--due", "2026-10-20")
    far = add(tg, "far", "--due", "2026-12-20")
    nodate = add(tg, "no date", "--type", "decision", "--meta", "decider=bo")
    ext = add(tg, "ext", "--type", "external", "--meta", "party=acme", "chase=2026-10-12", "needed_by=2027-01-01")
    plain = add(tg, "undated task")
    return late_small, late_big, soon, far, nodate, ext, plain


def test_agenda_buckets(tg):
    late_small, late_big, soon, far, nodate, ext, plain = agenda_fixture(tg)
    conflicted = add(tg, "needs gate", "--start", "2026-11-01", "--depends", str(far))
    done = add(tg, "finished", "--due", "2026-10-01")
    tg("done", str(done))
    data = tg("agenda")
    assert set(data) == {"late", "at_risk", "late_start", "conflicts", "due_soon", "chase_due", "review_due", "missing_date"}
    assert ids(data["late"]) == [late_big, late_small]
    assert ids(data["due_soon"]) == [soon]
    assert ids(data["chase_due"]) == [ext]
    assert ids(data["missing_date"]) == [nodate]
    assert [(c["from"]["id"], c["to"]["id"], c["gap"]) for c in data["conflicts"]] == [(far, conflicted, -49)]
    assert set(data["late"][0]) == {"id", "title", "type", "derived_status", "project", "parent", "lane", "start", "due", "late_days", "conflict_count"}
    assert data["late"][0]["late_days"] == 42


def test_agenda_within_and_type_and_scope(tg, raw):
    late_small, late_big, soon, far, nodate, ext, plain = agenda_fixture(tg)
    assert ids(tg("agenda", "--within", "100")["due_soon"]) == [soon, far, ext]
    assert ids(tg("agenda", "--within", "0")["due_soon"]) == []
    typed = tg("agenda", "--type", "decision", "external")
    assert ids(typed["missing_date"]) == [nodate] and ids(typed["late"]) == [] and ids(typed["chase_due"]) == [ext]
    other = json.loads(raw("--project", "other", "--json", "add", "elsewhere", "--due", "2026-01-01").stdout)["id"]
    assert other not in ids(tg("agenda")["late"])
    assert other in ids(tg("agenda", "--all-projects")["late"])


def test_agenda_human_output(raw, tg):
    late_small, late_big, soon, far, nodate, ext, plain = agenda_fixture(tg)
    add(tg, "needs gate", "--start", "2026-11-01", "--depends", str(far))
    out = raw("--project", "demo", "agenda").stdout
    headings = [l for l in out.splitlines() if l and not l.startswith(" ")]
    assert headings == ["Late", "Conflicts", "Due in 14 days", "Chase due", "Missing date"]
    assert f"  #{late_big} late big — due 2026-09-01 · ana · late 42d" in out
    assert f"  #{nodate} [decision] no date — no due date · bo" in out
    assert f"  #{ext} [external] ext — due 2027-01-01 · acme · chase 2026-10-12" in out
    assert "Due in 30 days" in raw("--project", "demo", "agenda", "--within", "30").stdout


def test_agenda_empty(raw, tg):
    add(tg, "calm")
    assert raw("--project", "demo", "agenda").stdout.strip() == "nothing needs attention"


def test_ls_search(tg):
    a = add(tg, "Order Venue booking")
    b = add(tg, "Other", "--notes", "ask the VENUE manager")
    add(tg, "Unrelated")
    c = add(tg, "Venue decision", "--type", "decision")
    assert ids(tg("ls", "--search", "venue")) == [a, b, c]
    assert ids(tg("ls", "--search", "venue", "--type", "decision")) == [c]
    assert ids(tg("ls", "--search", "venue", "--status", "done")) == []
    assert ids(tg("ls", "--search", "nothing")) == []


def test_brief_output(tg, raw):
    p = add(tg, "P", "--meta", "lane=ops", "--due", "2026-10-01")
    c = add(tg, "C", "--parent", str(p), "--depends", str(add(tg, "G")))
    keys = {"id", "title", "type", "derived_status", "project", "parent", "lane", "start", "due", "late_days", "conflict_count"}
    for command in (("ls",), ("ready",)):
        rows = tg("--brief", *command)
        assert rows and all(set(r) == keys for r in rows)
    by_id = {r["id"]: r for r in tg("ls", "--brief")}
    assert by_id[p]["lane"] == "ops" and by_id[p]["late_days"] == 12 and by_id[c]["parent"] == p
    shown = tg("show", str(c), "--brief")
    assert set(shown) == keys | {"depends_on", "blocks"} and shown["depends_on"] == [2] and shown["blocks"] == []
    out = raw("--project", "demo", "--brief", "ls").stdout
    assert out.startswith("[") and json.loads(out)
    assert set(tg("--brief", "agenda")["late"][0]) == keys


def test_done_warning_appears_in_json(tg, raw):
    a = add(tg, "A")
    b = add(tg, "B", "--depends", str(a))
    done = tg("done", str(b))
    assert done["warnings"] == [f"#{b} has unfinished dependencies: #{a}"]
    assert "warnings" not in tg("done", str(a))
    assert "warnings" not in tg("show", str(b))


def test_cross_project_links_rejected(tg, raw, fail):
    mine = add(tg, "mine")
    theirs = json.loads(raw("--project", "other", "--json", "add", "theirs").stdout)["id"]
    assert "cross projects" in fail("dep", "add", str(mine), str(theirs)).stderr
    fail("dep", "add", str(theirs), str(mine))
    assert "cross projects" in fail("add", "X", "--depends", str(theirs)).stderr
    fail("add", "X", "--blocks", str(theirs))
    assert "cross projects" in fail("add", "X", "--parent", str(theirs)).stderr
    child = add(tg, "child")
    fail("edit", str(child), "--parent", str(theirs))
    assert tg("show", str(child))["parent"] is None
    assert ids(tg("ls", "--all-projects")) == [mine, theirs, child]
    same = json.loads(raw("--project", "other", "--json", "add", "same", "--depends", str(theirs)).stdout)
    assert same["depends_on"] == [theirs]


def test_export_shape_and_scope(tg, raw, tmp_path):
    p = add(tg, "P", "--notes", "why", "--meta", "owner=x")
    c = add(tg, "C", "--parent", str(p))
    d = add(tg, "D", "--depends", str(c))
    tg("done", str(c))
    raw("--project", "other", "--json", "add", "elsewhere")
    data = json.loads(raw("--project", "demo", "export").stdout)
    assert data["version"] == 1 and data["exported_at"].endswith("Z")
    assert [t["id"] for t in data["tasks"]] == [p, c, d]
    keys = {"id", "project", "title", "status", "notes", "meta", "parent", "depends_on", "created_at", "updated_at", "done_at"}
    assert all(set(t) == keys for t in data["tasks"])
    by_id = {t["id"]: t for t in data["tasks"]}
    assert by_id[p]["notes"] == "why" and by_id[p]["meta"] == {"owner": "x"}
    assert by_id[c]["parent"] == p and by_id[c]["status"] == "done" and by_id[c]["done_at"]
    assert by_id[d]["depends_on"] == [c]
    assert len(json.loads(raw("--project", "demo", "export", "--all-projects").stdout)["tasks"]) == 4
    out = tmp_path / "sub" / "backup.json"
    r = tg("export", "--out", str(out))
    assert r == {"path": str(out), "tasks": 3}
    assert json.loads(out.read_text())["tasks"] == data["tasks"]


def test_graph_page_is_offline(tg, tmp_path):
    add(tg, "A")
    out = tmp_path / "g.html"
    tg("graph", "--no-open", "--out", str(out))
    html = out.read_text()
    assert "cdn.jsdelivr.net" not in html
    assert "cytoscape" in html and "dagre" in html
    assert html.count("<script>") >= 4 and "__DATA__" not in html


def test_payload_conflicts_span_and_dates(tg, tmp_path):
    p = add(tg, "P", "--type", "objective")
    a = add(tg, "A", "--parent", str(p), "--due", "2026-12-10")
    b = add(tg, "B", "--parent", str(p), "--depends", str(a), "--start", "2026-12-01")
    out = tmp_path / "g.html"
    tg("graph", "--no-open", "--out", str(out))
    data = json.loads(out.read_text().split("let DATA = ", 1)[1].split(";\n", 1)[0])
    nodes = {n["id"]: n for n in data["nodes"]}
    assert nodes[p]["span"] == {"start": "2026-12-01", "end": "2026-12-10"}
    assert nodes[a]["span"] is None and nodes[a]["start"] is None and nodes[a]["due"] == "2026-12-10"
    assert nodes[b]["start"] == "2026-12-01" and nodes[b]["due"] is None
    assert [c["with"] for c in nodes[a]["conflicts"]] == [b] and nodes[p]["conflicts"] == []


def test_ls_human_shows_due_person_and_inherited_lane(tg, raw):
    ws = add(tg, "Infra", "--meta", "lane=Infra")
    add(tg, "Build VPC", "--parent", str(ws), "--due", "2026-11-01", "--meta", "owner=Priya")
    add(tg, "Approve", "--type", "decision", "--meta", "decider=CISO")
    out = raw("--project", "demo", "ls").stdout
    assert "Build VPC — due 2026-11-01 · Priya · Infra" in out
    assert "[decision] Approve — CISO" in out
    assert tg("--brief", "ls")[1]["lane"] == "Infra"


def test_ls_filters_and_sort(tg):
    ws = add(tg, "Infra", "--meta", "lane=Infra", "team=Platform")
    a = add(tg, "a", "--parent", str(ws), "--due", "2026-12-01", "--meta", "owner=Priya", "tags=[\"net\"]")
    b = add(tg, "b", "--due", "2026-10-20", "--meta", "owner=raj", "lane=Data")
    c = add(tg, "c", "--due", "2026-10-01")
    d = add(tg, "d", "--type", "decision", "--meta", "decider=Priya")
    assert ids(tg("ls", "--owner", "priya")) == [a, d]
    assert ids(tg("ls", "--lane", "infra")) == [ws, a]
    assert ids(tg("ls", "--team", "Platform")) == [ws, a]
    assert ids(tg("ls", "--meta", "tags=net")) == [a]
    assert ids(tg("ls", "--meta", "lane=Data", "owner=raj")) == [b]
    assert ids(tg("ls", "--due-before", "2026-10-31")) == [b, c]
    assert ids(tg("ls", "--sort", "due")) == [c, b, a, ws, d]
    assert ids(tg("ls", "--sort", "late"))[0] == c
    assert ids(tg("ready")) == [a, b, c, d]


def test_add_promised(tg, fail):
    e = tg("add", "Pen test", "--type", "external", "--due", "2026-11-01", "--promised", "+2w")
    assert e["meta"]["promised"] == "2026-10-27"
    fail("add", "plain", "--promised", "2026-11-01")


def test_summary_and_milestone_done_at_is_latest_finish(tg, db):
    p = add(tg, "P")
    a = add(tg, "a", "--parent", str(p))
    b = add(tg, "b", "--parent", str(p))
    m = add(tg, "M", "--type", "milestone", "--depends", str(p))
    tg("done", str(a))
    assert tg("show", str(p))["done_at"] is None
    tg("done", str(b))
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("UPDATE tasks SET done_at='2026-10-01T00:00:00Z' WHERE id=?", (a,))
        conn.execute("UPDATE tasks SET done_at='2026-10-05T00:00:00Z' WHERE id=?", (b,))
    assert tg("show", str(p))["done_at"] == "2026-10-05T00:00:00Z"
    assert tg("show", str(m))["done_at"] == "2026-10-05T00:00:00Z"


def test_tree_roots_skip_isolated_leaves(tg):
    goal = add(tg, "goal")
    add(tg, "a", "--blocks", str(goal))
    loose = add(tg, "loose")
    ms = add(tg, "M", "--type", "milestone")
    assert [n["id"] for n in tg("tree")] == [goal, ms]
    tg("rm", str(goal), "--recursive")
    tg("rm", str(ms))
    assert loose in [n["id"] for n in tg("tree")]


def age_events(db, at="2026-09-01T00:00:00Z"):
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("UPDATE events SET at=?", (at,))


def events(db):
    with closing(sqlite3.connect(db)) as conn:
        return [(t, f, json.loads(o) if o else None, json.loads(n) if n else None) for t, f, o, n in conn.execute("SELECT task_id, field, old, new FROM events ORDER BY id")]


def test_events_record_every_mutation(tg, fail, db):
    a = add(tg, "A", "--due", "2026-11-01")
    b = add(tg, "B")
    tg("date", str(a), "--due", "2026-11-10")
    tg("edit", str(b), "--title", "B2", "--meta", "owner=ann")
    tg("dep", "add", str(b), str(a))
    tg("start", str(a))
    fail("dep", "add", str(a), str(b))
    tg("dep", "rm", str(b), str(a))
    tg("rm", str(b))
    assert events(db) == [
        (a, "created", None, "A"),
        (b, "created", None, "B"),
        (a, "due", "2026-11-01", "2026-11-10"),
        (b, "meta.owner", None, "ann"),
        (b, "title", "B", "B2"),
        (b, "depends_on", [], [a]),
        (a, "status", "open", "in_progress"),
        (b, "depends_on", [a], []),
        (b, "removed", "B2", None),
    ]


def test_events_capture_recursive_delete(tg, db):
    p = add(tg, "P")
    c = add(tg, "C", "--parent", str(p))
    tg("rm", str(p), "--recursive")
    assert [e[:2] for e in events(db)[-2:]] == [(p, "removed"), (c, "removed")]


def test_changes_buckets(tg, raw, db):
    late = add(tg, "VPC", "--due", "2026-10-10", "--meta", "owner=Priya")
    early = add(tg, "App", "--due", "2026-11-01")
    renamed = add(tg, "Old")
    gone = add(tg, "Gone")
    started = add(tg, "Begin")
    finished = add(tg, "Finish")
    back = add(tg, "Back")
    tg("done", str(back))
    m = add(tg, "M", "--type", "milestone", "--depends", str(finished))
    age_events(db)
    tg("date", str(late), "--due", "2026-10-24")
    tg("date", str(early), "--due", "2026-10-25")
    tg("edit", str(renamed), "--title", "Renamed", "--meta", "owner=Mei")
    tg("dep", "add", str(early), str(late))
    tg("rm", str(gone))
    tg("start", str(started))
    tg("done", str(finished))
    tg("reopen", str(back))
    fresh = add(tg, "Fresh")
    temp = add(tg, "Temp")
    tg("rm", str(temp))
    data = tg("changes")
    assert data["since"] == "2026-10-06"
    assert ids(data["new"]) == [fresh]
    assert ids(data["started"]) == [started]
    assert ids(data["completed"]) == [finished, m]
    assert ids(data["reopened"]) == [back]
    assert [(s["id"], s["field"], s["from"], s["to"], s["days"]) for s in data["slipped"]] == [(late, "due", "2026-10-10", "2026-10-24", 14)]
    assert [(s["id"], s["days"]) for s in data["pulled_in"]] == [(early, -7)]
    assert {r["id"]: [c["field"] for c in r["changes"]] for r in data["rescoped"]} == {early: ["depends_on"], renamed: ["title", "meta.owner"]}
    assert data["removed"] == [{"id": gone, "title": "Gone", "project": "demo"}]
    out = raw("--project", "demo", "changes").stdout
    assert f"#{late} VPC — due 2026-10-10 → 2026-10-24 (+14d)" in out
    assert f'#{renamed} Renamed — title "Old" → "Renamed"; owner - → Mei' in out
    assert f"#{early} App — depends on +#{late}" in out


def test_changes_since_and_scope(tg, raw, db):
    a = add(tg, "A", "--due", "2026-11-01")
    other = json.loads(raw("--project", "other", "--json", "add", "X", "--due", "2026-11-01").stdout)["id"]
    age_events(db, "2026-10-01T09:00:00Z")
    tg("date", str(a), "--due", "2026-11-02")
    raw("--project", "other", "date", str(other), "--due", "2026-11-03")
    assert ids(tg("changes")["slipped"]) == [a]
    assert ids(tg("changes", "--all-projects")["slipped"]) == [a, other]
    assert ids(tg("changes", "--since", "30d")["new"]) == [a]
    assert ids(tg("changes", "--since", "2026-10-01")["new"]) == [a]
    assert tg("changes", "--since", "-1w")["since"] == "2026-10-06"
    assert raw("--project", "demo", "changes", "--since", "2027-01-01").stdout.strip() == "no changes since 2027-01-01"


def test_changes_net_out_round_trips(tg, db):
    a = add(tg, "A", "--due", "2026-11-01")
    age_events(db)
    tg("date", str(a), "--due", "2026-11-09")
    tg("date", str(a), "--due", "2026-11-01")
    data = tg("changes")
    assert data["slipped"] == [] and data["pulled_in"] == [] and data["rescoped"] == []


def test_baseline_set_ls_diff_rm(tg, fail, raw):
    fail("baseline", "set")
    m = add(tg, "Pilot", "--type", "milestone", "--due", "2026-12-15")
    ws = add(tg, "Infra", "--meta", "lane=Infra")
    a = add(tg, "VPC", "--parent", str(ws), "--start", "2026-10-01", "--due", "2026-10-10")
    b = add(tg, "Runbook", "--due", "2026-11-01")
    gone = add(tg, "Gone")
    assert tg("baseline", "set", "--label", "SteerCo")["tasks"] == 5
    fail("baseline", "set", "--label", "SteerCo")
    tg("date", str(m), "--due", "2027-01-08")
    tg("date", str(a), "--due", "2026-10-24")
    tg("date", str(b), "--due", "2026-10-25")
    tg("rm", str(gone))
    new = add(tg, "New")
    diff = tg("baseline", "diff")
    assert diff["label"] == "SteerCo"
    assert [(r["id"], r["field"], r["baseline"], r["now"], r["days"]) for r in diff["moved"]] == [
        (m, "due", "2026-12-15", "2027-01-08", 24),
        (a, "due", "2026-10-10", "2026-10-24", 14),
        (b, "due", "2026-11-01", "2026-10-25", -7),
    ]
    assert ids(diff["added"]) == [new]
    assert diff["removed"] == [{"id": gone, "title": "Gone", "type": "task"}]
    assert diff["lanes"] == [{"lane": "Infra", "later": 1, "earlier": 0, "max_days": 14}, {"lane": "Unassigned", "later": 1, "earlier": 1, "max_days": 24}]
    out = raw("--project", "demo", "baseline", "diff").stdout
    assert f"#{m} [milestone] Pilot — due 2026-12-15 → 2027-01-08 (+24d)" in out
    shown = raw("--project", "demo", "show", str(a)).stdout
    assert "baseline: due 2026-10-10 (SteerCo), now +14d" in shown
    assert tg("show", str(a))["baseline"] == {"label": "SteerCo", "start": "2026-10-01", "due": "2026-10-10"}
    tg("baseline", "set", "--label", "later")
    assert [l["label"] for l in tg("baseline", "ls")] == ["SteerCo", "later"]
    assert tg("baseline", "diff")["moved"] == []
    assert tg("baseline", "diff", "--label", "SteerCo")["moved"]
    tg("baseline", "set", "--label", "later", "--replace")
    tg("baseline", "rm", "later")
    fail("baseline", "rm", "later")
    fail("baseline", "diff", "--label", "nope")


def test_baseline_is_per_project_and_in_graph_payload(tg, raw, tmp_path):
    a = add(tg, "A", "--due", "2026-11-01")
    tg("baseline", "set")
    raw("--project", "other", "add", "B")
    assert json.loads(raw("--project", "other", "--json", "baseline", "ls").stdout) == []
    tg("date", str(a), "--due", "2026-11-05")
    out = tmp_path / "g.html"
    tg("graph", "--no-open", "--out", str(out))
    assert '"baseline": {"label": "2026-10-13", "start": null, "due": "2026-11-01"}' in out.read_text()


def test_ids_are_never_reused(tg):
    a = add(tg, "A")
    b = add(tg, "B")
    tg("rm", str(b))
    assert add(tg, "C") == b + 1
    tg("rm", str(a))
    assert add(tg, "D") == b + 2


def milestone_chain(tg):
    gate = add(tg, "Approve", "--type", "decision", "--due", "2026-10-25")
    ws = add(tg, "Infra")
    vpc = add(tg, "VPC", "--parent", str(ws), "--due", "2026-10-10")
    rep = add(tg, "Replicate", "--start", "2026-10-15", "--due", "2026-11-15", "--depends", str(gate), str(ws))
    cut = add(tg, "Cut over", "--due", "2026-12-12", "--depends", str(rep))
    m = add(tg, "Pilot", "--type", "milestone", "--due", "2026-12-15", "--depends", str(cut))
    return gate, ws, vpc, rep, cut, m


def test_path_slack_driving_and_verdict(tg, raw):
    gate, ws, vpc, rep, cut, m = milestone_chain(tg)
    data = tg("path", str(m))
    slack = {(h["from"], h["to"]): h["slack"] for h in data["hops"]}
    assert slack[(cut, m)] == 3 and slack[(rep, cut)] == 27
    assert slack[(gate, rep)] == -10 and slack[(vpc, ws)] is None
    assert data["driving"] == [gate, rep, cut, m]
    assert data["verdict"] == "at_risk" and data["late_upstream"] == [vpc] and data["min_slack"] == -10
    assert data["negative_slack"] == 1
    out = raw("--project", "demo", "path", str(m)).stdout
    assert f"#{gate} [decision] Approve [ready] — due 2026-10-25 · needed 2026-10-15 · slack -10d" in out
    assert f"(part of) #{vpc} VPC [ready] — due 2026-10-10 · late 3d" in out
    assert f"driving: #{gate} → #{rep} → #{cut} → #{m}" in out
    tg("done", str(gate))
    tg("date", str(vpc), "--due", "2026-10-14")
    data = tg("path", str(m))
    assert data["verdict"] == "on_track" and gate not in {h["from"] for h in data["hops"]}


def test_outlook_on_milestones_show_and_agenda(tg, raw):
    gate, ws, vpc, rep, cut, m = milestone_chain(tg)
    assert tg("show", str(m))["outlook"]["verdict"] == "at_risk"
    assert tg("show", str(cut))["outlook"] is None
    assert "outlook: at risk — 1 late upstream (#" in raw("--project", "demo", "show", str(m)).stdout
    agenda = tg("agenda")
    assert ids(agenda["at_risk"]) == [m] and agenda["at_risk"][0]["outlook"]["min_slack"] == -10
    empty = add(tg, "Lonely", "--type", "milestone", "--due", "2026-12-01")
    assert tg("show", str(empty))["outlook"]["verdict"] == "on_track"
    undated = add(tg, "Undated gate", "--type", "milestone", "--depends", str(add(tg, "x")))
    assert tg("show", str(undated))["outlook"]["verdict"] == "unknown"


def test_agenda_should_have_started(tg, raw):
    late = add(tg, "Late start", "--start", "2026-10-01", "--due", "2026-12-01")
    going = add(tg, "Going", "--start", "2026-10-01", "--due", "2026-12-01")
    tg("start", str(going))
    add(tg, "Future", "--start", "2026-11-01")
    assert ids(tg("agenda")["late_start"]) == [late]
    assert f"#{late} Late start — due 2026-12-01 · start 2026-10-01, still ready" in raw("--project", "demo", "agenda").stdout


def test_risk_type_threatens_without_blocking(tg, raw, fail):
    ws = add(tg, "Infra", "--meta", "lane=Infra")
    work = add(tg, "Build", "--parent", str(ws), "--due", "2026-11-01")
    m = add(tg, "Live", "--type", "milestone", "--due", "2026-11-15", "--depends", str(ws))
    r = tg("add", "Vendor may slip", "--type", "risk", "--parent", str(ws), "--blocks", str(work), "--due", "2026-10-10",
           "--meta", "owner=Priya", "likelihood=high", "impact=high", "mitigation=second vendor")
    assert r["meta"]["review"] == "2026-10-10" and r["start"] is None and r["lane"] == "Infra"
    assert r["late_days"] is None and r["derived_status"] == "ready"
    w = tg("show", str(work))
    assert w["derived_status"] == "ready" and w["threats"] == [r["id"]] and w["conflicts"] == []
    p = tg("show", str(ws))
    assert p["rollup"] == {"done": 0, "total": 1} and p["span"] == {"start": "2026-11-01", "end": "2026-11-01"}
    tg("done", str(work))
    assert tg("show", str(ws))["derived_status"] == "done" and tg("show", str(m))["derived_status"] == "done"
    tg("reopen", str(work))
    o = tg("show", str(m))["outlook"]
    assert o["open_risks"] == [r["id"]] and r["id"] not in {h["from"] for h in tg("path", str(m))["hops"]}
    assert r["id"] not in ids(tg("ready"))
    agenda = tg("agenda")
    assert ids(agenda["review_due"]) == [r["id"]] and r["id"] not in ids(agenda["late"])
    assert f"#{r['id']} [risk] Vendor may slip — review 2026-10-10 · Priya · high/high" in raw("--project", "demo", "agenda").stdout
    assert "threatened by: #" in raw("--project", "demo", "show", str(work)).stdout
    tg("add", "Unreviewed", "--type", "risk")
    assert len(tg("agenda")["missing_date"]) == 1
    fail("add", "child", "--parent", str(r["id"]))


def test_issue_type_blocks_and_can_come_from_a_risk(tg):
    r = add(tg, "Key person leaves", "--type", "risk", "--meta", "review=2026-11-01")
    work = add(tg, "Build", "--depends", str(r))
    assert tg("show", str(work))["derived_status"] == "ready"
    tg("edit", str(r), "--type", "issue", "--meta", "severity=high", "raised=2026-10-12", "due=2026-10-20")
    issue = tg("show", str(r))
    assert issue["type"] == "issue" and issue["due"] == "2026-10-20"
    assert tg("show", str(work))["derived_status"] == "blocked"
    assert ids(tg("ready")) == [r]


def test_agenda_conflicts_once_per_edge_with_both_people(tg, raw):
    infra = add(tg, "Infra", "--meta", "lane=Infra")
    runners = add(tg, "CI runners", "--parent", str(infra), "--due", "2026-10-25", "--meta", "owner=Raj")
    auth = add(tg, "Auth service", "--start", "2026-10-20", "--due", "2026-11-10", "--depends", str(runners), "--meta", "owner=Tom", "lane=App")
    pen = add(tg, "Pen test", "--type", "external", "--due", "2026-12-05", "--promised", "2026-12-10", "--meta", "party=SecureCo")
    data = tg("agenda")["conflicts"]
    assert [(c["kind"], c["from"]["id"], c["to"] and c["to"]["id"], c["gap"]) for c in data] == [
        ("dependency", runners, auth, -5), ("promised", pen, None, -5)]
    assert data[0]["from"]["person"] == "Raj" and data[0]["from"]["lane"] == "Infra" and data[0]["to"]["person"] == "Tom"
    out = raw("--project", "demo", "agenda").stdout
    assert f"#{runners} CI runners (Raj · Infra) → #{auth} Auth service (Tom · App): due 2026-10-25, needed 2026-10-20, gap -5d" in out
    assert f"#{pen} [external] Pen test (SecureCo): promised 2026-12-10, needed 2026-12-05, gap -5d" in out
    assert out.count("CI runners (Raj") == 1


def test_deps_cross_and_open(tg, raw):
    infra = add(tg, "Infra", "--meta", "lane=Infra", "team=Platform")
    a = add(tg, "VPC", "--parent", str(infra), "--due", "2026-10-24", "--meta", "owner=Priya")
    b = add(tg, "IAM", "--parent", str(infra), "--due", "2026-10-20", "--meta", "owner=Priya", "--depends", str(a))
    c = add(tg, "Replicate", "--start", "2026-10-15", "--meta", "owner=Mei", "lane=Data", "--depends", str(a))
    d = add(tg, "Done dep", "--meta", "owner=Mei", "lane=Data")
    e = add(tg, "Uses done", "--meta", "owner=Priya", "lane=Infra", "--depends", str(d))
    add(tg, "Threat", "--type", "risk", "--blocks", str(c))
    tg("done", str(d))
    rows = tg("deps")
    assert [(r["from"]["id"], r["to"]["id"], r["slack"]) for r in rows] == [(a, c, -9), (a, b, -4), (d, e, None)]
    assert [(r["from"]["id"], r["to"]["id"]) for r in tg("deps", "--cross", "lane")] == [(a, c), (d, e)]
    assert [(r["from"]["id"], r["to"]["id"]) for r in tg("deps", "--cross", "lane", "--open")] == [(a, c)]
    assert [(r["from"]["id"], r["to"]["id"]) for r in tg("deps", "--cross", "owner")] == [(a, c), (d, e)]
    assert [(r["from"]["id"], r["to"]["id"]) for r in tg("deps", "--cross", "team")] == [(a, c)]
    out = raw("--project", "demo", "deps", "--cross", "lane", "--open").stdout.strip()
    assert out == f"#{a} VPC [ready] (Priya · Infra) → #{c} Replicate [blocked] (Mei · Data) · slack -9d"


def report_fixture(tg):
    infra = add(tg, "Infra", "--meta", "lane=Infra")
    late = add(tg, "VPC", "--parent", str(infra), "--due", "2026-10-10", "--meta", "owner=Priya")
    iam = add(tg, "IAM", "--parent", str(infra), "--due", "2026-10-30", "--meta", "owner=Priya")
    tg("done", str(iam))
    data = add(tg, "Replicate", "--start", "2026-10-15", "--due", "2026-11-15", "--meta", "owner=Mei", "lane=Data", "--depends", str(late))
    calm = add(tg, "Docs", "--due", "2026-12-01", "--meta", "owner=Bo", "lane=Docs")
    m = add(tg, "Live", "--type", "milestone", "--due", "2026-12-15", "--depends", str(data), "--meta", "lane=Programme")
    gate = add(tg, "Approve | sign", "--type", "decision", "--due", "2026-10-20", "--meta", "decider=CISO", "lane=Security")
    undecided = add(tg, "Vendor", "--type", "decision", "--meta", "decider=CTO", "lane=Security")
    ext = add(tg, "Pen test", "--type", "external", "--due", "2026-12-05", "--promised", "2026-12-10", "--meta", "party=SecureCo", "lane=Security")
    risk = add(tg, "Capacity", "--type", "risk", "--due", "2026-11-01", "--blocks", str(data), "--meta", "owner=Priya", "likelihood=high", "impact=high", "lane=Data", "mitigation=second region")
    low = add(tg, "Minor", "--type", "risk", "--due", "2026-11-01", "--meta", "likelihood=low", "impact=low", "lane=Data")
    issue = add(tg, "Runners flaky", "--type", "issue", "--due", "2026-10-18", "--meta", "owner=Raj", "severity=high", "lane=App")
    return locals()


def test_report_rag_groups_and_asks(tg):
    f = report_fixture(tg)
    r = tg("report")
    assert r["scope"] == "demo" and r["date"] == "2026-10-13" and r["overall"] == "red"
    assert [(m["id"], m["rag"]) for m in r["milestones"]] == [(f["m"], "red")]
    groups = {g["name"]: g for g in r["groups"]}
    assert [g["name"] for g in r["groups"]] == ["App", "Infra", "Programme", "Data", "Security", "Docs"]
    assert groups["Infra"]["rag"] == "red" and groups["Infra"]["rollup"] == {"done": 1, "total": 2} and groups["Infra"]["late"] == 1
    assert f"#{f['late']} VPC late 3d" in groups["Infra"]["reasons"]
    assert groups["App"]["rag"] == "red" and groups["Data"]["rag"] == "amber" and groups["Docs"]["rag"] == "green"
    assert any("high/high risk open" in why for why in groups["Data"]["reasons"])
    assert groups["Security"]["rag"] == "amber" and groups["Programme"]["next"]["id"] == f["m"]
    assert ids(r["decisions"]) == [f["gate"], f["undecided"]]
    assert ids(r["externals"]) == [f["ext"]] and r["externals"][0]["promised"] == "2026-12-10"
    assert ids(r["risks"]) == [f["risk"], f["low"]] and r["risks"][0]["score"] == 9
    assert ids(tg("report", "--risks", "1")["risks"]) == [f["risk"]]
    assert ids(r["issues"]) == [f["issue"]]
    assert [(a["kind"], a["id"]) for a in r["asks"]] == [("resolve", f["issue"]), ("decide", f["gate"]), ("chase", f["ext"]), ("decide", f["undecided"])]
    assert r["changes"]["new"] == 12 and r["changes"]["completed"] == 1


def test_report_by_owner_and_text_and_markdown(tg, raw):
    f = report_fixture(tg)
    owners = {g["name"]: g["rag"] for g in tg("report", "--by", "owner")["groups"]}
    assert owners["Priya"] == "red" and owners["Bo"] == "green" and owners["CISO"] == "green" and owners["SecureCo"] == "amber"
    text = raw("--project", "demo", "report").stdout
    assert text.startswith("Status: demo — 2026-10-13 — overall RED\nSince 2026-10-06: 12 new · 1 completed")
    assert "  GREEN  Docs — 0/1 done · 0 late · 0 conflicts · next #" in text
    assert f"  - Chase #{f['ext']} Pen test (SecureCo): promised 2026-12-10 after needed 2026-12-05" in text
    md = raw("--project", "demo", "report", "--md").stdout
    assert md.startswith("# Status: demo, 2026-10-13\n\n**Overall: Red**")
    assert "## Workstreams" in md and "| RAG | Workstream | Progress | Late | Conflicts | Next | Why |" in md
    assert f"| {f['gate']} | Approve \\| sign | CISO | 2026-10-20 |" in md
    assert "## Asks" in md and f"- Resolve #{f['issue']} Runners flaky (Raj): severity high, due 2026-10-18" in md


def test_report_all_green(tg, raw):
    add(tg, "Docs", "--due", "2026-12-01", "--meta", "lane=Docs")
    r = tg("report")
    assert r["overall"] == "green" and r["asks"] == []
    assert raw("--project", "demo", "report").stdout.rstrip().endswith("Asks\n  none")


def test_projects_portfolio_columns(tg, raw):
    late = add(tg, "VPC", "--due", "2026-10-10")
    m = add(tg, "Live", "--type", "milestone", "--due", "2026-12-01", "--depends", str(late))
    add(tg, "Later", "--type", "milestone", "--due", "2027-01-01")
    raw("--project", "calm", "add", "Docs", "--due", "2026-12-01")
    rows = {r["project"]: r for r in tg("projects")}
    demo = rows["demo"]
    assert demo["late"] == 1 and demo["conflicts"] == 0 and demo["at_risk"] == 1 and demo["rag"] == "red"
    assert demo["next_milestone"] == {"id": m, "title": "Live", "due": "2026-12-01"}
    assert rows["calm"]["rag"] == "green" and rows["calm"]["next_milestone"] is None
    out = raw("--project", "demo", "projects").stdout
    assert f"demo                 RED    total   3  done   0  ready   1  blocked   2 · 1 late · 0 conflicts · 1 at risk · next #{m} Live 2026-12-01" in out


def test_cross_project_dependency_only_on_milestones(tg, raw, fail):
    gate = json.loads(raw("--project", "platform", "--json", "add", "Dev env live", "--type", "milestone", "--due", "2026-11-01").stdout)["id"]
    work = json.loads(raw("--project", "platform", "--json", "add", "Build env", "--blocks", str(gate), "--due", "2026-10-20").stdout)["id"]
    load_ = add(tg, "Load warehouse", "--start", "2026-10-25", "--depends", str(gate))
    assert tg("show", str(load_))["derived_status"] == "blocked"
    conflicts = tg("show", str(load_))["conflicts"]
    assert [c["from"] for c in conflicts] == [gate]
    assert "milestone" in fail("dep", "add", str(load_), str(work)).stderr
    assert "must stay a milestone" in fail("edit", str(gate), "--type", "task").stderr
    assert tg("show", str(gate))["type"] == "milestone"
    tg("--project", "platform", "done", str(work))
    assert tg("show", str(load_))["derived_status"] == "ready"
    rows = tg("deps", "--cross", "project", "--all-projects")
    assert [(r["from"]["id"], r["to"]["id"]) for r in rows] == [(gate, load_)]
