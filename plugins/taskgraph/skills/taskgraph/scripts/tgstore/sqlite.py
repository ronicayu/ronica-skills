import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from tgstore.base import Capabilities, StoreError, now
from tgstore.changes import changeset, event_rows

DB_TIMEOUT = 30  # seconds a writer waits for the lock; background agents add results concurrently

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
CREATE TABLE IF NOT EXISTS results (
  id INTEGER PRIMARY KEY,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  at TEXT NOT NULL,
  status TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'task',
  attempt INTEGER,
  author TEXT,
  body TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_results_task ON results(task_id, id);
"""


def connect(path):
    path = Path(path or os.environ.get("TASKGRAPH_DB") or Path.home() / ".taskgraph" / "tasks.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=DB_TIMEOUT)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    if "parent_id" not in {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}:
        with conn:
            conn.execute("ALTER TABLE tasks ADD COLUMN parent_id INTEGER REFERENCES tasks(id)")
    return conn


def next_id(conn):
    sql = "SELECT MAX(i) FROM (SELECT MAX(id) AS i FROM tasks UNION ALL SELECT MAX(task_id) FROM events UNION ALL SELECT MAX(task_id) FROM baselines)"
    return (conn.execute(sql).fetchone()[0] or 0) + 1


def data_version(conn):
    return conn.execute("PRAGMA data_version").fetchone()[0]


def db_path(conn):
    return conn.execute("PRAGMA database_list").fetchone()[2]


@contextmanager
def record(conn, load):
    before = load(conn)
    yield
    rows = event_rows(changeset(before, load(conn)), now())
    conn.executemany("INSERT INTO events (task_id, project, at, field, old, new) VALUES (?, ?, ?, ?, ?, ?)", rows)


class SqliteStore:
    name = "sqlite"
    caps = Capabilities(
        cross_project_deps=True, claim=False, history="full", baselines="local", soft_delete=False,
        max_blockers=None, max_depth=None, max_children=None,
    )

    def __init__(self, db=None, load=None):
        self.db = db
        self.load = load  # the model reader of tg.py; the event journal compares two loads
        self.resolved = None
        self.before = None  # tasks as they were when the write began; only a remote store keeps it

    def connect(self, *, fresh=False, mode="read"):
        conn = connect(self.db)
        self.resolved = db_path(conn)
        return conn

    @contextmanager
    def write(self, conn, *, journal=True):
        if journal:
            with conn, record(conn, self.load):
                yield
        else:
            with conn:
                yield

    def new_id(self, conn):
        return next_id(conn)

    def resolve_id(self, provisional):
        return provisional

    def add_result(self, conn, task_id, row):
        # One statement: it checks the task and inserts in the same transaction, and reads nothing it later writes.
        with conn:
            cur = conn.execute(
                "INSERT INTO results (task_id, at, status, kind, attempt, author, body) SELECT id, ?, ?, ?, ?, ?, ? FROM tasks WHERE id=?",
                (now(), row.status, row.kind, row.attempt, row.author, row.body, task_id),
            )
            if cur.rowcount == 0:
                raise StoreError(f"no such task: {task_id}")
            return dict(conn.execute("SELECT * FROM results WHERE id=?", (cur.lastrowid,)).fetchone())

    def claim(self, conn, task_id):
        pass

    def claimant_of(self, conn, task_id):
        return None

    def sync(self, *, full=False):
        raise StoreError("tg sync: this project uses the local store; nothing to sync")

    def version(self, conn):
        return data_version(conn)

    def path(self):
        if self.resolved is None:
            with closing(self.connect()) as conn:
                return db_path(conn)
        return self.resolved
