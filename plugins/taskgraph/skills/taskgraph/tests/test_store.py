import io
import sqlite3
import sys
from contextlib import closing, contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import tg  # noqa: E402
from tgstore.base import ClaimLost, RateLimited, RemoteError, ResultInput, StoreError  # noqa: E402
from tgstore.changes import ChangeSet, Created, FieldChange, Removed, changeset  # noqa: E402
from tgstore.sqlite import SqliteStore  # noqa: E402


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setenv("TASKGRAPH_TODAY", "2026-10-13")


class RecordingStore(SqliteStore):
    # Records what each command asks of the store. A write is recorded only when it commits.
    def __init__(self, db, load, log):
        super().__init__(db, load)
        self.log = log

    @contextmanager
    def write(self, conn, *, journal=True):
        before = self.load(conn)
        with super().write(conn, journal=journal):
            yield
        self.log.append(("write", changeset(before, self.load(conn))))

    def add_result(self, conn, task_id, row):
        self.log.append(("add_result", task_id, row))
        return super().add_result(conn, task_id, row)

    def claim(self, conn, task_id):
        self.log.append(("claim", task_id))
        super().claim(conn, task_id)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "t.db"


@pytest.fixture
def log(monkeypatch, db):
    events = []
    monkeypatch.setattr(tg, "open_store", lambda args: RecordingStore(args.db, tg.load, events))
    return events


@pytest.fixture
def run(db, log):
    def go(*args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = tg.main(["--db", str(db), "--project", "demo", "--json", *args])
        return code, out.getvalue(), err.getvalue()

    return go


@pytest.fixture
def change(run, log):
    # Run one command that must succeed and return the change set of its one write.
    def go(*args):
        log.clear()
        code, _, err = run(*args)
        assert code == 0, err
        writes = [e[1] for e in log if e[0] == "write"]
        assert len(writes) == 1
        return writes[0]

    return go


def dump(db):
    with closing(sqlite3.connect(db)) as conn:
        return "\n".join(conn.iterdump())


def node(**over):
    task = {
        "project": "p", "title": "T", "status": "open", "type": "task", "parent": None, "notes": "",
        "start": None, "due": None, "meta": {}, "depends_on": [],
    }
    task.update(over)
    return task


def fields(title, **over):
    # tracked() of a new task that has the given title
    return {
        "title": title, "status": "open", "type": "task", "parent": None, "notes": "", "start": None, "due": None,
        "promised": None, "depends_on": [], **over,
    }


FIELD_CASES = [
    ("title", {"title": "U"}, "T", "U"),
    ("status", {"status": "done"}, "open", "done"),
    ("type", {"type": "decision"}, "task", "decision"),
    ("parent", {"parent": 2}, None, 2),
    ("notes", {"notes": "more"}, "", "more"),
    ("start", {"start": "2026-11-01"}, None, "2026-11-01"),
    ("due", {"due": "2026-11-09"}, None, "2026-11-09"),
    ("promised", {"meta": {"promised": "2026-11-05"}}, None, "2026-11-05"),
    ("meta.owner", {"meta": {"owner": "bob"}}, None, "bob"),
]


@pytest.mark.parametrize("field,over,old,new", FIELD_CASES, ids=[c[0] for c in FIELD_CASES])
def test_changeset_detects_each_field(field, over, old, new):
    before = {1: node(), 2: node(title="Parent")}
    after = {1: node(**over), 2: node(title="Parent")}
    found = changeset(before, after)
    assert found.changed == (FieldChange(1, "p", field, old, new),)
    assert not found.created and not found.removed and not found.edges_added and not found.edges_removed
    assert changeset(after, after) == ChangeSet() and not changeset(after, after)


def test_changeset_detects_meta_unset():
    before = {1: node(meta={"owner": "bob", "lane": "core"})}
    after = {1: node(meta={"lane": "core"})}
    assert changeset(before, after).changed == (FieldChange(1, "p", "meta.owner", "bob", None),)


def test_changeset_detects_added_and_removed_dependency():
    bare = {1: node(), 2: node()}
    linked = {1: node(), 2: node(depends_on=[1])}
    added = changeset(bare, linked)
    assert added.changed == (FieldChange(2, "p", "depends_on", [], [1]),)
    assert added.edges_added == ((2, 1),) and added.edges_removed == ()
    removed = changeset(linked, bare)
    assert removed.changed == (FieldChange(2, "p", "depends_on", [1], []),)
    assert removed.edges_added == () and removed.edges_removed == ((2, 1),)


def test_changeset_created_and_removed(change):
    created = change("add", "A")
    assert created.created == (Created(1, "demo", "A", fields("A")),)
    assert not created.removed and not created.changed and not created.edges_added
    removed = change("rm", "1")
    assert removed.removed == (Removed(1, "demo", "A"),)
    assert not removed.created and not removed.changed and not removed.edges_removed


def test_failed_command_writes_nothing(run, log, db):
    assert run("add", "A")[0] == 0  # 1
    assert run("add", "B", "--depends", "1")[0] == 0  # 2
    assert run("add", "Summary")[0] == 0  # 3
    assert run("add", "Part", "--parent", "3")[0] == 0  # 4
    assert run("add", "Y")[0] == 0  # 5
    assert run("dep", "add", "4", "5")[0] == 0
    assert run("add", "R", "--type", "risk")[0] == 0  # 6
    before = dump(db)
    log.clear()
    attempts = [
        ("add", "C", "--depends", "2", "--blocks", "1"),  # cycle: 1 -> C -> 2 -> 1
        ("dep", "add", "5", "3"),  # deadlock: 5 waits for 3, 3 for its part 4, 4 for 5
        ("edit", "5", "--parent", "6"),  # a risk cannot be a parent
    ]
    for args in attempts:
        code, out, err = run(*args)
        assert code == 1 and err.startswith("error:") and out == "", args
    assert [e for e in log if e[0] == "write"] == []
    assert dump(db) == before


def test_successful_commands_produce_expected_changesets(change, run):
    assert change("add", "A") == ChangeSet(created=(Created(1, "demo", "A", fields("A")),))
    assert change("add", "B") == ChangeSet(created=(Created(2, "demo", "B", fields("B")),))
    assert change("dep", "add", "2", "1") == ChangeSet(
        changed=(FieldChange(2, "demo", "depends_on", [], [1]),), edges_added=((2, 1),)
    )
    assert change("start", "1") == ChangeSet(changed=(FieldChange(1, "demo", "status", "open", "in_progress"),))
    assert change("done", "1") == ChangeSet(changed=(FieldChange(1, "demo", "status", "in_progress", "done"),))
    assert change("edit", "2", "--meta", "owner=bob") == ChangeSet(changed=(FieldChange(2, "demo", "meta.owner", None, "bob"),))
    assert run("add", "Parent")[0] == 0  # 3
    assert run("add", "Child", "--parent", "3", "--depends", "1")[0] == 0  # 4
    assert change("rm", "3", "--recursive") == ChangeSet(
        removed=(Removed(3, "demo", "Parent"), Removed(4, "demo", "Child")), edges_removed=((4, 1),)
    )


def test_result_add_goes_through_store(run, log):
    assert run("add", "A")[0] == 0
    log.clear()
    code, out, err = run("result", "add", "1", "--status", "PASS", "--kind", "review", "--attempt", "2", "--by", "w", "--body", "text")
    assert code == 0, err
    assert log == [("add_result", 1, ResultInput("PASS", "review", 2, "w", "text"))]
    log.clear()
    code, out, err = run("result", "add", "9", "--status", "PASS")
    assert code == 1 and err == "error: no such task: 9\n"


def test_start_calls_claim_once(run, log):
    assert run("add", "A")[0] == 0
    log.clear()
    assert run("start", "1")[0] == 0
    assert [e for e in log if e[0] == "claim"] == [("claim", 1)]
    log.clear()
    assert run("done", "1")[0] == 0
    assert run("reopen", "1")[0] == 0
    assert [e for e in log if e[0] == "claim"] == []


def test_sqlite_store_basics(db):
    store = SqliteStore(db, tg.load)
    with closing(store.connect()) as conn:
        assert store.path() == conn.execute("PRAGMA database_list").fetchone()[2]
        assert store.version(conn) == conn.execute("PRAGMA data_version").fetchone()[0]
        assert store.new_id(conn) == 1
        assert store.resolve_id(7) == 7
    assert store.caps.claim is False and store.caps.max_blockers is None
    with pytest.raises(StoreError, match="nothing to sync"):
        store.sync()


def test_store_errors_carry_their_details():
    refused = RemoteError("refused", applied=["a"], not_applied=["b"])
    assert str(refused) == "refused" and refused.applied == ("a",) and refused.not_applied == ("b",)
    limited = RateLimited("slow down", "2026-11-08T10:00:00Z")
    assert isinstance(limited, RemoteError) and limited.reset_at == "2026-11-08T10:00:00Z"
    lost = ClaimLost("#3 is claimed by ann", "ann", 42)
    assert isinstance(lost, StoreError) and (lost.winner, lost.winner_comment_id) == ("ann", 42)
