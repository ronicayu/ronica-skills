from __future__ import annotations

import fcntl
import json
import os
import socket
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from tgstore import config as cfg
from tgstore.base import Capabilities, StoreError, now
from tgstore.changes import PRIORITIES, ChangeSet, changeset, event_rows
from tgstore.github import body as bodies
from tgstore.remote import KEEP, Create, Edit, Plan, SyncState, canon
from tgstore.sqlite import DB_TIMEOUT, SCHEMA

EXTRA = """
CREATE TABLE IF NOT EXISTS remote_tasks (
  task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
  node_id TEXT, db_id INTEGER, meta TEXT NOT NULL DEFAULT '{}', fingerprint TEXT
);
CREATE TABLE IF NOT EXISTS local_meta (task_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (task_id, key));
CREATE TABLE IF NOT EXISTS pending_meta (
  task_id INTEGER NOT NULL, key TEXT NOT NULL, op TEXT NOT NULL CHECK (op IN ('set','unset')), value TEXT, base TEXT, at TEXT NOT NULL,
  PRIMARY KEY (task_id, key)
);
CREATE TABLE IF NOT EXISTS claims (comment_id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, token TEXT, claimant TEXT, voids TEXT NOT NULL DEFAULT '[]', at TEXT);
CREATE TABLE IF NOT EXISTS sync_state (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS remote_conflicts (task_id INTEGER NOT NULL, source TEXT NOT NULL, message TEXT NOT NULL);
"""
PENDING_AGE = 900  # seconds before a full pull sends deferred rows by itself
PARENT_TYPES = ("task", "objective")
IN_PROGRESS = "tg:in-progress"
REMOVED = "tg:removed"


class TaskGone(StoreError):
    """A task that GitHub no longer has as a task: deleted, unlabelled, removed, or a pull request."""


def open_cache(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=DB_TIMEOUT)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    if "parent_id" not in {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}:
        with conn:
            conn.execute("ALTER TABLE tasks ADD COLUMN parent_id INTEGER REFERENCES tasks(id)")
    conn.executescript(EXTRA)
    return conn


def get_state(conn, key, default=None):
    row = conn.execute("SELECT value FROM sync_state WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def put_state(conn, key, value):
    conn.execute("INSERT INTO sync_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))


def ancestors(parents, n):
    found, seen = [], {n}
    while parents.get(n) is not None and parents[n] not in seen:
        n = parents[n]
        found.append(n)
        seen.add(n)
    return found


def meta_diff(before, after):
    keys = (before.keys() | after.keys()) - {"type", "priority"}  # both are labels, not meta
    return {k: (before.get(k, KEEP), after.get(k, KEEP)) for k in sorted(keys) if before.get(k, KEEP) != after.get(k, KEEP)}


class CachedRemoteStore:
    name = "github"
    caps = Capabilities(
        cross_project_deps=False, claim=True, history="cache", baselines="local", soft_delete=True,
        max_blockers=50, max_depth=8, max_children=100,
    )

    def __init__(self, remote, entry, load, project):
        self.remote, self.entry, self.load, self.project = remote, entry, load, project
        self.cache = cfg.cache_path(entry)
        self.conn = None
        self.idmap = {}
        self.before = None
        self.claimed = {}  # task id -> ClaimOutcome of this command
        self.warnings = []

    # -- opening and refreshing -------------------------------------------------------------------------------------

    def connect(self, *, fresh=False, mode="read"):
        # mode: "read" (refresh when older than cache_ttl), "write" (always refresh), "none" (result add, sync: no refresh here)
        conn = self.conn = open_cache(self.cache)
        if mode == "none":
            return conn
        last = get_state(conn, "last_pull_at")
        if last is None or mode == "write" or fresh or time.time() - last >= self.entry.cache_ttl:
            self.refresh(conn, wait=last is None or mode == "write" or fresh, recheck=not (mode == "write" or fresh or last is None))
        return conn

    @contextmanager
    def locked(self, wait):
        handle = open(f"{self.cache}.lock", "a+")
        deadline = time.monotonic() + DB_TIMEOUT
        try:
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if not wait:
                        yield False
                        return
                    if time.monotonic() > deadline:
                        raise StoreError("another tg is refreshing the cache and did not finish in 30 s")
                    time.sleep(0.05)
            yield True
        finally:
            handle.close()

    def ensure(self, conn, ids):
        """Tasks that a command names but the cache lacks: a list page can lag behind a new issue, a single issue does not."""
        from tgstore.github.gh import HttpError

        for i in sorted({i for i in ids if i > 0}):
            if conn.execute("SELECT 1 FROM tasks WHERE id=?", (i,)).fetchone() is not None:
                continue
            try:
                task = self.remote.fetch(i)
            except HttpError as e:
                if e.status == 404:
                    continue
                raise
            if self.entry.label in task.labels and not task.removed and not task.item.get("pull_request"):
                with self.locked(True):
                    self.apply(conn, self.remote.single(task), self.sync_state(conn), first=False)

    def sync_state(self, conn):
        state = SyncState(pages={int(k): v for k, v in get_state(conn, "pages", {}).items()}, removed=set(get_state(conn, "removed", [])), comments_etag=get_state(conn, "comments_etag"))
        for task_id, fp in conn.execute("SELECT task_id, fingerprint FROM remote_tasks WHERE fingerprint IS NOT NULL"):
            state.fingerprints[task_id] = json.loads(fp)
        return state

    def refresh(self, conn, *, wait, full=False, comments=False, recheck=False):
        """Bring the cache up to date. Returns the number of tasks that changed, or None when another tg holds the lock."""
        with self.locked(wait) as got:
            if not got:
                return None
            last = get_state(conn, "last_pull_at")
            if recheck and last is not None and time.time() - last < self.entry.cache_ttl:
                return 0  # another tg refreshed while this one waited for the lock
            if not wait:
                conn.execute("PRAGMA busy_timeout=0")
            try:
                return self.pull_into(conn, full, comments)
            except sqlite3.OperationalError as e:
                if wait or "locked" not in str(e):
                    raise
                return None  # a write is in progress; read the cache as it is
            finally:
                conn.execute(f"PRAGMA busy_timeout={DB_TIMEOUT * 1000}")

    def pull_into(self, conn, full, comments):
        state = self.sync_state(conn)
        last_pull = get_state(conn, "last_pull_at")
        last_full = get_state(conn, "last_full_at")
        full = full or last_full is None or time.time() - last_full >= self.entry.full_every
        probe = self.remote.probe(state)
        edited, etag = self.remote.comment_changes(state, None if last_pull is None else last_pull - 60)
        changed = 0
        if full or probe.changed or edited:
            delta = self.remote.pull(state, probe, full=full, comments=comments, reread=edited)
            changed = len(delta.tasks)
            self.apply(conn, delta, state, first=last_full is None)
        else:
            with conn:
                put_state(conn, "last_pull_at", time.time())
        if etag != state.comments_etag:
            with conn:
                put_state(conn, "comments_etag", etag)
        if full and self.pending_rows(conn, older=PENDING_AGE):
            self.flush(conn, older=PENDING_AGE)
        return changed

    # -- applying a pull --------------------------------------------------------------------------------------------

    def apply(self, conn, delta, state, first):
        remote_by_number = {t.number: t for t in delta.tasks}
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            before = self.load(conn)
            conn.execute("PRAGMA defer_foreign_keys=ON")
            gone = set(delta.removed)
            if delta.full and delta.seen is not None:
                # a list page can lag behind a new issue: a task made in the last two minutes is not gone just because the page lacks it
                young = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 120))
                gone |= {i for i in before if i not in delta.seen and before[i]["created_at"] < young}
            for number in sorted(gone):
                self.forget(conn, number)
            removed = (state.removed - set(remote_by_number)) | set(delta.removed)
            known = (set(before) | set(remote_by_number)) - gone
            for t in delta.tasks:
                self.upsert(conn, t, delta.fingerprints[t.number], known)
            for number, blockers in delta.edges.items():
                if number in known:
                    self.set_edges(conn, number, blockers, known, removed)
            for number, rows in delta.results.items():
                if number in known:
                    conn.execute("DELETE FROM results WHERE task_id=?", (number,))
                    conn.executemany(
                        "INSERT OR REPLACE INTO results (id, task_id, at, status, kind, attempt, author, body) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        [(r["id"], number, r["at"], r["status"], r["kind"], r["attempt"], r["author"], r["body"]) for r in rows],
                    )
            for number, rows in delta.claims.items():
                if number in known:
                    self.store_claims(conn, number, rows)
            self.recompute_conflicts(conn)
            if delta.pages is not None:
                put_state(conn, "pages", {str(k): v for k, v in delta.pages.items()})
            put_state(conn, "removed", sorted(removed))
            if delta.pages is not None:  # a task read by id is not a pull: the next read still probes when its TTL is up
                put_state(conn, "last_pull_at", time.time())
            if delta.full:
                put_state(conn, "last_full_at", time.time())
            if not first:
                self.journal_pull(conn, before, remote_by_number)

    def forget(self, conn, number):
        conn.execute("UPDATE tasks SET parent_id=NULL WHERE parent_id=?", (number,))
        conn.execute("DELETE FROM tasks WHERE id=?", (number,))
        for table in ("local_meta", "pending_meta", "claims", "remote_conflicts"):
            conn.execute(f"DELETE FROM {table} WHERE task_id=?", (number,))

    def upsert(self, conn, t, fp, known):
        pending = []
        for row in conn.execute("SELECT * FROM pending_meta WHERE task_id=?", (t.number,)).fetchall():
            if (canon(t.meta[row["key"]]) if row["key"] in t.meta else None) != row["base"]:
                conn.execute("DELETE FROM pending_meta WHERE task_id=? AND key=?", (t.number, row["key"]))
                self.warn(f"warning: deferred {row['key']} on #{t.number} dropped; GitHub has a newer value")
            else:
                pending.append(row)
        parent = t.parent if t.parent in known else None
        conn.execute(
            "INSERT INTO tasks (id, project, title, status, notes, meta, created_at, updated_at, done_at, parent_id) VALUES (?, ?, ?, ?, ?, '{}', ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET title=excluded.title, status=excluded.status, notes=excluded.notes, created_at=excluded.created_at, "
            "updated_at=excluded.updated_at, done_at=excluded.done_at, parent_id=excluded.parent_id",
            (t.number, self.project, t.title, t.status, t.notes, t.created_at, t.updated_at, t.closed_at if t.status == "done" else None, parent),
        )
        conn.execute(
            "INSERT INTO remote_tasks (task_id, node_id, db_id, meta, fingerprint) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(task_id) DO UPDATE SET node_id=excluded.node_id, db_id=excluded.db_id, meta=excluded.meta, fingerprint=excluded.fingerprint",
            (t.number, t.node_id, t.db_id, json.dumps(t.meta, ensure_ascii=False), json.dumps(fp)),
        )
        self.write_meta(conn, t.number, t.type, t.priority)
        conn.execute("DELETE FROM remote_conflicts WHERE task_id=? AND source IN ('body', 'parent')", (t.number,))
        found = [("body", m) for m in bodies.conflicts(t.number, t.problems)]
        if t.parent is not None and t.parent not in known:
            found.append(("parent", f"#{t.number} is under #{t.parent}, which has no taskgraph label"))
        conn.executemany("INSERT INTO remote_conflicts (task_id, source, message) VALUES (?, ?, ?)", [(t.number, s, m) for s, m in found])

    def write_meta(self, conn, number, kind, priority=None):
        # tasks.meta = the type and priority (labels), what the remote holds, then the deferred rows, then the local-only keys; later wins
        remote = json.loads(conn.execute("SELECT meta FROM remote_tasks WHERE task_id=?", (number,)).fetchone()[0])
        meta = {"type": kind} if kind != "task" else {}
        if priority:
            meta["priority"] = priority
        meta.update(remote)
        for row in conn.execute("SELECT key, op, value FROM pending_meta WHERE task_id=?", (number,)):
            if row["op"] == "set":
                meta[row["key"]] = json.loads(row["value"])
            else:
                meta.pop(row["key"], None)
        for row in conn.execute("SELECT key, value FROM local_meta WHERE task_id=?", (number,)):
            meta[row["key"]] = json.loads(row["value"])
        conn.execute("UPDATE tasks SET meta=? WHERE id=?", (json.dumps(meta, ensure_ascii=False), number))

    def set_edges(self, conn, number, blockers, known, removed):
        conn.execute("DELETE FROM deps WHERE task_id=?", (number,))
        conn.execute("DELETE FROM remote_conflicts WHERE task_id=? AND source='edge'", (number,))
        for b in blockers:
            if b == number:
                continue
            if b in known:
                conn.execute("INSERT OR IGNORE INTO deps (task_id, depends_on) VALUES (?, ?)", (number, b))
            elif b not in removed:
                conn.execute("INSERT INTO remote_conflicts (task_id, source, message) VALUES (?, 'edge', ?)", (number, f"#{number} is blocked by #{b}, which has no taskgraph label"))

    def store_claims(self, conn, number, rows):
        conn.execute("DELETE FROM claims WHERE task_id=?", (number,))
        conn.executemany(
            "INSERT OR REPLACE INTO claims (comment_id, task_id, token, claimant, voids, at) VALUES (?, ?, ?, ?, ?, ?)",
            [(r["comment_id"], number, r["token"], r["claimant"], r["voids"], r["at"]) for r in rows],
        )

    def unvoided(self, conn, number):
        rows = conn.execute("SELECT * FROM claims WHERE task_id=? ORDER BY comment_id", (number,)).fetchall()
        voided = {v for r in rows for v in json.loads(r["voids"])}
        return [r for r in rows if r["token"] and r["comment_id"] not in voided]

    def recompute_conflicts(self, conn):
        # Breaks of tg's own rules that people can make in the GitHub UI (spec 6.6), and claim conflicts (8.3).
        conn.execute("DELETE FROM remote_conflicts WHERE source IN ('rule', 'claim')")
        kinds, parents, status = {}, {}, {}
        for r in conn.execute("SELECT id, parent_id, status, meta FROM tasks"):
            kinds[r["id"]], parents[r["id"]], status[r["id"]] = json.loads(r["meta"]).get("type", "task"), r["parent_id"], r["status"]
        found = []
        for n, parent in parents.items():
            if parent is not None and kinds[parent] not in PARENT_TYPES:
                found.append((n, parent, f"#{parent} is a {kinds[parent]}; parents must be a task or objective (#{n} is under it)"))
            if parent is not None and kinds[n] == "objective" and kinds[parent] != "objective":
                found.append((n, parent, f"parent of objective #{n} must be an objective"))
        for task, dep in conn.execute("SELECT task_id, depends_on FROM deps"):
            if dep in ancestors(parents, task) or task in ancestors(parents, dep):
                found.append((task, dep, f"#{task} is blocked by #{dep}, which is its ancestor or descendant"))
        for n, other, message in found:
            conn.executemany("INSERT INTO remote_conflicts (task_id, source, message) VALUES (?, 'rule', ?)", [(n, message), *([(other, message)] if other != n else [])])
        for n, st in status.items():
            mine = self.unvoided(conn, n)
            if st == "in_progress" and len(mine) > 1:
                conn.execute("INSERT INTO remote_conflicts (task_id, source, message) VALUES (?, 'claim', ?)", (n, f"claim conflict on #{n}: {mine[0]['claimant']} and {mine[1]['claimant']}"))

    def journal_pull(self, conn, before, remote_by_number):
        after = self.load(conn)
        cs, stamp = changeset(before, after), now()

        def at(i, field=None):
            t = remote_by_number.get(i)
            if t is None or field in ("depends_on", "parent"):
                return stamp  # dependency and sub-issue changes do not move updated_at
            return t.updated_at

        rows = []
        for c in cs.created:
            rows += event_rows(ChangeSet(created=(c,)), remote_by_number[c.id].created_at if c.id in remote_by_number else stamp)
        for r in cs.removed:
            rows += event_rows(ChangeSet(removed=(r,)), stamp)
        for f in cs.changed:
            rows += event_rows(ChangeSet(changed=(f,)), at(f.id, f.field))
        conn.executemany("INSERT INTO events (task_id, project, at, field, old, new) VALUES (?, ?, ?, ?, ?, ?)", rows)

    def labelled(self, meta):
        # the type and the priority in a tasks.meta text: the two keys that GitHub holds as labels
        meta = json.loads(meta)
        return meta.get("type", "task"), meta.get("priority")

    def warn(self, text):
        print(text, file=sys.stderr)

    # -- writing ----------------------------------------------------------------------------------------------------

    def new_id(self, conn):
        low = conn.execute("SELECT MIN(id) FROM tasks").fetchone()[0]
        return min(low or 0, 0) - 1

    def resolve_id(self, provisional):
        return self.idmap.get(provisional, provisional)

    def quiet(self, args):
        # an edit that only sets local-only or deferred meta keys makes no remote call, so it needs no refresh first
        keys = [m.partition("=")[0] for m in args.meta] + list(args.unset_meta)
        loud = args.title is not None or args.notes is not None or args.type is not None or args.parent is not None or args.no_parent
        loud = loud or args.priority is not None or args.no_priority  # the priority is a label
        return bool(keys) and not loud and all(self.kind_of(k) != "through" for k in keys)

    def kind_of(self, key):
        return "local" if key in self.entry.local else "deferred" if key in self.entry.deferred else "through"

    @contextmanager
    def write(self, conn, *, journal=True):
        self.claimed = {}
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            before = self.before = self.load(conn)  # inside the lock: a write that committed while this one waited is part of the baseline
            yield
            self.commit(conn, before, self.load(conn), journal)

    def check_limits(self, before, after, plan):
        caps = self.caps
        touched = {e.id for e in plan.edits if e.parent is not KEEP} | {c.id for c in plan.created}
        deep = set(touched)
        for t in after.values():
            if any(a in touched for a in self.chain(after, t["id"])[1:]):
                deep.add(t["id"])
        for i in sorted(deep):
            n = len(self.chain(after, i))
            if n > caps.max_depth:
                raise StoreError(f"#{i} would be {n} issues deep in a parent chain; GitHub allows {caps.max_depth}")
        for p in {after[i]["parent"] for i in touched if i in after and after[i]["parent"] is not None}:
            if len(after[p]["children"]) > caps.max_children:
                raise StoreError(f"#{p} would have {len(after[p]['children'])} sub-issues; GitHub allows {caps.max_children}")
        for i in {t for t, _ in plan.edges_added}:
            if len(after[i]["depends_on"]) > caps.max_blockers:
                raise StoreError(f"#{i} would have {len(after[i]['depends_on'])} blockers; GitHub allows {caps.max_blockers}")

    def chain(self, tasks, i):
        found = [i]
        while tasks[found[-1]]["parent"] is not None and tasks[found[-1]]["parent"] not in found:
            found.append(tasks[found[-1]]["parent"])
        return found

    def pending_for(self, conn, numbers=None, older=None):
        rows = [dict(r) for r in conn.execute("SELECT * FROM pending_meta ORDER BY task_id, key")]
        cutoff = time.time() - older if older is not None else None
        out = {}
        for r in rows:
            if (numbers is None or r["task_id"] in numbers) and (cutoff is None or r["at"] <= time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(cutoff))):
                out.setdefault(r["task_id"], []).append(r)
        return out

    def pending_rows(self, conn, older=None):
        return self.pending_for(conn, older=older)

    def build_plan(self, conn, before, after, cs):
        plan, local_rows, new_pending = Plan(), [], {}
        remote_meta = {r[0]: json.loads(r[1]) for r in conn.execute("SELECT task_id, meta FROM remote_tasks")}
        existing = self.pending_for(conn)
        for i in sorted(after.keys() - before.keys()):
            t = after[i]
            meta = {k: v for k, v in t["meta"].items() if k not in ("type", "priority")}
            plan.created.append(Create(i, t["title"], t["notes"], t["type"], t["parent"], {k: v for k, v in meta.items() if self.kind_of(k) != "local"}, t["priority"]))
            local_rows += [(i, k, v) for k, v in meta.items() if self.kind_of(k) == "local"]
        for i in sorted(after.keys() & before.keys()):
            b, a, e = before[i], after[i], Edit(i)
            e.title = a["title"] if a["title"] != b["title"] else None
            e.notes = a["notes"] if a["notes"] != b["notes"] else None
            e.status = a["status"] if (a["status"] != b["status"] or i in self.claimed) else None
            e.type = a["type"] if a["type"] != b["type"] else None
            e.priority = a["priority"] if a["priority"] != b["priority"] else KEEP
            e.parent = a["parent"] if a["parent"] != b["parent"] else KEEP
            old_rows = {r["key"]: r for r in existing.get(i, [])}
            rows = dict(old_rows)
            for k, (old, new) in meta_diff(b["meta"], a["meta"]).items():
                kind = self.kind_of(k)
                if kind == "local":
                    local_rows.append((i, k, new))
                elif kind == "through" and k == "gates" and all(isinstance(v, dict) or v is KEEP for v in (old, new)):
                    og, ng = ({} if v is KEEP else v for v in (old, new))
                    e.gates_set = {g: v for g, v in ng.items() if og.get(g) != v}
                    e.gates_unset = sorted(og.keys() - ng.keys())
                elif kind == "through":
                    if new is KEEP:
                        e.meta_unset.append(k)
                    else:
                        e.meta_set[k] = new
                else:
                    base = rows[k]["base"] if k in rows else (canon(remote_meta[i][k]) if k in remote_meta.get(i, {}) else None)
                    rows[k] = {"task_id": i, "key": k, "op": "unset" if new is KEEP else "set", "value": None if new is KEEP else canon(new), "base": base, "at": now(), "old": old_rows.get(k)}
                    new_pending.setdefault(i, {})[k] = rows[k]
            e.pending = sorted(old_rows.values(), key=lambda r: r["key"])  # only rows queued earlier ride along; this edit's own stay queued
            if e.title is not None or e.notes is not None or e.status is not None or e.type is not None or e.priority is not KEEP or e.parent is not KEEP or e.meta_set or e.meta_unset or e.gates_set or e.gates_unset:
                plan.edits.append(e)
        plan.removed = sorted(before.keys() - after.keys())
        plan.edges_added, plan.edges_removed = list(cs.edges_added), list(cs.edges_removed)
        plan.db_ids = {r[0]: r[1] for r in conn.execute("SELECT task_id, db_id FROM remote_tasks WHERE db_id IS NOT NULL")}
        plan.labels = {self.entry.label, IN_PROGRESS, REMOVED, *("tg:priority:" + p for p in PRIORITIES)} | {"tg:type:" + c.type for c in plan.created if c.type != "task"} | {"tg:type:" + e.type for e in plan.edits if e.type not in (None, "task")}
        return plan, local_rows, new_pending

    def commit(self, conn, before, after, journal):
        cs = changeset(before, after)
        plan, local_rows, new_pending = self.build_plan(conn, before, after, cs)
        self.check_limits(before, after, plan)
        pushed = None
        if plan:
            self.ensure_labels(conn, plan.labels)
            fresh = {}
            for i in sorted({e.id for e in plan.edits} | set(plan.removed) | set(self.claimed)):
                fresh[i] = self.fresh_task(i)
            for i, outcome in self.claimed.items():
                self.remote.check_deadline(outcome, fresh[i])
            pushed = self.remote.push(plan, fresh)
        self.finish(conn, plan, pushed, local_rows, new_pending)
        for i, outcome in self.claimed.items():
            self.store_claims(conn, self.resolve_id(i), outcome.claims)
        if journal:
            rows = event_rows(changeset(before, self.load(conn)), now())
            conn.executemany("INSERT INTO events (task_id, project, at, field, old, new) VALUES (?, ?, ?, ?, ?, ?)", rows)
        self.recompute_conflicts(conn)

    def fresh_task(self, i):
        from tgstore.github.gh import HttpError

        try:
            t = self.remote.fetch(i)
        except HttpError as e:
            if e.status == 404:
                raise TaskGone(f"#{i} no longer exists on GitHub; run tg sync")
            raise
        if self.entry.label not in t.labels or t.removed or t.item.get("pull_request"):
            raise TaskGone(f"#{i} is no longer a task on GitHub (no {self.entry.label} label); run tg sync")
        return t

    def ensure_labels(self, conn, labels):
        ready = set(get_state(conn, "labels", []))
        if labels - ready:
            self.remote.ensure_setup(labels)
            put_state(conn, "labels", sorted(ready | labels))

    def finish(self, conn, plan, pushed, local_rows, new_pending):
        """After the remote took the change (or when no remote call was needed): rename provisional ids, then the bookkeeping rows."""
        ids = pushed.ids if pushed else {}
        if ids:
            conn.execute("PRAGMA defer_foreign_keys=ON")
            for prov, number in ids.items():
                conn.execute("UPDATE tasks SET id=? WHERE id=?", (number, prov))
                conn.execute("UPDATE tasks SET parent_id=? WHERE parent_id=?", (number, prov))
                conn.execute("UPDATE deps SET task_id=? WHERE task_id=?", (number, prov))
                conn.execute("UPDATE deps SET depends_on=? WHERE depends_on=?", (number, prov))
            self.idmap.update(ids)
        num = lambda i: ids.get(i, i)
        touched = set()
        if pushed:
            for number, db_id in pushed.db_ids.items():
                if number in ids.values():
                    conn.execute("INSERT INTO remote_tasks (task_id, node_id, db_id, meta, fingerprint) VALUES (?, ?, ?, '{}', NULL)", (number, pushed.node_ids.get(number, ""), db_id))
            for number, meta in pushed.meta.items():
                conn.execute("UPDATE remote_tasks SET meta=? WHERE task_id=?", (json.dumps(meta, ensure_ascii=False), number))
                touched.add(number)
            for number in pushed.flushed:
                conn.execute("DELETE FROM pending_meta WHERE task_id=?", (number,))
                touched.add(number)
            for number, key in pushed.dropped:
                self.warn(f"warning: deferred {key} on #{number} dropped; GitHub has a newer value")
            for task, dep in [*plan.edges_added, *plan.edges_removed]:
                touched |= {num(task), num(dep)}
            touched |= {num(c.id) for c in plan.created} | {e.id for e in plan.edits} | set(plan.removed)
            for number in touched:
                row = conn.execute("SELECT fingerprint FROM remote_tasks WHERE task_id=?", (number,)).fetchone()
                if row:  # unknown content, known comment count: the next pull re-reads the task but not its comments
                    old = json.loads(row[0]) if row[0] else {"comments": 0}
                    conn.execute("UPDATE remote_tasks SET fingerprint=? WHERE task_id=?", (json.dumps({"all": None, "edges": None, "comments": old.get("comments", 0)}), number))
        flushed = pushed.flushed if pushed else set()
        for i, rows in new_pending.items():
            for r in rows.values():
                base = r["base"]
                if num(i) in flushed and r["old"] is not None:
                    base = r["old"]["value"] if r["old"]["op"] == "set" else None  # the earlier row went out; GitHub now holds its value
                    if (num(i), r["key"]) in pushed.dropped:  # the earlier row did not go out: GitHub kept the value it had
                        meta = pushed.meta.get(num(i), {})
                        base = canon(meta[r["key"]]) if r["key"] in meta else None
                conn.execute("INSERT OR REPLACE INTO pending_meta (task_id, key, op, value, base, at) VALUES (?, ?, ?, ?, ?, ?)",
                             (num(i), r["key"], r["op"], r["value"], base, r["at"]))
            touched.add(num(i))
        for i, key, value in local_rows:
            if value is KEEP:
                conn.execute("DELETE FROM local_meta WHERE task_id=? AND key=?", (num(i), key))
            else:
                conn.execute("INSERT OR REPLACE INTO local_meta (task_id, key, value) VALUES (?, ?, ?)", (num(i), key, json.dumps(value, ensure_ascii=False)))
            touched.add(num(i))
        for number in plan.removed:
            for table in ("local_meta", "pending_meta", "claims", "remote_conflicts"):
                conn.execute(f"DELETE FROM {table} WHERE task_id=?", (number,))
        for number in sorted(touched - set(plan.removed)):
            row = conn.execute("SELECT meta FROM tasks WHERE id=?", (number,)).fetchone()
            if row:
                self.write_meta(conn, number, *self.labelled(row[0]))

    # -- deferred rows and sync -------------------------------------------------------------------------------------

    def flush(self, conn, older=None):
        rows = self.pending_for(conn, older=older)
        return self.flush_numbers(conn, sorted(rows))

    def flush_numbers(self, conn, numbers):
        if not numbers:
            return 0
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = self.pending_for(conn, set(numbers))
            plan = Plan(edits=[Edit(n, pending=rows[n], flush=True) for n in sorted(rows)])
            plan.labels = {self.entry.label, IN_PROGRESS, REMOVED}
            self.ensure_labels(conn, plan.labels)
            fresh = {}
            for e in list(plan.edits):
                try:
                    fresh[e.id] = self.fresh_task(e.id)
                except TaskGone:  # nothing to send the rows to: drop them
                    conn.execute("DELETE FROM pending_meta WHERE task_id=?", (e.id,))
                    plan.edits.remove(e)
                    self.warn(f"warning: deferred {', '.join(r['key'] for r in rows[e.id])} on #{e.id} dropped; #{e.id} is no longer a task on GitHub")
                    row = conn.execute("SELECT meta FROM tasks WHERE id=?", (e.id,)).fetchone()
                    if row:
                        self.write_meta(conn, e.id, *self.labelled(row[0]))
            if not plan.edits:
                return 0
            pushed = self.remote.push(plan, fresh)
            self.finish(conn, plan, pushed, [], {})
        return len(pushed.flushed)

    def sync(self, *, full=False):
        conn = self.conn or self.connect(mode="none")
        changed = self.refresh(conn, wait=True, full=full, comments=full)  # first: a task that left GitHub is dropped from the cache with its deferred rows
        flushed = self.flush_numbers(conn, sorted(self.pending_for(conn)))
        return {"changed": changed or 0, "flushed": flushed, "full": full}

    # -- results, claims, identity ----------------------------------------------------------------------------------

    def add_result(self, conn, task_id, row):
        from tgstore.github.gh import HttpError

        try:
            task = self.remote.fetch(task_id)
            exists = self.entry.label in task.labels and not task.removed and not task.item.get("pull_request")
        except HttpError as e:
            if e.status != 404:
                raise
            exists = False
        if not exists:
            raise StoreError(f"no such task: {task_id}")
        if conn.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone() is None:
            self.refresh(conn, wait=True)
            if conn.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone() is None:
                raise StoreError(f"no such task: {task_id}")
        out = self.remote.post_result(task_id, row)
        with conn:
            conn.execute(
                "INSERT INTO results (id, task_id, at, status, kind, attempt, author, body) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (out["id"], task_id, out["at"], row.status, row.kind, row.attempt, row.author, row.body),
            )
        return out

    def claimant(self, conn):
        given = os.environ.get("TASKGRAPH_CLAIMANT") or self.entry.claimant
        if given:
            return given
        login = get_state(conn, "login")
        if login is None:
            login = self.remote.login()
            if conn.in_transaction:
                put_state(conn, "login", login)
            else:
                with conn:
                    put_state(conn, "login", login)
        return f"{login}@{socket.gethostname().split('.')[0]}:{cfg.checkout_id()}"

    def claim(self, conn, task_id):
        # Reads GitHub, never the cache. Raises ClaimLost; the label goes out with the write that follows (commit).
        self.claimed[task_id] = self.remote.claim(task_id, self.claimant(conn))

    def claimant_of(self, conn, task_id):
        mine = self.unvoided(conn, task_id)
        row = conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
        return mine[0]["claimant"] if mine and row and row["status"] == "in_progress" else None

    def version(self, conn):
        return conn.execute("PRAGMA data_version").fetchone()[0]

    def path(self):
        return str(self.cache)
