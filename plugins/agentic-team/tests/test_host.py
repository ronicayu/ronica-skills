"""Tests for scripts/host.py: the GitHub and GitLab mappings, run through a fake `sh`.

No process starts here. The fake `sh` records each command and answers from a table.
"""

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import host  # noqa: E402

CONFIG = {"merge": {"mode": "pr", "host": "auto", "remote": "origin", "base": "", "method": "merge"}}


class FakeSh:
    """Answers a command from the first rule whose words all appear in it."""

    def __init__(self, *rules):
        self.rules, self.calls = list(rules), []

    def __call__(self, cmd, cwd=None, input=None, env=None):
        self.calls.append({"cmd": list(cmd), "cwd": cwd, "input": input, "env": env})
        line = " ".join(cmd)
        for words, answer in self.rules:
            if all(w in line for w in words):
                out = answer.pop(0) if isinstance(answer, list) and len(answer) > 1 else answer[0] if isinstance(answer, list) else answer
                return subprocess.CompletedProcess(cmd, out.get("exit", 0), out.get("stdout", ""), out.get("stderr", ""))
        return subprocess.CompletedProcess(cmd, 1, "", f"fake: no answer for {line}")


def ok(value):
    return {"stdout": value if isinstance(value, str) else json.dumps(value)}


def gh(*rules):
    sh = FakeSh(*rules)
    return host.GitHub(sh, "/repo", "origin", "https://github.com/o/r.git"), sh


def gl(*rules):
    sh = FakeSh(*rules)
    return host.GitLab(sh, "/repo", "origin", "https://gitlab.com/g/p.git"), sh


class RemoteTest(unittest.TestCase):
    def test_65_pick_by_remote_url(self):
        for url in ("https://github.com/o/r.git", "git@github.com:o/r.git", "ssh://git@github.com/o/r"):
            self.assertIs(host.pick(CONFIG, url), host.GitHub, url)
        for url in ("https://gitlab.com/g/p.git", "git@gitlab.example.com:g/p.git", "ssh://git@gitlab.corp:2222/g/s/p.git"):
            self.assertIs(host.pick(CONFIG, url), host.GitLab, url)
        with self.assertRaises(host.HostError) as caught:
            host.pick(CONFIG, "git@git.example.com:g/p.git")
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("merge.host", str(caught.exception))
        self.assertIn("git@git.example.com:g/p.git", str(caught.exception))
        forced = {"merge": {**CONFIG["merge"], "host": "gitlab"}}
        self.assertIs(host.pick(forced, "git@git.example.com:g/p.git"), host.GitLab)
        self.assertEqual(host.parse_remote("git@git.example.com:g/p.git"), ("git.example.com", "g/p"))
        self.assertEqual(host.parse_remote("ssh://git@gitlab.corp:2222/g/s/p.git"), ("gitlab.corp", "g/s/p"))
        self.assertEqual(host.parse_remote("/tmp/work/origin.git"), ("", "tmp/work/origin"))
        self.assertEqual(host.GitLab(FakeSh(), "/r", "origin", "git@git.example.com:g/p.git").project, "g%2Fp")

    def test_missing_program_is_named_with_its_login_command(self):
        def missing(cmd, cwd=None, input=None, env=None):
            raise FileNotFoundError(cmd[0])

        for cls, url, words in ((host.GitHub, "https://github.com/o/r.git", ("cannot run gh", "gh auth login")),
                                (host.GitLab, "https://gitlab.com/g/p.git", ("cannot run glab", "glab auth login --hostname gitlab.com"))):
            with self.assertRaises(host.HostError) as caught:
                cls(missing, "/repo", "origin", url).default_branch()
            self.assertEqual(caught.exception.code, 1)
            for word in words:
                self.assertIn(word, str(caught.exception))


class GitHubTest(unittest.TestCase):
    def test_67_merge_state_words(self):
        wanted = {"CLEAN": "CLEAN", "HAS_HOOKS": "CLEAN", "BLOCKED": "BLOCKED", "UNSTABLE": "BLOCKED", "BEHIND": "BEHIND",
                  "DIRTY": "DIRTY", "DRAFT": "DRAFT", "UNKNOWN": "UNKNOWN", "SOMETHING_NEW": "UNKNOWN"}
        for word, state in wanted.items():
            view = {"number": 7, "url": "u", "state": "OPEN", "headRefOid": "a" * 40, "headRefName": "task-7",
                    "baseRefName": "main", "mergedAt": None, "mergeCommit": None, "mergeStateStatus": word}
            client, sh = gh((["pr", "view", "7"], ok(view)))
            found = client.pr(7)
            self.assertEqual((found.merge_state, found.raw_state), (state, word))
            self.assertEqual((found.number, found.head, found.head_branch, found.base_branch), (7, "a" * 40, "task-7", "main"))
            self.assertIn("mergeStateStatus", sh.calls[0]["cmd"][-1])
        merged = {"number": 7, "url": "u", "state": "MERGED", "headRefOid": "a", "headRefName": "b", "baseRefName": "main",
                  "mergedAt": "2026-10-26T10:00:00Z", "mergeCommit": {"oid": "c" * 40}, "mergeStateStatus": "UNKNOWN"}
        found = gh((["pr", "view"], ok(merged)))[0].pr(7)
        self.assertEqual((found.state, found.merge_commit, found.merged_at), ("MERGED", "c" * 40, "2026-10-26T10:00:00Z"))

    def test_67_run_status_words(self):
        def run_of(status, conclusion):
            return {"databaseId": 5, "attempt": 2, "status": status, "conclusion": conclusion, "headSha": "h", "url": "u",
                    "createdAt": "2026-10-26T10:00:00Z"}

        wanted = {("queued", ""): "pending", ("in_progress", ""): "pending", ("completed", "success"): "success",
                  ("completed", "failure"): "failure", ("completed", "timed_out"): "failure",
                  ("completed", "startup_failure"): "failure", ("completed", "action_required"): "failure",
                  ("completed", "cancelled"): "blocked", ("completed", "skipped"): "blocked", ("completed", "stale"): "blocked",
                  ("completed", "neutral"): "blocked", ("completed", "other"): "blocked"}
        for (status, conclusion), state in wanted.items():
            runs = gh((["run", "list"], ok([run_of(status, conclusion), dict(run_of("completed", "success"), headSha="other")])))[0].runs("task-1", "h", "ci.yml")
            self.assertEqual([(r.id, r.attempt, r.status) for r in runs], [("5", 2, state)], (status, conclusion))
        sh = FakeSh((["run", "list"], ok([])))
        host.GitHub(sh, "/repo", "origin").runs("task-1", "h", "ci.yml")
        self.assertEqual(sh.calls[0]["cmd"][:7], ["gh", "run", "list", "--branch", "task-1", "--workflow", "ci.yml"])

    def test_67_runs_are_newest_first(self):
        old = {"databaseId": 1, "attempt": 1, "status": "completed", "conclusion": "failure", "headSha": "h", "url": "u",
               "createdAt": "2026-10-26T10:00:00Z"}
        new = dict(old, databaseId=2, conclusion="success", createdAt="2026-10-26T10:05:00Z")
        runs = gh((["run", "list"], ok([old, new])))[0].runs("b", "h", "ci.yml")
        self.assertEqual([r.id for r in runs], ["2", "1"])

    def test_67_create_pr_parses_the_number_and_falls_back_to_find_pr(self):
        client, sh = gh((["pr", "create"], ok("https://github.com/o/r/pull/42\n")))
        created = client.create_pr("task-1", "main", "T", "body")
        self.assertEqual((created.number, created.url, created.state), (42, "https://github.com/o/r/pull/42", "OPEN"))
        call = sh.calls[0]
        self.assertEqual(call["cmd"][:3], ["gh", "pr", "create"])
        self.assertIn("--body-file", call["cmd"])
        self.assertEqual(call["input"], "body")
        listed = {"number": 9, "url": "u", "state": "OPEN", "headRefOid": "a", "headRefName": "task-1", "baseRefName": "main",
                  "mergedAt": None, "mergeCommit": None, "mergeStateStatus": "CLEAN"}
        client, _ = gh((["pr", "create"], {"exit": 1, "stderr": "a pull request for branch task-1 already exists\n"}),
                       (["pr", "list"], ok([listed, dict(listed, number=3)])))
        self.assertEqual(client.create_pr("task-1", "main", "T", "b").number, 9)
        client, _ = gh((["pr", "create"], {"exit": 1, "stderr": "no permission\nmore\n"}))
        with self.assertRaises(host.HostError) as caught:
            client.create_pr("task-1", "main", "T", "b")
        self.assertEqual(str(caught.exception), "gh pr create failed: no permission")

    def test_67_push_builds_the_lease_and_the_environment(self):
        client, sh = gh((["push"], {"stderr": "To origin\n"}))
        self.assertEqual(client.push("refs/heads/worktree-task-1", "task-1", ""), (True, "To origin"))
        self.assertEqual(sh.calls[0]["cmd"], ["git", "-C", "/repo", "push", "origin", "refs/heads/worktree-task-1:refs/heads/task-1",
                                              "--force-with-lease=refs/heads/task-1:"])
        self.assertEqual(sh.calls[0]["cwd"], "/repo")
        for key, value in (("GH_PROMPT_DISABLED", "1"), ("GH_NO_UPDATE_NOTIFIER", "1"), ("NO_COLOR", "1")):
            self.assertEqual(sh.calls[0]["env"][key], value)
        client.push("refs/heads/b", "task-1", "a" * 40)
        self.assertEqual(sh.calls[1]["cmd"][-1], f"--force-with-lease=refs/heads/task-1:{'a' * 40}")
        client, _ = gh((["push"], {"exit": 1, "stderr": "To origin\n ! [rejected] b -> task-1 (stale info)\n"}))
        self.assertEqual(client.push("refs/heads/b", "task-1", "a"), (False, "! [rejected] b -> task-1 (stale info)"))

    def test_67_merge_checks_and_dispatch(self):
        client, sh = gh((["pr", "merge"], {"exit": 1, "stderr": "Pull request is not mergeable\nmore\n"}))
        self.assertEqual(client.merge(3, "squash", "h" * 40), (False, "Pull request is not mergeable"))
        self.assertEqual(sh.calls[0]["cmd"], ["gh", "pr", "merge", "3", "--squash", "--match-head-commit", "h" * 40])
        self.assertEqual(gh((["pr", "merge"], ok("")))[0].merge(3, "rebase", "h"), (True, ""))
        checks = [{"name": "a", "state": "SUCCESS", "bucket": "pass"}, {"name": "b", "state": "FAILURE", "bucket": "fail"},
                  {"name": "c", "state": "PENDING", "bucket": "pending"}, {"name": "d", "state": "SKIPPED", "bucket": "skipping"}]
        for code in (0, 1, 8):
            client, sh = gh((["pr", "checks"], dict(ok(checks), exit=code)))
            self.assertEqual(client.blockers(3), "required checks: 1 pass, 1 fail, 1 pending, 1 skipping")
        self.assertIn("--required", sh.calls[0]["cmd"])
        for out in ({"exit": 1, "stderr": "no required checks reported on the 'task-3' branch\n"}, {"exit": 1}, ok("not json")):
            text = gh((["pr", "checks"], out))[0].blockers(3)  # informational: it never raises
            self.assertTrue(text and "required checks:" not in text, text)
        self.assertEqual(gh((["pr", "checks"], {"exit": 1, "stderr": "no required checks reported on the 'task-3' branch\n"}))[0].blockers(3),
                         "no required checks reported on the 'task-3' branch")
        self.assertEqual(gh((["workflow", "run"], ok("")))[0].dispatch("task-1", "ci.yml"), (True, ""))
        for stderr in ("HTTP 422: Workflow does not have 'workflow_dispatch' trigger", "could not create a workflow_dispatch event"):
            self.assertEqual(gh((["workflow", "run"], {"exit": 1, "stderr": stderr}))[0].dispatch("task-1", "ci.yml"),
                             (False, "no manual trigger"))
        self.assertEqual(gh((["workflow", "run"], {"exit": 1, "stderr": "HTTP 500: boom\n"}))[0].dispatch("task-1", "ci.yml"),
                         (False, "HTTP 500: boom"))

    def test_67_comment_edits_the_marked_comment_or_creates_one(self):
        marker = "<!-- agentic-team verdict task=7 -->"
        base = "repos/{owner}/{repo}/issues/1/comments"
        client, sh = gh((["issues/1/comments?per_page=100&page=1"], ok([{"id": 9, "body": "a human wrote this"}])),
                        (["-X", "POST"], ok({"id": 55, "html_url": "https://github.com/o/r/pull/1#issuecomment-55"})))
        self.assertEqual(client.comment(1, marker, marker + "\nbody"), ("https://github.com/o/r/pull/1#issuecomment-55", False))
        self.assertEqual(sh.calls[0]["cmd"], ["gh", "api", base + "?per_page=100&page=1"])
        self.assertEqual(sh.calls[1]["cmd"], ["gh", "api", "-X", "POST", base, "--input", "-"])
        self.assertEqual(json.loads(sh.calls[1]["input"]), {"body": marker + "\nbody"})
        client, sh = gh((["issues/1/comments?per_page=100&page=1"], ok([{"id": 9, "body": "x"}, {"id": 55, "body": marker + "\nold"}])),
                        (["-X", "PATCH"], ok({"id": 55, "html_url": "u55"})))
        self.assertEqual(client.comment(1, marker, "new"), ("u55", True))
        self.assertEqual(sh.calls[1]["cmd"], ["gh", "api", "-X", "PATCH", "repos/{owner}/{repo}/issues/comments/55", "--input", "-"])
        self.assertEqual(json.loads(sh.calls[1]["input"]), {"body": "new"})
        self.assertFalse([c for c in sh.calls if "POST" in c["cmd"]])
        client, sh = gh((["&page=1"], ok([{"id": i, "body": "x"} for i in range(100)])),
                        (["&page=2"], ok([{"id": 200, "body": marker}])),
                        (["-X", "PATCH"], ok({"id": 200, "html_url": "u200"})))
        self.assertEqual(client.comment(1, marker, "new"), ("u200", True))
        self.assertEqual([c["cmd"][2] for c in sh.calls[:2]], [base + "?per_page=100&page=1", base + "?per_page=100&page=2"])
        self.assertIn("issues/comments/200", sh.calls[2]["cmd"][4])
        client, _ = gh((["issues/1/comments?per_page=100"], ok([])),
                       (["-X", "POST"], {"exit": 1, "stderr": "HTTP 403: Resource not accessible by integration\nmore\n"}))
        with self.assertRaises(host.HostError) as caught:
            client.comment(1, marker, "body")
        self.assertEqual(str(caught.exception), "gh api issues/<number>/comments failed: HTTP 403: Resource not accessible by integration")

    def test_other_failures_raise_with_the_first_stderr_line(self):
        with self.assertRaises(host.HostError) as caught:
            gh((["pr", "view"], {"exit": 4, "stderr": "To get started with GitHub CLI, please run: gh auth login\nmore\n"}))[0].pr(1)
        self.assertEqual(str(caught.exception), "gh pr view failed: To get started with GitHub CLI, please run: gh auth login")
        self.assertEqual(gh((["repo", "view"], ok("main\n")))[0].default_branch(), "main")
        self.assertIsNone(gh((["pr", "list"], ok([])))[0].find_pr("task-1"))
        self.assertEqual(host.GitHub.label(7), "PR #7")


class GitLabTest(unittest.TestCase):
    def mr(self, **fields):
        base = {"iid": 7, "web_url": "https://gitlab.com/g/p/-/merge_requests/7", "state": "opened", "sha": "a" * 40,
                "source_branch": "task-7", "target_branch": "main", "merged_at": None, "merge_commit_sha": None,
                "squash_commit_sha": None, "detailed_merge_status": "mergeable", "has_conflicts": False}
        return {**base, **fields}

    def test_68_merge_state_words(self):
        wanted = {"mergeable": "CLEAN", "need_rebase": "BEHIND", "conflict": "DIRTY", "draft_status": "DRAFT", "checking": "UNKNOWN",
                  "unchecked": "UNKNOWN", "preparing": "UNKNOWN", "approvals_syncing": "UNKNOWN", "ci_must_pass": "BLOCKED",
                  "ci_still_running": "BLOCKED", "not_approved": "BLOCKED", "discussions_not_resolved": "BLOCKED",
                  "blocked_status": "BLOCKED", "external_status_checks": "BLOCKED", "requested_changes": "BLOCKED",
                  "jira_association_missing": "BLOCKED", "commits_status": "BLOCKED", "broken_status": "BLOCKED", "brand_new": "BLOCKED"}
        for word, state in wanted.items():
            client, sh = gl((["api", "projects/g%2Fp/merge_requests/7"], ok(self.mr(detailed_merge_status=word))))
            found = client.pr(7)
            self.assertEqual((found.merge_state, found.raw_state), (state, word))
            self.assertEqual((found.number, found.state, found.head, found.head_branch), (7, "OPEN", "a" * 40, "task-7"))
        self.assertEqual(gl((["api"], ok(self.mr(has_conflicts=True, detailed_merge_status="checking"))))[0].pr(7).merge_state, "DIRTY")
        for word, state in (("opened", "OPEN"), ("locked", "OPEN"), ("merged", "MERGED"), ("closed", "CLOSED")):
            self.assertEqual(gl((["api"], ok(self.mr(state=word))))[0].pr(7).state, state)
        self.assertEqual(host.GitLab.label(7), "MR !7")

    def test_68_merge_commit_falls_back_to_the_squash_commit_then_the_head(self):
        for fields, wanted in (({"merge_commit_sha": "m" * 40, "squash_commit_sha": "s" * 40}, "m" * 40),
                               ({"squash_commit_sha": "s" * 40}, "s" * 40), ({}, "a" * 40)):
            found = gl((["api"], ok(self.mr(state="merged", **fields))))[0].pr(7)
            self.assertEqual(found.merge_commit, wanted)

    def test_68_pipeline_and_job_statuses(self):
        def pipe(status, number=11):
            return {"id": number, "status": status, "web_url": f"https://x/{number}", "created_at": "t", "sha": "h" * 40}

        wanted = {"created": "pending", "waiting_for_resource": "pending", "preparing": "pending", "pending": "pending",
                  "running": "pending", "scheduled": "pending", "manual": "pending", "success": "success", "failed": "failure",
                  "canceled": "blocked", "skipped": "blocked", "unknown": "blocked"}
        for word, state in wanted.items():
            runs = gl((["api", "projects/g%2Fp/pipelines?sha=" + "h" * 40], ok([pipe(word), pipe("failed", 10)])))[0].runs("b", "h" * 40, "pipeline")
            self.assertEqual([(r.id, r.attempt, r.status, r.raw) for r in runs], [("11", 1, state, word), ("10", 1, "failure", "failed")])
        jobs = [{"id": 61, "name": "unit", "status": "success", "web_url": "j1", "created_at": "t"},
                {"id": 62, "name": "lint", "status": "failed", "web_url": "j2", "created_at": "t"}]
        rules = ((["pipelines?sha="], ok([pipe("running")])), (["pipelines/11/jobs"], ok(jobs)))
        runs = gl(*rules)[0].runs("b", "h" * 40, "unit")
        self.assertEqual([(r.id, r.status, r.url) for r in runs], [("11/61", "success", "j1")])
        runs = gl(*rules)[0].runs("b", "h" * 40, "missing")
        self.assertEqual([(r.id, r.status, r.raw) for r in runs], [("11", "blocked", "no job missing")])
        self.assertEqual(gl((["pipelines?sha="], ok([])))[0].runs("b", "h" * 40, "unit"), [])
        other = dict(pipe("success"), sha="9" * 40)  # a pipeline of another commit is never a run of this head
        self.assertEqual(gl((["pipelines?sha="], ok([other])))[0].runs("b", "h" * 40, "pipeline"), [])

    def test_68_merge_squash_and_messages(self):
        client, sh = gl((["api", "-X", "PUT"], ok(self.mr(state="merged"))))
        self.assertEqual(client.merge(7, "squash", "h" * 40), (True, ""))
        cmd = sh.calls[0]["cmd"]
        self.assertEqual(cmd[:5], ["glab", "api", "-X", "PUT", "projects/g%2Fp/merge_requests/7/merge"])
        self.assertIn("squash=true", cmd)
        self.assertIn(f"sha={'h' * 40}", cmd)
        self.assertIn("should_remove_source_branch=false", cmd)
        for method in ("merge", "rebase"):
            client, sh = gl((["api", "-X", "PUT"], ok(self.mr(state="merged"))))
            client.merge(7, method, "h")
            self.assertNotIn("squash=true", sh.calls[0]["cmd"])
        failed = gl((["api", "-X", "PUT"], {"exit": 1, "stdout": json.dumps({"message": "SHA does not match HEAD of source branch"})}))[0]
        self.assertEqual(failed.merge(7, "merge", "h"), (False, "SHA does not match HEAD of source branch"))
        self.assertEqual(gl((["api", "-X", "PUT"], ok(self.mr(state="opened"))))[0].merge(7, "merge", "h")[0], False)

    def test_68_requests_and_dispatch(self):
        client, sh = gl((["api", "-X", "POST", "projects/g%2Fp/merge_requests"], ok(self.mr())))
        created = client.create_pr("task-7", "main", "T", "body")
        self.assertEqual((created.number, created.head), (7, "a" * 40))
        for flag in ("source_branch=task-7", "target_branch=main", "title=T", "description=body", "remove_source_branch=false"):
            self.assertIn(flag, sh.calls[0]["cmd"])
        self.assertEqual(sh.calls[0]["env"]["GLAB_CHECK_UPDATE"], "false")
        client, _ = gl((["api", "-X", "POST"], {"exit": 1, "stdout": json.dumps({"message": "Another open merge request already exists"})}),
                       (["api", "projects/g%2Fp/merge_requests?source_branch=task-7"], ok([self.mr(iid=3), self.mr(iid=8)])))
        self.assertEqual(client.create_pr("task-7", "main", "T", "b").number, 8)
        self.assertEqual(gl((["api", "projects/g%2Fp"], ok({"default_branch": "trunk"})))[0].default_branch(), "trunk")
        self.assertEqual(gl((["api", "-X", "POST", "projects/g%2Fp/pipeline"], ok({})))[0].dispatch("task-7", "pipeline"), (True, ""))
        none = {"exit": 1, "stdout": json.dumps({"message": "Missing CI config file"})}
        self.assertEqual(gl((["api", "-X", "POST"], none))[0].dispatch("task-7", "pipeline"), (False, "no manual trigger"))
        other = {"exit": 1, "stdout": json.dumps({"message": "403 Forbidden"})}
        self.assertEqual(gl((["api", "-X", "POST"], other))[0].dispatch("task-7", "pipeline"), (False, "403 Forbidden"))

    def test_68_comment_edits_the_marked_note_or_creates_one(self):
        marker = "<!-- agentic-team verdict task=7 -->"
        system = {"id": 1, "body": "added 1 commit", "system": True}
        client, sh = gl((["merge_requests/7/notes?per_page=100&page=1"], ok([system])),
                        (["-X", "POST", "merge_requests/7/notes"], ok({"id": 302, "body": "..."})))
        self.assertEqual(client.comment(7, marker, "text"), ("note 302", False))
        self.assertEqual(sh.calls[1]["cmd"], ["glab", "api", "-X", "POST", "projects/g%2Fp/merge_requests/7/notes", "-f", "body=text"])
        client, sh = gl((["merge_requests/7/notes?per_page=100&page=1"],
                         ok([system, {"id": 302, "body": marker + "\nold", "system": False}])),
                        (["-X", "PUT"], ok({"id": 302})))
        self.assertEqual(client.comment(7, marker, "new"), ("note 302", True))
        self.assertEqual(sh.calls[1]["cmd"], ["glab", "api", "-X", "PUT", "projects/g%2Fp/merge_requests/7/notes/302", "-f", "body=new"])
        self.assertFalse([c for c in sh.calls if "POST" in c["cmd"]])
        client, _ = gl((["merge_requests/7/notes?per_page=100"], ok([])),
                       (["-X", "POST"], {"exit": 1, "stdout": json.dumps({"message": "403 Forbidden"})}))
        with self.assertRaises(host.HostError) as caught:
            client.comment(7, marker, "text")
        self.assertEqual(str(caught.exception), "glab api projects/<project>/merge_requests/7/notes failed: 403 Forbidden")

    def test_68_blockers_list_the_word_the_pipeline_and_the_approvals(self):
        client, _ = gl((["merge_requests/7/approvals"], ok({"approvals_left": 2})),
                       (["api", "projects/g%2Fp/merge_requests/7"], ok(self.mr(detailed_merge_status="not_approved"))),
                       (["pipelines?sha="], ok([{"id": 1, "status": "success"}])))
        self.assertEqual(client.blockers(7), "not_approved, pipeline success, approvals left: 2")
        client, _ = gl((["merge_requests/7/approvals"], {"exit": 1, "stderr": "403 Forbidden\nmore\n"}),
                       (["api", "projects/g%2Fp/merge_requests/7"], ok(self.mr(detailed_merge_status="not_approved"))),
                       (["pipelines?sha="], ok([{"id": 1, "status": "running"}])))
        self.assertEqual(client.blockers(7), "not_approved, pipeline running, glab api projects/<project>/merge_requests/7/approvals failed: 403 Forbidden")
        client, _ = gl((["api", "projects/g%2Fp/merge_requests/7"], {"exit": 1, "stderr": "404 Not found\n"}))
        self.assertIn("404 Not found", client.blockers(7))


if __name__ == "__main__":
    unittest.main()
