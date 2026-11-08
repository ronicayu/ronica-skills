import os
import sqlite3
from pathlib import Path

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
