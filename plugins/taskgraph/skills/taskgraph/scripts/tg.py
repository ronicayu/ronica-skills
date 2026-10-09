#!/usr/bin/env python3
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
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
CREATE TABLE IF NOT EXISTS deps (
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  depends_on INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  PRIMARY KEY (task_id, depends_on),
  CHECK (task_id <> depends_on)
);
CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project, status);
"""

FILTERS = ("open", "in_progress", "done", "ready", "blocked")
NODE_FIELDS = ("id", "title", "status", "derived_status", "project", "notes", "meta", "depends_on", "blocks", "created_at", "done_at")
DEFAULT_GRAPH = Path.home() / ".taskgraph" / "graph.html"


class Fail(Exception):
    pass


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_project():
    env = os.environ.get("TASKGRAPH_PROJECT")
    if env:
        return env
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip()
        if top:
            return Path(top).name
    except (OSError, subprocess.CalledProcessError):
        pass
    return Path.cwd().name


def connect(path):
    path = Path(path or os.environ.get("TASKGRAPH_DB") or Path.home() / ".taskgraph" / "tasks.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def load(conn):
    tasks = {}
    for row in conn.execute("SELECT * FROM tasks ORDER BY id"):
        task = dict(row)
        task["meta"] = json.loads(task["meta"])
        task["depends_on"] = []
        task["blocks"] = []
        tasks[task["id"]] = task
    for task_id, dep in conn.execute("SELECT task_id, depends_on FROM deps ORDER BY task_id, depends_on"):
        tasks[task_id]["depends_on"].append(dep)
        tasks[dep]["blocks"].append(task_id)
    for task in tasks.values():
        task["blocked_by"] = sum(tasks[d]["status"] != "done" for d in task["depends_on"])
        if task["status"] != "open":
            task["derived_status"] = task["status"]
        else:
            task["derived_status"] = "blocked" if task["blocked_by"] else "ready"
    return tasks


def get(tasks, task_id):
    if task_id not in tasks:
        raise Fail(f"no such task: {task_id}")
    return tasks[task_id]


def scoped(tasks, args):
    return [t for t in tasks.values() if args.all_projects or t["project"] == args.project]


def parse_meta(pairs):
    meta = {}
    for pair in pairs or []:
        key, sep, raw = pair.partition("=")
        if not sep or not key:
            raise Fail(f"bad meta (expected key=value): {pair}")
        try:
            meta[key] = json.loads(raw)
        except ValueError:
            meta[key] = raw
    return meta


def emit(args, data, text=None):
    if args.json:
        print(json.dumps(data, ensure_ascii=False))
    elif text is not None:
        print(text)


def line(task, with_project=False):
    prefix = f"{task['project']:<12} " if with_project else ""
    suffix = f"  (blocked by {task['blocked_by']})" if task["derived_status"] == "blocked" else ""
    return f"{prefix}{task['id']:>4}  {task['derived_status']:<11} {task['title']}{suffix}"


def reaches(conn, start, target):
    sql = """
    WITH RECURSIVE r(id) AS (
      SELECT :start UNION SELECT d.depends_on FROM deps d JOIN r ON d.task_id = r.id
    ) SELECT 1 FROM r WHERE id = :target
    """
    return conn.execute(sql, {"start": start, "target": target}).fetchone() is not None


def add_dep(conn, task_id, dep_id):
    for tid in (task_id, dep_id):
        if conn.execute("SELECT 1 FROM tasks WHERE id=?", (tid,)).fetchone() is None:
            raise Fail(f"no such task: {tid}")
    if reaches(conn, dep_id, task_id):
        raise Fail(f"cycle: #{task_id} depending on #{dep_id} would create a cycle")
    conn.execute("INSERT OR IGNORE INTO deps (task_id, depends_on) VALUES (?, ?)", (task_id, dep_id))


def cmd_add(conn, args):
    meta = parse_meta(args.meta)
    ts = now()
    with conn:
        cur = conn.execute(
            "INSERT INTO tasks (project, title, notes, meta, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (args.project, args.title, args.notes, json.dumps(meta), ts, ts),
        )
        task_id = cur.lastrowid
        for dep in args.depends:
            add_dep(conn, task_id, dep)
        for blocked in args.blocks:
            add_dep(conn, blocked, task_id)
    emit(args, load(conn)[task_id], task_id)


def cmd_dep_add(conn, args):
    with conn:
        add_dep(conn, args.task, args.depends_on)
    emit(args, {"task_id": args.task, "depends_on": args.depends_on}, f"#{args.task} depends on #{args.depends_on}")


def cmd_dep_rm(conn, args):
    with conn:
        cur = conn.execute("DELETE FROM deps WHERE task_id=? AND depends_on=?", (args.task, args.depends_on))
    if cur.rowcount == 0:
        raise Fail(f"no such dependency: #{args.task} -> #{args.depends_on}")
    emit(args, {"task_id": args.task, "removed": args.depends_on}, f"#{args.task} no longer depends on #{args.depends_on}")


def cmd_ls(conn, args):
    tasks = scoped(load(conn), args)
    wanted = args.status
    if wanted:
        tasks = [t for t in tasks if t["derived_status"] in wanted or t["status"] in wanted]
    else:
        tasks = [t for t in tasks if t["status"] != "done"]
    emit(args, tasks, "\n".join(line(t, args.all_projects) for t in tasks))


def cmd_ready(conn, args):
    args.status = ["ready"]
    cmd_ls(conn, args)


def cmd_show(conn, args):
    tasks = load(conn)
    task = get(tasks, args.id)

    def ref(i):
        return {k: tasks[i][k] for k in ("id", "title", "status", "derived_status")}

    data = dict(task, depends_on=[ref(i) for i in task["depends_on"]], blocks=[ref(i) for i in task["blocks"]])
    out = [
        f"#{task['id']} {task['title']}",
        f"status:  {task['derived_status']}",
        f"project: {task['project']}",
        f"created: {task['created_at']}",
        f"done:    {task['done_at'] or '-'}",
    ]
    if task["notes"]:
        out.append(f"notes:\n{task['notes']}")
    if task["meta"]:
        out.append("meta:\n" + json.dumps(task["meta"], indent=2, ensure_ascii=False))
    for label, key in (("depends on", "depends_on"), ("blocks", "blocks")):
        out.append(f"{label}:")
        out.extend(f"  #{r['id']} [{r['derived_status']}] {r['title']}" for r in data[key])
    emit(args, data, "\n".join(out))


def set_status(conn, args, status):
    tasks = load(conn)
    task = get(tasks, args.id)
    if status == "done" and task["blocked_by"]:
        unfinished = ", ".join(f"#{d}" for d in task["depends_on"] if tasks[d]["status"] != "done")
        print(f"warning: #{task['id']} has unfinished dependencies: {unfinished}", file=sys.stderr)
    ts = now()
    with conn:
        conn.execute(
            "UPDATE tasks SET status=?, done_at=?, updated_at=? WHERE id=?",
            (status, ts if status == "done" else None, ts, args.id),
        )
    emit(args, load(conn)[args.id], f"#{args.id} {status}")


def cmd_start(conn, args):
    set_status(conn, args, "in_progress")


def cmd_done(conn, args):
    set_status(conn, args, "done")


def cmd_reopen(conn, args):
    set_status(conn, args, "open")


def cmd_edit(conn, args):
    task = get(load(conn), args.id)
    meta = {**task["meta"], **parse_meta(args.meta)}
    for key in args.unset_meta:
        meta.pop(key, None)
    with conn:
        conn.execute(
            "UPDATE tasks SET title=?, notes=?, meta=?, updated_at=? WHERE id=?",
            (args.title if args.title is not None else task["title"], args.notes if args.notes is not None else task["notes"], json.dumps(meta), now(), args.id),
        )
    emit(args, load(conn)[args.id], f"#{args.id} updated")


def cmd_rm(conn, args):
    get(load(conn), args.id)
    with conn:
        conn.execute("DELETE FROM tasks WHERE id=?", (args.id,))
    emit(args, {"deleted": args.id}, f"deleted #{args.id}")


def subtree(tasks, task_id, key, seen):
    task = tasks[task_id]
    node = {"id": task_id, "title": task["title"], "derived_status": task["derived_status"], "children": []}
    if task_id in seen:
        node["repeat"] = True
        return node
    seen.add(task_id)
    node["children"] = [subtree(tasks, i, key, seen) for i in task[key]]
    return node


def render(node, depth=0):
    mark = " (see above)" if node.get("repeat") else ""
    yield f"{'  ' * depth}[{node['derived_status']}] #{node['id']} {node['title']}{mark}"
    for child in node["children"]:
        yield from render(child, depth + 1)


def paths_up(tasks, task_id):
    here = {"id": task_id, "title": tasks[task_id]["title"]}
    if not tasks[task_id]["blocks"]:
        return [[here]]
    return [[here] + path for b in tasks[task_id]["blocks"] for path in paths_up(tasks, b)]


def cmd_why(conn, args):
    tasks = load(conn)
    get(tasks, args.id)
    text = "\n".join(render(subtree(tasks, args.id, "blocks", set())))
    emit(args, paths_up(tasks, args.id), text)


def cmd_tree(conn, args):
    tasks = load(conn)
    if args.id is not None:
        roots = [get(tasks, args.id)["id"]]
    else:
        roots = [t["id"] for t in tasks.values() if t["project"] == args.project and not any(tasks[b]["project"] == args.project for b in t["blocks"])]
    seen = set()
    nodes = [subtree(tasks, r, "depends_on", seen) for r in roots]
    emit(args, nodes, "\n".join(l for n in nodes for l in render(n)))


def cmd_graph(conn, args):
    tasks = scoped(load(conn), args)
    ids = {t["id"] for t in tasks}
    nodes = []
    for t in tasks:
        node = {k: t[k] for k in NODE_FIELDS}
        node["depends_on"] = [i for i in t["depends_on"] if i in ids]
        node["blocks"] = [i for i in t["blocks"] if i in ids]
        nodes.append(node)
    edges = [{"source": d, "target": n["id"]} for n in nodes for d in n["depends_on"]]
    payload = {"nodes": nodes, "edges": edges, "projects": sorted({t["project"] for t in tasks}), "generated_at": now()}
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    template = (Path(__file__).parent / "graph_template.html").read_text(encoding="utf-8")
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(template.replace("__DATA__", data, 1), encoding="utf-8")
    if not args.no_open:
        webbrowser.open(out.resolve().as_uri())
    emit(args, {"path": str(out), "nodes": len(nodes), "edges": len(edges)}, str(out))


def cmd_projects(conn, args):
    stats = {}
    for t in load(conn).values():
        s = stats.setdefault(t["project"], {"project": t["project"], "total": 0, "done": 0, "in_progress": 0, "ready": 0, "blocked": 0})
        s["total"] += 1
        if t["derived_status"] in s:
            s[t["derived_status"]] += 1
    rows = sorted(stats.values(), key=lambda s: s["project"])
    text = "\n".join(f"{s['project']:<20} total {s['total']:>3}  done {s['done']:>3}  ready {s['ready']:>3}  blocked {s['blocked']:>3}" for s in rows)
    emit(args, rows, text)


COMMANDS = {
    "add": cmd_add,
    "dep add": cmd_dep_add,
    "dep rm": cmd_dep_rm,
    "ls": cmd_ls,
    "ready": cmd_ready,
    "show": cmd_show,
    "start": cmd_start,
    "done": cmd_done,
    "reopen": cmd_reopen,
    "edit": cmd_edit,
    "rm": cmd_rm,
    "why": cmd_why,
    "tree": cmd_tree,
    "graph": cmd_graph,
    "projects": cmd_projects,
}


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=argparse.SUPPRESS)
    common.add_argument("--project", default=argparse.SUPPRESS)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)

    parser = argparse.ArgumentParser(prog="tg", parents=[common])
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name, container=sub, **kw):
        return container.add_parser(name, parents=[common], **kw)

    p = command("add")
    p.add_argument("title")
    p.add_argument("--depends", type=int, nargs="+", action="extend", default=[])
    p.add_argument("--blocks", type=int, nargs="+", action="extend", default=[])
    p.add_argument("--notes", default="")
    p.add_argument("--meta", nargs="+", action="extend", default=[])

    dep = command("dep")
    dep_sub = dep.add_subparsers(dest="dep_command", required=True)
    for name in ("add", "rm"):
        p = command(name, dep_sub)
        p.add_argument("task", type=int)
        p.add_argument("depends_on", type=int)

    p = command("ls")
    p.add_argument("--status", choices=FILTERS, nargs="+")
    p.add_argument("--all-projects", action="store_true")

    p = command("ready")
    p.add_argument("--all-projects", action="store_true")

    for name in ("show", "start", "done", "reopen", "rm", "why"):
        command(name).add_argument("id", type=int)

    p = command("edit")
    p.add_argument("id", type=int)
    p.add_argument("--title")
    p.add_argument("--notes")
    p.add_argument("--meta", nargs="+", action="extend", default=[])
    p.add_argument("--unset-meta", nargs="+", action="extend", default=[])

    p = command("tree")
    p.add_argument("id", type=int, nargs="?")

    p = command("graph")
    p.add_argument("--out", default=str(DEFAULT_GRAPH))
    p.add_argument("--all-projects", action="store_true")
    p.add_argument("--no-open", action="store_true")

    command("projects")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv, argparse.Namespace(db=None, project=None, json=False))
    args.project = args.project or default_project()
    key = f"dep {args.dep_command}" if args.command == "dep" else args.command
    try:
        COMMANDS[key](connect(args.db), args)
    except (Fail, sqlite3.Error) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
