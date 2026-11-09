import io
import json
import math
import sqlite3
import time
from contextlib import closing, redirect_stderr, redirect_stdout

import pytest

import tg
from tgstore.cached import CachedRemoteStore
from tgstore.config import Entry
from tgstore.github.remote import GitHubRemote

LOCAL = ("sessions", "session", "cleanup_kept", "host_rebase")
DEFERRED = ("tokens", "model", "started_at")


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setenv("TASKGRAPH_TODAY", "2026-10-13")


class Env:
    def __init__(self, fake, tmp_path, monkeypatch):
        self.fake = fake
        self.cache = tmp_path / "cache.db"
        self.entry = Entry("demo", "github", "o/demo", cache=str(self.cache), local=LOCAL, deferred=DEFERRED)
        monkeypatch.setattr(tg, "open_store", lambda args: CachedRemoteStore(GitHubRemote(self.entry), self.entry, tg.load, "demo"))

    def run(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = tg.main(["--project", "demo", "--json", *args])
        return code, out.getvalue(), err.getvalue()

    def ok(self, *args):
        code, out, err = self.run(*args)
        assert code == 0, err
        return json.loads(out) if out.strip() else None

    def fail(self, *args):
        code, out, err = self.run(*args)
        assert code == 1 and err.startswith("error:"), (code, err)
        return err

    def sql(self, query, *params):
        with closing(sqlite3.connect(self.cache)) as db:
            return db.execute(query, params).fetchall()

    def age(self, seconds):
        with closing(sqlite3.connect(self.cache)) as db, db:
            db.execute("UPDATE sync_state SET value=? WHERE key='last_pull_at'", (json.dumps(time.time() - seconds),))

    def writes(self):
        return [c for c in self.fake.calls() if c["method"] != "GET" and c["path"] != "graphql"]


@pytest.fixture
def env(fake, tmp_path, monkeypatch):
    return Env(fake, tmp_path, monkeypatch)


def tg_text(env, *args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = tg.main(["--project", "demo", *args])
    return code, out.getvalue(), err.getvalue()


def titles(tasks):
    return [t["title"] for t in tasks]


def test_first_use_pulls_then_a_fresh_read_makes_no_call(env, fake):
    fake.add_issue("from a person")
    assert titles(env.ok("ls")) == ["from a person"]
    fake.clear_log()
    assert titles(env.ok("ls")) == ["from a person"]
    assert fake.calls() == []


def test_an_expired_ttl_makes_one_conditional_get_per_page_and_costs_nothing_when_nothing_changed(env, fake):
    with fake.locked() as s:
        for i in range(120):
            fake.new_issue(s, f"t{i}", labels=["taskgraph"])
    env.ok("ls")
    env.age(31)
    fake.clear_log()
    env.ok("ls")
    calls = fake.calls()
    assert len(calls) == math.ceil(120 / 100) + 1 == 3  # one per page, and one for the newest comment of the repository
    assert [(c["status"], c["counted"]) for c in calls] == [(304, False)] * 3
    fake.clear_log()
    env.ok("ls")  # the refresh above reset the clock
    assert fake.calls() == []


def test_a_persons_edit_shows_after_the_ttl_and_at_once_with_fresh(env, fake):
    n = fake.add_issue("old title")["number"]
    env.ok("ls")
    fake.edit_issue(n, title="new title")
    assert titles(env.ok("ls")) == ["old title"]
    assert titles(env.ok("--fresh", "ls")) == ["new title"]
    fake.edit_issue(n, title="newer")
    env.age(31)
    assert titles(env.ok("ls")) == ["newer"]


def test_a_dependency_added_without_updated_at_shows_after_the_next_probe(env, fake):
    a, b = fake.add_issue("a")["number"], fake.add_issue("b")["number"]
    assert {t["id"]: t["derived_status"] for t in env.ok("ls")} == {a: "ready", b: "ready"}
    fake.add_blocker(b, a)
    env.age(31)
    assert {t["id"]: t["derived_status"] for t in env.ok("ls")} == {a: "ready", b: "blocked"}


def test_a_person_closing_and_labelling_changes_status(env, fake):
    n = fake.add_issue("t")["number"]
    env.ok("ls")
    fake.edit_issue(n, labels=["taskgraph", "tg:in-progress"])
    assert env.ok("--fresh", "show", str(n))["status"] == "in_progress"
    fake.edit_issue(n, state="closed")
    assert env.ok("--fresh", "show", str(n))["status"] == "done"
    fake.edit_issue(n, state="open", labels=["taskgraph"])
    assert env.ok("--fresh", "show", str(n))["status"] == "open"


def test_add_makes_the_issue_with_its_labels_and_meta_and_prints_the_number(env, fake):
    fake.add_issue("a pull request", labels=(), pull_request=True)  # takes number 1
    t = env.ok("add", "Ship it", "--type", "decision", "--notes", "why", "--meta", "estimate=2", "lane=core")
    assert t["id"] == 2 and t["type"] == "decision" and t["meta"] == {"type": "decision", "estimate": 2, "lane": "core"}
    issue = fake.issue(2)
    assert issue["labels"] == ["taskgraph", "tg:type:decision"]
    assert issue["body"].startswith("why\n\n<!-- taskgraph:meta v1\n") and '{"estimate":2,"lane":"core"}' in issue["body"]
    assert env.run("add", "plain")[1].strip() != ""
    assert [t["id"] for t in env.ok("ls")] == [2, 3]


def test_provisional_id_is_renamed_in_every_table(env, fake):
    x = env.ok("add", "X")["id"]
    p = env.ok("add", "P")["id"]
    t = env.ok("add", "child", "--parent", str(p), "--depends", str(x))
    assert t["id"] == 3 and t["parent"] == p and t["depends_on"] == [x]
    assert env.sql("SELECT id FROM tasks WHERE id < 1") == []
    assert env.sql("SELECT task_id, depends_on FROM deps") == [(3, x)]
    assert env.sql("SELECT task_id FROM events WHERE task_id < 1") == []
    assert env.sql("SELECT task_id FROM remote_tasks ORDER BY 1") == [(1,), (2,), (3,)]
    state = fake.state()
    assert state["parent"] == {"3": p} and state["blocked_by"] == {"3": [x]}
    assert env.ok("--fresh", "show", "3")["parent"] == p  # and a pull agrees


def test_edit_meta_splits_by_class_in_one_patch(env, fake):
    a = env.ok("add", "A")["id"]
    fake.clear_log()
    env.ok("edit", str(a), "--meta", 'sessions=[{"id":"x"}]', 'tokens="1/2"', 'verify="make"')
    patches = [c for c in fake.calls() if c["method"] == "PATCH"]
    assert len(patches) == 1
    body = fake.issue(a)["body"]
    assert '{"verify":"make"}' in body and "sessions" not in body and "tokens" not in body
    shown = env.ok("show", str(a))["meta"]
    assert shown == {"verify": "make", "tokens": "1/2", "sessions": [{"id": "x"}]}
    assert env.sql("SELECT key FROM local_meta") == [("sessions",)] and env.sql("SELECT key FROM pending_meta") == [("tokens",)]
    fake.add_issue("noise")  # a pull must not touch the local key or the pending one
    env.ok("--fresh", "ls")
    assert env.ok("show", str(a))["meta"] == shown


def test_a_local_key_survives_a_person_editing_the_body(env, fake):
    a = env.ok("add", "A", "--meta", "verify=1")["id"]
    env.ok("edit", str(a), "--meta", 'session="s1"')
    fake.edit_issue(a, body="rewritten by a person")
    t = env.ok("--fresh", "show", str(a))
    assert t["meta"] == {"session": "s1"} and t["notes"] == "rewritten by a person"


def test_a_deferred_only_edit_makes_no_call_and_the_next_done_sends_it(env, fake):
    a = env.ok("add", "A")["id"]
    fake.clear_log()
    env.ok("edit", str(a), "--meta", 'tokens="9"')
    assert fake.calls() == []
    assert env.ok("show", str(a))["meta"] == {"tokens": "9"}
    env.ok("done", str(a))
    assert '"tokens":"9"' in fake.issue(a)["body"] and fake.issue(a)["state"] == "closed"
    assert env.sql("SELECT * FROM pending_meta") == []
    assert env.ok("show", str(a))["meta"] == {"tokens": "9"}


def test_sync_sends_deferred_rows(env, fake):
    a = env.ok("add", "A")["id"]
    env.ok("edit", str(a), "--meta", 'model="m"', 'started_at="t"')
    assert "model" not in fake.issue(a)["body"]
    store = CachedRemoteStore(GitHubRemote(env.entry), env.entry, tg.load, "demo")
    result = store.sync()
    assert result["flushed"] == 1 and '"model":"m"' in fake.issue(a)["body"] and '"started_at":"t"' in fake.issue(a)["body"]
    fake.clear_log()
    assert CachedRemoteStore(GitHubRemote(env.entry), env.entry, tg.load, "demo").sync()["flushed"] == 0


def old_task(fake, title):
    with fake.locked() as s:
        return fake.new_issue(s, title, labels=["taskgraph"], created_at="2026-01-01T00:00:00Z")["number"]


def unlabel(fake, n):
    with fake.locked() as s:
        s["issues"][str(n)]["labels"] = []  # a person removes the taskgraph label


def test_sync_full_drops_the_deferred_rows_of_a_task_that_left_github(env, fake):
    a, b = old_task(fake, "A"), old_task(fake, "B")
    env.ok("ls")
    env.ok("edit", str(a), "--meta", 'tokens="5"')
    unlabel(fake, a)
    code, out, err = env.run("sync", "--full")
    assert code == 0 and err == "", err
    assert [t["id"] for t in env.ok("--fresh", "ls")] == [b]
    assert env.sql("SELECT id FROM tasks") == [(b,)] and env.sql("SELECT * FROM pending_meta") == []


def test_plain_sync_drops_the_deferred_rows_of_a_task_that_left_github_with_one_warning(env, fake):
    a = old_task(fake, "A")
    env.ok("ls")
    env.ok("edit", str(a), "--meta", 'tokens="5"', 'model="m"')
    unlabel(fake, a)
    code, out, err = env.run("sync")
    assert code == 0, err
    assert err == f"warning: deferred model, tokens on #{a} dropped; #{a} is no longer a task on GitHub\n"
    assert env.sql("SELECT * FROM pending_meta") == []
    assert env.run("sync")[0] == 0


def test_a_pending_row_whose_key_changed_on_github_is_dropped_with_a_warning(env, fake):
    a = env.ok("add", "A", "--meta", "model=old")["id"]  # model is deferred, but a new task sends everything
    env.ok("edit", str(a), "--meta", "model=mine")
    fake.edit_issue(a, body="x\n\n<!-- taskgraph:meta v1\n{\"model\":\"theirs\"}\ntaskgraph:end -->\n")
    code, out, err = env.run("--fresh", "show", str(a))
    assert code == 0 and "warning: deferred model on #1 dropped; GitHub has a newer value" in err
    assert json.loads(out)["meta"] == {"model": "theirs"} and env.sql("SELECT * FROM pending_meta") == []


def test_a_new_deferred_row_after_a_dropped_one_takes_githubs_value_as_its_base(env, fake, monkeypatch):
    a = env.ok("add", "A")["id"]
    env.ok("edit", str(a), "--meta", 'tokens="mine"')
    refresh = CachedRemoteStore.refresh

    def refresh_then_a_person_edits(self, *args, **kwargs):
        done = refresh(self, *args, **kwargs)  # the person's edit lands after this write read GitHub and before it pushes
        fake.edit_issue(a, body='\n\n<!-- taskgraph:meta v1\n{"tokens":"theirs"}\ntaskgraph:end -->\n')
        return done

    with monkeypatch.context() as patched:
        patched.setattr(CachedRemoteStore, "refresh", refresh_then_a_person_edits)
        code, out, err = env.run("edit", str(a), "--title", "T", "--meta", 'tokens="newer"')
    assert code == 0 and f"warning: deferred tokens on #{a} dropped; GitHub has a newer value" in err
    assert env.sql("SELECT value, base FROM pending_meta") == [('"newer"', '"theirs"')]
    assert env.ok("--fresh", "show", str(a))["meta"] == {"tokens": "newer"}  # the pull keeps the user's value
    assert env.sql("SELECT value FROM pending_meta") == [('"newer"',)]
    env.ok("sync")
    assert '"tokens":"newer"' in fake.issue(a)["body"]


def test_failed_write_names_what_was_applied_and_leaves_the_cache_alone(env, fake):
    a, b = env.ok("add", "A")["id"], env.ok("add", "B")["id"]
    before = env.sql("SELECT id FROM tasks")
    fake.fault(fail_after=2)
    err = env.fail("add", "C", "--depends", str(a), str(b))
    assert "applied: created #3; not applied: dependency #-1 -> #1, dependency #-1 -> #2" in err and "HTTP 502" in err
    assert env.sql("SELECT id FROM tasks") == before and env.sql("SELECT * FROM deps") == []
    assert [t["title"] for t in env.ok("--fresh", "ls")] == ["A", "B", "C"]  # GitHub wins: the created issue shows up
    assert env.ok("show", "3")["depends_on"] == []


def test_a_refused_dependency_by_github_rolls_back_too(env, fake):
    a, b = env.ok("add", "A")["id"], env.ok("add", "B")["id"]
    fake.add_blocker(a, b)  # in the browser; the cache does not know yet
    env.age(0)
    env.fake.fault(fail_after=0)
    err = env.fail("dep", "add", str(b), str(a))  # the refresh before validation sees the cycle
    assert "cycle" in err


def test_rate_limit_stops_with_the_reset_time_and_does_not_retry(env, fake):
    env.ok("add", "A")
    reset = int(time.time()) + 900
    fake.fault(rate_limited=reset)
    fake.clear_log()
    err = env.fail("--fresh", "ls")
    assert "rate limit" in err and "try again after" in err
    assert len(fake.calls()) == 1
    fake.fault(rate_limited=False)
    assert titles(env.ok("--fresh", "ls")) == ["A"]


def test_rm_closes_as_not_planned_with_the_label_and_the_task_leaves_the_cache(env, fake):
    p = env.ok("add", "P")["id"]
    c = env.ok("add", "C", "--parent", str(p))["id"]
    d = env.ok("add", "D", "--depends", str(c))["id"]
    assert env.ok("rm", str(p), "--recursive") == {"deleted": p, "descendants": [c]}
    for n in (p, c):
        issue = fake.issue(n)
        assert (issue["state"], issue["state_reason"], "tg:removed" in issue["labels"]) == ("closed", "not_planned", True)
    assert [t["id"] for t in env.ok("--fresh", "ls", "--status", "open", "ready", "blocked", "done")] == [d]
    assert env.ok("show", str(d))["depends_on"] == []
    assert fake.state()["blocked_by"][str(d)] == []
    assert env.ok("show", str(d))["conflicts"] == []


def test_a_parent_chain_of_nine_and_a_51st_blocker_are_refused_before_any_call(env, fake):
    ids = [env.ok("add", "t0")["id"]]
    for i in range(1, 8):
        ids.append(env.ok("add", f"t{i}", "--parent", str(ids[-1]))["id"])
    assert len(ids) == 8
    fake.clear_log()
    err = env.fail("add", "too deep", "--parent", str(ids[-1]))
    assert "9 issues deep" in err and "GitHub allows 8" in err
    blockers = [env.ok("add", f"b{i}")["id"] for i in range(50)]
    goal = env.ok("add", "goal", "--depends", *map(str, blockers))["id"]
    fake.clear_log()
    extra = env.ok("add", "one more")["id"]
    fake.clear_log()
    assert "51 blockers" in env.fail("dep", "add", str(goal), str(extra))
    assert env.writes() == []
    assert len(fake.state()["blocked_by"][str(goal)]) == 50


def test_a_parent_blocked_by_its_own_child_is_a_conflict_not_a_crash(env, fake):
    p = env.ok("add", "P")["id"]
    c = env.ok("add", "C", "--parent", str(p))["id"]
    fake.add_blocker(p, c)  # GitHub accepts it (G3)
    shown = env.ok("--fresh", "show", str(p))
    assert any("ancestor or descendant" in x["message"] for x in shown["conflicts"])
    assert any("ancestor or descendant" in x["message"] for x in env.ok("show", str(c))["conflicts"])
    code, out, _ = tg_text(env, "ls")
    assert out.count("(conflict)") == 2
    agenda = env.ok("agenda")
    assert len(agenda["conflicts"]) == 1  # one row, not one per task
    # a later write that does not add a break still works
    assert env.ok("edit", str(c), "--title", "C renamed")["title"] == "C renamed"
    assert env.ok("add", "other", "--parent", str(p))["parent"] == p


def test_an_edge_to_a_non_task_is_a_conflict_and_to_a_removed_task_is_silent(env, fake):
    a = env.ok("add", "A")["id"]
    plain = fake.add_issue("not a task", labels=())["number"]
    gone = fake.add_issue("removed", labels=("taskgraph", "tg:removed"))["number"]
    fake.add_blocker(a, plain)
    fake.add_blocker(a, gone)
    shown = env.ok("--fresh", "show", str(a))
    assert [c["message"] for c in shown["conflicts"]] == [f"#{a} is blocked by #{plain}, which has no taskgraph label"]


def test_broken_meta_block_is_a_conflict_and_blocks_body_writes(env, fake):
    n = fake.add_issue("t", body="notes\n\n<!-- taskgraph:meta v1\n{oops\ntaskgraph:end -->\n")["number"]
    shown = env.ok("show", str(n))
    assert [c["message"] for c in shown["conflicts"]] == [f"meta block on #{n} is broken; fix or delete it on GitHub"]
    assert "is broken" in env.fail("edit", str(n), "--meta", "a=1")
    assert env.ok("done", str(n))["status"] == "done"  # a status change does not touch the body


def test_a_person_creating_an_issue_with_the_label_enters_tg_with_the_body_as_notes(env, fake):
    n = fake.add_issue("typed in the browser", body="just text")["number"]
    t = env.ok("show", str(n))
    assert (t["notes"], t["meta"], t["type"]) == ("just text", {}, "task")


def test_pull_writes_events_so_changes_lists_a_persons_date_change(env, fake):
    block = '\n\n<!-- taskgraph:meta v1\n{"due":"%s"}\ntaskgraph:end -->\n'
    a = fake.add_issue("A", body=block % "2026-11-01")["number"]
    env.ok("ls")  # the first pull: history starts here
    fake.edit_issue(a, body=block % "2026-11-05")
    env.ok("--fresh", "ls")
    slipped = env.ok("changes", "--since", "1d")["slipped"]
    assert [(s["id"], s["from"], s["to"]) for s in slipped] == [(a, "2026-11-01", "2026-11-05")]


def test_history_starts_at_the_first_pull(env, fake):
    fake.add_issue("old")
    env.ok("ls")
    assert env.sql("SELECT * FROM events") == []
    assert [t["title"] for t in env.ok("changes", "--since", "1d")["new"]] == []


def test_result_add_posts_a_comment_and_needs_no_refresh(env, fake):
    a = env.ok("add", "A")["id"]
    fake.clear_log()
    row = env.ok("result", "add", str(a), "--status", "PASS", "--attempt", "1", "--by", "w", "--body", "all good\nline 2")
    assert row["status"] == "PASS" and row["body"] == "all good\nline 2"
    assert [c["method"] for c in fake.calls()] == ["GET", "POST"]
    assert env.ok("result", "ls", str(a))[0]["body"] == "all good\nline 2"
    fake.clear_log()
    env.age(31)
    assert env.ok("--fresh", "result", "ls", str(a))[0]["id"] == row["id"]  # a pull reads the comment and agrees
    assert "no such task: 99" in env.fail("result", "add", "99", "--status", "PASS")


def test_result_from_another_machine_arrives_with_the_pull(env, fake):
    a = env.ok("add", "A")["id"]
    from tgstore.base import ResultInput
    from tgstore.github import comments as cm
    for text in cm.render_result(ResultInput("ISSUES", "verify", 2, "other-host", "found 2 problems"), "2026-11-08T09:00:00Z"):
        fake.add_comment(a, text)
    fake.add_comment(a, "a human remark")
    rows = env.ok("--fresh", "result", "ls", str(a))
    assert [(r["status"], r["kind"], r["attempt"], r["author"], r["body"]) for r in rows] == [("ISSUES", "verify", 2, "other-host", "found 2 problems")]


def test_status_changes_go_to_github(env, fake):
    a = env.ok("add", "A")["id"]
    env.ok("done", str(a))
    assert (fake.issue(a)["state"], fake.issue(a)["state_reason"]) == ("closed", "completed")
    env.ok("reopen", str(a))
    assert fake.issue(a)["state"] == "open" and fake.issue(a)["labels"] == ["taskgraph"]
    t = env.ok("--fresh", "show", str(a))
    assert t["status"] == "open" and t["done_at"] is None


def test_edit_title_notes_type_and_parent(env, fake):
    p, c = env.ok("add", "P")["id"], env.ok("add", "C")["id"]
    env.ok("edit", str(c), "--title", "C2", "--notes", "new notes", "--parent", str(p), "--type", "task")
    issue = fake.issue(c)
    assert issue["title"] == "C2" and issue["body"] == "new notes" and fake.state()["parent"] == {str(c): p}
    env.ok("edit", str(c), "--no-parent")
    assert fake.state()["parent"] == {}
    env.ok("edit", str(c), "--type", "decision")
    assert "tg:type:decision" in fake.issue(c)["labels"]
    env.ok("edit", str(c), "--type", "task")
    assert fake.issue(c)["labels"] == ["taskgraph"]


def test_priority_is_written_through_as_a_label_and_not_into_the_body(env, fake):
    t = env.ok("add", "Ship it", "--priority", "P1", "--meta", "lane=core")
    assert t["priority"] == "P1" and t["meta"] == {"priority": "P1", "lane": "core"}
    issue = fake.issue(t["id"])
    assert issue["labels"] == ["taskgraph", "tg:priority:P1"] and "priority" not in issue["body"] and '"lane":"core"' in issue["body"]
    assert env.ok("--fresh", "show", str(t["id"]))["priority"] == "P1"
    env.ok("edit", str(t["id"]), "--priority", "P0", "--type", "decision")
    assert fake.issue(t["id"])["labels"] == ["taskgraph", "tg:type:decision", "tg:priority:P0"]
    env.ok("edit", str(t["id"]), "--no-priority")
    assert fake.issue(t["id"])["labels"] == ["taskgraph", "tg:type:decision"] and "priority" not in fake.issue(t["id"])["body"]
    shown = env.ok("--fresh", "show", str(t["id"]))
    assert shown["priority"] is None and "priority" not in shown["meta"]
    plain = env.ok("add", "No priority")
    assert fake.issue(plain["id"])["labels"] == ["taskgraph"] and plain["priority"] is None


def test_a_priority_edit_with_nothing_else_is_one_patch_of_the_labels(env, fake):
    n = env.ok("add", "A", "--priority", "P3")["id"]
    fake.clear_log()
    env.ok("edit", str(n), "--priority", "P2")
    writes = [(c["method"], c["path"]) for c in env.writes()]
    assert writes == [("PATCH", f"repos/o/demo/issues/{n}")] and fake.issue(n)["labels"] == ["taskgraph", "tg:priority:P2"]
    fake.clear_log()
    env.ok("edit", str(n), "--priority", "P2")  # the same value: nothing to send
    assert env.writes() == []


def test_the_four_priority_labels_are_created_with_the_first_write(env, fake):
    env.ok("add", "A")
    assert {"tg:priority:P0", "tg:priority:P1", "tg:priority:P2", "tg:priority:P3"} <= set(fake.state()["labels"])


def test_a_persons_priority_label_is_pulled_and_the_label_wins_over_the_body(env, fake):
    n = fake.add_issue("t", body='text\n\n<!-- taskgraph:meta v1\n{"priority":"P0","lane":"x"}\ntaskgraph:end -->\n')["number"]
    t = env.ok("show", str(n))
    assert t["priority"] is None and t["meta"] == {"lane": "x"}  # a stray key in the block does not count
    fake.edit_issue(n, labels=["taskgraph", "tg:priority:P2"])
    t = env.ok("--fresh", "show", str(n))
    assert t["priority"] == "P2" and t["meta"] == {"priority": "P2", "lane": "x"}
    assert [x["id"] for x in env.ok("ls", "--priority", "P2")] == [n]
    fake.edit_issue(n, labels=["taskgraph", "tg:priority:P1"])
    assert env.ok("--fresh", "show", str(n))["priority"] == "P1"
    fake.edit_issue(n, labels=["taskgraph"])
    assert env.ok("--fresh", "show", str(n))["priority"] is None
    rows = env.sql("SELECT field, old, new FROM events WHERE task_id=? AND field='priority' ORDER BY id", n)
    assert [(f, json.loads(o) if o else None, json.loads(w) if w else None) for f, o, w in rows] == [("priority", None, "P2"), ("priority", "P2", "P1"), ("priority", "P1", None)]


def test_a_task_carries_at_most_one_priority_label(env, fake):
    n = fake.add_issue("t")["number"]
    fake.edit_issue(n, labels=["taskgraph", "tg:priority:P3", "tg:priority:P1", "tg:priority:P9"])
    t = env.ok("--fresh", "show", str(n))
    assert t["priority"] == "P1"  # the highest of the valid ones
    messages = [c["message"] for c in t["conflicts"]]
    assert f"#{n} has more than one priority label; the highest counts" in messages and f"#{n} has the label tg:priority:P9, which is not a priority" in messages
    env.ok("edit", str(n), "--priority", "P2")
    assert fake.issue(n)["labels"] == ["taskgraph", "tg:priority:P2"]
    fake.edit_issue(n, labels=["taskgraph", "tg:priority:P0", "tg:priority:P3"])
    env.ok("--fresh", "ls")
    env.ok("edit", str(n), "--no-priority")
    assert fake.issue(n)["labels"] == ["taskgraph"]


def test_dep_rm_and_date(env, fake):
    a, b = env.ok("add", "A")["id"], env.ok("add", "B", "--depends", "1")["id"]
    env.ok("dep", "rm", str(b), str(a))
    assert fake.state()["blocked_by"][str(b)] == []
    env.ok("date", str(a), "--due", "2026-12-01")
    assert '"due":"2026-12-01"' in fake.issue(a)["body"]


def test_two_tg_processes_share_one_refresh(env, fake):
    fake.add_issue("a")
    env.ok("ls")
    env.age(31)
    fake.clear_log()
    # the lock is free: one probe; a held lock makes a non-fresh read use the cache as it is
    import fcntl
    with open(f"{env.cache}.lock", "a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert titles(env.ok("ls")) == ["a"]
    assert fake.calls() == []
    assert titles(env.ok("ls")) == ["a"] and len(fake.calls()) == 2  # the page, and the newest comment


def test_a_write_refreshes_before_it_validates(env, fake):
    a = env.ok("add", "A")["id"]
    b = fake.add_issue("B by a person")["number"]
    fake.add_blocker(a, b)
    err = env.fail("dep", "add", str(b), str(a))  # the cache did not know the edge a -> b; the refresh did
    assert "cycle" in err


def test_sync_command_flushes_and_refreshes_and_full_reads_everything(env, fake):
    a = env.ok("add", "A")["id"]
    env.ok("edit", str(a), "--meta", 'tokens="3"')
    fake.add_issue("from a person")
    done = env.ok("sync")
    assert done == {"changed": 2, "flushed": 1, "full": False}  # A has no known content since its own write, so it is re-read
    assert '"tokens":"3"' in fake.issue(a)["body"]
    code, out, _ = tg_text(env, "sync")
    assert out.strip() == "synced: 1 changed, 0 deferred sent"  # the flush came after the pull: the next one re-reads A
    code, out, _ = tg_text(env, "sync")
    assert out.strip() == "synced: 0 changed, 0 deferred sent"
    env.ok("sync", "--full")
    fake.clear_log()
    assert env.ok("sync", "--full")["full"] is True
    paths = [(c["status"], c["counted"]) for c in fake.calls() if "issues?labels" in c["path"]]
    assert paths == [(304, False)]  # the page probe of a full pull is still conditional
    assert any(c["path"] == "graphql" for c in fake.calls())  # but every task's edges are read again
    assert any("issues/comments" in c["path"] for c in fake.calls())  # and every comment


def test_a_full_pull_notices_a_task_that_is_gone(env, fake):
    a, b = fake.add_issue("a")["number"], fake.add_issue("b")["number"]
    fake.edit_issue(b, created_at="2026-01-01T00:00:00Z")
    env.ok("ls")
    fake.edit_issue(b, labels=[])  # label removed in the browser: invisible to a page probe, found by the full pull
    env.ok("--fresh", "ls")
    assert [t["id"] for t in env.ok("ls")] == [a, b]
    env.ok("sync", "--full")
    assert [t["id"] for t in env.ok("ls")] == [a]
    assert env.ok("changes", "--since", "1d")["removed"][0]["id"] == b


def test_a_task_the_list_page_lags_behind_is_found_by_id_and_not_dropped_by_a_full_pull(env, fake):
    env.ok("ls")
    before = env.sql("SELECT value FROM sync_state WHERE key='last_pull_at'")
    n = fake.add_issue("made on another machine one second ago")["number"]
    fake.fault(hide_from_list=[n])  # GitHub's list page does not show it yet; the issue itself is there
    assert env.ok("show", str(n))["title"] == "made on another machine one second ago"
    assert env.run("show", "99")[0] == 1  # an id that does not exist is still an error
    assert env.sql("SELECT value FROM sync_state WHERE key='last_pull_at'") == before  # reading one task by id is not a pull
    env.ok("sync", "--full")  # a full pull whose pages lack a task younger than two minutes does not drop it
    assert [t["id"] for t in env.ok("ls")] == [n]
    fake.fault(hide_from_list=[])
    env.ok("--fresh", "ls")
    assert [t["id"] for t in env.ok("ls")] == [n]


def test_a_full_pull_sends_deferred_rows_older_than_15_minutes(env, fake):
    a = env.ok("add", "A")["id"]
    env.ok("edit", str(a), "--meta", 'tokens="7"')
    env.age(31)
    env.ok("ls")  # not a full pull yet, and the row is young: nothing is sent
    assert "tokens" not in fake.issue(a)["body"]
    with closing(sqlite3.connect(env.cache)) as db, db:
        db.execute("UPDATE pending_meta SET at='2020-01-01T00:00:00Z'")
        db.execute("UPDATE sync_state SET value=? WHERE key='last_full_at'", (json.dumps(time.time() - 700),))
    env.age(31)
    env.ok("ls")
    assert '"tokens":"7"' in fake.issue(a)["body"] and env.sql("SELECT * FROM pending_meta") == []
