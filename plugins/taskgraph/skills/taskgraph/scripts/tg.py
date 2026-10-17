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
CREATE TABLE IF NOT EXISTS baselines (
  project TEXT NOT NULL,
  label TEXT NOT NULL,
  at TEXT NOT NULL,
  task_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  type TEXT NOT NULL,
  start TEXT,
  due TEXT,
  PRIMARY KEY (project, label, task_id)
);
"""

FILTERS = ("open", "in_progress", "done", "ready", "blocked")
NODE_FIELDS = (
    "id", "title", "status", "derived_status", "project", "notes", "meta", "depends_on", "blocks", "created_at", "done_at",
    "type", "parent", "children", "rollup", "late_days", "chase_due", "start", "due", "span", "conflicts", "outlook", "threats",
)
TYPES = ("task", "milestone", "decision", "external", "objective", "risk", "issue")
PARENT_TYPES = ("task", "objective")
DATE_KEYS = ("date", "decide_by", "needed_by", "chase", "due", "start", "promised", "review", "raised")
DUE_KEYS = {"task": "due", "objective": "due", "milestone": "date", "decision": "decide_by", "external": "needed_by", "risk": "review", "issue": "due"}
POINTS = ("milestone", "decision", "risk")
DATE_FLAGS = ("--start", "--due", "--promised", "--due-before", "--since", "--from")
PERSON_KEYS = {"decision": "decider", "external": "party"}
INHERITED = ("lane", "team")
SORTS = ("id", "due", "late")
DATE_FIELDS = ("due", "start", "promised")
SCOPE_FIELDS = ("title", "type", "parent", "depends_on", "meta.owner", "meta.decider", "meta.party", "meta.lane", "meta.team")
RAG = ("green", "amber", "red")
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
LEVELS = {"low": 1, "medium": 2, "high": 3}
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


def effective_deps(tasks, task, kind=None):
    deps = set(task["depends_on"])
    for a in ancestors(tasks, task["id"]):
        deps.update(tasks[a]["depends_on"])
    return sorted(d for d in deps if (tasks[d]["type"] == "risk") == (kind == "risk"))


def blocking(tasks, ids):
    return [d for d in ids if tasks[d]["type"] != "risk"]


def inherited(tasks, task, key):
    for t in [task, *(tasks[a] for a in ancestors(tasks, task["id"]))]:
        value = t["meta"].get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def due_word(task):
    return "review" if task["type"] == "risk" else "due"


def person(task):
    return task["meta"].get(PERSON_KEYS.get(task["type"], "owner"))


def is_summary(task):
    return bool(task["parts"]) or task["type"] == "objective"


def computed(task):
    return is_summary(task) or task["type"] == "milestone"


def node_status(task, deps, current):
    deps_done = [current[d] == "done" for d in deps]
    if task["type"] == "milestone":
        return "done" if deps_done and all(deps_done) else "blocked"
    if is_summary(task):
        kids = [current[c] for c in task["parts"]]
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
        task["parts"] = [c for c in task["children"] if tasks[c]["type"] != "risk"]
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
        task["waits_for"] = effective[task["id"]]
        deps = blocking(tasks, task["depends_on"]) if computed(task) and task["type"] != "milestone" else effective[task["id"]]
        task["blocked_by"] = sum(current[d] != "done" for d in deps)
        if is_summary(task):
            leaves = [d for d in descendants(tasks, task["id"]) if not is_summary(tasks[d]) and tasks[d]["type"] != "risk"]
            task["rollup"] = {"done": sum(current[d] == "done" for d in leaves), "total": len(leaves)}
        else:
            task["rollup"] = None
        unfinished = current[task["id"]] != "done"
        due = parse_date(task["due"])
        task["late_days"] = (day - due).days if due and due < day and unfinished and task["type"] not in ("objective", "risk") else None
        chase = parse_date(task["meta"].get("chase")) if task["type"] == "external" else None
        task["chase_due"] = bool(chase and chase <= day and unfinished)
        task["span"] = span(tasks, task) if is_summary(task) else None
        task["threats"] = [r for r in effective_deps(tasks, task, "risk") if current[r] != "done"]
    finish_derived(tasks, effective, current)
    find_conflicts(tasks, effective, current)
    for task in tasks.values():
        task["outlook"] = outlook(tasks, task["id"]) if task["type"] in ("milestone", "objective") else None
    return tasks


def hops_into(tasks, task):
    found = []
    need = task["start"] or task["due"]
    for d in task["waits_for"]:
        found.append((d, need, "dependency"))
    if is_summary(task):
        found += [(c, task["due"], "child") for c in task["parts"]]
    return [(d, n, k) for d, n, k in found if tasks[d]["derived_status"] != "done"]


def upstream(tasks, root):
    hops, seen, queue = [], {root}, [root]
    while queue:
        task = tasks[queue.pop(0)]
        for d, need, kind in hops_into(tasks, task):
            dep = tasks[d]
            due = dep["due"] or (dep["span"] or {}).get("end")
            hops.append({"from": d, "to": task["id"], "kind": kind, "due": due, "need": need,
                         "slack": days_between(due, need), "status": dep["derived_status"], "late_days": dep["late_days"]})
            if d not in seen:
                seen.add(d)
                queue.append(d)
    return hops


def outlook(tasks, root, hops=None):
    hops = upstream(tasks, root) if hops is None else hops
    above = {h["from"] for h in hops}
    slacks = [h["slack"] for h in hops if h["slack"] is not None]
    late = sorted(i for i in above if tasks[i]["late_days"])
    negative = sum(s < 0 for s in slacks)
    undated = sorted(i for i in above if not tasks[i]["due"] and not is_summary(tasks[i]))
    risks = sorted({r for i in above | {root} for r in tasks[i]["threats"]})
    if negative or late or tasks[root]["late_days"]:
        verdict = "at_risk"
    elif not slacks:
        verdict = "unknown" if hops else "on_track"
    else:
        verdict = "on_track"
    return {"verdict": verdict, "min_slack": min(slacks, default=None), "negative_slack": negative, "late_upstream": late, "undated": undated,
            "open_risks": risks, "driving": driving(tasks, root, hops)}


def driving(tasks, root, hops):
    into, memo, never = {}, {}, float("inf")
    for h in hops:
        into.setdefault(h["to"], []).append(h)

    def worst(node):
        if node not in memo:
            options = []
            for h in into.get(node, []):
                low, chain = worst(h["from"])
                options.append((min(low, never if h["slack"] is None else h["slack"]), h["from"], chain))
            low, _, chain = min(options, key=lambda o: o[:2]) if options else (never, None, [])
            memo[node] = (low, chain + [node])
        return memo[node]

    return worst(root)[1]


def plural(n, one, many=None):
    return f"{n} {one if n == 1 else many or one + 's'}"


def outlook_text(o):
    if o["verdict"] == "on_track":
        return "on track" + (f" — min slack {o['min_slack']:+d}d" if o["min_slack"] is not None else "")
    if o["verdict"] == "unknown":
        return "unknown — nothing upstream has a date"
    parts = []
    if o["late_upstream"]:
        parts.append(f"{len(o['late_upstream'])} late upstream ({', '.join(f'#{i}' for i in o['late_upstream'])})")
    if o["negative_slack"]:
        parts.append(plural(o["negative_slack"], "hop", "hops") + " with negative slack")
    if o["min_slack"] is not None:
        parts.append(f"min slack {o['min_slack']:+d}d")
    if o["open_risks"]:
        parts.append(plural(len(o["open_risks"]), "open risk"))
    return "at risk — " + (", ".join(parts) or "itself late")


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
                below = effective[i] if task["type"] == "milestone" else task["parts"] + blocking(tasks, task["depends_on"])
                memo[i] = max(filter(None, map(finished, below)), default=None)
        return memo[i]

    for task in tasks.values():
        if computed(task):
            task["done_at"] = finished(task["id"])


def normal(value):
    return value if parse_date(value) else None


def span(tasks, task):
    below = [tasks[d] for d in descendants(tasks, task["id"]) if tasks[d]["type"] != "risk"]
    starts = [t["start"] or t["due"] for t in below if t["start"] or t["due"]]
    ends = [t["due"] or t["start"] for t in below if t["start"] or t["due"]]
    return {"start": min(starts), "end": max(ends)} if starts else None


def find_conflicts(tasks, effective, current):
    def flag(kind, late, needer, due, need, message):
        found = {"kind": kind, "from": late, "to": needer, "due": due, "need": need, "gap": days_between(due, need), "message": message}
        tasks[late]["conflicts"].append(dict(found, **{"with": needer}))
        if needer is not None:
            tasks[needer]["conflicts"].append(dict(found, **{"with": late}))

    for n in tasks.values():
        need = n["start"] or n["due"]
        for d in effective[n["id"]] if need else []:
            dep = tasks[d]
            if dep["due"] and dep["due"] > need and current[d] != "done":
                flag("dependency", d, n["id"], dep["due"], need, f"#{d} due {dep['due']} after #{n['id']} needs it {need}")
        parent = tasks[n["parent"]] if n["parent"] is not None else None
        if parent and parent["due"] and n["due"] and n["due"] > parent["due"] and n["type"] != "risk":
            found = {"kind": "parent", "from": n["id"], "to": parent["id"], "due": n["due"], "need": parent["due"], "gap": days_between(n["due"], parent["due"])}
            n["conflicts"].append(dict(found, **{"with": parent["id"], "message": f"#{n['id']} due {n['due']} after parent #{parent['id']} due {parent['due']}"}))
        promised = normal(n["meta"].get("promised")) if n["type"] == "external" else None
        if promised and n["due"] and promised > n["due"]:
            flag("promised", n["id"], None, promised, n["due"], f"#{n['id']} promised {promised} after needed {n['due']}")


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
    details = [f"{due_word(task)} {task['due']}" if task["due"] else None, person(task), task["lane"]]
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
        found = {d: "" for d in blocking(tasks, task["depends_on"])}
        for a in ancestors(tasks, task["id"]):
            for d in blocking(tasks, tasks[a]["depends_on"]):
                found.setdefault(d, f" (dependency of ancestor #{a})")
        edges[task["id"]] = [(d, found[d]) for d in sorted(found)]
        if is_summary(task):
            edges[task["id"]] += [(c, " (its child)") for c in task["parts"]]
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
    if tasks[task_id]["project"] != tasks[dep_id]["project"] and tasks[dep_id]["type"] != "milestone":
        raise Fail(f"#{task_id} is in project {tasks[task_id]['project']} and #{dep_id} in {tasks[dep_id]['project']}; dependencies cannot cross projects except on another project's milestone")
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
            if tasks[dep]["project"] != task["project"] and tasks[dep]["type"] != "milestone":
                raise Fail(f"#{task['id']} in project {task['project']} depends on #{dep} in {tasks[dep]['project']}, which must stay a milestone")
            if dep in ancestors(tasks, task["id"]) or task["id"] in ancestors(tasks, dep):
                raise Fail(f"#{task['id']} depends on #{dep}, which would be its ancestor or descendant")
    check_deadlock(conn)


def next_id(conn):
    sql = "SELECT MAX(i) FROM (SELECT MAX(id) AS i FROM tasks UNION ALL SELECT MAX(task_id) FROM events UNION ALL SELECT MAX(task_id) FROM baselines)"
    return (conn.execute(sql).fetchone()[0] or 0) + 1


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
        task_id = next_id(conn)
        conn.execute(
            "INSERT INTO tasks (id, project, title, notes, meta, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task_id, args.project, args.title, args.notes, json.dumps(meta), ts, ts),
        )
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
    args.type = [t for t in TYPES if t != "risk"]
    args.parent = args.search = args.owner = args.lane = args.team = args.due_before = None
    args.meta = []
    args.sort = "id"
    cmd_ls(conn, args)


def cmd_show(conn, args):
    tasks = load(conn)
    task = get(tasks, args.id)

    def ref(i):
        return {k: tasks[i][k] for k in ("id", "title", "status", "derived_status")}

    base = latest_baselines(conn, [task["project"]]).get(task["id"])
    data = dict(task, depends_on=[ref(i) for i in task["depends_on"]], blocks=[ref(i) for i in task["blocks"]], baseline=base)
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
    if base and (base["due"] or task["due"]) and base["due"] != task["due"]:
        delta = days_between(base["due"], task["due"])
        out.append(f"baseline: due {base['due'] or '-'} ({base['label']})" + (f", now {delta:+d}d" if delta is not None else ""))
    if task["late_days"]:
        out.append(f"late:    {task['late_days']}d")
    if task["outlook"] and task["derived_status"] != "done":
        out.append(f"outlook: {outlook_text(task['outlook'])} (path {task['id']} for detail)")
    if task["chase_due"]:
        out.append("chase:   due")
    if task["threats"]:
        out.append("threatened by: " + ", ".join(f"#{r} {tasks[r]['title']}" for r in task["threats"]))
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


def cmd_path(conn, args):
    tasks = load(conn)
    root = get(tasks, args.id)
    hops = upstream(tasks, root["id"])
    o = outlook(tasks, root["id"], hops)
    chain = o["driving"]
    into = {}
    for h in hops:
        into.setdefault(h["to"], []).append(h)
    head = f"#{root['id']} {marker(root)}{root['title']}" + (f" — due {root['due']}" if root["due"] else "")
    out, seen = [head], {root["id"]}

    def walk(node, depth):
        for h in sorted(into.get(node, []), key=lambda h: (h["slack"] if h["slack"] is not None else float("inf"), h["from"])):
            dep = tasks[h["from"]]
            parts = [f"due {h['due']}" if h["due"] else "no due date"]
            if h["need"]:
                parts.append(f"needed {h['need']}")
            if h["slack"] is not None:
                parts.append(f"slack {h['slack']:+d}d")
            if dep["late_days"]:
                parts.append(f"late {dep['late_days']}d")
            part = "(part of) " if h["kind"] == "child" else ""
            again = " (see above)" if h["from"] in seen else ""
            out.append(f"{'  ' * depth}{part}#{dep['id']} {marker(dep)}{dep['title']} [{dep['derived_status']}] — " + " · ".join(parts) + again)
            if not again:
                seen.add(h["from"])
                walk(h["from"], depth + 1)

    walk(root["id"], 1)
    if len(chain) > 1:
        out.append("driving: " + " → ".join(f"#{i}" for i in chain))
    out.append("verdict: " + outlook_text(o))
    emit(args, {"id": root["id"], "due": root["due"], "hops": hops, "driving": chain, **o}, "\n".join(out))


def cmd_deps(conn, args):
    tasks = load(conn)
    rows = []
    for t in scoped(tasks, args):
        need = t["start"] or t["due"]
        for d in blocking(tasks, t["depends_on"]):
            dep = tasks[d]
            if args.open and dep["derived_status"] == "done":
                continue
            if args.cross:
                side = (lambda x: (person(x) if args.cross == "owner" else x[args.cross]) or "Unassigned")
                if str(side(dep)).lower() == str(side(t)).lower():
                    continue
            rows.append((dep, t, days_between(dep["due"], need)))
    rows.sort(key=lambda r: (r[2] if r[2] is not None else float("inf"), r[0]["id"], r[1]["id"]))
    data = [{"from": who(d), "to": who(t), "due": d["due"], "need": t["start"] or t["due"], "slack": slack} for d, t, slack in rows]
    text = [f"{who_text(d, True)} → {who_text(t, True)}" + (f" · slack {slack:+d}d" if slack is not None else "") for d, t, slack in rows]
    emit(args, data, "\n".join(text) or "no dependencies")


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


def who(task):
    return {"id": task["id"], "title": task["title"], "type": task["type"], "derived_status": task["derived_status"],
            "person": person(task), "lane": task["lane"], "team": task["team"]}


def who_text(task, status=False):
    tags = " · ".join(str(x) for x in (person(task), task["lane"]) if x)
    return f"#{task['id']} {marker(task)}{task['title']}" + (f" [{task['derived_status']}]" if status else "") + (f" ({tags})" if tags else "")


def conflict_items(tasks, items):
    shown, found = {t["id"] for t in items}, {}
    for t in items:
        for c in t["conflicts"]:
            key = (c["kind"], c["from"], c["to"])
            if key not in found and (c["from"] in shown or c["to"] in shown):
                found[key] = c
    rows = sorted(found.values(), key=lambda c: (c["gap"], c["from"], c["to"] or 0))
    data = [{"kind": c["kind"], "from": who(tasks[c["from"]]), "to": who(tasks[c["to"]]) if c["to"] else None,
             "due": c["due"], "need": c["need"], "gap": c["gap"], "message": c["message"]} for c in rows]
    words = {"dependency": ("due", "needed"), "parent": ("due", "parent due"), "promised": ("promised", "needed")}
    text = []
    for c in rows:
        left = who_text(tasks[c["from"]]) + (f" → {who_text(tasks[c['to']])}" if c["to"] else "")
        due_word, need_word = words[c["kind"]]
        text.append(f"{left}: {due_word} {c['due']}, {need_word} {c['need']}, gap {c['gap']:+d}d")
    return data, text


def agenda_line(task, note):
    person = task["meta"].get({"decision": "decider", "external": "party"}.get(task["type"], "owner"))
    parts = [f"{due_word(task)} {task['due']}" if task["due"] else f"no {due_word(task)} date"]
    parts += [x for x in (person, note) if x]
    return f"#{task['id']} {marker(task)}{task['title']} — " + " · ".join(parts)


def cmd_agenda(conn, args):
    day = today()
    limit = (day + timedelta(days=args.within)).isoformat()
    tasks = load(conn)
    items = [t for t in scoped(tasks, args) if t["derived_status"] != "done" and (not args.type or t["type"] in args.type)]
    by_due = lambda t: (t["due"] or "9999-12-31", t["id"])
    buckets = {
        "late": sorted((t for t in items if t["late_days"]), key=lambda t: (-t["late_days"], t["id"])),
        "at_risk": sorted((t for t in items if t["outlook"] and t["outlook"]["verdict"] == "at_risk"), key=by_due),
        "late_start": sorted((t for t in items if t["status"] == "open" and not computed(t) and t["start"] and t["start"] < day.isoformat()), key=lambda t: (t["start"], t["id"])),
        "conflicts": sorted((t for t in items if t["conflicts"]), key=by_due),
        "due_soon": sorted((t for t in items if t["due"] and day.isoformat() <= t["due"] <= limit), key=by_due),
        "chase_due": sorted((t for t in items if t["chase_due"]), key=lambda t: (t["meta"]["chase"], t["id"])),
        "review_due": sorted((t for t in items if t["type"] == "risk" and t["due"] and t["due"] <= day.isoformat()), key=by_due),
        "missing_date": [t for t in items if t["type"] in ("decision", "external", "risk", "issue") and not t["due"]],
    }
    notes = {
        "late": lambda t: f"late {t['late_days']}d",
        "at_risk": lambda t: outlook_text(t["outlook"]).removeprefix("at risk — "),
        "late_start": lambda t: f"start {t['start']}, still {t['derived_status']}",
        "due_soon": lambda t: None,
        "chase_due": lambda t: f"chase {t['meta']['chase']}",
        "review_due": lambda t: "/".join(str(t["meta"][k]) for k in ("likelihood", "impact") if t["meta"].get(k)) or None,
        "missing_date": lambda t: None,
    }
    headings = {"late": "Late", "at_risk": "At risk", "late_start": "Should have started", "conflicts": "Conflicts", "due_soon": f"Due in {args.within} days", "chase_due": "Chase due", "review_due": "Risk review due", "missing_date": "Missing date"}
    conflict_data, conflict_text = conflict_items(tasks, buckets["conflicts"])
    out = []
    for name, found in buckets.items():
        lines = conflict_text if name == "conflicts" else [agenda_line(t, notes[name](t)) for t in found]
        if lines:
            out += [headings[name], *(f"  {l}" for l in lines), ""]
    data = {name: [dict(brief_task(t), outlook=t["outlook"]) if name == "at_risk" else brief_task(t) for t in found] for name, found in buckets.items()}
    data["conflicts"] = conflict_data
    emit(args, data, "\n".join(out).rstrip() or "nothing needs attention")


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
    found, text = collect_changes(conn, load(conn), args, since)
    out = [f"Changes since {since}"]
    for name, heading in CHANGE_BUCKETS.items():
        if text[name]:
            out += ["", heading, *(f"  {t}" for t in text[name])]
    emit(args, {"since": since, **found}, "\n".join(out) if len(out) > 1 else f"no changes since {since}")


def collect_changes(conn, tasks, args, since):
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
    return found, text


def baseline_labels(conn, project):
    sql = "SELECT label, MIN(at) AS at, COUNT(*) AS tasks FROM baselines WHERE project=? GROUP BY label ORDER BY at, label"
    return [dict(r) for r in conn.execute(sql, (project,))]


def baseline_rows(conn, project, label=None):
    labels = baseline_labels(conn, project)
    if label is None:
        if not labels:
            return None, {}
        label = labels[-1]["label"]
    elif label not in {l["label"] for l in labels}:
        raise Fail(f"no baseline {label!r} in project {project}")
    rows = conn.execute("SELECT * FROM baselines WHERE project=? AND label=?", (project, label))
    return label, {r["task_id"]: dict(r) for r in rows}


def latest_baselines(conn, projects):
    found = {}
    for project in projects:
        label, rows = baseline_rows(conn, project)
        found.update({i: {"label": label, "start": r["start"], "due": r["due"]} for i, r in rows.items()})
    return found


def days_between(old, new):
    return (date.fromisoformat(new) - date.fromisoformat(old)).days if old and new else None


def cmd_baseline_set(conn, args):
    label = args.label or today().isoformat()
    tasks = [t for t in load(conn).values() if t["project"] == args.project]
    if not tasks:
        raise Fail(f"project {args.project} has no tasks to baseline")
    with conn:
        if any(l["label"] == label for l in baseline_labels(conn, args.project)):
            if not args.replace:
                raise Fail(f"baseline {label!r} exists; pass --replace or choose another --label")
            conn.execute("DELETE FROM baselines WHERE project=? AND label=?", (args.project, label))
        ts = now()
        conn.executemany(
            "INSERT INTO baselines (project, label, at, task_id, title, type, start, due) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(args.project, label, ts, t["id"], t["title"], t["type"], t["start"], t["due"]) for t in tasks],
        )
    emit(args, {"label": label, "at": ts, "tasks": len(tasks)}, f"baseline {label!r}: {len(tasks)} tasks")


def cmd_baseline_ls(conn, args):
    labels = baseline_labels(conn, args.project)
    emit(args, labels, "\n".join(f"{l['label']:<24} {l['at'][:10]}  {l['tasks']} tasks" for l in labels) or "no baselines")


def cmd_baseline_rm(conn, args):
    with conn:
        cur = conn.execute("DELETE FROM baselines WHERE project=? AND label=?", (args.project, args.label))
    if cur.rowcount == 0:
        raise Fail(f"no baseline {args.label!r} in project {args.project}")
    emit(args, {"removed": args.label}, f"removed baseline {args.label!r}")


def cmd_baseline_diff(conn, args):
    label, base = baseline_rows(conn, args.project, args.label)
    if label is None:
        raise Fail(f"project {args.project} has no baseline; run baseline set first")
    at = next(l["at"] for l in baseline_labels(conn, args.project) if l["label"] == label)
    tasks = {i: t for i, t in load(conn).items() if t["project"] == args.project}
    moved, lanes = [], {}
    for i, t in tasks.items():
        if i not in base:
            continue
        for field in ("due", "start"):
            old, new = base[i][field], t[field]
            if old == new:
                continue
            days = days_between(old, new)
            moved.append(dict(brief_task(t), field=field, baseline=old, now=new, days=days))
            if field == "due" and days:
                lane = lanes.setdefault(t["lane"] or "Unassigned", {"lane": t["lane"] or "Unassigned", "later": 0, "earlier": 0, "max_days": 0})
                lane["later" if days > 0 else "earlier"] += 1
                lane["max_days"] = max(lane["max_days"], days)
    moved.sort(key=lambda m: (m["type"] != "milestone", m["field"] != "due", -(m["days"] or 0), m["id"]))
    added = [brief_task(t) for i, t in tasks.items() if i not in base]
    removed = [{"id": i, "title": r["title"], "type": r["type"]} for i, r in sorted(base.items()) if i not in tasks]
    lane_rows = sorted(lanes.values(), key=lambda l: (l["lane"] == "Unassigned", l["lane"].lower()))

    def shift(m):
        delta = f" ({m['days']:+d}d)" if m["days"] is not None else ""
        return f"#{m['id']} {'[milestone] ' if m['type'] == 'milestone' else ''}{m['title']} — {m['field']} {m['baseline'] or '-'} → {m['now'] or '-'}{delta}"

    out = [f"Baseline {label!r} (set {at[:10]}) vs now"]
    if moved:
        out += ["", "Moved", *(f"  {shift(m)}" for m in moved)]
    if added:
        out += ["", "Added since baseline", *(f"  #{t['id']} {t['title']}" for t in added)]
    if removed:
        out += ["", "Removed since baseline", *(f"  #{t['id']} {t['title']}" for t in removed)]
    if lane_rows:
        out += ["", "By lane", *(f"  {l['lane']}: {l['later']} later (max {l['max_days']:+d}d), {l['earlier']} earlier" for l in lane_rows)]
    if len(out) == 1:
        out.append("no changes")
    emit(args, {"label": label, "at": at, "moved": moved, "added": added, "removed": removed, "lanes": lane_rows}, "\n".join(out))


def level(value):
    if isinstance(value, (int, float)):
        return value
    return LEVELS.get(str(value).strip().lower(), 0) if value is not None else 0


def risk_score(task):
    return level(task["meta"].get("likelihood")) * level(task["meta"].get("impact"))


def worst(rags):
    return max(rags, key=RAG.index, default="green")


def group_name(task, by):
    value = person(task) if by == "owner" else task["project"] if by == "project" else task[by]
    return str(value) if value else "Unassigned"


def group_status(tasks, items, day, limit):
    red, amber = [], []
    for t in items:
        if t["derived_status"] == "done":
            continue
        ref = f"#{t['id']} {t['title']}"
        if t["late_days"]:
            red.append(f"{ref} late {t['late_days']}d")
        if t["outlook"] and t["outlook"]["verdict"] == "at_risk":
            red.append(f"{ref} at risk")
        if t["type"] == "issue" and level(t["meta"].get("severity")) >= 3:
            red.append(f"{ref} high-severity issue open")
        if t["conflicts"]:
            amber.append(f"{ref} date conflict")
        if t["due"] and day <= t["due"] <= limit and t["derived_status"] == "blocked":
            amber.append(f"{ref} due {t['due']} and still blocked")
        if t["status"] == "open" and not computed(t) and t["start"] and t["start"] < day:
            amber.append(f"{ref} should have started {t['start']}")
        if t["chase_due"]:
            amber.append(f"{ref} chase due")
        if t["type"] == "risk" and (risk_score(t) >= 9 or (t["due"] and t["due"] <= day)):
            amber.append(f"{ref} " + ("high/high risk open" if risk_score(t) >= 9 else "risk review due"))
        if t["type"] == "issue" and level(t["meta"].get("severity")) < 3:
            amber.append(f"{ref} issue open")
    return ("red" if red else "amber" if amber else "green"), red + amber


def node_rag(tasks, task, day, limit):
    if not is_summary(task):
        return group_status(tasks, [task], day, limit)[0]
    below = [tasks[d] for d in descendants(tasks, task["id"]) if not is_summary(tasks[d])]
    return group_status(tasks, below + ([task] if task["outlook"] else []), day, limit)[0]


def asks_for(tasks, day, limit):
    asks = []
    for t in tasks:
        if t["derived_status"] == "done":
            continue
        who_ = person(t)
        tag = f" ({who_})" if who_ else ""
        if t["type"] == "decision" and (not t["due"] or t["late_days"] or t["due"] <= limit):
            when = f"by {t['due']}" + (f", {t['late_days']}d late" if t["late_days"] else "") if t["due"] else "no decide-by date"
            asks.append({"kind": "decide", "id": t["id"], "text": f"Decide #{t['id']} {t['title']}{tag}: {when}"})
        if t["type"] == "external":
            promised = normal(t["meta"].get("promised"))
            why = [f"late {t['late_days']}d" if t["late_days"] else None, "chase due" if t["chase_due"] else None,
                   f"promised {promised} after needed {t['due']}" if promised and t["due"] and promised > t["due"] else None]
            if any(why):
                asks.append({"kind": "chase", "id": t["id"], "text": f"Chase #{t['id']} {t['title']}{tag}: " + ", ".join(w for w in why if w)})
        if t["type"] == "issue":
            sev = t["meta"].get("severity")
            asks.append({"kind": "resolve", "id": t["id"], "text": f"Resolve #{t['id']} {t['title']}{tag}" + (f": severity {sev}" if sev else "") + (f", due {t['due']}" if t["due"] else "")})
    return asks


def cmd_report(conn, args):
    day = today().isoformat()
    limit = (today() + timedelta(days=args.within)).isoformat()
    since = resolve_since(args.since)
    tasks = load(conn)
    scope = scoped(tasks, args)
    base = latest_baselines(conn, {t["project"] for t in scope})
    found, _ = collect_changes(conn, tasks, args, since)
    counts = {name: len(found[name]) for name in CHANGE_BUCKETS}
    slips = [c["days"] for c in found["slipped"] if c["field"] == "due"]

    milestones = []
    for t in sorted((t for t in scope if t["type"] == "milestone" and t["derived_status"] != "done"), key=lambda t: (t["due"] or "9999-12-31", t["id"])):
        o = t["outlook"]
        rag = "red" if o["verdict"] == "at_risk" else "amber" if o["verdict"] == "unknown" or not t["due"] else "green"
        b = base.get(t["id"])
        drift = days_between(b["due"], t["due"]) if b else None
        milestones.append(dict(brief_task(t), rag=rag, outlook=o, baseline_days=drift))

    groups = {}
    for t in scope:
        if not is_summary(t):
            groups.setdefault(group_name(t, args.by), []).append(t)
    rows = []
    for name, items in groups.items():
        rag, reasons = group_status(tasks, items, day, limit)
        leaves = [t for t in items if t["type"] not in ("milestone", "risk")]
        upcoming = sorted((t for t in items if t["derived_status"] != "done" and t["due"] and t["type"] != "risk"),
                          key=lambda t: (t["type"] != "milestone", t["due"], t["id"]))
        nxt = upcoming[0] if upcoming else None
        rows.append({
            "name": name, "rag": rag, "reasons": reasons,
            "rollup": {"done": sum(t["derived_status"] == "done" for t in leaves), "total": len(leaves)},
            "late": sum(bool(t["late_days"]) for t in items if t["derived_status"] != "done"),
            "conflicts": sum(bool(t["conflicts"]) for t in items if t["derived_status"] != "done"),
            "next": {"id": nxt["id"], "title": nxt["title"], "type": nxt["type"], "due": nxt["due"]} if nxt else None,
        })
    rows.sort(key=lambda r: (-RAG.index(r["rag"]), r["name"] == "Unassigned", r["name"].lower()))

    open_ = [t for t in scope if t["derived_status"] != "done"]
    by_due = lambda t: (t["due"] or "9999-12-31", t["id"])
    decisions = [dict(brief_task(t), decider=t["meta"].get("decider")) for t in sorted((t for t in open_ if t["type"] == "decision"), key=by_due)]
    externals = [dict(brief_task(t), party=t["meta"].get("party"), promised=normal(t["meta"].get("promised")), chase=t["meta"].get("chase"), chase_due=t["chase_due"])
                 for t in sorted((t for t in open_ if t["type"] == "external"), key=by_due)]
    risks = [dict(brief_task(t), owner=t["meta"].get("owner"), likelihood=t["meta"].get("likelihood"), impact=t["meta"].get("impact"),
                  mitigation=t["meta"].get("mitigation"), score=risk_score(t))
             for t in sorted((t for t in open_ if t["type"] == "risk"), key=lambda t: (-risk_score(t), t["due"] or "9999-12-31", t["id"]))][:args.risks]
    issues = [dict(brief_task(t), owner=t["meta"].get("owner"), severity=t["meta"].get("severity"))
              for t in sorted((t for t in open_ if t["type"] == "issue"), key=lambda t: (-level(t["meta"].get("severity")), *by_due(t)))]
    asks = asks_for(sorted(open_, key=by_due), day, limit)
    overall = worst([m["rag"] for m in milestones] + [r["rag"] for r in rows])
    title = "all projects" if args.all_projects else args.project
    data = {"scope": title, "date": day, "overall": overall, "since": since, "changes": counts, "max_slip": max(slips, default=None),
            "milestones": milestones, "by": args.by, "groups": rows, "decisions": decisions, "externals": externals,
            "risks": risks, "issues": issues, "asks": asks}
    emit(args, data, report_md(data) if args.md else report_text(data))


def change_line(data):
    c = data["changes"]
    slip = f" (max +{data['max_slip']}d)" if data["max_slip"] else ""
    return (f"Since {data['since']}: {c['new']} new · {c['completed']} completed · {c['slipped']} slipped{slip} · "
            f"{c['pulled_in']} pulled in · {c['rescoped']} re-scoped · {c['removed']} removed")


def milestone_note(m):
    drift = f" · baseline {m['baseline_days']:+d}d" if m["baseline_days"] else ""
    return outlook_text(m["outlook"]) + drift


def next_text(n):
    return f"next #{n['id']} {n['title']} {n['due']}" if n else "nothing dated ahead"


def report_text(d):
    out = [f"Status: {d['scope']} — {d['date']} — overall {d['overall'].upper()}", change_line(d)]
    if d["milestones"]:
        out += ["", "Milestones", *(f"  {m['rag'].upper():<6} #{m['id']} {m['title']} — {m['due'] or 'no date'} — {milestone_note(m)}" for m in d["milestones"])]
    out += ["", {"lane": "Workstreams", "team": "Teams", "owner": "Owners", "project": "Projects"}[d["by"]]]
    for r in d["groups"]:
        progress = f"{r['rollup']['done']}/{r['rollup']['total']} done · " if r["rollup"]["total"] else ""
        out.append(f"  {r['rag'].upper():<6} {r['name']} — {progress}{r['late']} late · {plural(r['conflicts'], 'conflict')} · {next_text(r['next'])}")
        out += [f"           {why}" for why in r["reasons"]]
    sections = [
        ("Decisions pending", d["decisions"], lambda t: f"#{t['id']} {t['title']} — {t['decider'] or 'no decider'} — " + (f"by {t['due']}" if t["due"] else "no date")),
        ("Externals", d["externals"], lambda t: f"#{t['id']} {t['title']} — {t['party'] or 'no party'} — " + " · ".join(x for x in (
            t["due"] and f"needed {t['due']}", t["promised"] and f"promised {t['promised']}", t["chase"] and f"chase {t['chase']}") if x)),
        ("Top risks", d["risks"], lambda t: f"#{t['id']} {t['title']} — {t['likelihood'] or '?'}/{t['impact'] or '?'} — {t['owner'] or 'no owner'} — "
            + (f"review {t['due']}" if t["due"] else "no review date") + (f" — {t['mitigation']}" if t["mitigation"] else "")),
        ("Open issues", d["issues"], lambda t: f"#{t['id']} {t['title']} — {t['severity'] or '?'} — {t['owner'] or 'no owner'}" + (f" — due {t['due']}" if t["due"] else "")),
    ]
    for heading, items, fmt in sections:
        if items:
            out += ["", heading, *(f"  {fmt(t)}" for t in items)]
    out += ["", "Asks", *(f"  - {a['text']}" for a in d["asks"])] if d["asks"] else ["", "Asks", "  none"]
    return "\n".join(out)


def cell(value):
    return str(value if value not in (None, "") else "-").replace("|", "\\|").replace("\n", " ")


def table(head, rows):
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head), *("| " + " | ".join(cell(c) for c in r) + " |" for r in rows)]


def report_md(d):
    rag = lambda r: r.capitalize()
    out = [f"# Status: {d['scope']}, {d['date']}", "", f"**Overall: {rag(d['overall'])}**", "", change_line(d)]
    if d["milestones"]:
        out += ["", "## Milestones", "", *table(["RAG", "Milestone", "Date", "Outlook"],
                [(rag(m["rag"]), f"#{m['id']} {m['title']}", m["due"], milestone_note(m)) for m in d["milestones"]])]
    heading = {"lane": "Workstreams", "team": "Teams", "owner": "Owners", "project": "Projects"}[d["by"]]
    out += ["", f"## {heading}", "", *table(["RAG", heading[:-1], "Progress", "Late", "Conflicts", "Next", "Why"],
            [(rag(r["rag"]), r["name"], f"{r['rollup']['done']}/{r['rollup']['total']}" if r["rollup"]["total"] else None, r["late"], r["conflicts"],
              f"#{r['next']['id']} {r['next']['title']} {r['next']['due']}" if r["next"] else None, "; ".join(r["reasons"])) for r in d["groups"]])]
    if d["decisions"]:
        out += ["", "## Decisions pending", "", *table(["#", "Decision", "Decider", "By"], [(t["id"], t["title"], t["decider"], t["due"]) for t in d["decisions"]])]
    if d["externals"]:
        out += ["", "## Externals", "", *table(["#", "External", "Party", "Needed", "Promised", "Chase"],
                [(t["id"], t["title"], t["party"], t["due"], t["promised"], t["chase"]) for t in d["externals"]])]
    if d["risks"]:
        out += ["", "## Top risks", "", *table(["#", "Risk", "Likelihood", "Impact", "Owner", "Review", "Mitigation"],
                [(t["id"], t["title"], t["likelihood"], t["impact"], t["owner"], t["due"], t["mitigation"]) for t in d["risks"]])]
    if d["issues"]:
        out += ["", "## Open issues", "", *table(["#", "Issue", "Severity", "Owner", "Due"], [(t["id"], t["title"], t["severity"], t["owner"], t["due"]) for t in d["issues"]])]
    out += ["", "## Asks", "", *(f"- {a['text']}" for a in d["asks"])] if d["asks"] else ["", "## Asks", "", "None."]
    return "\n".join(out)


# Capacity: who is over-committed, week by week. Each open item's estimate (hours) is spread
# evenly over the working days (Mon-Fri) still ahead in its window: from its start, or the
# Monday of its due week when it has no start, to its due date, never before today. Work that
# is already late lands on today. Summaries, milestones, risks and externals carry no load of
# ours; an item with an estimate but no dates is unscheduled. The page's Load view uses the
# same rules.
LOAD_SKIP = ("milestone", "risk", "external")


def estimate_hours(task):
    raw = task["meta"].get("estimate")
    try:
        hours = float(str(raw).strip().removesuffix("h")) if raw is not None and raw != "" else None
    except ValueError:
        return None
    return hours if hours and hours > 0 else None


def working_days(first, last):
    days, d = [], first
    while d <= last:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def load_spread(task, day):
    """Hours per date for one item, and whether it is already late; None when unscheduled."""
    hours = estimate_hours(task)
    due, start = parse_date(task["due"]), parse_date(task["start"])
    if not due and not start:
        return None, False
    due = due or start + timedelta(days=4 - start.weekday() if start.weekday() < 5 else 0)
    start = start or due - timedelta(days=due.weekday())
    if due < day:
        return {day: hours}, True
    days = working_days(max(start, day), due) or [max(start, day)]
    return {d: hours / len(days) for d in days}, False


def load_items(tasks):
    return [t for t in tasks if t["derived_status"] != "done" and not is_summary(t) and t["type"] not in LOAD_SKIP]


def cmd_load(conn, args):
    day = today()
    tasks = load(conn)
    first = parse_date(resolve_date(args.start)) if args.start else day
    first -= timedelta(days=first.weekday())
    weeks = [first + timedelta(weeks=i) for i in range(args.weeks)]
    end = weeks[-1] + timedelta(days=7)
    this_week = day - timedelta(days=day.weekday())
    left = len(working_days(day, this_week + timedelta(days=4)))
    capacity = [round(args.week_hours * (left / 5 if w == this_week else 1 if w > this_week else 0), 1) for w in weeks]
    groups, cells, unestimated = {}, {}, []
    for t in load_items(scoped(tasks, args)):
        if estimate_hours(t) is None:
            unestimated.append(t["id"])
            continue
        name = group_name(t, args.by)
        g = groups.setdefault(name, {"name": name, "hours": [0.0] * len(weeks), "later": 0.0, "unscheduled": 0.0})
        spread, overdue = load_spread(t, day)
        if spread is None:
            g["unscheduled"] += estimate_hours(t)
            continue
        for d, h in spread.items():
            if d >= end:
                g["later"] += h
            elif d >= first:
                i = (d - first).days // 7
                g["hours"][i] += h
                cell = cells.setdefault((name, i), {}).setdefault(t["id"], {"id": t["id"], "title": t["title"], "hours": 0.0, "overdue": overdue})
                cell["hours"] += h
    rows = sorted(groups.values(), key=lambda g: (g["name"] == "Unassigned", g["name"].lower()))
    over = []
    for g in rows:
        g["over"] = [i for i, h in enumerate(g["hours"]) if round(h, 1) > capacity[i]]
        for i in g["over"]:
            items = sorted(cells[(g["name"], i)].values(), key=lambda c: (-c["hours"], c["id"]))
            over.append({"group": g["name"], "week": weeks[i].isoformat(), "hours": round(g["hours"][i], 1), "capacity": capacity[i],
                         "items": [dict(c, hours=round(c["hours"], 1)) for c in items]})
        g["hours"] = [round(h, 1) for h in g["hours"]]
        g["later"], g["unscheduled"] = round(g["later"], 1), round(g["unscheduled"], 1)
    data = {"by": args.by, "week_hours": args.week_hours, "today": day.isoformat(),
            "weeks": [{"start": w.isoformat(), "capacity": c} for w, c in zip(weeks, capacity)],
            "groups": rows, "over": over, "unestimated": sorted(unestimated)}
    emit(args, data, load_text(data))


def load_text(d):
    if not d["groups"]:
        return "no open items with an estimate" + (f" ({len(d['unestimated'])} open items have none)" if d["unestimated"] else "")
    md = lambda iso: f"{int(iso[8:])} {MONTH_NAMES[int(iso[5:7]) - 1]}"
    width = max(len(g["name"]) for g in d["groups"]) + 2
    partial = [w["capacity"] < d["week_hours"] for w in d["weeks"]]
    head = [md(w["start"]) + ("*" if p else "") for w, p in zip(d["weeks"], partial)] + ["later", "unsched"]
    out = [f"Load by {d['by']} · {d['week_hours']:g}h a week · weeks starting {md(d['weeks'][0]['start'])}",
           " " * width + "".join(f"{h:>8}" for h in head)]
    for g in d["groups"]:
        cells = [f"{h:g}" + ("!" if i in g["over"] else "") for i, h in enumerate(g["hours"])]
        out.append(f"{g['name']:<{width}}" + "".join(f"{c if c != '0' else '·':>8}" for c in [*cells, f"{g['later']:g}", f"{g['unscheduled']:g}"]))
    if any(partial):
        w = d["weeks"][partial.index(True)]
        out.append(f"* {md(w['start'])} counts only the working days left this week ({w['capacity']:g}h).")
    out.append("! over capacity")
    if d["over"]:
        out += ["", "Over-committed"]
        for o in d["over"]:
            top = ", ".join(f"#{c['id']} {c['title']} {c['hours']:g}h" + (" (late)" if c["overdue"] else "") for c in o["items"][:3])
            more = f", +{len(o['items']) - 3} more" if len(o["items"]) > 3 else ""
            out.append(f"  {o['group']} w/c {md(o['week'])}: {o['hours']:g}h of {o['capacity']:g}h — {top}{more}")
    if d["unestimated"]:
        ids = ", ".join(f"#{i}" for i in d["unestimated"][:12]) + (" …" if len(d["unestimated"]) > 12 else "")
        out += ["", f"No estimate: {len(d['unestimated'])} open items ({ids})"]
    return "\n".join(out)


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
    everything = load(conn)
    tasks = scoped(everything, args)
    ids = {t["id"] for t in tasks}
    base = latest_baselines(conn, {t["project"] for t in tasks})
    day, limit = today().isoformat(), (today() + timedelta(days=14)).isoformat()
    nodes = []
    for t in tasks:
        node = {k: t[k] for k in NODE_FIELDS}
        node["baseline"] = base.get(t["id"])
        node["rag"] = node_rag(everything, t, day, limit)
        node["depends_on"] = [i for i in t["depends_on"] if i in ids]
        node["blocks"] = [i for i in t["blocks"] if i in ids]
        node["parent"] = t["parent"] if t["parent"] in ids else None
        node["children"] = [i for i in t["children"] if i in ids]
        node["threats"] = [i for i in t["threats"] if i in ids]
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
    tasks = load(conn)
    day = today().isoformat()
    limit = (today() + timedelta(days=14)).isoformat()
    stats = {}
    for t in tasks.values():
        s = stats.setdefault(t["project"], {"project": t["project"], "total": 0, "done": 0, "in_progress": 0, "ready": 0, "blocked": 0})
        s["total"] += 1
        if t["derived_status"] in s:
            s[t["derived_status"]] += 1
    for name, s in stats.items():
        mine = [t for t in tasks.values() if t["project"] == name]
        open_ = [t for t in mine if t["derived_status"] != "done"]
        ahead = sorted((t for t in open_ if t["type"] == "milestone"), key=lambda t: (t["due"] or "9999-12-31", t["id"]))
        s["late"] = sum(bool(t["late_days"]) for t in open_)
        s["conflicts"] = sum(bool(t["conflicts"]) for t in open_)
        s["at_risk"] = sum(t["outlook"]["verdict"] == "at_risk" for t in ahead)
        s["next_milestone"] = {"id": ahead[0]["id"], "title": ahead[0]["title"], "due": ahead[0]["due"]} if ahead else None
        s["rag"] = group_status(tasks, [t for t in mine if not is_summary(t)], day, limit)[0]
    rows = sorted(stats.values(), key=lambda s: s["project"])

    def text(s):
        n = s["next_milestone"]
        nxt = f" · next #{n['id']} {n['title']} {n['due'] or 'no date'}" if n else ""
        return (f"{s['project']:<20} {s['rag'].upper():<6} total {s['total']:>3}  done {s['done']:>3}  ready {s['ready']:>3}  blocked {s['blocked']:>3}"
                f" · {s['late']} late · {plural(s['conflicts'], 'conflict')} · {s['at_risk']} at risk{nxt}")

    emit(args, rows, "\n".join(map(text, rows)))


COMMANDS = {
    "add": cmd_add,
    "dep add": cmd_dep_add,
    "dep rm": cmd_dep_rm,
    "baseline set": cmd_baseline_set,
    "baseline ls": cmd_baseline_ls,
    "baseline diff": cmd_baseline_diff,
    "baseline rm": cmd_baseline_rm,
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
    "path": cmd_path,
    "deps": cmd_deps,
    "report": cmd_report,
    "load": cmd_load,
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

    base = command("baseline")
    base_sub = base.add_subparsers(dest="baseline_command", required=True)
    p = command("set", base_sub)
    p.add_argument("--label")
    p.add_argument("--replace", action="store_true")
    command("ls", base_sub)
    p = command("diff", base_sub)
    p.add_argument("--label")
    p = command("rm", base_sub)
    p.add_argument("label")

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

    for name in ("show", "start", "done", "reopen", "rm", "why", "path"):
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

    p = command("deps")
    p.add_argument("--cross", choices=("lane", "team", "owner", "project"))
    p.add_argument("--open", action="store_true")
    p.add_argument("--all-projects", action="store_true")

    p = command("report")
    p.add_argument("--by", choices=("lane", "team", "owner", "project"), default="lane")
    p.add_argument("--within", type=int, default=14)
    p.add_argument("--since", default="7d")
    p.add_argument("--risks", type=int, default=5)
    p.add_argument("--md", action="store_true")
    p.add_argument("--all-projects", action="store_true")

    p = command("load")
    p.add_argument("--by", choices=("owner", "team", "lane"), default="owner")
    p.add_argument("--weeks", type=int, default=8)
    p.add_argument("--from", dest="start")
    p.add_argument("--week-hours", type=float, default=30)
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
    key = f"{args.command} {getattr(args, args.command + '_command')}" if args.command in ("dep", "baseline") else args.command
    try:
        COMMANDS[key](connect(args.db), args)
    except (Fail, sqlite3.Error) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
