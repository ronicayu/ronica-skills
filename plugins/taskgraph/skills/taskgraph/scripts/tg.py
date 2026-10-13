#!/usr/bin/env python3
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.request
import webbrowser
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit

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
  done_at TEXT,
  parent_id INTEGER REFERENCES tasks(id)
);
CREATE TABLE IF NOT EXISTS deps (
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  depends_on INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  PRIMARY KEY (task_id, depends_on),
  CHECK (task_id <> depends_on)
);
CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project, status);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  task_id INTEGER NOT NULL,
  project TEXT NOT NULL,
  at TEXT NOT NULL,
  field TEXT NOT NULL,
  old TEXT,
  new TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_at ON events(at);
"""

FILTERS = ("open", "in_progress", "done", "ready", "blocked")
NODE_FIELDS = (
    "id", "title", "status", "derived_status", "project", "notes", "meta", "depends_on", "blocks", "created_at", "done_at",
    "type", "parent", "children", "rollup", "late_days", "chase_due", "start", "due", "span", "conflicts",
)
TYPES = ("task", "milestone", "decision", "external", "objective")
PARENT_TYPES = ("task", "objective")
DATE_KEYS = ("date", "decide_by", "needed_by", "chase", "due", "start", "promised")
DUE_KEYS = {"task": "due", "objective": "due", "milestone": "date", "decision": "decide_by", "external": "needed_by"}
POINTS = ("milestone", "decision")
DATE_FLAGS = ("--start", "--due", "--promised", "--due-before", "--since")
PERSON_KEYS = {"decision": "decider", "external": "party"}
INHERITED = ("lane", "team")
SORTS = ("id", "due", "late")
DATE_FIELDS = ("due", "start", "promised")
SCOPE_FIELDS = ("title", "type", "parent", "depends_on", "meta.owner", "meta.decider", "meta.party", "meta.lane", "meta.team")
CHANGE_BUCKETS = {
    "new": "New", "started": "Started", "completed": "Completed", "reopened": "Reopened",
    "slipped": "Slipped", "pulled_in": "Pulled in", "rescoped": "Re-scoped", "removed": "Removed",
}
VENDOR = Path(__file__).parent / "vendor"
DEFAULT_GRAPH = Path.home() / ".taskgraph" / "graph.html"


class Fail(Exception):
    pass


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today():
    env = os.environ.get("TASKGRAPH_TODAY")
    return date.fromisoformat(env) if env else datetime.now(timezone.utc).date()


def parse_date(value):
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.isoformat() == value else None


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
    if "parent_id" not in {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}:
        with conn:
            conn.execute("ALTER TABLE tasks ADD COLUMN parent_id INTEGER REFERENCES tasks(id)")
    return conn


def ancestors(tasks, task_id):
    found = []
    parent = tasks[task_id]["parent"]
    while parent is not None:
        found.append(parent)
        parent = tasks[parent]["parent"]
    return found


def descendants(tasks, task_id):
    found = []
    for child in tasks[task_id]["children"]:
        found.append(child)
        found.extend(descendants(tasks, child))
    return found


def effective_deps(tasks, task):
    deps = set(task["depends_on"])
    for a in ancestors(tasks, task["id"]):
        deps.update(tasks[a]["depends_on"])
    return sorted(deps)


def inherited(tasks, task, key):
    for t in [task, *(tasks[a] for a in ancestors(tasks, task["id"]))]:
        value = t["meta"].get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def person(task):
    return task["meta"].get(PERSON_KEYS.get(task["type"], "owner"))


def is_summary(task):
    return bool(task["children"]) or task["type"] == "objective"


def computed(task):
    return is_summary(task) or task["type"] == "milestone"


def node_status(task, deps, current):
    deps_done = [current[d] == "done" for d in deps]
    if task["type"] == "milestone":
        return "done" if deps_done and all(deps_done) else "blocked"
    if is_summary(task):
        kids = [current[c] for c in task["children"]]
        if kids and all(k == "done" for k in kids) and all(deps_done):
            return "done"
        return "in_progress" if any(k in ("in_progress", "done") for k in kids) else "blocked"
    if task["status"] != "open":
        return task["status"]
    return "ready" if all(deps_done) else "blocked"


def load(conn):
    tasks = {}
    for row in conn.execute("SELECT * FROM tasks ORDER BY id"):
        task = dict(row)
        task["meta"] = json.loads(task["meta"])
        task["type"] = task["meta"].get("type", "task")
        task["parent"] = task.pop("parent_id")
        task["children"] = []
        task["conflicts"] = []
        task["depends_on"] = []
        task["blocks"] = []
        task["start"] = None if task["type"] in POINTS else normal(task["meta"].get("start"))
        task["due"] = normal(task["meta"].get(DUE_KEYS[task["type"]]))
        tasks[task["id"]] = task
    for task in tasks.values():
        if task["parent"] is not None:
            tasks[task["parent"]]["children"].append(task["id"])
    for task_id, dep in conn.execute("SELECT task_id, depends_on FROM deps ORDER BY task_id, depends_on"):
        tasks[task_id]["depends_on"].append(dep)
        tasks[dep]["blocks"].append(task_id)
    for task in tasks.values():
        for key in INHERITED:
            task[key] = inherited(tasks, task, key)
    effective = {i: effective_deps(tasks, t) for i, t in tasks.items()}
    current = {i: "blocked" for i in tasks}
    for _ in range(len(tasks) + 1):
        following = {i: node_status(t, effective[i], current) for i, t in tasks.items()}
        if following == current:
            break
        current = following
    day = today()
    for task in tasks.values():
        task["derived_status"] = current[task["id"]]
        deps = task["depends_on"] if computed(task) and task["type"] != "milestone" else effective[task["id"]]
        task["blocked_by"] = sum(current[d] != "done" for d in deps)
        if is_summary(task):
            leaves = [d for d in descendants(tasks, task["id"]) if not is_summary(tasks[d])]
            task["rollup"] = {"done": sum(current[d] == "done" for d in leaves), "total": len(leaves)}
        else:
            task["rollup"] = None
        unfinished = current[task["id"]] != "done"
        due = parse_date(task["due"])
        task["late_days"] = (day - due).days if due and due < day and unfinished and task["type"] != "objective" else None
        chase = parse_date(task["meta"].get("chase")) if task["type"] == "external" else None
        task["chase_due"] = bool(chase and chase <= day and unfinished)
        task["span"] = span(tasks, task) if is_summary(task) else None
    finish_derived(tasks, effective, current)
    find_conflicts(tasks, effective, current)
    return tasks


def finish_derived(tasks, effective, current):
    memo = {}

    def finished(i):
        if i not in memo:
            task = tasks[i]
            if current[i] != "done":
                memo[i] = None
            elif not computed(task):
                memo[i] = task["done_at"]
            else:
                below = effective[i] if task["type"] == "milestone" else task["children"] + task["depends_on"]
                memo[i] = max(filter(None, map(finished, below)), default=None)
        return memo[i]

    for task in tasks.values():
        if computed(task):
            task["done_at"] = finished(task["id"])


def normal(value):
    return value if parse_date(value) else None


def span(tasks, task):
    below = [tasks[d] for d in descendants(tasks, task["id"])]
    starts = [t["start"] or t["due"] for t in below if t["start"] or t["due"]]
    ends = [t["due"] or t["start"] for t in below if t["start"] or t["due"]]
    return {"start": min(starts), "end": max(ends)} if starts else None


def find_conflicts(tasks, effective, current):
    def flag(task, kind, other, message):
        task["conflicts"].append({"kind": kind, "with": other, "message": message})

    for n in tasks.values():
        need = n["start"] or n["due"]
        for d in effective[n["id"]] if need else []:
            dep = tasks[d]
            if dep["due"] and dep["due"] > need and current[d] != "done":
                message = f"#{d} due {dep['due']} after #{n['id']} needs it {need}"
                flag(dep, "dependency", n["id"], message)
                flag(n, "dependency", d, message)
        parent = tasks[n["parent"]] if n["parent"] is not None else None
        if parent and parent["due"] and n["due"] and n["due"] > parent["due"]:
            flag(n, "parent", parent["id"], f"#{n['id']} due {n['due']} after parent #{parent['id']} due {parent['due']}")
        promised = normal(n["meta"].get("promised")) if n["type"] == "external" else None
        if promised and n["due"] and promised > n["due"]:
            flag(n, "promised", None, f"#{n['id']} promised {promised} after needed {n['due']}")


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


def check_meta(meta):
    if meta.get("type", "task") not in TYPES:
        raise Fail(f"unknown type {meta['type']!r} (expected one of {', '.join(TYPES)})")
    for key in DATE_KEYS:
        if key in meta and parse_date(meta[key]) is None:
            raise Fail(f"{key} must be YYYY-MM-DD: {meta[key]!r}")


def resolve_date(value):
    if value == "today":
        return today().isoformat()
    match = re.fullmatch(r"([+-])(\d+)([dw])", value)
    if match:
        days = int(match[2]) * (7 if match[3] == "w" else 1)
        return (today() + timedelta(days=-days if match[1] == "-" else days)).isoformat()
    if parse_date(value) is None:
        raise Fail(f"date must be YYYY-MM-DD, today, or an offset like +3d / -1w: {value!r}")
    return value


def check_span(meta):
    kind = meta.get("type", "task")
    start, due = meta.get("start"), meta.get(DUE_KEYS[kind])
    if kind not in POINTS and start and due and start > due:
        raise Fail(f"start {start} is after due {due}")


def brief_task(task):
    keys = ("id", "title", "type", "derived_status", "project", "parent", "lane", "start", "due", "late_days")
    return {**{k: task[k] for k in keys}, "conflict_count": len(task["conflicts"])}


def emit(args, data, text=None):
    if args.json:
        print(json.dumps(data, ensure_ascii=False))
    elif text is not None:
        print(text)


def marker(task):
    return f"[{task['type']}] " if task["type"] != "task" else ""


def line(task, with_project=False):
    prefix = f"{task['project']:<12} " if with_project else ""
    suffix = f"  (blocked by {task['blocked_by']})" if task["derived_status"] == "blocked" and task["blocked_by"] else ""
    if task["late_days"]:
        suffix += f"  (late {task['late_days']}d)"
    if task["chase_due"]:
        suffix += "  (chase due)"
    if task["conflicts"]:
        suffix += "  (conflict)"
    details = [f"due {task['due']}" if task["due"] else None, person(task), task["lane"]]
    details = " — " + " · ".join(str(d) for d in details if d) if any(details) else ""
    return f"{prefix}{task['id']:>4}  {task['derived_status']:<11} {marker(task)}{task['title']}{details}{suffix}"


def reaches(conn, start, target):
    sql = """
    WITH RECURSIVE r(id) AS (
      SELECT :start UNION SELECT d.depends_on FROM deps d JOIN r ON d.task_id = r.id
    ) SELECT 1 FROM r WHERE id = :target
    """
    return conn.execute(sql, {"start": start, "target": target}).fetchone() is not None


def wait_edges(tasks):
    edges = {}
    for task in tasks.values():
        found = {d: "" for d in task["depends_on"]}
        for a in ancestors(tasks, task["id"]):
            for d in tasks[a]["depends_on"]:
                found.setdefault(d, f" (dependency of ancestor #{a})")
        edges[task["id"]] = [(d, found[d]) for d in sorted(found)]
        if is_summary(task):
            edges[task["id"]] += [(c, " (its child)") for c in task["children"]]
    return edges


def check_deadlock(conn):
    edges = wait_edges(load(conn))
    state = {}

    def visit(node, trail):
        state[node] = "open"
        for target, note in edges[node]:
            step = f"#{node} waits for #{target}{note}"
            if state.get(target) == "open":
                start = next((i for i, (n, _) in enumerate(trail) if n == target), len(trail))
                chain = [text for _, text in trail[start:]] + [step]
                raise Fail("deadlock: " + ", ".join(chain))
            if target not in state:
                visit(target, trail + [(node, step)])
        state[node] = "done"

    for node in edges:
        if node not in state:
            visit(node, [])


def tracked(task):
    fields = {
        "title": task["title"], "status": task["status"], "type": task["type"], "parent": task["parent"], "notes": task["notes"],
        "start": task["start"], "due": task["due"], "promised": normal(task["meta"].get("promised")), "depends_on": task["depends_on"],
    }
    skip = {"type", "start", "promised", *DUE_KEYS.values()}
    fields.update({f"meta.{k}": v for k, v in task["meta"].items() if k not in skip})
    return fields


@contextmanager
def journal(conn):
    before = load(conn)
    yield
    after = load(conn)
    ts = now()
    rows = []
    for i in sorted(before.keys() | after.keys()):
        if i not in before:
            rows.append((i, after[i]["project"], ts, "created", None, json.dumps(after[i]["title"], ensure_ascii=False)))
        elif i not in after:
            rows.append((i, before[i]["project"], ts, "removed", json.dumps(before[i]["title"], ensure_ascii=False), None))
        else:
            old, new = tracked(before[i]), tracked(after[i])
            for field in sorted(old.keys() | new.keys()):
                if old.get(field) != new.get(field):
                    rows.append((i, after[i]["project"], ts, field, *(json.dumps(v.get(field), ensure_ascii=False) for v in (old, new))))
    conn.executemany("INSERT INTO events (task_id, project, at, field, old, new) VALUES (?, ?, ?, ?, ?, ?)", rows)


def add_dep(conn, task_id, dep_id):
    tasks = load(conn)
    get(tasks, task_id)
    get(tasks, dep_id)
    if tasks[task_id]["project"] != tasks[dep_id]["project"]:
        raise Fail(f"#{task_id} is in project {tasks[task_id]['project']} and #{dep_id} in {tasks[dep_id]['project']}; dependencies cannot cross projects")
    if task_id in ancestors(tasks, dep_id) or dep_id in ancestors(tasks, task_id):
        raise Fail(f"#{task_id} and #{dep_id} are in the same parent chain; a task cannot depend on its ancestor or descendant")
    if reaches(conn, dep_id, task_id):
        raise Fail(f"cycle: #{task_id} depending on #{dep_id} would create a cycle")
    conn.execute("INSERT OR IGNORE INTO deps (task_id, depends_on) VALUES (?, ?)", (task_id, dep_id))
    check_deadlock(conn)


def place(conn, task_id, kind, parent_id):
    tasks = load(conn)
    children = [tasks[c] for c in tasks[task_id]["children"]]
    if children and kind not in PARENT_TYPES:
        raise Fail(f"#{task_id} has children, so its type must be task or objective, not {kind}")
    if kind != "objective" and any(c["type"] == "objective" for c in children):
        raise Fail(f"#{task_id} has objective children, so its type must be objective")
    if parent_id is not None:
        parent = get(tasks, parent_id)
        if parent["project"] != tasks[task_id]["project"]:
            raise Fail(f"#{parent_id} is in project {parent['project']} and #{task_id} in {tasks[task_id]['project']}; parents cannot cross projects")
        if parent["type"] not in PARENT_TYPES:
            raise Fail(f"#{parent_id} is a {parent['type']}; parents must be a task or objective")
        if kind == "objective" and parent["type"] != "objective":
            raise Fail(f"parent of objective #{task_id} must be an objective")
        if parent_id == task_id or task_id in ancestors(tasks, parent_id):
            raise Fail(f"cycle: #{task_id} cannot be its own ancestor")
    conn.execute("UPDATE tasks SET parent_id=? WHERE id=?", (parent_id, task_id))
    tasks = load(conn)
    for task in tasks.values():
        for dep in task["depends_on"]:
            if dep in ancestors(tasks, task["id"]) or task["id"] in ancestors(tasks, dep):
                raise Fail(f"#{task['id']} depends on #{dep}, which would be its ancestor or descendant")
    check_deadlock(conn)


def cmd_add(conn, args):
    meta = parse_meta(args.meta)
    if args.type is not None:
        meta["type"] = args.type
    check_meta(meta)
    if meta.get("type") == "task":
        del meta["type"]
    if args.start is not None:
        meta["start"] = resolve_date(args.start)
    if args.due is not None:
        meta[DUE_KEYS[meta.get("type", "task")]] = resolve_date(args.due)
    if args.promised is not None:
        if meta.get("type") != "external":
            raise Fail("--promised applies to externals only")
        meta["promised"] = resolve_date(args.promised)
    check_span(meta)
    ts = now()
    with conn, journal(conn):
        cur = conn.execute(
            "INSERT INTO tasks (project, title, notes, meta, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (args.project, args.title, args.notes, json.dumps(meta), ts, ts),
        )
        task_id = cur.lastrowid
        if args.parent is not None:
            place(conn, task_id, meta.get("type", "task"), args.parent)
        for dep in args.depends:
            add_dep(conn, task_id, dep)
        for blocked in args.blocks:
            add_dep(conn, blocked, task_id)
    emit(args, load(conn)[task_id], task_id)


def cmd_dep_add(conn, args):
    with conn, journal(conn):
        add_dep(conn, args.task, args.depends_on)
    emit(args, {"task_id": args.task, "depends_on": args.depends_on}, f"#{args.task} depends on #{args.depends_on}")


def cmd_dep_rm(conn, args):
    with conn, journal(conn):
        cur = conn.execute("DELETE FROM deps WHERE task_id=? AND depends_on=?", (args.task, args.depends_on))
    if cur.rowcount == 0:
        raise Fail(f"no such dependency: #{args.task} -> #{args.depends_on}")
    emit(args, {"task_id": args.task, "removed": args.depends_on}, f"#{args.task} no longer depends on #{args.depends_on}")


def cmd_ls(conn, args):
    everything = load(conn)
    tasks = scoped(everything, args)
    if args.parent is not None:
        get(everything, args.parent)
        tasks = [t for t in tasks if t["parent"] == args.parent]
    if args.type:
        tasks = [t for t in tasks if t["type"] in args.type]
    if args.search:
        needle = args.search.lower()
        tasks = [t for t in tasks if needle in t["title"].lower() or needle in t["notes"].lower()]
    for key, wanted in (("owner", args.owner), ("lane", args.lane), ("team", args.team)):
        if wanted is not None:
            tasks = [t for t in tasks if same(person(t) if key == "owner" else t[key], wanted)]
    for key, wanted in parse_meta(args.meta).items():
        tasks = [t for t in tasks if same(t[key] if key in INHERITED else t["meta"].get(key), wanted)]
    if args.due_before is not None:
        limit = resolve_date(args.due_before)
        tasks = [t for t in tasks if t["due"] and t["due"] <= limit]
    wanted = args.status
    if wanted:
        tasks = [t for t in tasks if t["derived_status"] in wanted or (t["status"] in wanted and not computed(t))]
    else:
        tasks = [t for t in tasks if t["derived_status"] != "done"]
    if args.sort == "due":
        tasks.sort(key=lambda t: (t["due"] or "9999-12-31", t["id"]))
    elif args.sort == "late":
        tasks.sort(key=lambda t: (-(t["late_days"] or 0), t["due"] or "9999-12-31", t["id"]))
    emit(args, [brief_task(t) for t in tasks] if args.brief else tasks, "\n".join(line(t, args.all_projects) for t in tasks))


def same(actual, wanted):
    if isinstance(actual, list):
        return any(same(a, wanted) for a in actual)
    return actual is not None and str(actual).strip().lower() == str(wanted).strip().lower()


def cmd_ready(conn, args):
    args.status = ["ready"]
    args.parent = args.type = args.search = args.owner = args.lane = args.team = args.due_before = None
    args.meta = []
    args.sort = "id"
    cmd_ls(conn, args)


def cmd_show(conn, args):
    tasks = load(conn)
    task = get(tasks, args.id)

    def ref(i):
        return {k: tasks[i][k] for k in ("id", "title", "status", "derived_status")}

    data = dict(task, depends_on=[ref(i) for i in task["depends_on"]], blocks=[ref(i) for i in task["blocks"]])
    if args.brief:
        data = dict(brief_task(task), depends_on=task["depends_on"], blocks=task["blocks"])
    out = [
        f"#{task['id']} {task['title']}",
        f"type:    {task['type']}",
        f"status:  {task['derived_status']}",
        f"project: {task['project']}",
        f"created: {task['created_at']}",
        f"done:    {task['done_at'] or '-'}",
    ]
    if task["parent"] is not None:
        out.append(f"parent:  #{task['parent']} {tasks[task['parent']]['title']}")
    if task["children"]:
        out.append("children: " + ", ".join(f"#{c}" for c in task["children"]))
    if task["rollup"]:
        out.append(f"rollup:  {task['rollup']['done']}/{task['rollup']['total']}")
    if task["start"]:
        out.append(f"start:   {task['start']}")
    if task["due"]:
        out.append(f"due:     {task['due']}")
    if task["meta"].get("promised") and task["type"] == "external":
        out.append(f"promised: {task['meta']['promised']}")
    if task["late_days"]:
        out.append(f"late:    {task['late_days']}d")
    if task["chase_due"]:
        out.append("chase:   due")
    if task["conflicts"]:
        out.append("conflicts:")
        out.extend(f"  {c['message']}" for c in task["conflicts"])
    if task["notes"]:
        out.append(f"notes:\n{task['notes']}")
    if task["meta"]:
        out.append("meta:\n" + json.dumps(task["meta"], indent=2, ensure_ascii=False))
    for label, key in (("depends on", "depends_on"), ("blocks", "blocks")):
        out.append(f"{label}:")
        out.extend(f"  #{r['id']} [{r['derived_status']}] {r['title']}" for r in (tasks[i] for i in task[key]))
    emit(args, data, "\n".join(out))


def set_status(conn, args, status):
    tasks = load(conn)
    task = get(tasks, args.id)
    if is_summary(task):
        raise Fail(f"status of #{task['id']} is derived from its children")
    if task["type"] == "milestone":
        raise Fail(f"status of #{task['id']} is derived from its dependencies")
    unfinished = [d for d in effective_deps(tasks, task) if tasks[d]["derived_status"] != "done"]
    warnings = []
    if status == "done" and unfinished:
        warnings.append(f"#{task['id']} has unfinished dependencies: {', '.join(f'#{d}' for d in unfinished)}")
        print(f"warning: {warnings[0]}", file=sys.stderr)
    ts = now()
    with conn, journal(conn):
        conn.execute(
            "UPDATE tasks SET status=?, done_at=?, updated_at=? WHERE id=?",
            (status, ts if status == "done" else None, ts, args.id),
        )
    data = load(conn)[args.id]
    emit(args, dict(data, warnings=warnings) if warnings else data, f"#{args.id} {status}")


def cmd_start(conn, args):
    set_status(conn, args, "in_progress")


def cmd_done(conn, args):
    set_status(conn, args, "done")


def cmd_reopen(conn, args):
    set_status(conn, args, "open")


def cmd_edit(conn, args):
    task = get(load(conn), args.id)
    if args.parent is not None and args.no_parent:
        raise Fail("--parent and --no-parent cannot be combined")
    changes = parse_meta(args.meta)
    if args.type is not None:
        changes["type"] = args.type
    check_meta(changes)
    meta = {**task["meta"], **changes}
    for key in args.unset_meta:
        meta.pop(key, None)
    if meta.get("type") == "task":
        del meta["type"]
    parent = None if args.no_parent else task["parent"] if args.parent is None else args.parent
    with conn, journal(conn):
        conn.execute(
            "UPDATE tasks SET title=?, notes=?, meta=?, updated_at=? WHERE id=?",
            (args.title if args.title is not None else task["title"], args.notes if args.notes is not None else task["notes"], json.dumps(meta), now(), args.id),
        )
        place(conn, args.id, meta.get("type", "task"), parent)
    emit(args, load(conn)[args.id], f"#{args.id} updated")


def cmd_rm(conn, args):
    tasks = load(conn)
    get(tasks, args.id)
    below = descendants(tasks, args.id)
    if below and not args.recursive:
        raise Fail(f"#{args.id} has {len(tasks[args.id]['children'])} children; pass --recursive to delete the whole subtree")
    doomed = [args.id, *below]
    with conn, journal(conn):
        conn.execute(f"DELETE FROM tasks WHERE id IN ({','.join('?' * len(doomed))})", doomed)
    data = {"deleted": args.id, **({"descendants": below} if below else {})}
    emit(args, data, f"deleted #{args.id}" + (f" and {len(below)} descendants" if below else ""))


def subtree(tasks, task_id, kids, seen, via=None):
    task = tasks[task_id]
    node = {"id": task_id, "title": task["title"], "type": task["type"], "derived_status": task["derived_status"], "children": []}
    if via:
        node["via"] = via
    if task_id in seen:
        node["repeat"] = True
        return node
    seen.add(task_id)
    node["children"] = [subtree(tasks, i, kids, seen, v) for i, v in kids(task)]
    return node


def render(node, depth=0):
    mark = " (see above)" if node.get("repeat") else ""
    kind = f"[{node['type']}] " if node["type"] != "task" else ""
    part = "(part of) " if node.get("via") == "parent" else ""
    yield f"{'  ' * depth}{part}[{node['derived_status']}] #{node['id']} {kind}{node['title']}{mark}"
    for child in node["children"]:
        yield from render(child, depth + 1)


def upward(task):
    return [(b, "blocks") for b in task["blocks"]] + ([(task["parent"], "parent")] if task["parent"] is not None else [])


def paths_up(tasks, task_id, via=None):
    here = {"id": task_id, "title": tasks[task_id]["title"], "via": via}
    steps = upward(tasks[task_id])
    if not steps:
        return [[here]]
    return [[here] + path for b, v in steps for path in paths_up(tasks, b, v)]


def cmd_why(conn, args):
    tasks = load(conn)
    get(tasks, args.id)
    text = "\n".join(render(subtree(tasks, args.id, upward, set())))
    emit(args, paths_up(tasks, args.id), text)


def cmd_tree(conn, args):
    tasks = load(conn)
    key = "children" if args.children else "depends_on"

    def kids(task):
        return [(i, None) for i in task[key]]

    if args.id is not None:
        roots = [get(tasks, args.id)["id"]]
    elif args.children:
        roots = [t["id"] for t in tasks.values() if t["project"] == args.project and (t["parent"] is None or tasks[t["parent"]]["project"] != args.project)]
    else:
        tops = [t for t in tasks.values() if t["project"] == args.project and not any(tasks[b]["project"] == args.project for b in t["blocks"])]
        roots = [t["id"] for t in tops if t["depends_on"] or t["type"] in ("milestone", "objective")] or [t["id"] for t in tops]
    seen = set()
    nodes = [subtree(tasks, r, kids, seen) for r in roots]
    emit(args, nodes, "\n".join(l for n in nodes for l in render(n)))


def cmd_date(conn, args):
    task = get(load(conn), args.id)
    meta = dict(task["meta"])
    keys = {"start": "start", "due": DUE_KEYS[task["type"]], "promised": "promised"}
    given = {"start": args.start, "due": args.due, "promised": args.promised}
    setting = {n for n, v in given.items() if v is not None}
    if not setting and not args.clear:
        raise Fail("nothing to change (pass --start, --due, --promised or --clear)")
    if "promised" in setting | set(args.clear) and task["type"] != "external":
        raise Fail(f"promised applies to externals, but #{task['id']} is a {task['type']}")
    if setting & set(args.clear):
        raise Fail("cannot set and clear the same date")
    for name in setting:
        meta[keys[name]] = resolve_date(given[name])
    for name in args.clear:
        meta.pop(keys[name], None)
    check_span(meta)
    with conn, journal(conn):
        conn.execute("UPDATE tasks SET meta=?, updated_at=? WHERE id=?", (json.dumps(meta), now(), args.id))
    data = load(conn)[args.id]
    text = f"#{args.id} start {data['start'] or '-'} due {data['due'] or '-'}"
    if data["type"] == "external":
        text += f" promised {data['meta'].get('promised') or '-'}"
    emit(args, data, text)


def agenda_line(task, note):
    person = task["meta"].get({"decision": "decider", "external": "party"}.get(task["type"], "owner"))
    parts = [f"due {task['due']}" if task["due"] else "no due date"]
    parts += [x for x in (person, note) if x]
    return f"#{task['id']} {marker(task)}{task['title']} — " + " · ".join(parts)


def cmd_agenda(conn, args):
    day = today()
    limit = (day + timedelta(days=args.within)).isoformat()
    items = [t for t in scoped(load(conn), args) if t["derived_status"] != "done" and (not args.type or t["type"] in args.type)]
    by_due = lambda t: (t["due"] or "9999-12-31", t["id"])
    buckets = {
        "late": sorted((t for t in items if t["late_days"]), key=lambda t: (-t["late_days"], t["id"])),
        "conflicts": sorted((t for t in items if t["conflicts"]), key=by_due),
        "due_soon": sorted((t for t in items if t["due"] and day.isoformat() <= t["due"] <= limit), key=by_due),
        "chase_due": sorted((t for t in items if t["chase_due"]), key=lambda t: (t["meta"]["chase"], t["id"])),
        "missing_date": [t for t in items if t["type"] in ("decision", "external") and not t["due"]],
    }
    notes = {
        "late": lambda t: f"late {t['late_days']}d",
        "conflicts": lambda t: "; ".join(c["message"] for c in t["conflicts"]),
        "due_soon": lambda t: None,
        "chase_due": lambda t: f"chase {t['meta']['chase']}",
        "missing_date": lambda t: None,
    }
    headings = {"late": "Late", "conflicts": "Conflicts", "due_soon": f"Due in {args.within} days", "chase_due": "Chase due", "missing_date": "Missing date"}
    out = []
    for name, found in buckets.items():
        if found:
            out += [headings[name], *(f"  {agenda_line(t, notes[name](t))}" for t in found), ""]
    emit(args, {name: [brief_task(t) for t in found] for name, found in buckets.items()}, "\n".join(out).rstrip() or "nothing needs attention")


def resolve_since(value):
    return resolve_date("-" + value if re.fullmatch(r"\d+[dw]", value) else value)


def net_changes(rows):
    first, last = {}, {}
    for r in rows:
        first.setdefault(r["field"], json.loads(r["old"]) if r["old"] is not None else None)
        last[r["field"]] = json.loads(r["new"]) if r["new"] is not None else None
    return {f: (first[f], last[f]) for f in first if first[f] != last[f]}


def describe(field, old, new):
    name = field.removeprefix("meta.").replace("_", " ")
    if field == "depends_on":
        gone, came = sorted(set(old or []) - set(new or [])), sorted(set(new or []) - set(old or []))
        return "depends on " + " ".join([*(f"+#{i}" for i in came), *(f"-#{i}" for i in gone)])
    if field == "parent":
        return f"parent {f'#{old}' if old else '-'} → {f'#{new}' if new else '-'}"
    if field == "title":
        return f"title {json.dumps(old, ensure_ascii=False)} → {json.dumps(new, ensure_ascii=False)}"
    return f"{name} {old if old is not None else '-'} → {new if new is not None else '-'}"


def cmd_changes(conn, args):
    since = resolve_since(args.since)
    tasks = load(conn)
    rows = [r for r in conn.execute("SELECT * FROM events WHERE at >= ? ORDER BY id", (since + "T00:00:00Z",)) if args.all_projects or r["project"] == args.project]
    by_task = {}
    for r in rows:
        by_task.setdefault(r["task_id"], []).append(r)
    found = {name: [] for name in CHANGE_BUCKETS}
    text = {name: [] for name in CHANGE_BUCKETS}
    for task_id, events in by_task.items():
        fields = {e["field"] for e in events}
        if "removed" in fields:
            if "created" not in fields:
                title = json.loads(next(e["old"] for e in events if e["field"] == "removed"))
                found["removed"].append({"id": task_id, "title": title, "project": events[0]["project"]})
                text["removed"].append(f"#{task_id} {title}")
            continue
        task = tasks.get(task_id)
        if task is None:
            continue
        if "created" in fields:
            found["new"].append(brief_task(task))
            text["new"].append(agenda_line(task, None))
            continue
        net = net_changes(e for e in events if e["field"] not in ("created", "removed"))
        old_status, new_status = net.get("status", (None, None))
        if new_status == "in_progress" and old_status == "open":
            found["started"].append(brief_task(task))
            text["started"].append(agenda_line(task, None))
        if old_status == "done" and new_status != "done":
            found["reopened"].append(brief_task(task))
            text["reopened"].append(agenda_line(task, None))
        scope = []
        for field in DATE_FIELDS:
            if field not in net:
                continue
            old, new = net[field]
            if old and new:
                days = (date.fromisoformat(new) - date.fromisoformat(old)).days
                bucket = "slipped" if days > 0 else "pulled_in"
                found[bucket].append(dict(brief_task(task), field=field, **{"from": old, "to": new, "days": days}))
                text[bucket].append(f"#{task_id} {marker(task)}{task['title']} — {field} {old} → {new} ({days:+d}d)")
            else:
                scope.append({"field": field, "from": old, "to": new})
        scope += [{"field": f, "from": net[f][0], "to": net[f][1]} for f in SCOPE_FIELDS if f in net]
        if scope:
            found["rescoped"].append(dict(brief_task(task), changes=scope))
            text["rescoped"].append(f"#{task_id} {marker(task)}{task['title']} — " + "; ".join(describe(c["field"], c["from"], c["to"]) for c in scope))
    for task in scoped(tasks, args):
        if task["derived_status"] == "done" and task["done_at"] and task["done_at"] >= since + "T00:00:00Z":
            found["completed"].append(dict(brief_task(task), done_at=task["done_at"]))
            text["completed"].append(f"#{task['id']} {marker(task)}{task['title']} — done {task['done_at'][:10]}")
    out = [f"Changes since {since}"]
    for name, heading in CHANGE_BUCKETS.items():
        if text[name]:
            out += ["", heading, *(f"  {t}" for t in text[name])]
    emit(args, {"since": since, **found}, "\n".join(out) if len(out) > 1 else f"no changes since {since}")


def cmd_export(conn, args):
    keys = ("id", "project", "title", "status", "notes", "meta", "parent", "depends_on", "created_at", "updated_at", "done_at")
    tasks = [{k: t[k] for k in keys} for t in scoped(load(conn), args)]
    text = json.dumps({"version": 1, "exported_at": now(), "tasks": tasks}, ensure_ascii=False, indent=2)
    if args.out is None:
        print(text)
        return
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    emit(args, {"path": str(out), "tasks": len(tasks)}, str(out))


def graph_payload(conn, args):
    tasks = scoped(load(conn), args)
    ids = {t["id"] for t in tasks}
    nodes = []
    for t in tasks:
        node = {k: t[k] for k in NODE_FIELDS}
        node["depends_on"] = [i for i in t["depends_on"] if i in ids]
        node["blocks"] = [i for i in t["blocks"] if i in ids]
        node["parent"] = t["parent"] if t["parent"] in ids else None
        node["children"] = [i for i in t["children"] if i in ids]
        nodes.append(node)
    edges = [{"source": d, "target": n["id"]} for n in nodes for d in n["depends_on"]]
    return {"nodes": nodes, "edges": edges, "projects": sorted({t["project"] for t in tasks}), "generated_at": now(), "today": today().isoformat(), "live": False}


def render_page(payload):
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    head, tail = (Path(__file__).parent / "graph_template.html").read_text(encoding="utf-8").split("__DATA__", 1)
    return inline_vendor(head) + data + inline_vendor(tail)


def inline_vendor(html):
    def swap(match):
        path = VENDOR / match[1]
        if not path.is_file():
            return match[0]
        return "<script>" + path.read_text(encoding="utf-8").replace("</script", "<\\/script") + "</script>"

    return re.sub(r'<script src="https://cdn\.jsdelivr\.net/npm/[^"]*/([^/"]+)"></script>', swap, html)


def cmd_graph(conn, args):
    payload = graph_payload(conn, args)
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_page(payload), encoding="utf-8")
    if not args.no_open:
        webbrowser.open(out.resolve().as_uri())
    emit(args, {"path": str(out), "nodes": len(payload["nodes"]), "edges": len(payload["edges"])}, str(out))


def data_version(conn):
    return conn.execute("PRAGMA data_version").fetchone()[0]


def db_path(conn):
    return conn.execute("PRAGMA database_list").fetchone()[2]


def make_handler(conn, args):
    identity = {"app": "taskgraph", "db": db_path(conn)}
    everything = argparse.Namespace(**{**vars(args), "all_projects": True})

    class Handler(BaseHTTPRequestHandler):
        def send(self, body, content_type):
            raw = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def live_payload(self):
            return dict(graph_payload(conn, everything), live=True, version=data_version(conn))

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/":
                self.send(render_page(self.live_payload()), "text/html; charset=utf-8")
            elif path == "/version":
                self.send(json.dumps(dict(identity, version=data_version(conn))), "application/json")
            elif path == "/data.json":
                self.send(json.dumps(self.live_payload(), ensure_ascii=False), "application/json; charset=utf-8")
            else:
                self.send_error(404)

        def log_message(self, *a):
            pass

    return Handler


def probe(url):
    try:
        with urllib.request.urlopen(url + "version", timeout=1) as r:
            return json.load(r)
    except (OSError, ValueError):
        return {}


def cmd_serve(conn, args):
    base = f"http://127.0.0.1:{args.port}/"
    url = base if args.all_projects else f"{base}?project={quote(args.project, safe='')}"
    try:
        server = HTTPServer(("127.0.0.1", args.port), make_handler(conn, args))
    except OSError:
        other = probe(base)
        if other.get("app") != "taskgraph":
            raise Fail(f"port {args.port} in use")
        if other.get("db") != db_path(conn):
            raise Fail(f"port {args.port} is serving taskgraph for {other.get('db')}; pass --port to serve {db_path(conn)}")
        if not args.no_open:
            webbrowser.open(url)
        emit(args, {"url": url, "already_running": True}, f"already running at {url}")
        return
    emit(args, {"url": url}, url)
    sys.stdout.flush()
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


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
    "date": cmd_date,
    "agenda": cmd_agenda,
    "changes": cmd_changes,
    "export": cmd_export,
    "tree": cmd_tree,
    "graph": cmd_graph,
    "serve": cmd_serve,
    "projects": cmd_projects,
}


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=argparse.SUPPRESS)
    common.add_argument("--project", default=argparse.SUPPRESS)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--brief", action="store_true", default=argparse.SUPPRESS)

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
    p.add_argument("--type")
    p.add_argument("--parent", type=int)
    p.add_argument("--start")
    p.add_argument("--due")
    p.add_argument("--promised")

    dep = command("dep")
    dep_sub = dep.add_subparsers(dest="dep_command", required=True)
    for name in ("add", "rm"):
        p = command(name, dep_sub)
        p.add_argument("task", type=int)
        p.add_argument("depends_on", type=int)

    p = command("ls")
    p.add_argument("--status", choices=FILTERS, nargs="+", action="extend")
    p.add_argument("--parent", type=int)
    p.add_argument("--type", choices=TYPES, nargs="+", action="extend")
    p.add_argument("--search")
    p.add_argument("--owner")
    p.add_argument("--lane")
    p.add_argument("--team")
    p.add_argument("--meta", nargs="+", action="extend", default=[])
    p.add_argument("--due-before")
    p.add_argument("--sort", choices=SORTS, default="id")
    p.add_argument("--all-projects", action="store_true")

    p = command("ready")
    p.add_argument("--all-projects", action="store_true")

    for name in ("show", "start", "done", "reopen", "rm", "why"):
        p = command(name)
        p.add_argument("id", type=int)
        if name == "rm":
            p.add_argument("--recursive", action="store_true")

    p = command("edit")
    p.add_argument("id", type=int)
    p.add_argument("--title")
    p.add_argument("--notes")
    p.add_argument("--meta", nargs="+", action="extend", default=[])
    p.add_argument("--unset-meta", nargs="+", action="extend", default=[])
    p.add_argument("--type")
    p.add_argument("--parent", type=int)
    p.add_argument("--no-parent", action="store_true")

    p = command("date")
    p.add_argument("id", type=int)
    p.add_argument("--start")
    p.add_argument("--due")
    p.add_argument("--promised")
    p.add_argument("--clear", choices=("start", "due", "promised"), nargs="+", action="extend", default=[])

    p = command("agenda")
    p.add_argument("--within", type=int, default=14)
    p.add_argument("--type", choices=TYPES, nargs="+", action="extend")
    p.add_argument("--all-projects", action="store_true")

    p = command("changes")
    p.add_argument("--since", default="7d")
    p.add_argument("--all-projects", action="store_true")

    p = command("export")
    p.add_argument("--out")
    p.add_argument("--all-projects", action="store_true")

    p = command("tree")
    p.add_argument("id", type=int, nargs="?")
    p.add_argument("--children", action="store_true")

    p = command("graph")
    p.add_argument("--out", default=str(DEFAULT_GRAPH))
    p.add_argument("--all-projects", action="store_true")
    p.add_argument("--no-open", action="store_true")

    p = command("serve")
    p.add_argument("--port", type=int, default=7777)
    p.add_argument("--all-projects", action="store_true")
    p.add_argument("--no-open", action="store_true")

    command("projects")
    return parser


def join_offsets(argv):
    out = []
    for arg in argv:
        if out and out[-1] in DATE_FLAGS and re.fullmatch(r"-\d+[dw]", arg):
            out[-1] += "=" + arg
        else:
            out.append(arg)
    return out


def main(argv=None):
    argv = join_offsets(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv, argparse.Namespace(db=None, project=None, json=False, brief=False))
    args.json = args.json or args.brief
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
