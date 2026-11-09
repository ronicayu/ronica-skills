import time

import pytest

from tgstore.base import RateLimited, RemoteError, StoreError
from tgstore.github.gh import Gh, HttpError

REPO = "repos/o/demo"
LIST = f"{REPO}/issues?labels=taskgraph&state=all&sort=created&direction=asc"


@pytest.fixture
def gh(fake):
    return Gh()


def make(gh, title="t", body="", labels=("taskgraph",)):
    return gh.post(f"{REPO}/issues", {"title": title, "body": body, "labels": list(labels)}).body


def test_issue_numbers_are_shared_with_pull_requests(gh, fake):
    assert make(gh)["number"] == 1
    fake.add_issue("a pull request", labels=(), pull_request=True)
    assert make(gh)["number"] == 3
    items = gh.get(f"{REPO}/issues?state=all&direction=asc").body
    assert [bool(i.get("pull_request")) for i in items] == [False, True, False]


def test_page_etag_gives_304_and_the_call_is_not_counted(gh, fake):
    make(gh)
    first = gh.get(f"{LIST}&per_page=100&page=1")
    again = gh.get(f"{LIST}&per_page=100&page=1", etag=first.headers["etag"])
    assert (first.status, again.status, again.body) == (200, 304, None)
    assert first.headers["etag"].startswith('W/"')
    assert [c["counted"] for c in fake.calls()[-2:]] == [True, False]
    make(gh)
    assert gh.get(f"{LIST}&per_page=100&page=1", etag=first.headers["etag"]).status == 200


def test_dependencies_and_comments_do_not_move_updated_at(gh, fake):
    a, b = make(gh), make(gh)
    fake.edit_issue(a["number"], updated_at="2026-01-01T00:00:00Z")
    fake.edit_issue(b["number"], updated_at="2026-01-01T00:00:00Z")
    gh.post(f"{REPO}/issues/{a['number']}/dependencies/blocked_by", {"issue_id": b["id"]})
    gh.post(f"{REPO}/issues/{a['number']}/comments", {"body": "hello"})
    one = gh.get(f"{REPO}/issues/{a['number']}").body
    assert one["updated_at"] == "2026-01-01T00:00:00Z"
    assert one["issue_dependencies_summary"]["total_blocked_by"] == 1 and one["comments"] == 1
    assert gh.get(f"{REPO}/issues/{b['number']}").body["issue_dependencies_summary"]["total_blocking"] == 1


def test_cycle_and_self_dependency_are_refused_but_a_parent_blocked_by_its_child_is_not(gh):
    a, b, c = make(gh), make(gh), make(gh)
    dep = lambda x, y: gh.post(f"{REPO}/issues/{x['number']}/dependencies/blocked_by", {"issue_id": y["id"]})
    dep(a, b)
    for x, y in ((b, a), (c, c)):
        with pytest.raises(HttpError) as caught:
            dep(x, y)
        assert caught.value.status == 422 and "VALIDATION" not in str(caught.value) and "422" in str(caught.value)
    gh.post(f"{REPO}/issues/{a['number']}/sub_issues", {"sub_issue_id": c["id"]})
    assert dep(a, c).status == 201  # G3: GitHub accepts it


def test_a_ninth_issue_in_a_parent_chain_is_refused(gh):
    chain = [make(gh) for _ in range(9)]
    for parent, child in zip(chain, chain[1:8]):
        gh.post(f"{REPO}/issues/{parent['number']}/sub_issues", {"sub_issue_id": child["id"]})
    with pytest.raises(HttpError) as caught:
        gh.post(f"{REPO}/issues/{chain[7]['number']}/sub_issues", {"sub_issue_id": chain[8]["id"]})
    assert caught.value.status == 422 and "7 layers" in str(caught.value)


def test_more_than_50_blockers_are_accepted_and_read_back_in_pages(gh, fake):
    target = make(gh)
    others = [make(gh) for _ in range(120)]
    for o in others:
        gh.post(f"{REPO}/issues/{target['number']}/dependencies/blocked_by", {"issue_id": o["id"]})
    data = gh.graphql(f'query Edges {{ repository(owner: "o", name: "demo") {{ i{target["number"]}: issue(number: {target["number"]}) {{ blockedBy(first: 100) {{ totalCount }} }} }} }}')
    assert data["repository"][f"i{target['number']}"]["blockedBy"]["totalCount"] == 120


def test_an_issue_body_is_truncated_silently_and_a_comment_is_refused(gh):
    issue = make(gh)
    big = gh.patch(f"{REPO}/issues/{issue['number']}", {"body": "é" * 131073}).body
    assert len(big["body"].encode()) == 262144
    with pytest.raises(HttpError) as caught:
        gh.post(f"{REPO}/issues/{issue['number']}/comments", {"body": "x" * 262145})
    assert caught.value.status == 422
    assert gh.post(f"{REPO}/issues/{issue['number']}/comments", {"body": "x" * 262144}).status == 201


def test_comment_ids_grow_and_hidden_ids_vanish_for_a_few_reads(gh, fake):
    issue = make(gh)
    ids = [gh.post(f"{REPO}/issues/{issue['number']}/comments", {"body": str(i)}).body["id"] for i in range(3)]
    assert ids == sorted(ids) and len(set(ids)) == 3
    fake.fault(hide_comment_ids={"ids": [ids[0]], "reads": 1})
    seen = lambda: [c["id"] for c in gh.get(f"{REPO}/issues/{issue['number']}/comments").body]
    assert seen() == ids[1:] and seen() == ids


def test_fail_after_fails_exactly_the_nth_write(gh, fake):
    make(gh)
    fake.fault(fail_after=2)
    make(gh)
    with pytest.raises(HttpError) as caught:
        make(gh)
    assert caught.value.status == 502
    make(gh)


def test_rate_limit_raises_with_the_reset_time_and_gh_stops_asking(gh, fake):
    reset = int(time.time()) + 600
    fake.fault(rate_limited=reset)
    with pytest.raises(RateLimited) as caught:
        gh.get(f"{REPO}/issues/1")
    assert caught.value.reset_at.endswith("Z") and "try again after" in str(caught.value)
    before = len(fake.calls())
    with pytest.raises(RateLimited):
        gh.get(f"{REPO}/issues/1")
    assert len(fake.calls()) == before  # the second call never left the process


def test_unknown_issue_is_an_http_error_with_its_status(gh):
    with pytest.raises(HttpError) as caught:
        gh.get(f"{REPO}/issues/99")
    assert caught.value.status == 404


def test_gh_missing_and_gh_failing_have_clear_errors(monkeypatch):
    monkeypatch.setenv("TASKGRAPH_GH", "/nonexistent/gh")
    with pytest.raises(StoreError, match="gh is not installed"):
        Gh().get("user")
    monkeypatch.setenv("TASKGRAPH_GH", "sh -c 'echo To get started with GitHub CLI, please run: gh auth login >&2; exit 4' --")
    with pytest.raises(StoreError) as caught:
        Gh().get("user")
    assert str(caught.value) == "gh is not logged in for github.com; run gh auth login"
    monkeypatch.setenv("TASKGRAPH_GH", "sh -c 'echo dial tcp: lookup api.github.com >&2; exit 1' --")
    with pytest.raises(RemoteError, match="cannot reach GitHub"):
        Gh().get("user")


def test_writes_are_paced(gh, monkeypatch):
    monkeypatch.setenv("TASKGRAPH_GH_PACE", "0.4")
    make(gh)
    start = time.monotonic()
    make(gh)
    assert time.monotonic() - start >= 0.35
    start = time.monotonic()
    gh.get("user")
    assert time.monotonic() - start < 0.35  # reads are not paced


def test_clock_offset_moves_comment_times_and_the_date_header(gh, fake):
    issue = make(gh)
    fake.fault(clock_offset=3600)
    c = gh.post(f"{REPO}/issues/{issue['number']}/comments", {"body": "x"})
    assert c.body["created_at"] > issue["created_at"] and gh.server_time - time.time() > 3500
