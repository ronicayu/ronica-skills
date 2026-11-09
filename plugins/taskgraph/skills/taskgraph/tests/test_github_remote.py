import pytest

from tgstore.base import RemoteError, ResultInput, StoreError
from tgstore.config import Entry
from tgstore.github.remote import GitHubRemote, fingerprint, task_from_item
from tgstore.remote import Create, Edit, Plan, SyncState, canon


@pytest.fixture
def remote(fake):
    return GitHubRemote(Entry("demo", "github", "o/demo"))


def counted(fake):
    return [c for c in fake.calls() if c["counted"]]


def sync(remote, state, full=False):
    probe = remote.probe(state)
    delta = remote.pull(state, probe, full=full)
    state.pages = probe.info
    state.fingerprints.update(delta.fingerprints)
    return probe, delta


def test_first_probe_reads_every_page_and_the_next_one_is_all_304(remote, fake):
    for i in range(3):
        fake.add_issue(f"t{i}")
    fake.add_issue("not a task", labels=())  # no label: not on the list
    fake.add_issue("a labelled pull request", pull_request=True)
    state = SyncState()
    probe, delta = sync(remote, state)
    assert sorted(t.number for t in delta.tasks) == [1, 2, 3] and probe.changed
    fake.clear_log()
    probe, delta = sync(remote, state)
    assert not probe.changed and delta.tasks == []
    assert [(c["status"], c["counted"]) for c in fake.calls()] == [(304, False)]


def test_two_hundred_tasks_take_three_page_requests_when_nothing_changed(remote, fake):
    with fake.locked() as s:
        for i in range(200):
            fake.new_issue(s, f"t{i}", labels=["taskgraph"])
    state = SyncState()
    sync(remote, state)
    fake.clear_log()
    sync(remote, state)
    assert [c["status"] for c in fake.calls()] == [304, 304, 304]  # 200 items fill two pages; the third page is empty


def test_an_edit_and_a_dependency_without_updated_at_both_show_in_the_next_pull(remote, fake):
    a, b = fake.add_issue("a")["number"], fake.add_issue("b")["number"]
    state = SyncState()
    sync(remote, state)
    fake.add_blocker(b, a)  # no updated_at change
    probe, delta = sync(remote, state)
    assert [t.number for t in delta.tasks] == [a, b] and delta.edges == {a: [], b: [a]}  # the blocker's summary changes too
    fake.edit_issue(a, title="renamed")
    probe, delta = sync(remote, state)
    assert [(t.number, t.title) for t in delta.tasks] == [(a, "renamed")] and delta.edges == {}


def test_comments_are_read_only_for_issues_whose_count_changed(remote, fake):
    a, b = fake.add_issue("a")["number"], fake.add_issue("b")["number"]
    state = SyncState()
    sync(remote, state)
    fake.add_comment(a, "just talk")
    fake.clear_log()
    probe, delta = sync(remote, state)
    paths = [c["path"] for c in fake.calls()]
    assert any(p.startswith(f"repos/o/demo/issues/{a}/comments") for p in paths) and not any(f"/issues/{b}/" in p for p in paths)
    assert delta.results == {a: []} and delta.claims == {a: []}


def test_removed_label_is_reported_and_a_labelled_pr_is_skipped(remote, fake):
    a = fake.add_issue("gone", labels=("taskgraph", "tg:removed"))["number"]
    fake.add_issue("pr", pull_request=True)
    probe, delta = sync(remote, SyncState())
    assert delta.removed == [a] and delta.tasks == []


def test_task_from_item_maps_state_labels_parent_and_block():
    body = "notes\n\n<!-- taskgraph:meta v1\n{\"lane\":\"core\",\"type\":\"x\"}\ntaskgraph:end -->\n"
    item = {"number": 4, "id": 9, "node_id": "n", "title": "t", "body": body, "state": "open", "labels": [{"name": "taskgraph"}, {"name": "tg:in-progress"}, {"name": "tg:type:decision"}, {"name": "tg:type:bogus"}],
            "created_at": "c", "updated_at": "u", "closed_at": None, "parent_issue_url": "https://api.github.com/repos/o/r/issues/2", "comments": 3}
    t = task_from_item(item)
    assert (t.status, t.type, t.parent, t.notes, t.meta, t.comments) == ("in_progress", "decision", 2, "notes", {"lane": "core"}, 3)
    assert t.problems == ["type:tg:type:bogus"]
    assert task_from_item(dict(item, state="closed", labels=[])).status == "done"
    assert fingerprint(item)["all"] != fingerprint(dict(item, title="u"))["all"]


def test_task_from_item_reads_the_priority_from_the_label():
    def item(*labels, body=""):
        return {"number": 4, "id": 9, "title": "t", "body": body, "state": "open", "labels": [{"name": n} for n in ("taskgraph", *labels)],
                "created_at": "c", "updated_at": "u", "closed_at": None}

    assert task_from_item(item()).priority is None
    assert task_from_item(item("tg:priority:P2")).priority == "P2" and task_from_item(item("tg:priority:P2")).problems == []
    stray = '<!-- taskgraph:meta v1\n{"priority":"P0"}\ntaskgraph:end -->\n'
    assert (task_from_item(item(body=stray)).priority, task_from_item(item(body=stray)).meta) == (None, {})
    many = task_from_item(item("tg:priority:P3", "tg:priority:P1", "tg:priority:P7"))
    assert many.priority == "P1" and many.problems == ["priority:tg:priority:P7", "two_priorities"]


def test_push_creates_then_links_parent_then_edges_and_reports_ids(remote, fake):
    p = fake.add_issue("parent")["number"]
    x = fake.add_issue("x")["number"]
    plan = Plan(created=[Create(-1, "child", "why", "decision", p, {"lane": "core"})], edges_added=[(-1, x)], db_ids={p: fake.issue(p)["id"], x: fake.issue(x)["id"]})
    fake.clear_log()
    pushed = remote.push(plan, {})
    assert pushed.ids == {-1: 3}
    issue = fake.issue(3)
    assert issue["labels"] == ["taskgraph", "tg:type:decision"] and "lane" in issue["body"]
    state = fake.state()
    assert state["parent"]["3"] == p and state["blocked_by"]["3"] == [x]
    assert [(c["method"], c["path"].split("/", 3)[-1]) for c in fake.calls()] == [
        ("POST", "issues"), ("POST", f"issues/{p}/sub_issues"), ("POST", "issues/3/dependencies/blocked_by")]


def test_push_failure_names_what_was_applied_and_what_was_not(remote, fake):
    a, b = fake.add_issue("a")["number"], fake.add_issue("b")["number"]
    fake.fault(fail_after=2)
    plan = Plan(created=[Create(-1, "new", "", "task", None, {})], edges_added=[(-1, a), (-1, b)], db_ids={a: fake.issue(a)["id"], b: fake.issue(b)["id"]})
    with pytest.raises(RemoteError) as caught:
        remote.push(plan, {})
    assert "applied: created #3; not applied: dependency #-1 -> #" in str(caught.value) and "HTTP 502" in str(caught.value)
    assert caught.value.applied == ("created #3",) and len(caught.value.not_applied) == 2


def test_edit_sends_only_what_differs_and_keeps_human_text(remote, fake):
    n = fake.add_issue("t", body="human text\n\n<!-- taskgraph:meta v1\n{\"keep\":1,\"lane\":\"a\"}\ntaskgraph:end -->\n")["number"]
    fresh = {n: remote.fetch(n)}
    fake.clear_log()
    pushed = remote.push(Plan(edits=[Edit(n, status="in_progress", meta_set={"lane": "b"})]), fresh)
    issue = fake.issue(n)
    assert issue["labels"] == ["taskgraph", "tg:in-progress"] and "human text" in issue["body"] and '"keep":1,"lane":"b"' in issue["body"]
    assert [c["method"] for c in fake.calls()] == ["PATCH"] and pushed.meta[n] == {"keep": 1, "lane": "b"}
    fake.clear_log()
    remote.push(Plan(edits=[Edit(n, status="in_progress")]), {n: remote.fetch(n)})
    assert [c["method"] for c in fake.calls()] == ["GET"]  # nothing differs: no PATCH


def test_done_closes_as_completed_and_reopen_clears_the_label(remote, fake):
    n = fake.add_issue("t", labels=("taskgraph", "tg:in-progress"))["number"]
    remote.push(Plan(edits=[Edit(n, status="done")]), {n: remote.fetch(n)})
    issue = fake.issue(n)
    assert (issue["state"], issue["state_reason"], issue["labels"]) == ("closed", "completed", ["taskgraph"])
    remote.push(Plan(edits=[Edit(n, status="open")]), {n: remote.fetch(n)})
    assert fake.issue(n)["state"] == "open"


def test_pending_rows_ride_along_and_a_changed_key_is_dropped(remote, fake):
    n = fake.add_issue("t", body="\n\n<!-- taskgraph:meta v1\n{\"tokens\":\"1\",\"model\":\"old\"}\ntaskgraph:end -->\n")["number"]
    rows = [{"key": "tokens", "op": "set", "value": canon("2"), "base": canon("1")},
            {"key": "model", "op": "set", "value": canon("new"), "base": canon("older")},  # GitHub has "old", not "older"
            {"key": "started_at", "op": "set", "value": canon("t0"), "base": None}]
    pushed = remote.push(Plan(edits=[Edit(n, status="done", pending=rows)]), {n: remote.fetch(n)})
    assert pushed.dropped == [(n, "model")] and pushed.flushed == {n}
    assert pushed.meta[n] == {"tokens": "2", "model": "old", "started_at": "t0"}
    # without another reason to PATCH, rows stay pending
    m = fake.add_issue("u")["number"]
    fake.clear_log()
    pushed = remote.push(Plan(edits=[Edit(m, meta_set={}, pending=rows[:1])]), {m: remote.fetch(m)})
    assert pushed.flushed == set() and [c["method"] for c in fake.calls()] == ["GET"]
    pushed = remote.push(Plan(edits=[Edit(m, pending=[dict(rows[2])], flush=True)]), {m: remote.fetch(m)})
    assert pushed.flushed == {m} and fake.issue(m)["body"].count("started_at") == 1


def test_a_broken_block_refuses_a_body_write_but_not_a_status_write(remote, fake):
    n = fake.add_issue("t", body="x\n\n<!-- taskgraph:meta v1\n{oops\ntaskgraph:end -->\n")["number"]
    with pytest.raises(StoreError, match="meta block on #1 is broken"):
        remote.push(Plan(edits=[Edit(n, meta_set={"a": 1})]), {n: remote.fetch(n)})
    pushed = remote.push(Plan(edits=[Edit(n, status="done", pending=[{"key": "k", "op": "set", "value": "1", "base": None}])]), {n: remote.fetch(n)})
    assert fake.issue(n)["state"] == "closed" and "oops" in fake.issue(n)["body"] and pushed.flushed == set()


def test_remove_closes_not_planned_with_the_label_and_detaches_edges(remote, fake):
    p, a, b = (fake.add_issue(t)["number"] for t in "pab")
    fake.set_parent(a, p)
    fake.add_blocker(a, b)
    ids = {n: fake.issue(n)["id"] for n in (p, a, b)}
    plan = Plan(removed=[a], edges_removed=[(a, b)], db_ids=ids)
    remote.push(plan, {a: remote.fetch(a)})
    issue, state = fake.issue(a), fake.state()
    assert (issue["state"], issue["state_reason"], "tg:removed" in issue["labels"]) == ("closed", "not_planned", True)
    assert str(a) not in state["parent"] and state["blocked_by"][str(a)] == []


def test_a_body_over_the_limit_is_refused_before_any_call(remote, fake):
    n = fake.add_issue("t")["number"]
    fresh = {n: remote.fetch(n)}
    fake.clear_log()
    with pytest.raises(StoreError, match="body would be 260,001 bytes"):
        remote.push(Plan(edits=[Edit(n, notes="x" * 260001)]), fresh)
    assert fake.calls() == []


def test_post_result_splits_into_parts_and_returns_the_first_comment_id(remote, fake):
    n = fake.add_issue("t")["number"]
    row = remote.post_result(n, ResultInput("PASS", "task", 1, "w", "line\n" * 120_000))
    comments = fake.comments(n)
    assert len(comments) == 3 and row["id"] == min(c["id"] for c in comments)
    assert remote.read_comments(n)[0]["result"]["parts"] == 3


def test_ensure_setup_creates_only_missing_labels(remote, fake):
    fake.fault(labels=["taskgraph"])
    remote.ensure_setup(["taskgraph", "tg:in-progress", "tg:removed"])
    assert fake.state()["labels"] == ["taskgraph", "tg:in-progress", "tg:removed"]
    fake.clear_log()
    remote.ensure_setup(["taskgraph", "tg:in-progress"])
    assert [c["method"] for c in fake.calls()] == ["GET"]
