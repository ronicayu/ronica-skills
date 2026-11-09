import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import tg
from tgstore.base import ClaimLost
from tgstore.cached import CachedRemoteStore
from tgstore.config import Entry
from tgstore.github import comments as cm
from tgstore.github.remote import GitHubRemote
from test_cached_store import Env, tg_text

SCRIPT = Path(tg.__file__).resolve()


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setenv("TASKGRAPH_TODAY", "2026-10-13")


@pytest.fixture
def env(fake, tmp_path, monkeypatch):
    monkeypatch.setenv("TASKGRAPH_CLAIMANT", "alice@host:1")
    return Env(fake, tmp_path, monkeypatch)


def claim_comments(fake, n):
    return [(c["id"], cm.parse_comment({**c, "user": {"login": c["user"]}})) for c in fake.comments(n)]


def plant(fake, n, claimant, age=0, voids=()):
    # a claim made by somebody else, `age` seconds ago
    c = fake.add_comment(n, cm.render_claim("tok" + claimant[:9].ljust(9, "0"), claimant, "2026-11-08T09:00:00Z", voids))
    if age:
        fake.age_comment(c["id"], age)
    return c["id"]


def labelled(fake, n, on=True):
    fake.edit_issue(n, labels=["taskgraph", "tg:in-progress"] if on else ["taskgraph"])


def task(env):
    return env.ok("add", "T")["id"]


def test_no_claim_means_a_win_one_comment_one_patch(env, fake):
    n = task(env)
    fake.clear_log()
    out = env.ok("start", str(n))
    assert out["status"] == "in_progress"
    [(cid, parsed)] = claim_comments(fake, n)
    assert parsed["claim"]["claimant"] == "alice@host:1" and parsed["voids"] == []
    assert fake.issue(n)["labels"] == ["taskgraph", "tg:in-progress"]
    assert [c["method"] for c in env.writes()] == ["POST", "PATCH"]
    assert env.sql("SELECT comment_id, claimant FROM claims") == [(cid, "alice@host:1")]
    code, text, _ = tg_text(env, "show", str(n))
    assert "claimed by alice@host:1" in text


def test_held_by_me_writes_nothing(env, fake):
    n = task(env)
    env.ok("start", str(n))
    fake.clear_log()
    assert env.ok("start", str(n))["status"] == "in_progress"
    assert env.writes() == [] and len(claim_comments(fake, n)) == 1


def test_a_failed_label_patch_is_repaired_by_the_next_start(env, fake):
    n = task(env)
    fake.fault(fail_after=2)  # the claim comment is write 1, the label PATCH write 2
    assert "HTTP 502" in env.fail("start", str(n))
    assert fake.issue(n)["labels"] == ["taskgraph"] and len(claim_comments(fake, n)) == 1
    assert env.ok("show", str(n))["status"] == "open"
    fake.clear_log()
    env.ok("start", str(n))
    assert fake.issue(n)["labels"] == ["taskgraph", "tg:in-progress"]
    assert [c["method"] for c in env.writes()] == ["PATCH"] and len(claim_comments(fake, n)) == 1


def test_held_by_another_is_refused_and_names_the_holder(env, fake):
    n = task(env)
    plant(fake, n, "bob@host:2", age=5)
    labelled(fake, n)
    fake.clear_log()
    err = env.fail("start", str(n))
    assert err.startswith(f"error: #{n} is claimed by bob@host:2 since ")
    assert env.writes() == []
    assert env.sql("SELECT status FROM tasks") == [("in_progress",)]  # the refresh saw the label; nothing was written by start


def test_an_old_claim_with_the_label_still_held_is_not_stale(env, fake):
    n = task(env)
    plant(fake, n, "bob@host:2", age=3600)
    labelled(fake, n)
    assert "claimed by bob@host:2" in env.fail("start", str(n))


def test_a_claim_without_the_label_is_voided_only_after_60_seconds(env, fake):
    n = task(env)
    old = plant(fake, n, "bob@host:2", age=59)
    assert f"claimed by bob@host:2" in env.fail("start", str(n))
    fake.age_comment(old, 2)  # now 61 s
    fake.clear_log()
    env.ok("start", str(n))
    mine = [p for cid, p in claim_comments(fake, n) if p["claim"]["claimant"] == "alice@host:1"]
    assert len(mine) == 1 and mine[0]["voids"] == [old]
    assert [c["method"] for c in env.writes()] == ["POST", "PATCH"]


def test_my_own_claim_is_reused_only_while_younger_than_60_seconds(env, fake):
    n = task(env)
    env.ok("start", str(n))
    [(first, _)] = claim_comments(fake, n)
    fake.age_comment(first, 61)  # the label is still on the issue, so the claim is not stale, but it is too old to reuse
    fake.clear_log()
    env.ok("start", str(n))
    comments = claim_comments(fake, n)
    assert len(comments) == 2 and comments[1][1]["voids"] == [first] and comments[1][1]["claim"]["claimant"] == "alice@host:1"
    assert env.sql("SELECT claimant FROM claims WHERE comment_id=?", comments[1][0]) == [("alice@host:1",)]


def test_done_then_start_again_within_60_seconds_reuses_the_claim(env, fake):
    n = task(env)
    env.ok("start", str(n))
    env.ok("done", str(n))
    [(first, _)] = claim_comments(fake, n)
    fake.age_comment(first, 10)
    fake.clear_log()
    assert env.ok("start", str(n))["status"] == "in_progress"
    assert len(claim_comments(fake, n)) == 1
    issue = fake.issue(n)
    assert issue["state"] == "open" and "tg:in-progress" in issue["labels"]
    assert [c["method"] for c in env.writes()] == ["PATCH"]


def test_done_then_start_again_after_60_seconds_posts_a_new_claim_that_voids_the_old(env, fake):
    n = task(env)
    env.ok("start", str(n))
    env.ok("done", str(n))
    [(first, _)] = claim_comments(fake, n)
    fake.age_comment(first, 61)
    env.ok("start", str(n))
    comments = claim_comments(fake, n)
    assert len(comments) == 2 and comments[1][1]["voids"] == [first]
    assert fake.issue(n)["state"] == "open"


def test_done_and_reopen_post_nothing(env, fake):
    n = task(env)
    env.ok("start", str(n))
    fake.clear_log()
    env.ok("reopen", str(n))
    env.ok("done", str(n))
    assert len(claim_comments(fake, n)) == 1 and all(c["path"].count("comments") == 0 for c in env.writes())


def remote_for(env, claimant):
    return GitHubRemote(env.entry)


def test_two_claimers_that_both_post_before_either_reads_give_exactly_one_winner(env, fake):
    n = task(env)
    fake.fault(hold_after_post=2)  # each claim POST waits until both comments exist
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(lambda who=who: GitHubRemote(env.entry).claim(n, who)) for who in ("m1", "m2")]
    outcomes = []
    for f in futures:
        try:
            outcomes.append(("won", f.result().claimant))
        except ClaimLost as e:
            outcomes.append(("lost", e.winner))
    won = [o for o in outcomes if o[0] == "won"]
    assert len(won) == 1 and [o[1] for o in outcomes if o[0] == "lost"] == [won[0][1]]
    left = claim_comments(fake, n)
    assert len(left) == 1 and left[0][1]["claim"]["claimant"] == won[0][1]  # the loser's comment is gone


def test_a_lagging_first_read_is_caught_by_the_confirm_read(env, fake):
    n = task(env)
    alice = GitHubRemote(env.entry).claim(n, "alice@host:1")
    fake.fault(hide_comment_ids={"ids": [alice.comment_id], "reads": 2})  # bob's first two reads miss alice's comment
    with pytest.raises(ClaimLost) as lost:
        GitHubRemote(env.entry).claim(n, "bob@host:2")
    assert lost.value.winner == "alice@host:1"
    assert [p["claim"]["claimant"] for _, p in claim_comments(fake, n)] == ["alice@host:1"]


def test_when_both_confirm_reads_miss_the_other_both_win_and_show_says_so(env, fake, monkeypatch):
    n = task(env)
    env.ok("start", str(n))
    [(first, _)] = claim_comments(fake, n)
    fake.fault(hide_comment_ids={"ids": [first], "reads": 4})  # the refresh before the write reads the comments once, the claim three times
    monkeypatch.setenv("TASKGRAPH_CLAIMANT", "bob@host:2")
    env.ok("start", str(n))  # bob never saw alice's claim
    assert len(claim_comments(fake, n)) == 2
    shown = env.ok("--fresh", "show", str(n))
    assert [c["message"] for c in shown["conflicts"]] == [f"claim conflict on #{n}: alice@host:1 and bob@host:2"]
    assert any("claim conflict" in line for line in tg_text(env, "show", str(n))[1].splitlines())


def test_a_loser_whose_comment_voids_a_stale_claim_keeps_a_void_only_comment(env, fake):
    n = task(env)
    stale = plant(fake, n, "old@host:0", age=300)
    winner = plant(fake, n, "carol@host:3", age=0)  # no label on the issue: only the 300 s old claim is stale
    # alice's first read hides carol's claim, so alice sees only the stale one, voids it and posts
    fake.fault(hide_comment_ids={"ids": [winner], "reads": 1})
    with pytest.raises(ClaimLost) as lost:
        GitHubRemote(env.entry).claim(n, "alice@host:1")
    assert lost.value.winner == "carol@host:3"
    mine = [(cid, p) for cid, p in claim_comments(fake, n) if cid not in (stale, winner)]
    assert len(mine) == 1 and mine[0][1]["voids"] == [stale] and "claim" not in mine[0][1]
    body = next(c["body"] for c in fake.comments(n) if c["id"] == mine[0][0])
    assert body == cm.marker("void", {"of": stale})
    remote = GitHubRemote(env.entry)
    assert [p["id"] for p in remote.unvoided(remote.read_comments(n))] == [winner]  # the stale claim stays voided


def test_the_30_second_deadline_gives_the_claim_up(env, fake):
    n = task(env)
    fake.fault(advance={"reads": 3, "seconds": 31})  # after the confirm read, the clock jumps before the PATCH
    err = env.fail("start", str(n))
    assert err == "error: claim took too long; run tg start again\n"
    assert fake.issue(n)["labels"] == ["taskgraph"] and claim_comments(fake, n) == []  # no void in it: the comment is deleted
    assert env.ok("show", str(n))["status"] == "open"
    env.ok("start", str(n))
    assert fake.issue(n)["labels"] == ["taskgraph", "tg:in-progress"]


def test_a_deadline_miss_keeps_a_void_only_comment_when_it_voided_a_stale_claim(env, fake):
    n = task(env)
    stale = plant(fake, n, "old@host:0", age=300)
    fake.fault(advance={"reads": 3, "seconds": 31})
    assert "claim took too long" in env.fail("start", str(n))
    [(cid, parsed)] = [(c, p) for c, p in claim_comments(fake, n) if c != stale]
    assert parsed["voids"] == [stale] and "claim" not in parsed


def test_start_is_checked_against_github_not_the_cache(env, fake):
    n = task(env)
    env.ok("--fresh", "ls")
    plant(fake, n, "bob@host:2", age=5)  # the cache does not know it, and no label yet: the claim read finds it
    labelled(fake, n)
    assert "claimed by bob@host:2" in env.fail("start", str(n))


def test_two_tg_processes_race_for_one_task(fake, tmp_path):
    # the real thing: two tg.py processes, two cache files, one fake repository
    scripts = []
    for who in ("m1", "m2"):
        config = tmp_path / f"{who}.toml"
        config.write_text(f'version = 1\n[projects.demo]\nbackend = "github"\nrepo = "o/demo"\ncache = "{tmp_path / who}.db"\n', encoding="utf-8")
        scripts.append((who, config))
    if sys.version_info < (3, 11):
        pytest.skip("a config file needs Python 3.11")
    import os
    env = {**os.environ, "TASKGRAPH_TODAY": "2026-10-13"}
    first = subprocess.run([sys.executable, str(SCRIPT), "--project", "demo", "--json", "add", "T"], capture_output=True, text=True, env={**env, "TASKGRAPH_CONFIG": str(scripts[0][1])})
    assert first.returncode == 0, first.stderr
    n = json.loads(first.stdout)["id"]
    fake.fault(hold_after_post=2)
    procs = [subprocess.Popen([sys.executable, str(SCRIPT), "--project", "demo", "--json", "start", str(n)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              env={**env, "TASKGRAPH_CONFIG": str(config), "TASKGRAPH_CLAIMANT": who}) for who, config in scripts]
    results = [(p.wait(), p.stdout.read(), p.stderr.read()) for p in procs]
    assert sorted(code for code, _, _ in results) == [0, 1]
    loser = next(r for r in results if r[0] == 1)
    winner = scripts[[r[0] for r in results].index(0)][0]
    assert loser[2] == f"error: #{n} is claimed by {winner}\n"
    assert len(fake.comments(n)) == 1
