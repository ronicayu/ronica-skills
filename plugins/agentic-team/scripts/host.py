"""The code host seam: push a branch, open a pull or merge request, read its
state and checks, merge it, and find the CI runs of a commit.

run.py is the only caller. This module covers the code host and nothing else.
Taskgraph (issue #15, a storage backend for Taskgraph) is a separate seam:
that one covers snapshot, claim and `result add`; this one covers push,
request, checks and merge. Neither depends on the other. The module holds no
Taskgraph types and runs processes only through the `sh` callback it is given.

GitHub is spoken through `gh` (verified on gh 2.102.0). GitLab is the second
implementation, spoken through `glab api` (REST v4). Every GitLab line is
unverified until the checks in the GitLab class comment are done.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from urllib.parse import quote as urlquote


class HostError(Exception):
    """A failure with an exit code: 1 a tool failed, 2 refused."""

    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


@dataclass
class PR:
    number: int
    url: str
    state: str            # "OPEN" | "MERGED" | "CLOSED"
    head: str             # head SHA on the host
    head_branch: str
    base_branch: str
    merged_at: str | None  # host time string, or None
    merge_commit: str | None
    merge_state: str      # "CLEAN" | "BLOCKED" | "BEHIND" | "DIRTY" | "DRAFT" | "UNKNOWN"
    raw_state: str        # the host's own word, for event lines


@dataclass
class Run:
    id: str
    attempt: int
    status: str           # "pending" | "success" | "failure" | "blocked"
    raw: str
    url: str
    created: str


def first_line(text):
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[0] if lines else ""


def parse_remote(url):
    """(host name, project path) of a remote URL. A local path has no host name."""
    url = url.strip()
    if url.startswith("file://"):
        url = url[7:]
    match = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://(?:[^@/]*@)?([^/:]+)(?::\d+)?/(.*)$", url)
    if not match:
        match = re.match(r"^(?:[^@/]+@)?([^/:]+):(?!//)(.*)$", url)  # git@host:group/project
    name, path = (match.group(1), match.group(2)) if match else ("", url)
    path = path.strip("/")
    return name, path[:-4] if path.endswith(".git") else path


def pick(config, url):
    """The Host class for merge.host, or for the remote URL when merge.host is auto."""
    merge = config["merge"]
    if merge["host"] != "auto":
        return {"github": GitHub, "gitlab": GitLab}[merge["host"]]
    name = parse_remote(url)[0].lower()
    if name == "github.com":
        return GitHub
    if "gitlab" in name:
        return GitLab
    raise HostError(f'merge.host is "auto" and remote {merge["remote"]} ({url}) is neither github.com '
                    'nor a gitlab host; set merge.host to "github" or "gitlab"', 2)


class Host:
    name = cli = noun = prefix = ""
    env = {"NO_COLOR": "1", "GIT_TERMINAL_PROMPT": "0"}

    def __init__(self, sh, root, remote, url=None):
        self.sh, self.root, self.remote, self.url = sh, root, remote, url

    @classmethod
    def label(cls, number):
        return f"{cls.noun} {cls.prefix}{number}"

    def missing(self):
        raise NotImplementedError

    def call(self, cmd, input=None):
        """Run a process in the root with the host environment. Never waits on a prompt."""
        try:
            return self.sh(cmd, cwd=self.root, input=input, env=self.env)
        except FileNotFoundError:
            raise HostError(self.missing() if cmd[0] == self.cli else f"cannot run {cmd[0]}: not found")

    def need(self, out, what):
        if out.returncode != 0:
            raise HostError(f"{self.cli} {what} failed: {first_line(out.stderr) or first_line(out.stdout)}")
        return out.stdout

    def json(self, out, what):
        try:
            return json.loads(self.need(out, what) or "null")
        except ValueError:
            raise HostError(f"{self.cli} {what} failed: output is not JSON")

    def push(self, local_ref, branch, expect):
        """Push `local_ref` to the remote branch, only if it is at `expect` ("" means: must not exist)."""
        out = self.call(["git", "-C", self.root, "push", self.remote, f"{local_ref}:refs/heads/{branch}",
                         f"--force-with-lease=refs/heads/{branch}:{expect}"])
        lines = [line.strip() for line in out.stderr.splitlines() if line.strip()]
        why = next((line for line in lines if line.startswith(("!", "error", "fatal"))), lines[0] if lines else "")
        return out.returncode == 0, why


class GitHub(Host):
    name, cli, noun, prefix = "github", "gh", "PR", "#"
    env = {**Host.env, "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1"}
    fields = "number,url,state,headRefOid,headRefName,baseRefName,mergedAt,mergeCommit,mergeStateStatus"
    states = {"CLEAN": "CLEAN", "HAS_HOOKS": "CLEAN", "BLOCKED": "BLOCKED", "UNSTABLE": "BLOCKED",
              "BEHIND": "BEHIND", "DIRTY": "DIRTY", "DRAFT": "DRAFT"}
    failed = ("failure", "timed_out", "startup_failure", "action_required")

    def missing(self):
        return "cannot run gh: install the GitHub CLI and run gh auth login"

    def gh(self, *args, input=None):
        return self.call(["gh", *args], input)

    def to_pr(self, d):
        raw = d.get("mergeStateStatus") or "UNKNOWN"
        return PR(int(d["number"]), d.get("url") or "", d.get("state") or "", d.get("headRefOid") or "",
                  d.get("headRefName") or "", d.get("baseRefName") or "", d.get("mergedAt") or None,
                  (d.get("mergeCommit") or {}).get("oid"), self.states.get(raw, "UNKNOWN"), raw)

    def default_branch(self):
        args = ("repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name")
        return self.need(self.gh(*args), "repo view").strip()

    def find_pr(self, branch):
        args = ("pr", "list", "--head", branch, "--state", "all", "--json", self.fields, "--limit", "5")
        found = self.json(self.gh(*args), "pr list") or []
        return self.to_pr(max(found, key=lambda d: d["number"])) if found else None

    def create_pr(self, branch, base, title, body):
        out = self.gh("pr", "create", "--head", branch, "--base", base, "--title", title, "--body-file", "-", input=body)
        if out.returncode != 0 and "already exists" in out.stderr:
            found = self.find_pr(branch)
            if found:
                return found
        lines = self.need(out, "pr create").strip().splitlines()
        url = lines[-1].strip() if lines else ""
        number = url.rstrip("/").rsplit("/", 1)[-1]
        if not number.isdigit():
            raise HostError(f"gh pr create failed: no request URL in its output: {url}")
        return PR(int(number), url, "OPEN", "", branch, base, None, None, "UNKNOWN", "UNKNOWN")

    def pr(self, number):
        return self.to_pr(self.json(self.gh("pr", "view", str(number), "--json", self.fields), "pr view"))

    def blockers(self, number):
        """Informational: it never raises. A failed check may exit 1 with the JSON still printed."""
        out = self.gh("pr", "checks", str(number), "--required", "--json", "name,state,bucket")
        try:
            checks = json.loads(out.stdout or "null")
        except ValueError:
            checks = None
        if not isinstance(checks, list):  # e.g. no required checks reported
            return first_line(out.stderr) or first_line(out.stdout) or "no check report"
        count = Counter(c.get("bucket") for c in checks)
        text = f"required checks: {count['pass']} pass, {count['fail']} fail, {count['pending']} pending"
        return text + "".join(f", {count[b]} {b}" for b in ("skipping", "cancel") if count[b])

    def merge(self, number, method, head):
        out = self.gh("pr", "merge", str(number), f"--{method}", "--match-head-commit", head)
        return out.returncode == 0, first_line(out.stderr) or first_line(out.stdout)

    def runs(self, branch, head, name):
        args = ("run", "list", "--branch", branch, "--workflow", name, "--json",
                "databaseId,attempt,status,conclusion,headSha,url,createdAt", "--limit", "20")
        found = [d for d in self.json(self.gh(*args), "run list") or [] if d.get("headSha") == head]
        found.sort(key=lambda d: (d.get("createdAt") or "", d["databaseId"]), reverse=True)
        runs = []
        for d in found:
            done = d.get("status") == "completed"
            conclusion = d.get("conclusion") or ""
            status = ("pending" if not done else "success" if conclusion == "success"
                      else "failure" if conclusion in self.failed else "blocked")
            runs.append(Run(str(d["databaseId"]), int(d.get("attempt") or 1), status,
                            conclusion if done else d.get("status") or "", d.get("url") or "", d.get("createdAt") or ""))
        return runs

    def dispatch(self, branch, name):
        out = self.gh("workflow", "run", name, "--ref", branch)
        if out.returncode == 0:
            return True, ""
        if "422" in out.stderr or "workflow_dispatch" in out.stderr:
            return False, "no manual trigger"
        return False, first_line(out.stderr)


class GitLab(Host):
    """GitLab through `glab api`, the REST v4 API. UNVERIFIED: glab is not installed on the machine
    this was written on, so every glab line here rests on the documentation and the fake glab in
    the tests. Check these against a test project before you rely on it:
      1. `glab api` takes -X, -f key=value and -F, prints the raw JSON body, and exits non-zero on
         a non-2xx status after printing the body.
      2. Whether `:id` stands for the current project. Until then the project path P comes from
         the remote URL.
      3. The merge request list filters `source_branch` and `state=all`, and `detailed_merge_status`
         (GitLab 15.6 or later) holds the words mapped below.
      4. `pipelines?sha=` also returns merge request pipelines for that SHA.
      5. The merge endpoint's `sha` parameter rejects a mismatched head with HTTP 409.
      6. `glab` never prompts on the `api` path without a TTY.
      7. After a fast-forward merge, which of `merge_commit_sha` and `sha` is set.
      8. `merge_requests/<iid>/approvals` returns `approvals_left` and `approval_rules_left` on the
         instance's tier (approval rules are a paid feature).
    """

    name, cli, noun, prefix = "gitlab", "glab", "MR", "!"
    env = {**Host.env, "GLAB_CHECK_UPDATE": "false"}  # UNVERIFIED variable name, harmless if ignored
    states = {"mergeable": "CLEAN", "need_rebase": "BEHIND", "conflict": "DIRTY", "draft_status": "DRAFT",
              "checking": "UNKNOWN", "unchecked": "UNKNOWN", "preparing": "UNKNOWN", "approvals_syncing": "UNKNOWN",
              "": "UNKNOWN"}
    running = ("created", "waiting_for_resource", "preparing", "pending", "running", "scheduled", "manual")
    _project = None

    def missing(self):
        host = parse_remote(self.url or "")[0] or "<host>"
        return f"cannot run glab: install the GitLab CLI and run glab auth login --hostname {host}"

    @property
    def project(self):
        if self._project is None:
            url = self.url
            if url is None:
                url = self.call(["git", "-C", self.root, "remote", "get-url", self.remote]).stdout.strip()
            self._project = urlquote(parse_remote(url)[1], safe="")
        return self._project

    def api(self, path, *flags, method=None):
        """(process result, parsed body or None) for one REST call on this project."""
        # UNVERIFIED: `glab api <endpoint> -X M -f k=v`, and the body printed on a non-2xx exit.
        args = ["api", *(["-X", method] if method else []), f"projects/{self.project}{path}", *flags]
        out = self.call(["glab", *args])
        try:
            body = json.loads(out.stdout or out.stderr or "null")
        except ValueError:
            body = None
        return out, body

    def get(self, path):
        out, body = self.api(path)
        self.need(out, "api projects/<project>" + path.split("?")[0])
        return body

    def message(self, out, body):
        if isinstance(body, dict):
            return str(body.get("message") or body.get("error") or "")
        return first_line(out.stderr) or first_line(out.stdout)

    def to_pr(self, d):
        # UNVERIFIED JSON fields: iid, web_url, state, sha, source_branch, target_branch, merged_at,
        # merge_commit_sha, squash_commit_sha, detailed_merge_status, has_conflicts.
        word = d.get("detailed_merge_status") or ""
        state = {"opened": "OPEN", "locked": "OPEN", "merged": "MERGED", "closed": "CLOSED"}.get(d.get("state"), "")
        merge_state = ("DIRTY" if word == "conflict" or d.get("has_conflicts")
                       else self.states.get(word, "BLOCKED"))
        merge_commit = d.get("merge_commit_sha") or d.get("squash_commit_sha") or d.get("sha")
        return PR(int(d["iid"]), d.get("web_url") or "", state, d.get("sha") or "", d.get("source_branch") or "",
                  d.get("target_branch") or "", d.get("merged_at") or None, merge_commit, merge_state, word or d.get("state") or "")

    def default_branch(self):
        out, body = self.api("")
        self.need(out, "api projects/<project>")
        return str((body or {}).get("default_branch") or "")

    def find_pr(self, branch):
        # UNVERIFIED: the source_branch, state=all, order_by and sort query parameters.
        query = f"?source_branch={urlquote(branch, safe='')}&state=all&order_by=created_at&sort=desc&per_page=5"
        found = self.get("/merge_requests" + query) or []
        return self.to_pr(max(found, key=lambda d: d["iid"])) if found else None

    def create_pr(self, branch, base, title, body):
        # UNVERIFIED: the POST fields, and HTTP 409 "already exists" for a second request.
        out, made = self.api("/merge_requests", "-f", f"source_branch={branch}", "-f", f"target_branch={base}",
                             "-f", f"title={title}", "-f", f"description={body}", "-f", "remove_source_branch=false",
                             method="POST")
        if out.returncode != 0 and "already exists" in (out.stdout + out.stderr):
            found = self.find_pr(branch)
            if found:
                return found
        self.need(out, "api projects/<project>/merge_requests")
        return self.to_pr(made)

    def pr(self, number):
        return self.to_pr(self.get(f"/merge_requests/{number}"))

    def blockers(self, number):
        """Informational: it never raises. A failed call adds the first line of its error instead."""
        # UNVERIFIED: pipelines?sha= and the approvals_left field of merge_requests/<iid>/approvals.
        try:
            p = self.pr(number)
        except HostError as exc:
            return first_line(str(exc))
        parts = [p.raw_state]
        try:
            pipelines = self.get(f"/pipelines?sha={p.head}&per_page=1") or []
            parts.append(f"pipeline {pipelines[0].get('status')}" if pipelines else "no pipeline")
        except HostError as exc:
            parts.append(first_line(str(exc)))
        try:
            left = (self.get(f"/merge_requests/{number}/approvals") or {}).get("approvals_left") or 0
            if left > 0:
                parts.append(f"approvals left: {left}")
        except HostError as exc:  # e.g. a 403 or 404 where approvals are not part of the plan
            parts.append(first_line(str(exc)))
        return ", ".join(parts)

    def merge(self, number, method, head):
        # UNVERIFIED: the sha, should_remove_source_branch and squash fields of the merge endpoint.
        flags = ["-f", f"sha={head}", "-f", "should_remove_source_branch=false"] + (["-f", "squash=true"] if method == "squash" else [])
        out, body = self.api(f"/merge_requests/{number}/merge", *flags, method="PUT")
        if out.returncode == 0 and isinstance(body, dict) and body.get("state") == "merged":
            return True, ""
        return False, self.message(out, body) or "the merge request is not merged"

    def runs(self, branch, head, name):
        # UNVERIFIED: pipelines?sha=, order_by=id and the pipelines/<id>/jobs endpoint.
        found = [d for d in self.get(f"/pipelines?sha={head}&order_by=id&sort=desc&per_page=20") or []
                 if d.get("sha") == head]  # do not trust the server-side filter

        def status(word):
            return "pending" if word in self.running else "success" if word == "success" else "failure" if word == "failed" else "blocked"

        if name == "pipeline" or not found:
            return [Run(str(d["id"]), 1, status(d.get("status")), d.get("status") or "", d.get("web_url") or "",
                        d.get("created_at") or "") for d in found]
        newest = found[0]
        jobs = [j for j in self.get(f"/pipelines/{newest['id']}/jobs?per_page=100") or [] if j.get("name") == name]
        if not jobs:
            return [Run(str(newest["id"]), 1, "blocked", f"no job {name}", newest.get("web_url") or "", newest.get("created_at") or "")]
        job = max(jobs, key=lambda j: j["id"])
        return [Run(f"{newest['id']}/{job['id']}", 1, status(job.get("status")), job.get("status") or "",
                    job.get("web_url") or "", job.get("created_at") or newest.get("created_at") or "")]

    def dispatch(self, branch, name):
        # UNVERIFIED: POST projects/<project>/pipeline and its HTTP 400 "Missing CI config" answer.
        out, body = self.api("/pipeline", "-f", f"ref={branch}", method="POST")
        if out.returncode == 0:
            return True, ""
        text = out.stdout + out.stderr
        if ".gitlab-ci.yml" in text or "Missing CI config" in text:
            return False, "no manual trigger"
        return False, self.message(out, body)
