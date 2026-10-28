"""Tests for scripts/run.py. Run: "$PY" -m unittest discover plugins/agentic-team/tests

Each test builds a temporary git repository as the root with a bare origin.git
beside it, a temporary Taskgraph database, a temporary HOME, the real tg.py from
plugins/taskgraph, and fakes first on PATH: `claude`, `gh`, and `glab`. Each fake
logs every call and answers from files the test writes. Nothing here starts a
real Claude session or reaches a real code host.
"""

import functools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from urllib.parse import quote as urlquote

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.dirname(os.path.dirname(HERE))
RUN = os.path.join(os.path.dirname(HERE), "scripts", "run.py")
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import host as codehost  # noqa: E402
TG = os.path.join(PLUGINS, "taskgraph", "skills", "taskgraph", "scripts", "tg.py")

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, re, subprocess, sys

argv = sys.argv[1:]
with open(os.environ["FAKE_CLAUDE_LOG"], "a") as fh:
    fh.write(json.dumps(argv) + "\n")


def read(name):
    path = os.environ.get(name)
    return open(path).read() if path and os.path.isfile(path) else None


cmd = argv[0] if argv else ""
if cmd == "agents":
    print(read("FAKE_CLAUDE_AGENTS") or "[]")
elif cmd == "--bg":
    wt = os.path.join(".claude", "worktrees", argv[argv.index("--worktree") + 1])
    if os.environ.get("FAKE_CLAUDE_DIRTY"):  # the session wrote a file before it failed
        open(os.path.join(wt, "junk.txt"), "w").write("x")
    if os.environ.get("FAKE_CLAUDE_COMMIT"):  # the session moved the branch
        subprocess.run(["git", "-C", wt, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "--allow-empty",
                        "-m", "x"], check=True)
    if os.environ.get("FAKE_CLAUDE_MOVE"):  # claude no longer reuses the prepared worktree
        subprocess.run(["git", "-C", wt, "checkout", "-q", "--detach", os.environ["FAKE_CLAUDE_MOVE"]], check=True)
    if os.environ.get("FAKE_CLAUDE_UNTRUSTED"):
        sys.stderr.write("Workspace not trusted. Run claude in the repository first.\n")
        sys.exit(1)
    if os.environ.get("FAKE_CLAUDE_BG_ERROR"):
        sys.stderr.write(os.environ["FAKE_CLAUDE_BG_ERROR"] + "\n")
        sys.exit(1)
    if os.environ.get("FAKE_CLAUDE_BG_ROW"):  # the new session shows up in `claude agents`
        open(os.environ["FAKE_CLAUDE_AGENTS"], "w").write("[" + os.environ["FAKE_CLAUDE_BG_ROW"] + "]")
    said = os.environ.get("FAKE_CLAUDE_BG_SAID")
    if said is None:  # what claude 2.1.311 prints: the short id and the name, then help lines
        name = argv[argv.index("--name") + 1]
        said = ("backgrounded \u00b7 sess-%s \u00b7 %s\n  claude stop sess-%s      stop this session\n"
                % (name, name, name))
    sys.stdout.write(said)
elif cmd == "stop":
    if os.environ.get("FAKE_CLAUDE_STOP_FAIL"):
        sys.stderr.write("boom\n")
        sys.exit(1)
elif cmd == "logs":
    folder = os.environ.get("FAKE_CLAUDE_LOGS_DIR")
    path = os.path.join(folder, argv[1] + ".txt") if folder else ""
    if path and os.path.isfile(path):
        sys.stdout.write(open(path).read())
elif cmd == "rm":
    table = json.loads(read("FAKE_CLAUDE_RM") or "{}")
    entry = table.get(argv[1], {})
    if entry.get("exit") and "--discard-unpushed" not in argv:
        sys.stderr.write(entry.get("stderr", "") + "\n")
        sys.exit(entry["exit"])
    if os.environ.get("FAKE_CLAUDE_AFTER_RM"):  # a session started while the rows were being removed
        open(os.environ["FAKE_CLAUDE_AGENTS"], "w").write(open(os.environ["FAKE_CLAUDE_AFTER_RM"]).read())
    if not entry.get("row_only"):  # like the real claude rm: the worktree goes with the session that owns it
        folder = argv[1][len("sess-"):] if argv[1].startswith("sess-") else argv[1]
        if re.fullmatch(r"task-\d+-\d+", folder):  # sess-task-<id>-<attempt>: the folder is task-<id>
            folder = folder.rsplit("-", 1)[0]
        for cmd_ in (["worktree", "remove", "-f", "-f", os.path.join(".claude", "worktrees", folder)],
                     ["branch", "-D", "worktree-" + folder]):
            subprocess.run(["git"] + cmd_, capture_output=True)
'''

# One template, written under two names. It logs argv to $FAKE_<NAME>_LOG, then answers from the JSON table
# in the file $FAKE_<NAME>: the longest table key that is a prefix of the joined argv wins. A value is
# {"stdout", "stderr", "exit"} or a list of them, consumed in order, the last one repeating.
FAKE_HOST = r'''#!/usr/bin/env python3
import json, os, sys

name = os.path.basename(sys.argv[0]).upper()
argv = sys.argv[1:]
log = os.environ["FAKE_%s_LOG" % name]
with open(log, "a") as fh:
    fh.write(json.dumps(argv) + "\n")
if "-" in argv:  # a body on stdin
    with open(log + ".in", "a") as fh:
        fh.write(json.dumps({"argv": argv, "stdin": sys.stdin.read()}) + "\n")
path = os.environ.get("FAKE_" + name)
table = json.load(open(path)) if path and os.path.isfile(path) else {}
line = " ".join(argv)
keys = [k for k in table if line.startswith(k)]
if not keys:
    sys.stderr.write("fake: no answer for %s\n" % json.dumps(argv))
    sys.exit(1)
key = max(keys, key=len)
value = table[key]
if isinstance(value, list):
    seen = json.load(open(path + ".pos")) if os.path.isfile(path + ".pos") else {}
    index = seen.get(key, 0)
    seen[key] = index + 1
    json.dump(seen, open(path + ".pos", "w"))
    value = value[min(index, len(value) - 1)]
sys.stdout.write(value.get("stdout", ""))
sys.stderr.write(value.get("stderr", ""))
sys.exit(value.get("exit", 0))
'''

CHECKPOINT = "2026-10-26 10:00 SGT — completed: a; next: b; blocker: none"
SHA_A = "a" * 40


def transcript(output_tokens):
    records = [
        {"type": "user", "timestamp": "2026-10-26T01:00:00Z", "message": {"content": "hi"}},
        {"type": "assistant", "timestamp": "2026-10-26T01:05:00Z",
         "message": {"id": "m1", "usage": {"output_tokens": output_tokens, "input_tokens": 3,
                                           "cache_read_input_tokens": 5, "cache_creation_input_tokens": 7}}},
    ]
    return "".join(json.dumps(r) + "\n" for r in records)


def both_hosts(test):
    """Run a PR-mode test once for GitHub (gh) and once for GitLab (glab), each on a fresh repository."""
    @functools.wraps(test)
    def wrapper(self):
        for index, name in enumerate(("github", "gitlab")):
            with self.subTest(host=name):
                if index:
                    self.tearDown()
                    self.setUp()
                self.host = name
                test(self)
    return wrapper


class Base(unittest.TestCase):
    host = "github"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.realpath(self._tmp.name)
        self.root = os.path.join(self.dir, "repo")
        self.home = os.path.join(self.dir, "home")
        self.bin = os.path.join(self.dir, "bin")
        self.logs = os.path.join(self.dir, "logs")
        for path in (self.root, self.home, self.bin, self.logs):
            os.makedirs(path)
        self.git("init", "-q", "-b", "main")
        for key, value in (("user.name", "t"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
            self.git("config", key, value)
        self.git("commit", "-q", "--allow-empty", "-m", "base")
        with open(os.path.join(self.root, ".git", "info", "exclude"), "a") as fh:
            fh.write(".claude/worktrees/\n.agentic-team/\n.agentic-team.toml\n")
        self.origin = os.path.join(self.dir, "origin.git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.origin], check=True)
        self.git("remote", "add", "origin", self.origin)
        for name, text in (("claude", FAKE_CLAUDE), ("gh", FAKE_HOST), ("glab", FAKE_HOST)):
            fake = os.path.join(self.bin, name)
            with open(fake, "w") as fh:
                fh.write(text)
            os.chmod(fake, 0o755)
        self.log = os.path.join(self.dir, "claude.log")
        self.agents_file = os.path.join(self.dir, "agents.json")
        self.rm_file = os.path.join(self.dir, "rm.json")
        self.db = os.path.join(self.dir, "tasks.db")
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("TASKGRAPH_DB", "TASKGRAPH_TG", "CLAUDE_CONFIG_DIR")}
        self.env.update({
            "HOME": self.home, "TASKGRAPH_DB": self.db,
            "PATH": self.bin + os.pathsep + os.environ.get("PATH", ""),
            "FAKE_CLAUDE_LOG": self.log, "FAKE_CLAUDE_AGENTS": self.agents_file,
            "FAKE_CLAUDE_LOGS_DIR": self.logs, "FAKE_CLAUDE_RM": self.rm_file,
            "FAKE_GH": os.path.join(self.dir, "gh.json"), "FAKE_GH_LOG": os.path.join(self.dir, "gh.log"),
            "FAKE_GLAB": os.path.join(self.dir, "glab.json"), "FAKE_GLAB_LOG": os.path.join(self.dir, "glab.log"),
        })
        self.project = urlquote(codehost.parse_remote(self.origin)[1], safe="")  # the GitLab project path
        self.write_config()

    def tearDown(self):
        self._tmp.cleanup()

    # --- helpers

    def git(self, *args, cwd=None):
        out = subprocess.run(["git", "-C", cwd or self.root, *args], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip()

    def write_config(self, extra="", sessions=""):
        with open(os.path.join(self.root, ".agentic-team.toml"), "w") as fh:
            fh.write('[taskgraph]\nproject = "demo"\n[sessions]\ntimezone = "UTC"\n' + sessions
                     + textwrap.dedent(extra))

    def orders(self, text):
        os.makedirs(os.path.join(self.root, ".agentic-team"), exist_ok=True)
        with open(os.path.join(self.root, ".agentic-team", "standing-orders.md"), "w") as fh:
            fh.write(text)

    def tg(self, *args, stdin=None, env=None):
        out = subprocess.run([sys.executable, TG, "--project", "demo", "--json", *args],
                             input=stdin, capture_output=True, text=True, env=env or self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def add_task(self, title="Sweep domains", notes="Why: reason.\n- [ ] done", scope="src/", verify="make test",
                 start=False, depends=(), env=None, **meta):
        pairs = [f"scope={scope}", f"verify={verify}", "estimate=1"] + [f"{k}={v}" for k, v in meta.items()]
        args = ["add", title, "--notes", notes, "--meta", *pairs]
        for dep in depends:
            args += ["--depends", str(dep)]
        task_id = self.tg(*args, env=env)["id"]
        if start:
            self.tg("start", str(task_id), env=env)
        return task_id

    def add_result(self, task_id, status, body="", kind="task", attempt=1, by="worker"):
        return self.tg("result", "add", str(task_id), "--kind", kind, "--attempt", str(attempt), "--by", by,
                       "--status", status, "--body-file", "-", stdin=body)

    def results(self, task_id):
        return self.tg("result", "ls", str(task_id))

    def meta(self, task_id):
        return self.tg("show", str(task_id))["meta"]

    def status_of(self, task_id):
        return self.tg("show", str(task_id))["status"]

    def worktree(self, name, base="HEAD"):
        path = os.path.join(self.root, ".claude", "worktrees", name)
        self.git("worktree", "add", "-q", path, "-b", f"worktree-{name}", base)
        return path

    def wt_path(self, name):
        return os.path.join(self.root, ".claude", "worktrees", name)

    def wt_commit(self, wt, name="out.txt", text="x\n"):
        with open(os.path.join(wt, name), "w") as fh:
            fh.write(text)
        self.git("add", "-A", cwd=wt)
        self.git("commit", "-q", "-m", f"work on {name}", cwd=wt)
        return self.git("rev-parse", "HEAD", cwd=wt)

    def row(self, wtname, attempt=1, status="busy", state="working", name=None, **extra):
        """A row of `claude agents --json`. A task folder is shared by its attempts, so the id carries the
        attempt (sess-task-1-1, the id a real launch records); a verifier folder has one session."""
        cwd = os.path.join(self.root, ".claude", "worktrees", wtname)
        sid = f"sess-{wtname}-{attempt}" if re.fullmatch(r"task-\d+", wtname) else f"sess-{wtname}"
        return {"id": sid, "name": name or wtname, "cwd": cwd, "status": status, "state": state, **extra}

    def finished(self, wtname, attempt=1, **extra):
        return self.row(wtname, attempt, status="idle", state="done", **extra)

    def entry(self, task, attempt=1, kind="task", worktree=None, name=None):
        """The `sessions` meta entry run.py records for a session it started."""
        if kind == "verify":
            worktree = worktree or f"verify-{task}-{attempt}"
            return {"id": f"sess-{worktree}", "kind": kind, "attempt": attempt, "name": name or worktree,
                    "worktree": worktree}
        return {"id": f"sess-task-{task}-{attempt}", "kind": "task", "attempt": attempt,
                "name": name or f"task-{task}-{attempt}", "worktree": f"task-{task}"}

    def record_sessions(self, task, *entries):
        self.tg("edit", str(task), "--meta", "sessions=" + json.dumps(list(entries)))

    def agents(self, *rows):
        with open(self.agents_file, "w") as fh:
            json.dump(list(rows), fh)

    def calls(self, command=None):
        if not os.path.isfile(self.log):
            return []
        with open(self.log) as fh:
            found = [json.loads(line) for line in fh if line.strip()]
        return [c for c in found if command is None or c[0] == command]

    def run_cmd(self, *args, pre=(), tg=TG, env=None, root=None):
        cmd = [sys.executable, RUN, "--root", root or self.root]
        if tg:
            cmd += ["--tg", tg]
        return subprocess.run(cmd + list(pre) + list(args), capture_output=True, text=True,
                              cwd=self.dir, env=env or self.env)

    def ok(self, *args, **kw):
        out = self.run_cmd(*args, **kw)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out

    def events(self, *args, **kw):
        out = self.ok(*args, pre=["--json"], **kw)
        return json.loads(out.stdout)

    @staticmethod
    def named(events, name):
        return [e for e in events if e["event"] == name]

    def one(self, events, name):
        found = self.named(events, name)
        self.assertEqual(len(found), 1, f"{name} in {[e['event'] for e in events]}")
        return found[0]

    @staticmethod
    def section(text, name):
        match = re.search(rf"(?ms)^## {name}\n\n(.*?)(?=^## |\Z)", text)
        return match.group(1).strip() if match else None

    def assert_base(self, text, sha):
        """The brief names the base and the worktree branch, and tells the worker to move nothing."""
        self.assertIn(f"Base commit: {sha}. Your worktree is already at the base commit `{sha}`, on branch `worktree-task-", text)
        self.assertIn(f"If `git rev-parse HEAD` is not `{sha}`, report BLOCKED and change nothing.", text)
        self.assertNotRegex(text, r"git (reset|checkout|switch)")

    def brief(self, task_id, *extra, **kw):
        return self.ok("launch", str(task_id), "--dry-run", *extra, **kw).stdout

    def task_wt(self, task_id=1):
        """The task's one worktree, created on first use."""
        path = self.wt_path(f"task-{task_id}")
        return path if os.path.isdir(path) else self.worktree(f"task-{task_id}")

    def pass_report(self, task_id=1, attempt=1, wt=None, head=None, branch=None):
        wt = wt or self.task_wt(task_id)
        head = head or self.wt_commit(wt)
        self.add_result(task_id, "PASS", f"Task: {task_id}\nStatus: PASS\nBranch: {branch or f'worktree-task-{task_id}'}\n"
                        f"Head: {head}\nWorktree: {wt}\nCheckpoint: {CHECKPOINT}\n", attempt=attempt)
        return wt, head

    def running_task(self, attempt=1, sessions=None, **meta):
        """A started task. It has the session run.py would have recorded for `attempt`, unless a test passes
        `sessions` (a list of entries; [] for an unrecorded row)."""
        task = self.add_task(start=True, attempt=attempt, **meta)
        entries = [self.entry(task, attempt)] if sessions is None else sessions
        self.record_sessions(task, *entries)
        return task

    def make_runner(self):
        return types.SimpleNamespace(root=self.root)

    def commit_file(self, name, text, cwd=None, message=None, binary=False):
        path = os.path.join(cwd or self.root, name)
        with open(path, "wb" if binary else "w") as fh:
            fh.write(text)
        self.git("add", "-A", cwd=cwd)
        self.git("commit", "-q", "-m", message or f"edit {name}", cwd=cwd)
        return self.git("rev-parse", "HEAD", cwd=cwd)

    def feature_branch(self, name="feature"):
        self.git("checkout", "-q", "-b", name)
        tip = self.commit_file(f"{name}.txt", "work\n")
        self.git("checkout", "-q", "main")
        return tip

    def merges(self):
        return self.git("log", "--merges", "--format=%s")

    def status_sections(self, *args):
        out = self.ok("status", *args)
        sections = {}
        for block in re.split(r"(?m)^## ", out.stdout)[1:]:
            sections[re.sub(r" \(\d+\)$", "", block.splitlines()[0])] = block
        return sections

    def verified_by(self, verdict, task=None):
        task = task or self.running_task()
        self.pass_report(task)
        status = {"verify-failed": "ISSUES", "verify-blocked": "BLOCKED"}.get(verdict, "PASS")
        self.add_result(task, status, f"Status: {status}\nVerdict: {verdict}\n", kind="verify", by=f"verify-{task}-1")
        return task

    # --- code host fakes (pr mode)

    def pr_config(self, extra=""):
        self.write_config(f'[merge]\nmode = "pr"\nhost = "{self.host}"\n' + extra)
        self.git("push", "-q", "origin", "main")

    def fake_host(self, **state):
        """Write the fake gh or glab answer table for one request state, in the dialect of self.host.

        number, state (OPEN MERGED CLOSED), merge_state (CLEAN BLOCKED BEHIND DIRTY DRAFT UNKNOWN), head,
        base, branch, merge_commit, squash_commit, listed (find_pr sees it), checks (buckets), runs (newest
        first: {id, attempt, state: success|failure|cancelled|pending, head}), jobs (GitLab, of the newest
        pipeline), dispatch (ok|none|error), merge (ok or an error message), then (a state change that the
        next view shows, as after a merge), extra (table entries added last)."""
        s = {"number": 1, "state": "OPEN", "merge_state": "CLEAN", "head": "f" * 40, "base": "main", "branch": "task-1",
             "merge_commit": None, "squash_commit": None, "listed": False, "checks": (), "runs": (), "jobs": (),
             "dispatch": "ok", "merge": "ok", "then": None, "extra": {}}
        s.update(state)

        def out(text="", exit=0, err=""):
            return {"stdout": text, "stderr": err, "exit": exit}

        def at(run):
            return f"2026-10-26T10:{(run['id'] // 60) % 60:02d}:{run['id'] % 60:02d}Z"

        def views(build):
            now = build(s)
            return [out(json.dumps(now))] + ([out(json.dumps(build({**s, **s["then"]})))] if s["then"] else [])

        n, runs = s["number"], list(s["runs"])
        if self.host == "github":
            words = {"UNKNOWN": "UNKNOWN"}

            def view(x):
                return {"number": x["number"], "url": f"https://github.com/o/r/pull/{x['number']}", "state": x["state"],
                        "headRefOid": x["head"], "headRefName": x["branch"], "baseRefName": x["base"],
                        "mergedAt": "2026-10-26T11:00:00Z" if x["state"] == "MERGED" else None,
                        "mergeCommit": {"oid": x["merge_commit"]} if x["merge_commit"] else None,
                        "mergeStateStatus": words.get(x["merge_state"], x["merge_state"])}

            shown = {"success": ("completed", "success"), "failure": ("completed", "failure"),
                     "cancelled": ("completed", "cancelled"), "pending": ("in_progress", None)}
            table = {
                "repo view": out(s["base"] + "\n"),
                "pr list": out(json.dumps([view(s)] if s["listed"] else [])),
                "pr create": out(f"https://github.com/o/r/pull/{n}\n"),
                "pr view": views(view),
                "pr checks": out(json.dumps([{"name": f"c{i}", "state": b, "bucket": b} for i, b in enumerate(s["checks"])]),
                                 exit=1 if "fail" in s["checks"] else 8 if "pending" in s["checks"] else 0),
                "pr merge": out() if s["merge"] == "ok" else out(exit=1, err=s["merge"] + "\n"),
                "run list": out(json.dumps([{"databaseId": r["id"], "attempt": r.get("attempt", 1),
                                             "status": shown[r["state"]][0], "conclusion": shown[r["state"]][1],
                                             "headSha": r.get("head") or s["head"], "url": f"https://ci.example/runs/{r['id']}",
                                             "createdAt": at(r)} for r in runs])),
                "workflow run": {"ok": out(), "none": out(exit=1, err="HTTP 422: Workflow does not have 'workflow_dispatch' trigger\n"),
                                 "error": out(exit=1, err="HTTP 500: boom\n")}[s["dispatch"]],
            }
        else:
            words = {"CLEAN": "mergeable", "BLOCKED": "ci_must_pass", "BEHIND": "need_rebase", "DIRTY": "conflict",
                     "DRAFT": "draft_status", "UNKNOWN": "checking"}
            proj = f"projects/{self.project}"
            api = f"api {proj}"

            def view(x):
                return {"iid": x["number"], "web_url": f"https://gitlab.example.com/g/p/-/merge_requests/{x['number']}",
                        "state": {"OPEN": "opened", "MERGED": "merged", "CLOSED": "closed"}[x["state"]], "sha": x["head"],
                        "source_branch": x["branch"], "target_branch": x["base"],
                        "merged_at": "2026-10-26T11:00:00Z" if x["state"] == "MERGED" else None,
                        "merge_commit_sha": x["merge_commit"], "squash_commit_sha": x["squash_commit"],
                        "detailed_merge_status": words[x["merge_state"]], "has_conflicts": x["merge_state"] == "DIRTY"}

            word = {"success": "success", "failure": "failed", "cancelled": "canceled", "pending": "running"}
            pipes = [{"id": r["id"], "status": word[r["state"]], "web_url": f"https://ci.example/pipelines/{r['id']}",
                      "created_at": at(r), "sha": r.get("head") or s["head"]} for r in runs]
            if not pipes and s["checks"]:
                status = "failed" if "fail" in s["checks"] else "running" if "pending" in s["checks"] else "success"
                pipes = [{"id": 900, "status": status, "web_url": "https://ci.example/pipelines/900", "created_at": at({"id": 900}),
                          "sha": s["head"]}]
            merged = {**view({**s, "state": "MERGED"})}
            table = {
                api: out(json.dumps({"default_branch": s["base"]})),
                f"{api}/merge_requests?": out(json.dumps([view(s)] if s["listed"] else [])),
                f"{api}/merge_requests/{n}": views(view),
                f"{api}/merge_requests/{n}/approvals": out(json.dumps({"approvals_left": 0})),
                f"api -X POST {proj}/merge_requests": out(json.dumps(view(s))),
                f"api -X PUT {proj}/merge_requests/{n}/merge": (out(json.dumps(merged)) if s["merge"] == "ok"
                                                              else out(json.dumps({"message": s["merge"]}), exit=1)),
                f"{api}/pipelines?": out(json.dumps(pipes)),
                f"api -X POST {proj}/pipeline": {"ok": out("{}"), "error": out(json.dumps({"message": "boom"}), exit=1),
                                                "none": out(json.dumps({"message": "Missing CI config file"}), exit=1)}[s["dispatch"]],
            }
            if pipes and s["jobs"]:
                table[f"{api}/pipelines/{pipes[0]['id']}/jobs"] = out(json.dumps(
                    [{"id": 5000 + i, "name": j["name"], "status": j["status"], "web_url": f"https://ci.example/jobs/{5000 + i}",
                      "created_at": "2026-10-26T10:00:00Z"} for i, j in enumerate(s["jobs"])]))
        table.update(s["extra"])
        path = os.path.join(self.dir, "gh.json" if self.host == "github" else "glab.json")
        for stale in (path, path + ".pos"):
            if os.path.isfile(stale):
                os.remove(stale)
        with open(path, "w") as fh:
            json.dump(table, fh)

    def host_log(self, name=None):
        """The argv lists the fake gh or glab was called with."""
        path = os.path.join(self.dir, f"{name or ('gh' if self.host == 'github' else 'glab')}.log")
        if not os.path.isfile(path):
            return []
        with open(path) as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def host_calls(self, *words):
        """The logged calls whose joined argv starts with the words."""
        return [c for c in self.host_log() if " ".join(c).startswith(" ".join(words))]

    def host_stdin(self):
        path = os.path.join(self.dir, ("gh" if self.host == "github" else "glab") + ".log.in")
        if not os.path.isfile(path):
            return []
        with open(path) as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def label(self, number=1):
        return f"PR #{number}" if self.host == "github" else f"MR !{number}"

    def merge_calls(self):
        return self.host_calls("pr merge") if self.host == "github" else self.host_calls("api -X PUT")

    def create_calls(self):
        return (self.host_calls("pr create") if self.host == "github"
                else self.host_calls("api", "-X", "POST", f"projects/{self.project}/merge_requests"))

    def checkout(self):
        """What a pr-mode command must leave alone: the root's branch, HEAD, and porcelain."""
        return (self.git("branch", "--show-current"), self.git("rev-parse", "HEAD"), self.git("status", "--porcelain"))

    def remote_sha(self, branch="task-1"):
        out = subprocess.run(["git", "-C", self.origin, "rev-parse", "--verify", "-q", f"refs/heads/{branch}"],
                             capture_output=True, text=True)
        return out.stdout.strip() or None

    def pr_task(self, files=("out.txt", "x\n"), **meta):
        """A running task whose worker passed, in pr mode. Returns (task, worktree, head)."""
        self.pr_config()
        task = self.running_task(base=json.dumps(self.git("rev-parse", "HEAD")), **meta)
        wt = self.task_wt(task)
        wt, head = self.pass_report(task, wt=wt, head=self.wt_commit(wt, *files))
        self.agents(self.finished(f"task-{task}"))
        return task, wt, head

    def fresh(self):
        self.tearDown()
        self.setUp()

    def worktree_state(self):
        """(registered worktrees, worktree-* branches, folders under .claude/worktrees)"""
        folder = os.path.join(self.root, ".claude", "worktrees")
        return (len(re.findall(r"(?m)^worktree ", self.git("worktree", "list", "--porcelain"))),
                self.git("branch", "--list", "worktree-*"),
                sorted(os.listdir(folder)) if os.path.isdir(folder) else [])


class RunTest(Base):
    # --- common

    def test_01_not_a_repository_root(self):
        plain = os.path.join(self.dir, "plain")
        os.makedirs(plain)
        out = self.run_cmd("record", root=plain)
        self.assertEqual(out.returncode, 2)
        self.assertIn(plain, out.stderr)
        self.assertIn("not a repository root", out.stderr)
        sub = os.path.join(self.root, "sub")
        os.makedirs(sub)
        out = self.run_cmd("record", root=sub)
        self.assertEqual(out.returncode, 2)
        self.assertIn(sub, out.stderr)

    def test_02_config_problem(self):
        with open(os.path.join(self.root, ".agentic-team.toml"), "w") as fh:
            fh.write('[taskgraph]\nproject = "TODO"\n')
        out = self.run_cmd("record")
        self.assertEqual(out.returncode, 2)
        self.assertIn("taskgraph.project is TODO", out.stderr)

    def test_03_tg_resolution(self):
        env = dict(self.env, TASKGRAPH_TG=TG)
        self.assertEqual(self.run_cmd("record", tg=None, env=env).returncode, 0)
        out = self.run_cmd("record", tg=os.path.join(self.dir, "missing-tg.py"), env=env)
        self.assertEqual(out.returncode, 1)
        self.assertIn("tg", out.stderr)

    def test_04_json_is_one_array_and_refusals_stay_on_stderr(self):
        self.add_task()
        events = self.events("record")
        self.assertIsInstance(events, list)
        self.assertEqual(set(events[0]), {"event", "task", "attempt", "session", "detail", "next"})
        decision = self.tg("add", "Q?", "--type", "decision")["id"]
        out = self.run_cmd("launch", str(decision), pre=["--json"])
        self.assertEqual(out.returncode, 2)
        self.assertEqual(json.loads(out.stdout), [])
        self.assertTrue(out.stderr.startswith("run.py: "))

    # --- brief rendering, through launch --dry-run

    def test_05_label_lines_stay_in_goal(self):
        task = self.add_task(notes=textwrap.dedent("""
            Why: list stale domains.
            Serves: the ops team.
            Purpose: tidy up the registry.

            - [ ] every domain listed
        """).strip())
        text = self.brief(task)
        goal = self.section(text, "GOAL")
        for line in ("Why: list stale domains.", "Serves: the ops team.", "Purpose: tidy up the registry."):
            self.assertIn(line, goal)
        self.assertEqual(self.section(text, "ACCEPTANCE"), "- every domain listed")

    def test_05_known_labels_still_parse(self):
        task = self.add_task(notes=textwrap.dedent("""
            Why: list stale domains.
            Exit test: pytest passes
            exit tests: lint passes
            Acceptance: reviewed by a person
            - [x] checked item
        """).strip())
        text = self.brief(task)
        self.assertEqual(self.section(text, "GOAL"), "Sweep domains. Why: list stale domains.")
        self.assertEqual(self.section(text, "ACCEPTANCE").splitlines(),
                         ["- pytest passes", "- lint passes", "- reviewed by a person", "- checked item"])

    def test_06_unscoped_task_is_refused_with_the_fix(self):
        task = self.tg("add", "Sweep", "--notes", "Exit test: it works")["id"]
        out = self.run_cmd("launch", str(task), "--dry-run")
        self.assertEqual(out.returncode, 2)
        for word in ("not scoped", "GOAL", "SCOPE", "VERIFY", f"edit {task} --meta scope="):
            self.assertIn(word, out.stderr)
        self.assertNotIn("ACCEPTANCE", out.stderr)

    def test_07_result_command_and_keyword(self):
        task = self.add_task()
        text = self.brief(task)
        command = self.section(text, "REPORT")
        expected = (f'"{sys.executable}" "{TG}" --db "{self.db}" --project demo '
                    "result add 1 --kind task --attempt 1 --by task-1-1 --status <STATUS> --body-file -")
        self.assertIn(expected, command)
        self.assertIn("<<'REPORT'\n<your report>\nREPORT", command)
        self.assertIn(f'"{sys.executable}" "{TG}" --db "{self.db}" --project demo show 1', text)
        self.assertIn("--by task-1-1-sweep", self.brief(task, "--keyword", "sweep"))
        bad = self.run_cmd("launch", str(task), "--dry-run", "--keyword", "bad name")
        self.assertEqual(bad.returncode, 2)

    def test_08_default_database_is_home_taskgraph(self):
        env = {k: v for k, v in self.env.items() if k != "TASKGRAPH_DB"}
        task = self.add_task(env=env)
        text = self.brief(task, env=env)
        self.assertIn(f'--db "{os.path.join(self.home, ".taskgraph", "tasks.db")}"', text)

    def test_09_upstream_and_previous_report_come_from_results(self):
        up = self.add_task("Build base", "Why: base.\n- [ ] built")
        task = self.add_task("Use base", "Why: needs base.\n- [ ] used", depends=(up,), attempt=1)
        self.add_result(up, "PASS", "Task: 1\nFiles: base.txt\n", attempt=1)
        self.add_result(up, "DIED", "manager saw no session", attempt=2, by="manager")
        self.add_result(task, "ISSUES", f"Task: 2\nIssues: broken\nCheckpoint: {CHECKPOINT}\n", attempt=1)
        self.add_result(task, "DIED", "manager saw no session", attempt=2, by="manager")
        self.add_result(task, "BLOCKED", "permission prompt", attempt=2, by="manager")
        self.add_result(task, "PASS", "verifier said fine", kind="verify", attempt=1, by="verify-2-1")
        self.tg("done", str(up))
        self.worktree("task-2")
        text = self.brief(task)
        context = self.section(text, "CONTEXT")
        self.assertIn("### Previous attempt (result #3, ISSUES, attempt 1)", context)
        self.assertIn("Issues: broken", context)
        self.assertIn("### Upstream #1: Build base", context)
        self.assertIn("Files: base.txt", context)
        self.assertIn(f"Last checkpoint: {CHECKPOINT}", context)
        for skipped in ("manager saw no session", "permission prompt", "verifier said fine"):
            self.assertNotIn(skipped, text)
        self.assertIn("--attempt 2 --by task-2-2", text)
        self.add_result(task, "PASS", "report copied from the logs", attempt=1, by="manager")
        self.assertIn("report copied from the logs", self.brief(task))

    def test_09_upstream_without_result(self):
        up = self.add_task("Build base", "Why: base.\n- [ ] built")
        task = self.add_task("Use base", "Why: needs base.\n- [ ] used", depends=(up,))
        self.tg("done", str(up))
        self.assertIn("No report on file.", self.brief(task))

    def test_10_base_commit_sources(self):
        task = self.add_task()
        head = self.git("rev-parse", "HEAD")
        text = self.brief(task)
        self.assertIn(f"Base commit: {head}", text)
        self.assert_base(text, head)
        self.ok("launch", str(task))
        wt = self.wt_path("task-1")
        built = self.wt_commit(wt)
        # A retry builds on the worktree's HEAD, not on a commit a report names.
        self.add_result(task, "PASS", f"Task: 1\nBranch: worktree-task-1\nHead: {SHA_A}\n")
        text = self.brief(task)
        self.assertIn(f"Attempt 2. Your worktree is at `{built}` on branch `worktree-task-1`.", text)
        self.assertIn(f"If `git rev-parse HEAD` is not `{built}`, report BLOCKED and change nothing.", text)
        self.assertNotIn("Base commit:", text)
        self.assertNotRegex(text, r"git (reset|checkout|switch)")
        later = "b" * 40
        self.add_result(task, "STOPPED", f"Session: s\nWorktree: w\nBranch: b\nHead: {later}\nFiles: None\n",
                        attempt=1, by="manager")
        self.assertIn(f"Your worktree is at `{built}`", self.brief(task))

    def test_11_report_command_runs_in_bash(self):
        odd = os.path.join(self.dir, "we ird $dir")
        os.makedirs(odd)
        os.symlink(os.path.dirname(TG), os.path.join(odd, "bin"))
        tg = os.path.join(odd, "bin", "tg.py")
        env = dict(self.env, TASKGRAPH_DB=os.path.join(odd, "my $db.sqlite"))
        task = self.add_task(env=env)
        text = self.brief(task, tg=tg, env=env)
        command = re.search(r"```sh\n(.*?)\n```", self.section(text, "REPORT"), re.S).group(1)
        body = "Task: 1\nStatus: PASS\nIssues: a $HOME `date` \"quoted\" line\n"
        command = command.replace("<STATUS>", "PASS").replace("<your report>", body.rstrip("\n"))
        out = subprocess.run(["bash", "-c", command], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        result = self.tg("result", "ls", str(task), env=env)[0]
        self.assertEqual((result["kind"], result["attempt"], result["author"], result["status"]),
                         ("task", 1, "task-1-1", "PASS"))
        self.assertEqual(result["body"], body)

    def test_12_forbidden_and_removed_sections(self):
        self.write_config('[constraints]\nforbidden = ["do not touch the lockfile", "send nothing"]\n')
        task = self.add_task()
        text = self.brief(task)
        self.assertEqual(self.section(text, "FORBIDDEN").splitlines(),
                         ["- do not touch the lockfile", "- send nothing"])
        for gone in ("Shared-file rules", "Supplemental plan", "Consultants", "Session:"):
            self.assertNotIn(gone, text)
        self.write_config("[constraints]\nforbidden = []\n")
        self.assertEqual(self.section(self.brief(task), "FORBIDDEN"), "None beyond the worker rules.")

    def test_13_verify_brief(self):
        task = self.running_task()
        self.add_result(task, "PASS", f"Task: 1\nStatus: PASS\nHead: {SHA_A}\nFiles: out.txt\n")
        text = self.ok("verify", str(task), "--dry-run").stdout
        self.assertIn("Judge whether the output of task 1", self.section(text, "GOAL"))
        self.assertIn("Do not fix anything", self.section(text, "GOAL"))
        self.assertTrue(self.section(text, "SCOPE").startswith("Read only."))
        context = self.section(text, "CONTEXT")
        self.assertIn(f"Output under review: {SHA_A}", context)
        self.assertIn(f"Your worktree is already at `{SHA_A}`. Do not check out another commit.", context)
        self.assertIn(f"If `git rev-parse HEAD` is not `{SHA_A}`, report BLOCKED.", context)
        self.assertNotIn("git checkout", text)
        self.assertIn("### Worker report (result #1, PASS, attempt 1)", context)
        self.assertIn("Files: out.txt", context)
        self.assertIn("Last checkpoint: None", context)
        self.assertIn("Then exercise the real output", self.section(text, "VERIFY"))
        self.assertIn("Base commit: unknown (", context)
        self.assertIn(f"Head commit: {SHA_A}", context)
        self.assertIn("### Method: code", self.section(text, "VERIFY"))
        self.assertIn("A behaviour change you did not drive is `check-only`", " ".join(self.section(text, "VERIFY").split()))
        self.assertIn("--kind verify --attempt 1 --by verify-1-1 --status <STATUS>", text)
        self.assertIn("`Verdict:` line", self.section(text, "REPORT"))
        self.assertTrue(self.section(text, "AUTONOMY").startswith("- None."))
        self.assertEqual(self.calls("--bg"), [])

    def verify_context(self, task, *extra):
        text = self.ok("verify", str(task), "--dry-run", *extra).stdout
        return self.section(text, "CONTEXT"), self.section(text, "VERIFY"), text

    def test_13_verify_brief_names_the_base_from_the_meta(self):
        task = self.running_task(base=json.dumps(self.git("rev-parse", "HEAD")))
        old_head = self.git("rev-parse", "HEAD")
        wt, head = self.pass_report(task)
        self.commit_file("later.txt", "main moved\n")
        context, _, text = self.verify_context(task)
        self.assertIn(f"Base commit: {old_head} (the task's base meta). Head commit: {head}.", context)
        self.assertIn(f"git diff {old_head} {head}", context)
        self.assertIn(f'git archive {old_head} | tar -x -C "$(mktemp -d)"', context)
        self.assertIn("Never check out, reset, or add a worktree.", context)
        self.assertNotRegex(text, r"git (reset|checkout|switch)")

    def test_13_verify_brief_falls_back_to_the_merge_base(self):
        main_head = self.git("rev-parse", "HEAD")
        task = self.running_task()
        wt, head = self.pass_report(task)
        context, _, _ = self.verify_context(task)
        self.assertIn(f"Base commit: {main_head} (merge base with HEAD). Head commit: {head}.", context)

    def test_13_verify_brief_a_base_meta_that_is_not_an_ancestor_is_ignored(self):
        task = self.running_task(base=json.dumps(self.feature_branch()))
        wt, head = self.pass_report(task)
        context, _, _ = self.verify_context(task)
        self.assertIn("(merge base with HEAD)", context)
        self.assertNotIn("base meta", context)

    def test_13_verify_brief_checksum_output_has_no_base(self):
        task = self.running_task()
        self.add_result(task, "PASS", "Task: 1\nStatus: PASS\nFiles: sums.txt\n")
        context, _, _ = self.verify_context(task, "--ref", "sums.txt abc")
        self.assertIn("Base commit: none; the output is outside git.", context)
        self.assertNotIn("Head commit:", context)

    def test_13_verify_brief_by_kind(self):
        for kind in ("schema", "design-doc"):
            with self.subTest(kind):
                task = self.running_task(verify_kind=kind)
                self.pass_report(task)
                _, verify, _ = self.verify_context(task)
                self.assertIn(f"### Method: {kind}", verify)
                self.assertIn(f"This is the only level that closes a {kind} task", " ".join(verify.split()))
                self.assertLess(verify.index("make test"), verify.index("### Method"))
                self.assertNotIn("Then exercise the real output: run it, open it", verify)
                self.assertNotIn("### Method: code", verify)
                if kind == "schema":
                    self.assertIn("--rm", verify)
                    self.assertIn("leftover container:", verify)
                else:
                    self.assertIn("decision: <the question, one line>", verify)
                    self.assertIn("does not lower the verdict", verify)
                detail = self.one(self.events("verify", str(task)), "verifying")["detail"]
                self.assertIn(f" kind {kind}", detail)

    def test_13_the_config_default_kind_applies_without_the_meta(self):
        self.write_config('[verify]\nkind = "design-doc"\n')
        plain, explicit = self.running_task(), self.running_task(verify_kind="code")
        self.pass_report(plain)
        self.pass_report(explicit)
        self.assertIn("### Method: design-doc", self.verify_context(plain)[1])
        self.assertIn("### Method: code", self.verify_context(explicit)[1])

    # --- launch

    def test_14_stop_first_line_halts_launch(self):
        task = self.add_task()
        self.orders("# Standing orders\n\nSTOP: paused\n")
        out = self.run_cmd("launch", str(task))
        self.assertEqual(out.returncode, 3)
        self.assertIn("STOP: paused", out.stderr)
        self.orders("1. STOP: paused\n")
        self.assertEqual(self.run_cmd("launch", str(task)).returncode, 3)
        self.orders("1. Keep tests green\nSTOP: paused\n")
        self.assertEqual(self.run_cmd("launch", str(task), "--dry-run").returncode, 0)
        self.orders("<!--\nSTOP: example\n-->\n\nNone yet.\n")
        self.assertEqual(self.run_cmd("launch", str(task), "--dry-run").returncode, 0)

    def test_15_launch_happy_path(self):
        task = self.add_task(verdict="test-verified", verdict_ref="abc1234")
        events = self.events("launch", str(task))
        launched = self.one(events, "launched")
        self.assertEqual((launched["task"], launched["attempt"], launched["session"]), (1, 1, "task-1-1"))
        self.assertIn("claude said: backgrounded \u00b7 sess-task-1-1 \u00b7 task-1-1", launched["detail"])
        self.assertNotIn("stop this session", launched["detail"])
        self.assertIn("worktree .claude/worktrees/task-1 base ", launched["detail"])
        brief_path = os.path.join(self.root, ".agentic-team", "briefs", "task-1-1.md")
        with open(brief_path) as fh:
            text = fh.read()
        self.assertEqual(self.calls("--bg"), [[
            "--bg", "--worktree", "task-1", "--agent", "agentic-team:worker", "--model", "sonnet",
            "--effort", "high", "--permission-mode", "auto", "--name", "task-1-1", text]])
        self.assertEqual(self.status_of(task), "in_progress")
        meta = self.meta(task)
        self.assertEqual((meta["session"], meta["model"], meta["attempt"]), ("task-1-1", "sonnet", 1))
        self.assertEqual(meta["sessions"], [self.entry(task)])
        self.assertRegex(meta["started_at"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC$")
        self.assertNotIn("verdict", meta)
        self.assertNotIn("verdict_ref", meta)

    def test_15_started_at_is_set_on_every_launch(self):
        task = self.add_task()
        self.ok("launch", str(task))
        self.tg("edit", str(task), "--meta", 'started_at="2000-01-01 00:00 UTC"')
        self.ok("launch", str(task))
        self.assertNotEqual(self.meta(task)["started_at"], "2000-01-01 00:00 UTC")
        self.assertEqual(self.meta(task)["attempt"], 2)

    def test_16_model_resolution(self):
        self.write_config('[models.overrides]\n"data migration" = { model = "opus", effort = "high" }\n')
        mech = self.add_task(tier="mechanical")
        over = self.add_task(tier="data migration")
        plain = self.add_task()
        unknown = self.add_task(tier="poetry")

        def command(task, *extra):
            out = self.run_cmd("launch", str(task), "--dry-run", *extra)
            self.assertEqual(out.returncode, 0, out.stderr)
            return out.stderr

        self.assertIn("--model haiku --permission-mode", command(mech))
        self.assertIn("--model opus --effort high", command(over))
        self.assertIn("--model sonnet --effort high", command(plain))
        self.assertIn("--model opus --permission-mode", command(plain, "--tier", "judgement"))
        self.assertIn("--model x --effort low", command(plain, "--model", "x", "--effort", "low"))
        out = self.run_cmd("launch", str(unknown), "--dry-run")
        self.assertEqual(out.returncode, 2)
        self.assertIn("no tier or models.overrides entry named 'poetry'", out.stderr)

    def test_17_refusals_by_task_state(self):
        decision = self.tg("add", "Q?", "--type", "decision")["id"]
        out = self.run_cmd("launch", str(decision))
        self.assertEqual(out.returncode, 2)
        self.assertIn("is a decision", out.stderr)
        finished = self.add_task()
        self.tg("done", str(finished))
        out = self.run_cmd("launch", str(finished))
        self.assertEqual((out.returncode, "is done" in out.stderr), (2, True))
        blocked = self.add_task(depends=(self.add_task(),))
        out = self.run_cmd("launch", str(blocked))
        self.assertEqual(out.returncode, 2)
        self.assertIn("waits for #", out.stderr)

    def test_17_decision_that_blocks_a_started_task(self):
        task = self.running_task()
        self.add_result(task, "BLOCKED", "Task: 1\nStatus: BLOCKED\n")
        gate = self.tg("add", "Which way?", "--type", "decision", "--meta", "decider=operator", "--blocks", str(task))["id"]
        out = self.run_cmd("launch", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn(f"waits for #{gate} (decision)", out.stderr)
        self.assertEqual(self.calls("--bg"), [])
        self.tg("edit", str(gate), "--notes", "go left")
        self.tg("done", str(gate))
        self.worktree("task-1")
        self.assertEqual(self.run_cmd("launch", str(task)).returncode, 0)

    def test_17_abandoned_task_needs_an_attempt(self):
        task = self.running_task(attempt=3, abandoned="died", verdict="check-only")
        out = self.run_cmd("launch", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("is abandoned (died)", out.stderr)
        self.assertIn("--attempt 4", out.stderr)
        self.worktree("task-1")
        self.ok("launch", str(task), "--attempt", "4")
        meta = self.meta(task)
        self.assertEqual(meta["attempt"], 4)
        self.assertNotIn("abandoned", meta)
        self.assertNotIn("verdict", meta)

    def test_17a_stopped_attempt_needs_record_first(self):
        task = self.running_task()
        wt = self.worktree("task-1")
        self.add_result(task, "STOPPED", f"Session: sess-task-1-1\nWorktree: {wt}\nBranch: worktree-task-1\n"
                        "Stopped: now\nFiles: wip.txt\n", by="manager")
        out = self.run_cmd("launch", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("run run.py record first", out.stderr)
        with open(os.path.join(wt, "wip.txt"), "w") as fh:
            fh.write("half done\n")
        self.agents()
        self.ok("record")
        head = self.git("rev-parse", "HEAD", cwd=wt)
        text = self.brief(task)
        self.assertIn(f"Attempt 2. Your worktree is at `{head}` on branch `worktree-task-1`.", text)
        self.assertIn("--worktree task-1 ", self.run_cmd("launch", str(task), "--dry-run").stderr)

    def test_17b_verifier_tier_without_a_model(self):
        task = self.add_task(tier="verifier")
        out = self.run_cmd("launch", str(task), "--dry-run")
        self.assertEqual(out.returncode, 2)
        self.assertIn("has no model", out.stderr)
        self.write_config('[models]\nverifier = "opus"\n')
        self.assertIn("--model opus", self.run_cmd("launch", str(task), "--dry-run").stderr)

    def test_18_unmerged_dependency_blocks_launch(self):
        up = self.add_task("Build base", "Why: base.\n- [ ] built", attempt=1, verdict_ref=SHA_A)
        task = self.add_task("Use base", "Why: needs base.\n- [ ] used", depends=(up,))
        self.tg("done", str(up))
        out = self.run_cmd("launch", str(task), "--dry-run")
        self.assertEqual(out.returncode, 2)
        self.assertIn("worktree-task-1 is not merged", out.stderr)
        self.assertIn("run.py merged 1 --by operator", out.stderr)
        self.tg("edit", str(up), "--meta", 'merged_at="2026-10-26 10:00 UTC"')
        self.assertEqual(self.run_cmd("launch", str(task), "--dry-run").returncode, 0)
        self.tg("edit", str(up), "--unset-meta", "merged_at", "--meta", 'verdict_ref="abc123  out.txt"')
        self.assertEqual(self.run_cmd("launch", str(task), "--dry-run").returncode, 0)

    def test_19_attempt_cap(self):
        failed = self.running_task(attempt=3)
        self.add_result(failed, "ISSUES", "Task: 1\n", attempt=3)
        out = self.run_cmd("launch", str(failed), "--dry-run")
        self.assertEqual(out.returncode, 2)
        self.assertIn("attempt 3 has failed", out.stderr)
        self.assertIn("run.py abandon 1", out.stderr)
        self.worktree("task-1")
        override = self.run_cmd("launch", str(failed), "--dry-run", "--attempt", "4")
        self.assertIn("--worktree task-1 ", override.stderr)
        self.assertIn("--attempt 4 --by task-1-4", override.stdout)
        paused = self.running_task(attempt=3)
        self.worktree("task-2")
        self.add_result(paused, "STOPPED", f"Session: s\nWorktree: w\nBranch: b\nHead: {SHA_A}\nFiles: None\n",
                        attempt=3, by="manager")
        self.assertIn("--attempt 4 --by task-2-4", self.run_cmd("launch", str(paused), "--dry-run").stdout)
        retry = self.running_task(attempt=2)
        self.worktree("task-3")
        self.assertIn("--attempt 3 --by task-3-3", self.run_cmd("launch", str(retry), "--dry-run").stdout)

    def test_20_live_session_blocks_launch(self):
        task = self.running_task()
        self.worktree("task-1")
        self.agents(self.row("task-1", name="task-1-1-sweep"))
        out = self.run_cmd("launch", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("has a live session sess-task-1-1", out.stderr)
        self.agents(self.finished("task-1"))
        self.assertEqual(self.run_cmd("launch", str(task)).returncode, 0)

    def test_21_cap_counts_live_workers_and_verifiers(self):
        self.write_config(sessions="max_parallel = 1\n")
        task = self.add_task()
        self.agents(self.row("task-9"))
        out = self.run_cmd("launch", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("cap full: 1/1 sessions live", out.stderr)
        self.agents(self.finished("task-9"))
        self.assertEqual(self.run_cmd("launch", str(task), "--dry-run").returncode, 0)
        self.agents(self.row("verify-9-1"))
        self.assertEqual(self.run_cmd("launch", str(task), "--dry-run").returncode, 2)

    def test_22_untrusted_workspace(self):
        task = self.add_task()
        env = dict(self.env, FAKE_CLAUDE_UNTRUSTED="1")
        out = self.run_cmd("launch", str(task), env=env)
        self.assertEqual(out.returncode, 1)
        self.assertIn("not trusted", out.stderr)
        self.assertIn("accept the trust prompt", out.stderr)
        self.assertEqual(self.status_of(task), "open")
        self.assertNotIn("session", self.meta(task))

    def test_23_second_launch_is_attempt_two(self):
        task = self.add_task()
        self.ok("launch", str(task))
        first = self.meta(task)
        self.agents(self.finished("task-1"))
        self.ok("launch", str(task))
        calls = self.calls("--bg")
        self.assertEqual([c[c.index("--worktree") + 1] for c in calls], ["task-1", "task-1"])
        self.assertEqual([c[c.index("--name") + 1] for c in calls], ["task-1-1", "task-1-2"])
        meta = self.meta(task)
        self.assertEqual(meta["session"], "task-1-2")
        self.assertEqual(meta["base"], first["base"])
        self.assertEqual(meta["sessions"], [self.entry(task, 1), self.entry(task, 2)])
        self.assertEqual(self.worktree_state()[2], ["task-1"])
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.wt_path("task-1")), first["base"])


    def test_23_launch_creates_the_worktree_at_the_base(self):
        tip = self.feature_branch()
        self.assertNotEqual(tip, self.git("rev-parse", "HEAD"))
        task = self.add_task()
        self.ok("launch", str(task), "--base", tip)
        wt = self.wt_path("task-1")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt), tip)
        self.assertEqual(self.git("branch", "--show-current", cwd=wt), "worktree-task-1")
        self.assertEqual(self.git("status", "--porcelain", cwd=wt), "")
        self.assertEqual(self.calls("--bg")[0][2], "task-1")
        other = self.add_task()
        self.ok("launch", str(other))
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.wt_path("task-2")), self.git("rev-parse", "HEAD"))

    def clash(self, case):
        """Leave a branch, folder or registration at task-1 for `case`."""
        if case == "branch at base":
            self.git("branch", "worktree-task-1")
        elif case == "branch ahead":
            self.git("checkout", "-q", "-b", "worktree-task-1")
            self.commit_file("a.txt", "a\n")
            self.commit_file("b.txt", "b\n")
            self.git("checkout", "-q", "main")
        elif case == "plain folder":
            os.makedirs(self.wt_path("task-1"))
            with open(os.path.join(self.wt_path("task-1"), "keep.txt"), "w") as fh:
                fh.write("mine\n")
        elif case == "registered worktree":
            self.worktree("task-1")
        else:  # a stale registration: the folder is gone
            shutil.rmtree(self.worktree("task-1"))

    def clear_clash(self):
        shutil.rmtree(self.wt_path("task-1"), ignore_errors=True)
        self.git("worktree", "prune")
        if self.git("branch", "--list", "worktree-task-1"):
            self.git("branch", "-D", "worktree-task-1")

    def test_23_launch_refuses_an_existing_branch_or_folder_and_creates_nothing(self):
        task = self.add_task()
        short = self.git("rev-parse", "--short=7", "HEAD")
        cases = {
            "branch at base": ([f"branch worktree-task-1 is at {short}; nothing is on it", "`git branch -D worktree-task-1`"],
                               ["git worktree"]),
            "branch ahead": ([f"holds 2 commits beyond {short}; remove it only if you do not need them"], ["git worktree"]),
            "plain folder": (["folder .claude/worktrees/task-1 is a plain folder, not a git worktree",
                              "move or delete .claude/worktrees/task-1 yourself"], ["git worktree remove", "--force"]),
            "registered worktree": (["is a git worktree", "`git worktree remove .claude/worktrees/task-1`",
                                     "`git branch -D worktree-task-1`"], ["--force"]),
            "stale registration": (["stale worktree registration", "`git worktree prune`"], ["git branch -D", "--force"]),
        }
        for case, (present, absent) in cases.items():
            with self.subTest(case):
                self.clash(case.replace("stale registration", "stale"))
                before = self.worktree_state()
                out = self.run_cmd("launch", str(task))
                self.assertEqual(out.returncode, 2, out.stderr)
                for text in present:
                    self.assertIn(text, out.stderr)
                for text in absent:
                    self.assertNotIn(text, out.stderr)
                self.assertIn("Nothing was created. To reuse this name: ", out.stderr)
                self.assertNotIn("--attempt", out.stderr)
                self.assertEqual(self.calls("--bg"), [])
                self.assertEqual(self.worktree_state(), before)
                self.assertEqual(self.status_of(task), "open")
                self.assertFalse(os.path.exists(os.path.join(self.root, ".agentic-team", "briefs", "task-1-1.md")))
                if case == "plain folder":
                    with open(os.path.join(self.wt_path("task-1"), "keep.txt")) as fh:
                        self.assertEqual(fh.read(), "mine\n")
                self.clear_clash()
        self.ok("launch", str(task))
        self.assertTrue(os.path.isdir(self.wt_path("task-1")))

    def test_23_launch_removes_what_it_created_when_claude_fails(self):
        task = self.add_task()
        before = self.worktree_state()
        for env in (dict(self.env, FAKE_CLAUDE_UNTRUSTED="1"),
                    dict(self.env, FAKE_CLAUDE_BG_ERROR="unexpected failure")):
            out = self.run_cmd("launch", str(task), env=env)
            self.assertEqual(out.returncode, 1)
            self.assertEqual(self.worktree_state(), before)
            self.assertEqual(self.status_of(task), "open")
        self.assertIn("unexpected failure", out.stderr)

    def test_23_a_sandbox_error_gets_the_sandbox_hint(self):
        task = self.add_task()
        for message in ("mkdir: Operation not permitted", "EPERM: open ~/.claude/x", "Read-only file system"):
            with self.subTest(message):
                out = self.run_cmd("launch", str(task), env=dict(self.env, FAKE_CLAUDE_BG_ERROR=message))
                self.assertEqual(out.returncode, 1)
                self.assertIn(message, out.stderr)
                self.assertIn("claude --bg writes session data under ~/.claude", out.stderr)
                self.assertIn("outside the Bash sandbox", out.stderr)
                self.assertIn("operator's agreement", out.stderr)
        plain = self.run_cmd("launch", str(task), env=dict(self.env, FAKE_CLAUDE_BG_ERROR="quota exceeded"))
        self.assertNotIn("~/.claude", plain.stderr)

    def test_23_dry_run_creates_nothing(self):
        task = self.add_task()
        before = self.worktree_state()
        self.ok("launch", str(task), "--dry-run")
        self.assertEqual(self.worktree_state(), before)
        running = self.running_task()
        self.add_result(running, "PASS", f"Task: {running}\nStatus: PASS\nHead: {self.git('rev-parse', 'HEAD')}\n")
        self.ok("verify", str(running), "--dry-run")
        self.assertEqual(self.worktree_state(), before)
        self.assertEqual(self.calls("--bg"), [])

    def test_23_a_live_session_repair_creates_no_worktree(self):
        task = self.add_task()
        self.agents(self.row("task-1"))
        self.assertEqual(self.one(self.events("launch", str(task)), "repaired")["task"], task)
        self.assertEqual(self.worktree_state()[1:], ("", []))

    def retry_ready(self, status="ISSUES"):
        """A task whose attempt 1 ran in task-1, committed once, and filed `status`. Returns (task, wt, head)."""
        task = self.add_task()
        self.ok("launch", str(task))
        wt = self.wt_path("task-1")
        head = self.wt_commit(wt)
        self.agents(self.finished("task-1"))
        self.add_result(task, status, f"Task: 1\nStatus: {status}\nBranch: worktree-task-1\nHead: {head}\n")
        return task, wt, head

    def test_23_a_retry_continues_in_the_same_worktree(self):
        task, wt, head = self.retry_ready()
        first = self.meta(task)
        events = self.events("launch", str(task))
        detail = self.one(events, "launched")["detail"]
        self.assertIn("worktree .claude/worktrees/task-1 ", detail)
        self.assertIn(f"continues at {head[:7]}", detail)
        self.assertNotIn(" base ", detail)
        self.assertEqual(self.worktree_state()[2], ["task-1"])
        self.assertEqual(self.git("branch", "--show-current", cwd=wt), "worktree-task-1")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt), head)
        calls = self.calls("--bg")
        self.assertEqual([c[c.index("--worktree") + 1] for c in calls], ["task-1", "task-1"])
        text = calls[-1][-1]
        self.assertIn(f"Attempt 2. Your worktree is at `{head}` on branch `worktree-task-1`.", text)
        self.assertIn("It holds the commits of the earlier attempts of this task.", text)
        self.assertNotIn("Base commit:", text)
        meta = self.meta(task)
        self.assertEqual(meta["sessions"], [self.entry(task, 1), self.entry(task, 2)])
        self.assertEqual((meta["attempt"], meta["base"]), (2, first["base"]))

    def test_23_base_on_a_retry_is_refused_and_creates_nothing(self):
        task, wt, head = self.retry_ready()
        before = self.worktree_state()
        out = self.run_cmd("launch", str(task), "--base", "main")
        self.assertEqual(out.returncode, 2)
        self.assertIn(f"#1 continues in .claude/worktrees/task-1 at {head[:7]}; --base applies to a first attempt. "
                      "To restart from main: git worktree remove -f -f .claude/worktrees/task-1 && "
                      "git branch -D worktree-task-1, then rerun with --base.", out.stderr)
        self.assertEqual(len(self.calls("--bg")), 1)
        self.assertEqual(self.worktree_state(), before)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt), head)
        self.assertEqual(self.meta(task)["attempt"], 1)

    def test_23_a_dirty_worktree_is_committed_before_the_retry(self):
        task, wt, head = self.retry_ready("DIED")
        with open(os.path.join(wt, "left.txt"), "w") as fh:
            fh.write("half\n")
        dry = self.brief(task)  # a dry run commits nothing
        self.assertIn(f"Your worktree is at `{head}`", dry)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt), head)
        self.assertEqual(self.git("status", "--porcelain", cwd=wt), "?? left.txt")
        detail = self.one(self.events("launch", str(task)), "launched")["detail"]
        new = self.git("rev-parse", "HEAD", cwd=wt)
        self.assertNotEqual(new, head)
        self.assertEqual(self.git("log", "-1", "--format=%s", cwd=wt), "WIP task 1 attempt 1: DIED")
        self.assertEqual(self.git("status", "--porcelain", cwd=wt), "")
        self.assertIn(f"committed 1 uncommitted files of attempt 1 as {new[:7]} (left.txt)", detail)
        self.assertIn("includes every untracked file that is not ignored, and in pr mode it is pushed with the branch", detail)
        self.assertIn(f"continues at {new[:7]}", detail)
        self.assertIn(f"Attempt 2. Your worktree is at `{new}`", self.calls("--bg")[-1][-1])
        self.assertIn("left.txt", self.git("show", "--stat", "--format=", "HEAD", cwd=wt))

    def test_23_a_clean_retry_commits_nothing_and_a_stopped_attempt_needs_record_first(self):
        task, wt, head = self.retry_ready("STOPPED")
        self.ok("launch", str(task))
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt), head)
        other = self.add_task(attempt=1)
        self.worktree("task-2")
        self.add_result(other, "STOPPED", "Session: s\nWorktree: w\nBranch: b\nStopped: now\nFiles: x\n", by="manager")
        out = self.run_cmd("launch", str(other))
        self.assertEqual(out.returncode, 2)
        self.assertIn("run run.py record first", out.stderr)

    def test_23_a_worktree_on_another_branch_or_a_plain_folder_is_refused(self):
        task, wt, head = self.retry_ready()
        self.git("switch", "-q", "-c", "elsewhere", cwd=wt)
        out = self.run_cmd("launch", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn(".claude/worktrees/task-1 is on elsewhere, not worktree-task-1; "
                      "run git -C .claude/worktrees/task-1 switch worktree-task-1", out.stderr)
        self.git("checkout", "-q", "--detach", cwd=wt)
        out = self.run_cmd("launch", str(task))
        self.assertIn("is on a detached HEAD at", out.stderr)
        self.assertIn("worktree-task-1 (this keeps the commits)", out.stderr)
        self.assertEqual(len(self.calls("--bg")), 1)
        self.git("worktree", "remove", "-f", wt)
        os.makedirs(wt)
        out = self.run_cmd("launch", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("folder .claude/worktrees/task-1 is a plain folder, not a git worktree; "
                      "move or delete it yourself", out.stderr)
        self.assertEqual(len(self.calls("--bg")), 1)
        self.assertEqual(os.listdir(wt), [])

    def test_23_a_missing_worktree_is_reattached_from_its_branch(self):
        task, wt, head = self.retry_ready()
        self.git("worktree", "remove", "-f", wt)
        before = self.worktree_state()
        self.brief(task)  # a dry run creates nothing
        self.assertEqual(self.worktree_state(), before)
        detail = self.one(self.events("launch", str(task)), "launched")["detail"]
        self.assertIn(f"reattached worktree-task-1 at {head[:7]}", detail)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt), head)
        self.assertEqual(self.git("branch", "--show-current", cwd=wt), "worktree-task-1")
        self.assertIn(f"Your worktree is at `{head}`", self.calls("--bg")[-1][-1])

    def test_23_a_missing_worktree_and_branch_start_again_at_the_last_head(self):
        tip = self.feature_branch("feat")
        task = self.add_task()
        self.ok("adopt", str(task), "--branch", "feat", "--head", tip)
        base = self.meta(task)["base"]
        self.assertEqual(self.worktree_state()[2], [])
        self.add_result(task, "ISSUES", f"Task: 1\nStatus: ISSUES\nBranch: feat\nHead: {tip}\n", attempt=1)
        detail = self.one(self.events("launch", str(task)), "launched")["detail"]
        self.assertIn(f"created at Head {tip[:7]} of attempt 1", detail)
        wt = self.wt_path("task-1")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt), tip)
        self.assertEqual(self.git("branch", "--show-current", cwd=wt), "worktree-task-1")
        meta = self.meta(task)
        self.assertEqual((meta["attempt"], meta["base"]), (2, base))
        self.assertEqual(len(meta["sessions"]), 1)
        self.assertEqual(meta["sessions"][0]["attempt"], 2)

    def test_23_nothing_to_continue_from_asks_for_a_base(self):
        task = self.running_task()
        self.add_result(task, "ISSUES", f"Task: 1\nStatus: ISSUES\nBranch: b\nHead: {SHA_A}\n")  # not in this repository
        for extra in ((), ("--dry-run",)):
            out = self.run_cmd("launch", str(task), *extra)
            self.assertEqual(out.returncode, 2)
            self.assertIn("#1 attempt 1 left no worktree, branch or Head in this repository; pass --base <sha|branch>",
                          out.stderr)
        self.assertEqual(self.worktree_state(), (1, "", []))
        tip = self.feature_branch()
        self.ok("launch", str(task), "--base", tip)
        wt = self.wt_path("task-1")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt), tip)
        self.assertEqual(self.meta(task)["attempt"], 2)
        self.assertIn(f"Base commit: {tip}.", self.calls("--bg")[-1][-1])

    def test_23_a_failed_start_of_a_retry_removes_nothing(self):
        task, wt, head = self.retry_ready()
        with open(os.path.join(wt, "left.txt"), "w") as fh:
            fh.write("half\n")
        before = self.worktree_state()
        out = self.run_cmd("launch", str(task), env=dict(self.env, FAKE_CLAUDE_BG_ERROR="unexpected failure"))
        self.assertEqual(out.returncode, 1)
        self.assertIn("unexpected failure", out.stderr)
        self.assertNotIn("kept .claude", out.stderr)
        self.assertEqual(self.worktree_state(), before)
        self.assertTrue(os.path.isdir(wt))
        self.assertEqual(self.git("status", "--porcelain", cwd=wt), "")  # the WIP commit stays
        self.assertEqual(self.meta(task)["attempt"], 1)
        self.assertEqual(len(self.meta(task)["sessions"]), 1)
        self.git("worktree", "remove", "-f", wt)
        out = self.run_cmd("launch", str(task), env=dict(self.env, FAKE_CLAUDE_BG_ERROR="unexpected failure"))
        self.assertEqual(out.returncode, 1)
        self.assertTrue(os.path.isdir(wt))  # reattached from the branch, then kept

    def test_23_a_retry_reports_a_worktree_that_moved_since_the_last_report(self):
        task, wt, head = self.retry_ready()
        moved = self.wt_commit(wt, "more.txt")
        detail = self.one(self.events("launch", str(task)), "launched")["detail"]
        self.assertIn(f"worktree HEAD {moved[:7]} is not the last report's Head {head[:7]}", detail)
        self.assertIn(f"continues at {moved[:7]}", detail)

    def test_23_a_retry_of_a_stacked_task_that_holds_its_dependency_is_not_refused(self):
        dep = self.feature_branch("dep")
        up = self.add_task("Build base", "Why: base.\n- [ ] built", attempt=1, verdict_ref=dep)
        task = self.add_task("Use base", "Why: needs base.\n- [ ] used", depends=(up,))
        self.tg("done", str(up))
        self.ok("launch", str(task), "--base", "dep")
        self.agents(self.finished("task-2"))
        self.add_result(task, "ISSUES", "Task: 2\nStatus: ISSUES\n")
        self.ok("launch", str(task))  # no --base: the worktree already holds the dependency's commit
        self.assertEqual(self.meta(task)["attempt"], 2)
        self.assertEqual(self.meta(task)["base"], dep)

    def test_23_a_session_that_started_keeps_its_worktree(self):
        task = self.add_task()
        base = self.git("rev-parse", "HEAD")
        cases = {
            "uncommitted changes": (dict(FAKE_CLAUDE_DIRTY="1"), (), "it has uncommitted changes"),
            "a moved branch": (dict(FAKE_CLAUDE_COMMIT="1"), (), f"branch worktree-task-1 is no longer at {base[:7]}"),
            "a session row": ({}, (self.finished("task-1"),), "a session row uses it"),
        }
        for case, (extra_env, rows, why) in cases.items():
            with self.subTest(case):
                self.agents(*rows)
                env = dict(self.env, FAKE_CLAUDE_BG_ERROR="exited after it detached", **extra_env)
                out = self.run_cmd("launch", str(task), env=env)
                self.assertEqual(out.returncode, 1)
                self.assertIn("exited after it detached", out.stderr)
                self.assertIn(f"kept .claude/worktrees/task-1: {why}", out.stderr)
                self.assertTrue(os.path.isdir(self.wt_path("task-1")))
                self.assertTrue(self.git("branch", "--list", "worktree-task-1"))
                self.assertEqual(self.status_of(task), "open")
                shutil.rmtree(self.wt_path("task-1"))
                self.git("worktree", "prune")
                self.git("branch", "-D", "worktree-task-1")

    def test_23_a_worktree_that_claude_did_not_reuse_is_a_warning_not_a_failure(self):
        earlier = self.git("rev-parse", "HEAD")
        base = self.commit_file("later.txt", "x\n")
        warning = f"the session's worktree is not at {base[:7]}; claude may no longer reuse a prepared worktree"
        self.assertNotIn("no longer reuse", self.one(self.events("launch", str(self.add_task())), "launched")["detail"])
        for case, move in (("another commit", earlier), ("detached at the base", base)):
            with self.subTest(case):
                other = self.add_task()
                events = self.events("launch", str(other), env=dict(self.env, FAKE_CLAUDE_MOVE=move))
                self.assertIn(warning, self.one(events, "launched")["detail"])
                self.assertEqual(self.meta(other)["session"], f"task-{other}-1")
                self.assertEqual(self.status_of(other), "in_progress")

    def test_23_the_base_is_a_full_sha_in_the_brief_and_the_meta(self):
        task = self.add_task()
        full = self.git("rev-parse", "HEAD")
        self.assert_base(self.brief(task, "--base", full[:9]), full)
        self.ok("launch", str(task), "--base", full[:9])
        self.assertEqual(self.meta(task)["base"], full)

    # --- verify

    def test_24_verify_refusals(self):
        task = self.running_task()
        out = self.run_cmd("verify", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("no worker result for attempt 1", out.stderr)
        self.add_result(task, "ISSUES", "Task: 1\n")
        out = self.run_cmd("verify", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("reported ISSUES, not PASS", out.stderr)
        self.add_result(task, "PASS", "Task: 1\nStatus: PASS\nFiles: sums.txt\n")
        out = self.run_cmd("verify", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("has no Head: line; pass --ref", out.stderr)
        accepted = self.run_cmd("verify", str(task), "--ref", "sums.txt abc", "--dry-run")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertIn("Output under review: sums.txt abc", accepted.stdout)
        idle = self.add_task()
        self.assertEqual(self.run_cmd("verify", str(idle)).returncode, 2)

    def test_25_verify_happy_path(self):
        task = self.running_task(session="task-1-1", model="sonnet")
        self.add_result(task, "PASS", f"Task: 1\nStatus: PASS\nHead: {self.git('rev-parse', 'HEAD')}\n")
        before = self.meta(task)
        self.ok("verify", str(task))
        argv = self.calls("--bg")[0]
        self.assertEqual(argv[:-1], ["--bg", "--worktree", "verify-1-1", "--agent", "agentic-team:worker",
                                     "--model", "opus", "--permission-mode", "auto", "--name", "verify-1-1"])
        with open(os.path.join(self.root, ".agentic-team", "briefs", "task-1-1-verify.md")) as fh:
            self.assertEqual(fh.read(), argv[-1])
        self.assertEqual(self.meta(task), {**before, "sessions": before["sessions"] + [self.entry(task, 1, "verify")]})
        self.assertEqual(self.status_of(task), "in_progress")

    def test_25_verifier_model_choice(self):
        task = self.running_task(model="opus")
        self.add_result(task, "PASS", f"Task: 1\nStatus: PASS\nHead: {self.git('rev-parse', 'HEAD')}\n")
        self.assertIn("--model sonnet", self.run_cmd("verify", str(task), "--dry-run").stderr)
        self.write_config('[models]\nverifier = { model = "haiku", effort = "low" }\n')
        self.ok("verify", str(task))
        argv = self.calls("--bg")[0]
        self.assertEqual(argv[argv.index("--model") + 1], "haiku")
        self.assertEqual(argv[argv.index("--effort") + 1], "low")

    def test_26_existing_verdict_blocks_a_second_verifier(self):
        task = self.running_task()
        self.add_result(task, "PASS", f"Task: 1\nStatus: PASS\nHead: {self.git('rev-parse', 'HEAD')}\n")
        self.add_result(task, "BLOCKED", "Verdict: verify-blocked\n", kind="verify", by="verify-1-1")
        out = self.run_cmd("verify", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("already has verify result #2 (Verdict: verify-blocked)", out.stderr)
        self.agents(self.finished("verify-1-1"))
        self.ok("verify", str(task), "--again")
        argv = self.calls("--bg")[0]
        self.assertIn("verify-1-1-2", argv)
        self.assertEqual(argv[argv.index("--worktree") + 1], "verify-1-1-2")
        self.assertTrue(os.path.isfile(os.path.join(self.root, ".agentic-team", "briefs", "task-1-1-verify-2.md")))

    def test_26_manager_verify_row_does_not_block(self):
        task = self.running_task()
        self.add_result(task, "PASS", f"Task: 1\nStatus: PASS\nHead: {SHA_A}\n")
        self.add_result(task, "PASS", "Verdict: test-verified\nRan: make test\n", kind="verify", by="manager")
        self.assertEqual(self.run_cmd("verify", str(task), "--dry-run").returncode, 0)

    def test_26_running_verifier_blocks(self):
        task = self.running_task()
        self.add_result(task, "PASS", f"Task: 1\nStatus: PASS\nHead: {SHA_A}\n")
        self.agents(self.row("verify-1-1"))
        out = self.run_cmd("verify", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("is still running", out.stderr)

    def test_27_verify_launches_under_stop(self):
        task = self.running_task()
        self.add_result(task, "PASS", f"Task: 1\nStatus: PASS\nHead: {self.git('rev-parse', 'HEAD')}\n")
        self.orders("STOP: paused\n")
        self.ok("verify", str(task))
        self.assertEqual(len(self.calls("--bg")), 1)


    def verify_ready(self):
        task = self.running_task()
        wt, head = self.pass_report(task)
        return task, wt, head

    def test_27_verify_creates_the_verifier_worktree_at_the_ref(self):
        task, wt, head = self.verify_ready()
        self.commit_file("later.txt", "main moved\n")
        self.ok("verify", str(task))
        verifier = self.wt_path("verify-1-1")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=verifier), head)
        self.assertEqual(self.git("branch", "--show-current", cwd=verifier), "worktree-verify-1-1")
        argv = self.calls("--bg")[0]
        self.assertEqual(argv[argv.index("--worktree") + 1], "verify-1-1")
        self.assertIn(f"Your worktree is already at `{head}`. Do not check out another commit.", argv[-1])
        self.assertNotIn("git checkout", argv[-1])
        self.agents(self.finished("verify-1-1"))
        self.ok("verify", str(task), "--again")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.wt_path("verify-1-1-2")), head)

    def test_27_verify_resolves_a_short_ref_and_skips_checksums(self):
        task, wt, head = self.verify_ready()
        self.ok("verify", str(task), "--ref", head[:9])
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.wt_path("verify-1-1")), head)
        self.assertIn(f"Output under review: {head}.", self.calls("--bg")[0][-1])
        sums = self.running_task()
        self.add_result(sums, "PASS", f"Task: {sums}\nStatus: PASS\nFiles: sums.txt\n")
        before = self.worktree_state()
        self.ok("verify", str(sums), "--ref", "sums.txt abc")
        self.assertEqual(self.worktree_state(), before)
        brief = self.calls("--bg")[-1][-1]
        self.assertIn("list of checksums", brief)
        self.assertNotIn("Your worktree is already", brief)

    def test_27_verify_counts_a_stale_branch_when_it_picks_a_name(self):
        task, wt, head = self.verify_ready()
        self.git("branch", "worktree-verify-1-1")
        self.git("branch", "worktree-verify-1-1-2")
        self.ok("verify", str(task))
        self.assertEqual(self.calls("--bg")[0][2], "verify-1-1-3")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.wt_path("verify-1-1-3")), head)
        self.assertTrue(self.git("branch", "--list", "worktree-verify-1-1"))  # the stale branch stays

    def test_27_verify_cleans_up_after_a_failed_start(self):
        task, wt, head = self.verify_ready()
        before = self.worktree_state()
        out = self.run_cmd("verify", str(task), env=dict(self.env, FAKE_CLAUDE_UNTRUSTED="1"))
        self.assertEqual(out.returncode, 1)
        self.assertIn("accept the trust prompt", out.stderr)
        self.assertEqual(self.worktree_state(), before)
        out = self.run_cmd("verify", str(task), "--ref", "f" * 40)
        self.assertEqual(out.returncode, 1)
        self.assertIn("git worktree add failed", out.stderr)
        self.assertEqual(self.worktree_state(), before)

    def test_27_a_verifier_that_claude_moved_gets_a_warning_but_a_detached_head_at_the_ref_does_not(self):
        task, wt, head = self.verify_ready()
        other = self.commit_file("later.txt", "x\n")
        events = self.events("verify", str(task), env=dict(self.env, FAKE_CLAUDE_MOVE=other))
        self.assertIn(f"the session's worktree is not at {head[:7]}; claude may no longer reuse a prepared worktree",
                      self.one(events, "verifying")["detail"])
        self.agents(self.finished("verify-1-1"))
        events = self.events("verify", str(task), "--again", env=dict(self.env, FAKE_CLAUDE_MOVE=head))
        self.assertNotIn("no longer reuse", self.one(events, "verifying")["detail"])

    # --- record

    def test_28_arrived_pass(self):
        low = self.running_task()
        high = self.running_task(risk="high")
        self.add_result(low, "PASS", "Task: 1\n")
        self.add_result(high, "PASS", "Task: 2\n")
        arrived = {e["task"]: e for e in self.named(self.events("record"), "arrived")}
        self.assertIn("run.py close 1", arrived[1]["next"])
        self.assertIn("rerun VERIFY", arrived[1]["next"])
        self.assertEqual(arrived[2]["next"], "run.py verify 2")
        self.assertEqual(arrived[1]["detail"], "PASS by worker (result #1)")
        text = self.ok("record").stdout
        self.assertIn("arrived #1 attempt 1: PASS by worker (result #1) | next:", text)

    def test_28_arrived_pass_by_kind(self):
        schema = self.running_task(verify_kind="schema", risk="low")
        doc = self.running_task(verify_kind="design-doc")
        self.add_result(schema, "PASS", f"Task: {schema}\n")
        self.add_result(doc, "PASS", f"Task: {doc}\n")
        arrived = {e["task"]: e for e in self.named(self.events("record"), "arrived")}
        self.assertEqual(arrived[schema]["next"], f"run.py verify {schema}")
        self.assertEqual(arrived[doc]["next"], f"run.py verify {doc}")

    def test_29_verifier_sessions(self):
        task = self.running_task()
        self.add_result(task, "PASS", "Task: 1\nStatus: PASS\n")
        self.agents(self.row("verify-1-1"))
        self.assertEqual(len(self.named(self.events("record"), "verifying")), 1)
        self.agents(self.row("verify-1-1", status="waiting", state="blocked", waitingFor="permission"))
        stuck = self.one(self.events("record"), "stuck")
        self.assertIn("sess-verify-1-1", stuck["detail"])
        self.assertIn("claude logs sess-verify-1-1", stuck["next"])
        self.assertIn("run.py verify 1 --again", stuck["next"])
        self.assertIn(["stop", "sess-verify-1-1"], self.calls("stop"))
        filed = [r for r in self.results(task) if r["kind"] == "verify"]
        self.assertEqual([(r["status"], r["author"]) for r in filed], [("BLOCKED", "manager")])

    def test_29_finished_verifier_with_no_result_is_filed_once(self):
        task = self.running_task()
        self.add_result(task, "PASS", "Task: 1\nStatus: PASS\n")
        self.agents(self.finished("verify-1-1"))
        first = self.events("record")
        self.assertEqual(self.one(first, "verifier-died")["task"], 1)
        self.assertEqual(len(self.named(first, "arrived")), 1)
        second = self.events("record")
        self.assertEqual(self.named(second, "verifier-died"), [])
        died = [r for r in self.results(task) if r["kind"] == "verify" and r["status"] == "DIED"]
        self.assertEqual(len(died), 1)
        self.assertEqual(died[0]["author"], "manager")

    def test_30_verified_events(self):
        task = self.running_task()
        self.add_result(task, "PASS", "Task: 1\nStatus: PASS\n")
        self.add_result(task, "PASS", "Verdict: test-verified\nRan: make test\n", kind="verify", by="manager")
        events = self.events("record")
        self.assertEqual(self.named(events, "verified"), [])
        self.assertEqual(len(self.named(events, "arrived")), 1)
        self.add_result(task, "PASS", "Status: PASS\nVerdict: test-verified\n", kind="verify", by="verify-1-1")
        verified = self.one(self.events("record"), "verified")
        self.assertIn("Verdict test-verified by verify-1-1 (result #3)", verified["detail"])
        self.assertEqual(verified["next"], "run run.py close 1")

    def test_30_second_verifier_beats_an_old_verdict(self):
        task = self.running_task(verdict="verify-blocked")
        self.add_result(task, "PASS", "Task: 1\nStatus: PASS\n")
        self.add_result(task, "BLOCKED", "Verdict: verify-blocked\n", kind="verify", by="verify-1-1")
        self.assertEqual(len(self.named(self.events("record"), "unclosed")), 1)
        self.add_result(task, "PASS", "Verdict: test-verified\n", kind="verify", by="verify-1-1-2")
        events = self.events("record")
        self.assertEqual(self.named(events, "unclosed"), [])
        self.assertIn("Verdict test-verified", self.one(events, "verified")["detail"])

    def test_30_verifier_result_without_a_verdict_line(self):
        task = self.running_task()
        self.add_result(task, "PASS", "Task: 1\nStatus: PASS\n")
        self.add_result(task, "PASS", "all fine\n", kind="verify", by="verify-1-1")
        verified = self.one(self.events("record"), "verified")
        self.assertIn("no Verdict line", verified["detail"])
        self.assertIn("--verdict L", verified["next"])

    def test_31_unclosed_next_step_by_verdict(self):
        wanted = {"verify-blocked": "retry the check", "verify-failed": "fix round: run.py launch",
                  "check-only": "run.py verify", "test-verified": "run run.py close",
                  "artifact-verified": "run run.py close"}
        for verdict, text in wanted.items():
            task = self.running_task(verdict=verdict)
            self.add_result(task, "PASS", "Task: 1\n")
        found = {e["task"]: e for e in self.named(self.events("record"), "unclosed")}
        self.assertEqual(len(found), 5)
        for index, (verdict, text) in enumerate(wanted.items(), start=1):
            self.assertIn(f"verdict {verdict}", found[index]["detail"])
            self.assertIn(text, found[index]["next"])
        self.assertIn("--again", found[3]["next"])

    def test_32_stuck_worker_is_stopped_and_filed(self):
        task = self.running_task()
        self.agents(self.row("task-1", status="waiting", state="working", waitingFor="Bash permission"))
        stuck = self.one(self.events("record"), "stuck")
        self.assertIn("Bash permission", stuck["detail"])
        self.assertIn("claude logs sess-task-1-1", stuck["next"])
        self.assertIn(["stop", "sess-task-1-1"], self.calls("stop"))
        filed = self.results(task)
        self.assertEqual([(r["status"], r["author"], r["attempt"]) for r in filed], [("BLOCKED", "manager", 1)])
        self.assertIn("Bash permission", filed[0]["body"])
        self.assertIn("Session: sess-task-1-1", filed[0]["body"])
        self.running_task()
        self.agents(self.row("task-2", status="idle", state="blocked"))
        again = {e["task"]: e for e in self.named(self.events("record"), "stuck")}
        self.assertEqual(again[1]["detail"], "filed earlier")
        self.assertIn("stopped sess-task-2-1", again[2]["detail"])

    def test_33_busy_and_unknown_rows(self):
        busy = self.running_task()
        odd = self.running_task()
        self.agents(self.row("task-1"), self.row("task-2", status="idle", state="foo"))
        events = self.events("record")
        self.assertEqual(self.one(events, "running")["task"], busy)
        unknown = self.one(events, "unknown")
        self.assertEqual(unknown["task"], odd)
        self.assertIn("not filed as DIED", unknown["detail"])
        self.assertEqual(self.results(odd), [])

    def test_34_finished_session_with_a_complete_report_is_salvaged(self):
        task = self.running_task()
        self.agents(self.finished("task-1"))
        report = (f"Task: 1\nStatus: ISSUES\nBranch: worktree-task-1\nHead: {SHA_A}\n"
                  f"Issues: one\nCheckpoint: {CHECKPOINT}\n")
        with open(os.path.join(self.logs, "sess-task-1-1.txt"), "w") as fh:
            fh.write("tool output\nTask: 1 started\nTask: 1\n" + "old\n" + "Task: 1\n" + report[len("Task: 1\n"):]
                     + '{"id": 5, "status": "PASS"}\nsession ended\n')
        events = self.events("record")
        salvaged = self.one(events, "salvaged")
        self.assertIn("ISSUES from claude logs sess-task-1-1 (result #1)", salvaged["detail"])
        arrived = self.one(events, "arrived")
        self.assertIn("ISSUES by manager (result #1)", arrived["detail"])
        row = self.results(task)[0]
        self.assertEqual((row["status"], row["author"], row["kind"]), ("ISSUES", "manager", "task"))
        self.assertEqual(row["body"], report)

    def test_35_incomplete_logs_file_died(self):
        task = self.running_task(attempt=3)
        early = self.running_task(attempt=1)
        gone = self.running_task(attempt=2)
        self.agents(self.finished("task-1", 3), self.finished("task-2"))
        with open(os.path.join(self.logs, "sess-task-1-3.txt"), "w") as fh:
            fh.write("Task: 1\nStatus: PASS\n")  # no Checkpoint line: incomplete
        events = {e["task"]: e for e in self.named(self.events("record"), "died")}
        self.assertIn("abandon 1 died", events[task]["next"])
        self.assertEqual(events[early]["next"], f"run.py launch {early}")
        self.assertIn("no result", self.results(early)[0]["body"])
        self.assertIn("status", self.results(early)[0]["body"].replace("idle/done", "status"))
        self.assertIn("no session recorded for attempt 2", self.results(gone)[0]["body"])
        self.assertEqual([r["status"] for r in self.results(task)], ["DIED"])

    def test_36_pause_phase_one_commits_the_wip(self):
        task = self.running_task()
        wt = self.worktree("task-1")
        base = self.git("rev-parse", "HEAD", cwd=wt)
        with open(os.path.join(wt, "wip.txt"), "w") as fh:
            fh.write("half\n")
        self.add_result(task, "STOPPED", f"Session: sess-task-1-1\nWorktree: {wt}\nBranch: worktree-task-1\n"
                        "Stopped: now\nFiles: ?? wip.txt\n", by="manager")
        self.agents(self.row("task-1", status="busy"))
        busy = self.events("record")
        self.assertEqual(len(self.named(busy, "stopping")), 1)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt), base)
        self.assertEqual(len(self.results(task)), 1)
        self.agents()
        stopped = self.one(self.events("record"), "stopped")
        head = self.git("rev-parse", "HEAD", cwd=wt)
        self.assertNotEqual(head, base)
        self.assertEqual(self.git("log", "-1", "--format=%s", cwd=wt), "WIP task 1 attempt 1: stopped by pause")
        self.assertIn(f"WIP committed {head} on worktree-task-1", stopped["detail"])
        latest = self.results(task)[-1]
        self.assertEqual((latest["status"], latest["author"]), ("STOPPED", "manager"))
        self.assertIn(f"Head: {head}", latest["body"])
        self.assertIn("Files: ?? wip.txt", latest["body"])

    def test_36_clean_worktree_is_not_committed(self):
        task = self.running_task()
        wt = self.worktree("task-1")
        base = self.git("rev-parse", "HEAD", cwd=wt)
        self.add_result(task, "STOPPED", f"Session: s\nWorktree: {wt}\nBranch: b\nStopped: now\nFiles: None\n", by="manager")
        self.ok("record")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt), base)
        self.assertIn(f"Head: {base}", self.results(task)[-1]["body"])

    def test_36_missing_worktree_files_head_none(self):
        task = self.running_task()
        self.add_result(task, "STOPPED", "Session: s\nWorktree: /nowhere/task-1-1\nBranch: b\nStopped: now\nFiles: None\n",
                        by="manager")
        stopped = self.one(self.events("record"), "stopped")
        self.assertIn("worktree missing", stopped["detail"])
        self.assertIn("Head: None", self.results(task)[-1]["body"])
        self.assertEqual(len(self.named(self.events("record"), "stopped")), 1)

    def stopped_row(self, name, sid="e6ebab39"):
        # What the real CLI lists in --all after `claude stop`: no status, state "stopped",
        # and a working directory that is not the worktree.
        return {"id": sid, "cwd": os.path.join(self.dir, "elsewhere"), "kind": "background",
                "startedAt": 1761000000000, "sessionId": "0d7c-stopped", "name": name, "state": "stopped"}

    def test_36_stopped_session_is_matched_by_its_recorded_id_and_its_wip_committed(self):
        task = self.running_task()
        wt = self.worktree("task-1")
        base = self.git("rev-parse", "HEAD", cwd=wt)
        self.agents(self.row("task-1", name="task-1-1-smoke"))
        self.ok("stop", str(task))
        self.assertIn(f"Worktree: {wt}", self.results(task)[0]["body"])
        with open(os.path.join(wt, "wip.txt"), "w") as fh:
            fh.write("half\n")
        self.agents(self.stopped_row("task-1-1-smoke", sid="sess-task-1-1"))
        stopped = self.one(self.events("record"), "stopped")
        head = self.git("rev-parse", "HEAD", cwd=wt)
        self.assertNotEqual(head, base)
        self.assertEqual(self.git("log", "-1", "--format=%s", cwd=wt), "WIP task 1 attempt 1: stopped by pause")
        self.assertIn(f"WIP committed {head}", stopped["detail"])
        self.assertEqual(stopped["session"], "sess-task-1-1")
        latest = self.results(task)[-1]
        self.assertIn(f"Worktree: {wt}", latest["body"])
        self.assertIn(f"Head: {head}", latest["body"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "elsewhere")))

    def test_36_stopped_session_is_not_live_and_not_counted(self):
        self.write_config(sessions="max_parallel = 1\n")
        task = self.add_task()
        running = self.running_task(attempt=1, sessions=[{**self.entry(2), "id": "e6ebab39"}])
        self.add_result(running, "STOPPED", "Session: e6ebab39\nWorktree: x/task-2-1\nFiles: None\n", by="manager")
        self.agents(self.stopped_row("task-2-1-smoke"), self.stopped_row("task-9-1-smoke", sid="f00d"))
        self.assertEqual(self.one(self.events("record"), "slots")["detail"], "0/1 live")
        self.assertEqual(self.run_cmd("launch", str(task), "--dry-run").returncode, 0)

    def test_36_foreign_live_rows_are_ignored(self):
        self.write_config(sessions="max_parallel = 1\n")
        task = self.add_task()
        running = self.running_task(attempt=1)
        foreign_cwd = os.path.join(self.dir, "other-repo", ".claude", "worktrees", f"task-{running}-1")
        foreign = {"id": "foreign-1", "name": f"task-{running}-1", "cwd": foreign_cwd, "status": "busy", "state": "working"}
        stuck = dict(foreign, id="foreign-2", name=f"task-{task}-1", status="waiting", state="blocked",
                     waitingFor="permission")
        self.agents(foreign, stuck)
        events = self.events("record")
        self.assertEqual(self.one(events, "slots")["detail"], "0/1 live")
        self.assertEqual(self.named(events, "running"), [])
        self.assertEqual(self.one(events, "died")["task"], running)
        self.assertEqual(self.calls("stop"), [])
        self.assertEqual(self.run_cmd("launch", str(task), "--dry-run").returncode, 0)
        verify = self.running_task(attempt=1)
        self.add_result(verify, "PASS", f"Task: {verify}\nStatus: PASS\nHead: {SHA_A}\n")
        self.agents(dict(foreign, name=f"verify-{verify}-1", cwd=foreign_cwd.replace("task-", "verify-")))
        self.assertEqual(self.run_cmd("verify", str(verify), "--dry-run").returncode, 0)

    def test_36_foreign_stopped_rows_are_never_stopped_or_removed(self):
        task = self.add_task(attempt=1, verdict_ref=SHA_A, merged_at="x", merged_by="operator", sessions="[]")
        self.tg("done", str(task))
        self.agents(self.stopped_row("task-1-1-smoke", sid="foreign-stopped"),
                    self.stopped_row("verify-1-1", sid="foreign-verify"))
        events = self.events("record")
        self.assertEqual(self.named(events, "removed") + self.named(events, "kept"), [])
        self.events("merged", str(task))
        self.assertEqual(self.calls("rm"), [])
        self.assertEqual(self.calls("stop"), [])

    def test_36_stopped_worker_without_a_recorded_id_is_no_session(self):
        task = self.running_task()
        self.agents(self.stopped_row("task-1-1-smoke"))
        died = self.one(self.events("record"), "died")
        self.assertEqual(died["task"], task)
        self.assertIsNone(died["session"])
        self.assertIn("no session recorded for attempt 1", self.results(task)[0]["body"])

    def test_36_stopped_session_tokens_use_the_derived_worktree(self):
        task = self.running_task(sessions=[{**self.entry(1), "id": "e6ebab39"}])
        wt, _ = self.pass_report(task)
        self.add_result(task, "STOPPED", f"Session: e6ebab39\nWorktree: {wt}\nFiles: None\n", by="manager")
        self.agents(self.stopped_row("task-1-1-smoke"))
        self.transcript_for(wt, "0d7c-stopped.jsonl", tokens=9)
        self.ok("close", str(task), "--verdict", "test-verified")
        self.assertEqual(self.meta(task)["tokens"], "9/3")

    def test_37_stopped_with_a_head_files_nothing(self):
        task = self.running_task()
        self.add_result(task, "STOPPED", f"Session: s\nWorktree: w\nBranch: b\nHead: {SHA_A}\nFiles: None\n", by="manager")
        stopped = self.one(self.events("record"), "stopped")
        self.assertIn(f"head {SHA_A}", stopped["detail"])
        self.assertEqual(len(self.results(task)), 1)

    def test_38_gated_by_an_open_decision(self):
        task = self.running_task()
        self.add_result(task, "BLOCKED", "Task: 1\nStatus: BLOCKED\nIssues: which API?\n")
        gate = self.tg("add", "Which API?", "--type", "decision", "--meta", "decider=operator", "--blocks", str(task))["id"]
        events = self.events("record")
        gated = self.one(events, "gated")
        self.assertIn(f'waits for decision #{gate} "Which API?"', gated["detail"])
        self.assertEqual(self.named(events, "arrived"), [])

    def test_39_merged_branch_is_recorded_and_unmerged_is_listed(self):
        task = self.add_task(attempt=1)
        wt = self.worktree("task-1")
        head = self.wt_commit(wt)
        later = self.add_task("Use base", depends=(task,))
        self.tg("edit", str(task), "--meta", f"verdict_ref={head}", "verdict=test-verified")
        self.tg("done", str(task))
        unmerged = self.one(self.events("record"), "unmerged")
        self.assertIn("worktree-task-1", unmerged["detail"])
        self.assertIn(f"blocks #{later}", unmerged["detail"])
        self.assertNotIn("merged_at", self.meta(task))
        self.git("merge", "--no-ff", "-q", "-m", "merge", "worktree-task-1")
        merged = self.one(self.events("record"), "merged")
        self.assertIn("recorded merged_by=operator", merged["detail"])
        meta = self.meta(task)
        self.assertEqual(meta["merged_by"], "operator")
        self.assertRegex(meta["merged_at"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC$")

    def test_39_recorded_merge_runs_cleanup(self):
        task = self.add_task(attempt=1, sessions="[]")
        wt = self.worktree("task-1")
        head = self.wt_commit(wt)
        self.git("merge", "--no-ff", "-q", "-m", "merge", "worktree-task-1")
        self.tg("edit", str(task), "--meta", f"verdict_ref={head}")
        self.tg("done", str(task))
        self.agents(self.finished("task-1"))
        events = self.events("record")
        self.assertEqual(len(self.named(events, "merged")), 1)
        self.assertEqual(self.one(events, "removed")["session"], "sess-task-1-1")
        self.assertIn(["rm", "sess-task-1-1"], self.calls("rm"))

    def test_40_leftover_rows_of_a_merged_task_are_removed(self):
        task = self.add_task(attempt=1, verdict_ref=SHA_A, merged_at="x", merged_by="operator", sessions="[]")
        self.tg("done", str(task))
        self.agents(self.finished("task-1"), self.finished("verify-1-1"))
        events = self.events("record")
        self.assertEqual(sorted(e["session"] for e in self.named(events, "removed")),
                         ["sess-task-1-1", "sess-verify-1-1"])
        self.assertEqual(len(self.calls("rm")), 2)

    def test_41_decisions_and_ready_lists(self):
        base = self.add_task("Base", attempt=1, verdict_ref=SHA_A)
        self.tg("done", str(base))
        behind = self.add_task("Behind", depends=(base,))
        free = self.add_task("Free")
        held = self.add_task("Held")
        gate = self.tg("add", "Pick a name", "--type", "decision", "--meta", "decider=operator",
                       "--due", "2026-11-01", "--blocks", str(held))["id"]
        undated = self.tg("add", "Pick a colour", "--type", "decision")["id"]
        events = self.events("record")
        decisions = {e["task"]: e["detail"] for e in self.named(events, "decision")}
        self.assertEqual(decisions[gate], '"Pick a name" decider operator by 2026-11-01 blocks #' + str(held))
        self.assertEqual(decisions[undated], '"Pick a colour" decider none by no date blocks none')
        self.assertEqual(self.one(events, "ready")["detail"], f"#{free}")
        self.assertEqual(self.one(events, "waits")["task"], behind)
        self.assertIn(f"dependency #{base} not merged", self.one(events, "waits")["detail"])
        text = self.ok("record").stdout
        self.assertIn(f"decision #{gate}: ", text)
        self.assertIn(f"ready: #{free}", text)

    def test_41_nothing_ready(self):
        self.assertEqual(self.one(self.events("record"), "ready")["detail"], "none")

    def test_42_slots_count_live_rows_only(self):
        self.agents(self.row("task-5"), self.finished("task-6"), self.row("verify-7-1", status="waiting"))
        self.assertEqual(self.one(self.events("record"), "slots")["detail"], "2/2 live")

    def test_43_abandoned_tasks_are_skipped(self):
        task = self.running_task(attempt=3, abandoned="died")
        done = self.add_task(attempt=1, verdict_ref=SHA_A, merged_at="x", abandoned="died")
        self.tg("done", str(done))
        self.agents(self.finished("task-1", 3), self.finished("task-2"))
        events = self.events("record")
        self.assertEqual([e for e in events if e["task"] in (task, done)], [])
        self.assertEqual(self.calls("rm"), [])
        self.assertEqual(self.calls("stop"), [])

    # --- close

    def test_44_close_needs_a_passing_worker_result(self):
        task = self.running_task()
        out = self.run_cmd("close", str(task), "--verdict", "test-verified")
        self.assertEqual(out.returncode, 2)
        self.assertIn("no worker result for attempt 1", out.stderr)
        self.add_result(task, "ISSUES", "Task: 1\n")
        out = self.run_cmd("close", str(task), "--verdict", "test-verified")
        self.assertEqual(out.returncode, 2)
        self.assertIn("reported ISSUES, not PASS", out.stderr)

    def test_45_manager_verdict_is_filed(self):
        task = self.running_task()
        self.pass_report(task)
        out = self.run_cmd("close", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("has no verifier verdict", out.stderr)
        self.ok("close", str(task), "--verdict", "test-verified", "--ran", "pytest ok")
        filed = [r for r in self.results(task) if r["kind"] == "verify"][-1]
        self.assertEqual((filed["status"], filed["author"]), ("PASS", "manager"))
        self.assertIn("Verdict: test-verified", filed["body"])
        self.assertIn("Ran: pytest ok", filed["body"])
        self.assertEqual(self.status_of(task), "done")

    def test_45_failed_and_blocked_verdicts_map_to_statuses(self):
        task = self.running_task()
        self.pass_report(task)
        self.ok("close", str(task), "--verdict", "verify-failed")
        self.ok("close", str(task), "--verdict", "verify-blocked", "--ran", "no network")
        filed = [r for r in self.results(task) if r["kind"] == "verify"]
        self.assertEqual([r["status"] for r in filed], ["ISSUES", "BLOCKED"])
        self.assertIn("Ran: not stated", filed[0]["body"])

    def test_46_verifier_verdict_is_used(self):
        task = self.running_task()
        self.pass_report(task)
        self.add_result(task, "PASS", "Status: PASS\nVerdict: artifact-verified\n", kind="verify", by="verify-1-1")
        out = self.run_cmd("close", str(task), "--verdict", "test-verified")
        self.assertEqual(out.returncode, 2)
        self.assertIn("verifier verify-1-1 said artifact-verified", out.stderr)
        self.assertIn("--override-verifier", out.stderr)
        events = self.events("close", str(task))
        self.assertIn("artifact-verified at", self.one(events, "closed")["detail"])
        self.assertEqual(self.meta(task)["verdict"], "artifact-verified")
        self.assertEqual([r["author"] for r in self.results(task) if r["kind"] == "verify"], ["verify-1-1"])

    def test_47_output_must_not_change_after_the_verdict(self):
        task = self.running_task()
        wt, head = self.pass_report(task)
        self.wt_commit(wt, "more.txt")
        out = self.run_cmd("close", str(task), "--verdict", "test-verified")
        self.assertEqual(out.returncode, 2)
        self.assertIn("the change differs (different diff)", out.stderr)
        self.assertEqual(self.status_of(task), "in_progress")
        self.assertNotIn("verdict", self.meta(task))
        self.assertEqual([r for r in self.results(task) if r["kind"] == "verify"], [])

    def test_47_missing_branch_and_checksum_output(self):
        task = self.running_task()
        self.add_result(task, "PASS", f"Task: 1\nStatus: PASS\nBranch: worktree-gone\nHead: {SHA_A}\n")
        out = self.run_cmd("close", str(task), "--verdict", "test-verified")
        self.assertEqual(out.returncode, 2)
        self.assertIn("branch worktree-gone not found", out.stderr)
        self.ok("close", str(task), "--verdict", "artifact-verified", "--ref", "abc123  out.txt")
        self.assertEqual(self.meta(task)["verdict_ref"], "abc123  out.txt")
        self.assertEqual(self.status_of(task), "done")
        self.assertEqual(self.calls("--bg"), [])

    def test_48_check_only_does_not_close(self):
        task = self.running_task()
        self.pass_report(task)
        events = self.events("close", str(task), "--verdict", "check-only")
        self.assertIn("check-only; not closed", self.one(events, "verdict")["detail"])
        self.assertEqual(self.named(events, "closed"), [])
        self.assertEqual(self.status_of(task), "in_progress")
        meta = self.meta(task)
        self.assertEqual(meta["verdict"], "check-only")
        self.assertTrue(re.fullmatch(r"[0-9a-f]{40}", meta["verdict_ref"]))

    def test_48_test_verified_does_not_close_a_schema_or_design_doc_task(self):
        for kind in ("schema", "design-doc"):
            with self.subTest(kind):
                task = self.verified_by("test-verified", task=self.running_task(verify_kind=kind))
                events = self.events("close", str(task))
                verdict = self.one(events, "verdict")
                self.assertEqual(verdict["detail"], "test-verified; not closed")
                self.assertIn(f"test-verified does not close a {kind} task", verdict["next"])
                self.assertIn(f"run.py verify {task} --again", verdict["next"])
                self.assertEqual(self.named(events, "closed"), [])
                self.assertEqual(self.status_of(task), "in_progress")
                meta = self.meta(task)
                self.assertEqual(meta["verdict"], "test-verified")
                self.assertTrue(re.fullmatch(r"[0-9a-f]{40}", meta["verdict_ref"]))
                unclosed = [e for e in self.named(self.events("record"), "unclosed") if e["task"] == task]
                self.assertEqual(len(unclosed), 1)
                self.assertEqual(unclosed[0]["next"], verdict["next"])
                other = self.verified_by("artifact-verified", task=self.running_task(verify_kind=kind))
                closed = self.events("close", str(other))
                self.one(closed, "closed")
                self.assertEqual(self.status_of(other), "done")

    def test_48_a_manager_verdict_test_verified_does_not_close_a_schema_task(self):
        task = self.running_task(verify_kind="schema")
        self.pass_report(task)
        events = self.events("close", str(task), "--verdict", "test-verified", "--ran", "ran the scripts")
        (row,) = [r for r in self.results(task) if r["kind"] == "verify" and r["author"] == "manager"]
        self.assertIn("Verdict: test-verified", row["body"])
        self.assertEqual(self.one(events, "verdict")["detail"], "test-verified; not closed")
        self.assertEqual(self.status_of(task), "in_progress")
        out = self.run_cmd("close", str(task), "--verdict", "artifact-verified", "--override-verifier", "recomputed",
                           "--ran", "https://ci/run/9")
        self.assertEqual(out.returncode, 2)
        self.assertIn("no verifier verdict to override; pass --verdict alone", out.stderr)
        events = self.events("close", str(task), "--verdict", "artifact-verified", "--ran", "recomputed 182 columns")
        self.one(events, "closed")
        self.assertEqual(self.status_of(task), "done")
        self.assertEqual(self.meta(task)["verdict"], "artifact-verified")

    def test_48_a_code_task_still_closes_on_test_verified(self):
        task = self.verified_by("test-verified")
        events = self.events("close", str(task))
        self.one(events, "closed")
        self.assertEqual(self.status_of(task), "done")

    def test_90_an_unknown_verify_kind_is_refused_everywhere(self):
        for bad in ("Code", "doc", "design_doc"):
            with self.subTest(bad):
                self.fresh()
                message = f'#1 verify_kind must be "code", "schema" or "design-doc", not {bad}'
                task = self.add_task(verify_kind=bad)
                out = self.run_cmd("launch", str(task))
                self.assertEqual(out.returncode, 2)
                self.assertIn(message, out.stderr)
                self.fresh()
                task = self.running_task(verify_kind=bad)
                self.pass_report(task)
                before = self.worktree_state()
                out = self.run_cmd("verify", str(task))
                self.assertEqual(out.returncode, 2)
                self.assertIn(message, out.stderr)
                self.assertEqual(self.worktree_state(), before)
                out = self.run_cmd("close", str(task), "--verdict", "test-verified", "--ran", "x")
                self.assertEqual(out.returncode, 2)
                self.assertIn(message, out.stderr)
                self.assertEqual(self.status_of(task), "in_progress")
                self.assertEqual([r for r in self.results(task) if r["kind"] == "verify"], [])
                self.fresh()
                task = self.add_task(verify_kind=bad)
                tip = self.wt_commit(self.worktree(f"task-{task}"))
                out = self.run_cmd("adopt", str(task), "--branch", f"worktree-task-{task}", "--head", tip)
                self.assertEqual(out.returncode, 2)
                self.assertIn(message, out.stderr)

    def test_90_an_empty_verify_kind_is_the_default(self):
        task = self.add_task(verify_kind="code")
        self.tg("edit", str(task), "--meta", "verify_kind=")
        stored = self.meta(task).get("verify_kind")
        if stored not in ("", None):
            self.skipTest(f"tg stored {stored!r}")
        out = self.run_cmd("launch", str(task), "--dry-run")
        self.assertEqual(out.returncode, 0, out.stderr)

    def transcript_for(self, wt, name, tokens=11, folder=None):
        folder = os.path.join(self.home, ".claude", "projects", re.sub(r"[^A-Za-z0-9]", "-", folder or wt))
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name), "w") as fh:
            fh.write(transcript(tokens))

    def test_49_tokens_from_the_transcript(self):
        task = self.running_task()
        wt, head = self.pass_report(task)
        self.agents(self.finished("task-1", sessionId="abc123-full"))
        self.transcript_for(wt, "abc123-full.jsonl")
        events = self.events("close", str(task), "--verdict", "test-verified")
        self.assertEqual(self.meta(task)["tokens"], "11/3")
        self.assertIn("out 11 in 3 cache-read 5 cache-write 7", self.one(events, "tokens")["detail"])

    def test_49_missing_foreign_and_ambiguous_transcripts(self):
        for case in ("missing", "foreign", "ambiguous"):
            with self.subTest(case):
                task = self.running_task(attempt=1)
                wt, _ = self.pass_report(task, attempt=1, wt=self.worktree(f"task-{task}"))
                self.agents(self.finished(f"task-{task}", sessionId="abc123"))
                if case == "foreign":
                    self.transcript_for(wt, "abc123.jsonl", folder="/work/other-project")
                if case == "ambiguous":
                    self.transcript_for(wt, "abc123-a.jsonl")
                    self.transcript_for(wt, "abc123-b.jsonl")
                events = self.events("close", str(task), "--verdict", "test-verified")
                self.assertIn("none recorded", self.one(events, "tokens")["detail"])
                self.assertNotIn("tokens", self.meta(task))

    def test_49_session_id_falls_back_to_the_row_id(self):
        task = self.running_task()
        wt, _ = self.pass_report(task)
        self.agents(self.finished("task-1"))
        self.transcript_for(wt, "sess-task-1-1.jsonl", tokens=4)
        self.ok("close", str(task), "--verdict", "test-verified")
        self.assertEqual(self.meta(task)["tokens"], "4/3")

    def close_tokens(self, session_row, transcripts, sessions=None):
        """Close a fresh task whose session row is `session_row(name)`; transcripts is [(name, kwargs)] for transcript_for."""
        task = self.running_task(attempt=1, sessions=sessions)
        wt, _ = self.pass_report(task, attempt=1, wt=self.worktree(f"task-{task}"))
        self.agents(session_row(f"task-{task}"))
        for name, kwargs in transcripts:
            self.transcript_for(wt, name, **kwargs)
        events = self.events("close", str(task), "--verdict", "test-verified")
        folder = os.path.join(self.home, ".claude", "projects", re.sub(r"[^A-Za-z0-9]", "-", wt))
        return self.one(events, "tokens")["detail"], self.meta(task).get("tokens"), folder

    def test_49_a_missing_token_count_names_the_reason(self):
        row = lambda wt: {**self.finished(wt), "id": ""}  # noqa: E731
        detail, tokens, _ = self.close_tokens(row, [], sessions=[])  # nothing recorded, and the row has no id
        self.assertEqual((detail, tokens), ("no session id recorded; none recorded", None))
        detail, tokens, folder = self.close_tokens(lambda wt: self.finished(wt, sessionId="abc123"), [])
        self.assertEqual((detail, tokens), (f"transcript folder {folder} not found; none recorded", None))
        detail, tokens, folder = self.close_tokens(lambda wt: self.finished(wt, sessionId="abc123"),
                                                   [("other.jsonl", {})])
        self.assertEqual((detail, tokens), (f"no transcript abc123*.jsonl in {folder}; none recorded", None))

    def test_49_a_full_session_id_is_found_under_another_folder_once(self):
        uuid = "0a1b2c3d-1111-4222-8333-444455556666"
        row = lambda wt: self.finished(wt, sessionId=uuid)  # noqa: E731
        detail, tokens, _ = self.close_tokens(row, [(f"{uuid}.jsonl", {"folder": "/work/elsewhere", "tokens": 6})])
        self.assertEqual(tokens, "6/3")
        self.assertIn("out 6 in 3", detail)
        detail, tokens, _ = self.close_tokens(row, [(f"{uuid}.jsonl", {"folder": "/work/one"}),
                                                    (f"{uuid}.jsonl", {"folder": "/work/two"})])
        self.assertIsNone(tokens)
        self.assertIn(f"session id {uuid} matches several transcripts", detail)
        # A short id is never searched across folders.
        detail, tokens, folder = self.close_tokens(lambda wt: self.finished(wt, sessionId="abc123"),
                                                   [("abc123.jsonl", {"folder": "/work/elsewhere"})])
        self.assertEqual((detail, tokens), (f"transcript folder {folder} not found; none recorded", None))

    def test_50_close_marks_done_and_stops_the_session(self):
        task = self.running_task()
        self.pass_report(task)
        self.agents(self.row("task-1"))
        later = self.add_task("Next", depends=(task,))
        events = self.events("close", str(task), "--verdict", "test-verified", "--ran", "make test")
        closed = self.one(events, "closed")
        self.assertEqual(self.one(events, "waits")["task"], later)
        self.assertIn("test-verified at", closed["detail"])
        self.assertIn("branch worktree-task-1", closed["detail"])
        self.assertEqual(self.status_of(task), "done")
        self.assertIn(["stop", "sess-task-1-1"], self.calls("stop"))
        stopped = [r for r in self.results(task) if r["status"] == "STOPPED"]
        self.assertEqual(len(stopped), 1)
        self.assertIn("Session: sess-task-1-1", stopped[0]["body"])
        self.assertEqual(self.one(events, "ready")["detail"], "none")

    def merge_setup(self):
        task = self.running_task()
        wt, head = self.pass_report(task)
        self.agents(self.finished("task-1"))
        return task, wt, head

    def test_51_no_merge_line_lists_the_branch(self):
        task, wt, head = self.merge_setup()
        before = self.git("rev-parse", "HEAD")
        events = self.events("close", str(task), "--verdict", "test-verified")
        ready = self.one(events, "ready-to-merge")
        self.assertEqual(ready["detail"], "branch worktree-task-1")
        self.assertIn(f"run.py merged {task} --by operator", ready["next"])
        self.assertEqual(self.git("rev-parse", "HEAD"), before)
        self.assertEqual(self.named(events, "merged"), [])
        self.assertEqual(self.calls("rm"), [])

    def test_51_merge_line_merges_into_a_clean_checkout(self):
        task, wt, head = self.merge_setup()
        self.orders("# Standing orders\n\n1. Keep tests green\n2. MERGE: verified branches into main\n")
        events = self.events("close", str(task), "--verdict", "test-verified")
        merged = self.one(events, "merged")
        self.assertIn("worktree-task-1 into", merged["detail"])
        self.assertEqual(self.merges(), "Merge worktree-task-1 (task #1)")
        meta = self.meta(task)
        self.assertEqual(meta["merged_by"], "manager")
        self.assertIn("merged_at", meta)
        self.assertIn(["rm", "sess-task-1-1"], self.calls("rm"))

    def test_51_dirty_checkout_detached_head_and_stop(self):
        task, wt, head = self.merge_setup()
        self.orders("MERGE: verified branches into main\n")
        with open(os.path.join(self.root, "dirty.txt"), "w") as fh:
            fh.write("x\n")
        events = self.events("close", str(task), "--verdict", "test-verified")
        self.assertIn("main checkout is not clean", self.one(events, "ready-to-merge")["detail"])
        self.assertEqual(self.merges(), "")
        os.remove(os.path.join(self.root, "dirty.txt"))
        self.git("checkout", "-q", "--detach")
        other = self.running_task()
        self.pass_report(other, wt=self.worktree("task-2"))
        events = self.events("close", str(other), "--verdict", "test-verified")
        self.assertIn("main checkout is detached", self.one(events, "ready-to-merge")["detail"])

    def test_51_stop_blocks_the_merge(self):
        task, wt, head = self.merge_setup()
        self.orders("STOP: paused\nMERGE: verified branches into main\n")
        events = self.events("close", str(task), "--verdict", "test-verified")
        self.assertIn("not merged during a pause", self.one(events, "ready-to-merge")["detail"])
        self.assertEqual(self.merges(), "")
        self.assertEqual(self.status_of(task), "done")

    def test_51_conflict_is_aborted(self):
        with open(os.path.join(self.root, "f.txt"), "w") as fh:
            fh.write("one\n")
        self.git("add", "f.txt")
        self.git("commit", "-q", "-m", "add f")
        task = self.running_task()
        wt = self.worktree("task-1")
        head = self.wt_commit(wt, "f.txt", "theirs\n")
        self.pass_report(task, wt=wt, head=head)
        with open(os.path.join(self.root, "f.txt"), "w") as fh:
            fh.write("ours\n")
        self.git("commit", "-q", "-am", "ours")
        later = self.add_task("Next", depends=(task,))
        self.orders("MERGE: verified branches into main\n")
        out = self.ok("close", str(task), "--verdict", "test-verified", pre=["--json"])
        events = json.loads(out.stdout)
        conflict = self.one(events, "conflict")
        self.assertIn("merge aborted", conflict["detail"])
        self.assertIn("--type decision", conflict["next"])
        self.assertIn(f"--blocks {later}", conflict["next"])
        self.assertFalse(os.path.exists(os.path.join(self.root, ".git", "MERGE_HEAD")))
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertNotIn("merged_at", self.meta(task))

    # --- merged and cleanup

    def closed_task(self, merged=False):
        task = self.add_task(attempt=1, verdict_ref=SHA_A, verdict="test-verified", sessions="[]")
        if merged:
            self.tg("edit", str(task), "--meta", 'merged_at="2026-10-26 10:00 UTC"', "merged_by=operator")
        self.tg("done", str(task))
        return task

    def test_52_merged_records_the_operators_word(self):
        task = self.closed_task()
        events = self.events("merged", str(task))
        self.assertEqual(self.one(events, "merged")["detail"], "recorded merged_by=operator")
        meta = self.meta(task)
        self.assertEqual(meta["merged_by"], "operator")
        self.assertIn("merged_at", meta)
        again = self.events("merged", str(task))
        self.assertIn("already recorded", self.one(again, "merged")["detail"])
        running = self.running_task()
        out = self.run_cmd("merged", str(running))
        self.assertEqual(out.returncode, 2)
        self.assertIn("is not a closed task", out.stderr)

    def test_53_cleanup_keeps_uncommitted_work(self):
        task = self.closed_task()
        wt = self.worktree("task-1")
        with open(os.path.join(wt, "wip.txt"), "w") as fh:
            fh.write("x\n")
        self.agents(self.finished("task-1"))
        events = self.events("merged", str(task))
        self.assertIn("uncommitted changes", self.one(events, "kept")["detail"])
        self.assertEqual(self.calls("rm"), [])
        self.assertTrue(os.path.isfile(os.path.join(wt, "wip.txt")))

    def test_53_discard_unpushed_only_for_commits_in_head(self):
        task = self.closed_task()
        head = self.git("rev-parse", "HEAD")
        self.agents(self.finished("task-1"))
        with open(self.rm_file, "w") as fh:
            json.dump({"sess-task-1-1": {"exit": 1, "stderr": f"unpushed commits; pass --discard-unpushed {head[:12]}@wt-1"}}, fh)
        events = self.events("merged", str(task))
        self.assertIn("discarded", self.one(events, "removed")["detail"])
        self.assertEqual(self.calls("rm")[-1], ["rm", "sess-task-1-1", "--discard-unpushed", f"{head[:12]}@wt-1"])
        self.assertTrue(all("--force-remove-worktree" not in c for c in self.calls()))

    def test_53_unmerged_commit_is_never_discarded(self):
        task = self.closed_task()
        wt = self.worktree("task-1")
        side = self.wt_commit(wt)
        self.agents(self.finished("task-1"))
        with open(self.rm_file, "w") as fh:
            json.dump({"sess-task-1-1": {"exit": 1, "stderr": f"unpushed commits; pass --discard-unpushed {side}@wt-1"}}, fh)
        events = self.events("merged", str(task))
        self.assertEqual(self.one(events, "kept")["detail"], f"task-1: commit {side[:7]} is not merged")
        self.assertEqual(len(self.calls("rm")), 1)
        self.assertTrue(os.path.isdir(wt))

    def test_53_untracked_files_are_listed_never_deleted(self):
        task = self.closed_task()
        wt = self.worktree("task-1")
        with open(os.path.join(wt, "notes.txt"), "w") as fh:
            fh.write("mine\n")
        self.agents(self.finished("task-1"))
        with open(self.rm_file, "w") as fh:
            json.dump({"sess-task-1-1": {"exit": 1, "stderr": "worktree has untracked files"}}, fh)
        events = self.events("merged", str(task))
        self.assertEqual(self.one(events, "kept")["detail"], "task-1: uncommitted changes (?? notes.txt)")
        self.assertTrue(os.path.isfile(os.path.join(wt, "notes.txt")))
        self.assertTrue(all("--force-remove-worktree" not in c for c in self.calls()))

    def test_53_other_failure_and_directory_without_a_session(self):
        task = self.closed_task()
        wt = self.worktree("task-1")
        self.agents(self.finished("verify-1-1"))
        with open(self.rm_file, "w") as fh:
            json.dump({"sess-verify-1-1": {"exit": 1, "stderr": "detached at an unmerged commit\nmore"}}, fh)
        events = self.events("merged", str(task))
        self.assertEqual([e["detail"] for e in self.named(events, "kept")],
                         ["verify-1-1: claude rm said: detached at an unmerged commit"])
        self.assertEqual([e["detail"] for e in self.named(events, "removed")],
                         [f"worktree task-1 (merged at {self.git('rev-parse', '--short=7', 'HEAD')})"])  # clean and merged: git removes it
        self.assertFalse(os.path.exists(wt))

    def test_53_abandoned_task_is_never_cleaned_up(self):
        task = self.closed_task(merged=True)
        self.tg("edit", str(task), "--meta", "abandoned=died")
        self.agents(self.finished("task-1"))
        self.events("merged", str(task))
        self.assertEqual(self.calls("rm"), [])

    # --- stop and abandon

    def test_54_stop_files_a_stopped_row_and_touches_no_git_state(self):
        task = self.running_task()
        wt = self.worktree("task-1")
        with open(os.path.join(wt, "wip.txt"), "w") as fh:
            fh.write("half\n")
        head = self.git("rev-parse", "HEAD", cwd=wt)
        self.agents(self.row("task-1"))
        events = self.events("stop", str(task))
        self.assertIn("run.py record commits its WIP", self.one(events, "stopped")["detail"])
        self.assertIn(["stop", "sess-task-1-1"], self.calls("stop"))
        row = self.results(task)[0]
        self.assertEqual((row["status"], row["author"], row["attempt"]), ("STOPPED", "manager", 1))
        for line in ("Session: sess-task-1-1", f"Worktree: {wt}", "Branch: worktree-task-1", "Files: ?? wip.txt"):
            self.assertIn(line, row["body"])
        self.assertNotIn("Head:", row["body"])
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt), head)
        self.assertTrue(os.path.isfile(os.path.join(wt, "wip.txt")))
        self.agents()
        out = self.run_cmd("stop", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("has no live session", out.stderr)

    def test_55_abandon(self):
        task = self.running_task(attempt=3, sessions=[self.entry(1, 1), self.entry(1, 3)])
        self.worktree("task-1")
        self.agents(self.row("task-1", 3), self.finished("task-1"))
        events = self.events("abandon", str(task), "died")
        self.assertEqual(self.meta(task)["abandoned"], "died")
        self.assertIn(["stop", "sess-task-1-3"], self.calls("stop"))
        detail = self.one(events, "abandoned")["detail"]
        self.assertIn("worktrees kept: task-1;", detail)
        filed = [r for r in self.results(task) if r["status"] == "ABANDONED"]
        self.assertEqual(len(filed), 1)
        self.assertIn("Session: sess-task-1-3", filed[0]["body"])
        self.assertIn("Worktree:", filed[0]["body"])
        out = self.run_cmd("abandon", str(task), "gave-up")
        self.assertEqual(out.returncode, 2)
        idle = self.add_task()
        self.assertEqual(self.run_cmd("abandon", str(idle), "died").returncode, 2)

    # --- review fixes

    def test_57_close_survives_a_failing_stop_and_can_be_resumed(self):
        task = self.running_task()
        self.pass_report(task)
        self.agents(self.row("task-1"))
        self.orders("MERGE: verified branches into main\n")
        with open(os.path.join(self.root, "dirty.txt"), "w") as fh:
            fh.write("x\n")
        env = dict(self.env, FAKE_CLAUDE_STOP_FAIL="1")
        events = self.events("close", str(task), "--verdict", "test-verified", env=env)
        self.assertIn("still live; claude stop said: boom", self.one(events, "kept")["detail"])
        self.assertEqual(self.status_of(task), "done")
        self.assertIn("main checkout is not clean", self.one(events, "ready-to-merge")["detail"])
        self.assertEqual([r for r in self.results(task) if r["status"] == "STOPPED"], [])
        os.remove(os.path.join(self.root, "dirty.txt"))
        again = self.events("close", str(task))
        self.assertEqual(self.one(again, "resumed")["task"], task)
        self.assertEqual(self.one(again, "merged")["task"], task)
        self.assertEqual(self.merges(), "Merge worktree-task-1 (task #1)")
        self.assertEqual(self.meta(task)["merged_by"], "manager")
        self.assertIn(["stop", "sess-task-1-1"], self.calls("stop"))
        self.assertEqual(self.run_cmd("close", str(task)).returncode, 2)

    def test_57_resumed_close_refuses_a_changed_branch(self):
        task = self.running_task()
        wt, _ = self.pass_report(task)
        self.ok("close", str(task), "--verdict", "test-verified")
        self.wt_commit(wt, "later.txt")
        out = self.run_cmd("close", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("the change differs (different diff)", out.stderr)

    def test_58_a_done_decisions_notes_reach_the_next_brief(self):
        task = self.running_task()
        self.add_result(task, "BLOCKED", "Task: 1\nStatus: BLOCKED\nIssues: which API?\n")
        gate = self.tg("add", "Which API?", "--type", "decision", "--meta", "decider=operator",
                       "--notes", "Options: REST or RPC.", "--blocks", str(task))["id"]
        self.tg("edit", str(gate), "--notes", "Options: REST or RPC. Answer: use the REST API.")
        self.tg("done", str(gate))
        self.worktree("task-1")
        arrived = self.one(self.events("record"), "arrived")
        self.assertEqual(arrived["next"], f"decision #{gate} answered; run.py launch {task}")
        context = self.section(self.brief(task), "CONTEXT")
        self.assertIn(f"### Decision #{gate}: Which API? (done)", context)
        self.assertIn("Answer: use the REST API.", context)
        self.assertNotIn("No report on file.", context)

    def test_59_launch_repairs_an_open_task_with_a_live_session(self):
        task = self.add_task()
        self.agents(self.row("task-1", name="task-1-1-smoke"))
        events = self.events("launch", str(task))
        repaired = self.one(events, "repaired")
        self.assertEqual((repaired["task"], repaired["attempt"], repaired["session"]), (1, 1, "sess-task-1-1"))
        self.assertEqual(self.calls("--bg"), [])
        self.assertEqual(self.status_of(task), "in_progress")
        meta = self.meta(task)
        self.assertEqual((meta["attempt"], meta["session"]), (1, "task-1-1-smoke"))
        self.assertIn("started_at", meta)
        self.assertEqual(meta["sessions"], [{"id": "sess-task-1-1", "kind": "task", "attempt": 1, "name": "task-1-1-smoke",
                                             "worktree": "task-1"}])
        again = self.run_cmd("launch", str(task))
        self.assertEqual(again.returncode, 2)
        self.assertIn("has a live session", again.stderr)

    def test_60_cleanup_skips_a_session_that_is_still_running(self):
        task = self.closed_task(merged=True)
        self.agents(self.row("verify-1-1"), self.finished("task-1"))
        events = self.events("merged", str(task))
        self.assertIn("still running", self.one(events, "kept")["detail"])
        self.assertEqual(self.calls("rm"), [["rm", "sess-task-1-1"]])

    def test_61_checksum_close_cleans_up_at_once(self):
        task = self.running_task()
        self.add_result(task, "PASS", "Task: 1\nStatus: PASS\nHead: abc123  out.txt\n")
        self.agents(self.finished("task-1"))
        events = self.events("close", str(task), "--verdict", "artifact-verified")
        self.assertEqual(self.one(events, "removed")["session"], "sess-task-1-1")

    def test_62_repeating_a_close_files_one_manager_verdict(self):
        task = self.running_task()
        self.pass_report(task)
        for _ in range(2):
            self.ok("close", str(task), "--verdict", "check-only", "--ran", "lint")
        filed = [r for r in self.results(task) if r["kind"] == "verify"]
        self.assertEqual(len(filed), 1)
        self.ok("close", str(task), "--verdict", "test-verified", "--ran", "pytest")
        self.assertEqual(len([r for r in self.results(task) if r["kind"] == "verify"]), 2)

    def test_63_dry_run_json_and_a_live_verifier_blocks_launch(self):
        task = self.add_task()
        out = self.run_cmd("launch", str(task), "--dry-run", pre=["--json"])
        self.assertEqual(out.returncode, 0, out.stderr)
        events = json.loads(out.stdout)
        self.assertEqual([e["event"] for e in events], ["dry-run"])
        self.assertIn("## GOAL", events[0]["detail"])
        self.assertIn("--worktree task-1 ", out.stderr)
        self.assertIn("--name task-1-1 ", out.stderr)
        self.assertEqual(self.calls("--bg"), [])
        self.agents(self.row("verify-1-1"))
        blocked = self.run_cmd("launch", str(task))
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("has a live session sess-verify-1-1", blocked.stderr)

    # --- status


    def test_56_earlier_died_result_with_live_attempt_is_in_flight(self):
        task = self.running_task(attempt=2, session="task-1-2", model="sonnet", started_at='"2026-10-26 09:00 UTC"')
        self.add_result(task, "DIED", "no session", attempt=1, by="manager")
        sections = self.status_sections()
        self.assertEqual(sections["In flight"].splitlines()[0], "In flight (1)")
        self.assertIn("#1", sections["In flight"])
        self.assertIn("DIED", sections["In flight"])
        self.assertIn("2026-10-26 09:00 UTC", sections["In flight"])
        self.assertIn("None.", sections["Failed or abandoned"])
        self.assertIn("None.", sections["Waiting for verification or triage"])

    def test_56_abandoned_marker_lists_task_as_abandoned(self):
        task = self.running_task(attempt=3, abandoned="died")
        self.add_result(task, "DIED", "no session", attempt=3, by="manager")
        sections = self.status_sections()
        self.assertIn("#1", sections["Failed or abandoned"])
        self.assertIn("died", sections["Failed or abandoned"])
        self.assertIn("None.", sections["In flight"])

    def test_56_result_for_current_attempt_is_waiting(self):
        task = self.running_task(session="task-1-1")
        self.add_result(task, "PASS", f"Task: 1\nStatus: PASS\nCheckpoint: {CHECKPOINT}\n")
        sections = self.status_sections()
        waiting = sections["Waiting for verification or triage"]
        for word in ("#1", "PASS", CHECKPOINT):
            self.assertIn(word, waiting)
        self.assertIn("None.", sections["In flight"])

    def test_56_verdict_without_close_is_listed_apart(self):
        task = self.running_task(verdict="verify-blocked")
        self.add_result(task, "PASS", "Task: 1\n")
        sections = self.status_sections()
        self.assertIn("None.", sections["Waiting for verification or triage"])
        self.assertIn("None.", sections["In flight"])
        self.assertEqual(sections["Verdict recorded, not closed"].splitlines()[0], "Verdict recorded, not closed (1)")
        self.assertIn("verify-blocked", sections["Verdict recorded, not closed"])

    def test_56_done_task_without_merge_is_listed_until_merged_at(self):
        unmerged = self.add_task("Sweep", attempt=1, verdict_ref=SHA_A, verdict="test-verified")
        merged = self.add_task("Build", attempt=1, verdict_ref=SHA_A, verdict="test-verified",
                               merged_at='"2026-10-26 10:00 UTC"', merged_by="operator")
        outside = self.add_task("Notes", attempt=1, verdict_ref='"abc123  out.txt"', verdict="artifact-verified")
        for task in (unmerged, merged, outside):
            self.tg("done", str(task))
        section = self.status_sections("--since", "2099-01-01")["Done, branch not merged"]
        self.assertEqual(section.splitlines()[0], "Done, branch not merged (1)")
        self.assertIn(f"#{unmerged} ", section)
        self.assertNotIn(f"#{merged} ", section)
        self.assertNotIn(f"#{outside} ", section)

    def test_56_in_flight_shows_latest_result_and_old_checkpoint(self):
        self.running_task(attempt=2)
        self.add_result(1, "ISSUES", f"Checkpoint: {CHECKPOINT}\n", attempt=1)
        in_flight = self.status_sections()["In flight"]
        self.assertIn("ISSUES", in_flight)
        self.assertIn(CHECKPOINT, in_flight)

    def test_56_stopped_task_is_in_flight(self):
        task = self.running_task()
        self.add_result(task, "STOPPED", "Session: s\nFiles: None\n", by="manager")
        sections = self.status_sections()
        self.assertIn("STOPPED", sections["In flight"])
        self.assertIn("None.", sections["Waiting for verification or triage"])

    def test_56_decisions_ready_done_columns_and_mark(self):
        done = self.add_task("Shipped", attempt=1, tokens='"11/3"', verdict="test-verified",
                             started_at='"2026-10-26 08:00 UTC"')
        self.add_result(done, "PASS", "Task: 1\nStatus: PASS\n")
        self.add_result(done, "PASS", "Verdict: test-verified\n", kind="verify", by="verify-1-1")
        self.tg("done", str(done))
        free = self.add_task("Free work")
        held = self.add_task("Held work")
        self.tg("add", "Pick a name", "--type", "decision", "--meta", "decider=operator", "--due", "2026-11-01",
                "--blocks", str(held))
        self.tg("add", "Open question", "--type", "decision", "--meta", "decider=operator")
        sections = self.status_sections("--mark")
        row = next(line for line in sections["Done since last report"].splitlines() if "Shipped" in line)
        for word in ("11 / 3", "test-verified", "verify-1-1", "2026-10-26 08:00 UTC"):
            self.assertIn(word, row)
        header = sections["Done since last report"].splitlines()[2]
        self.assertIn("Verified by", header)
        self.assertIn("Started", header)
        self.assertNotIn("Ended", header)
        decisions = sections["Open decisions"]
        self.assertEqual(decisions.splitlines()[0], "Open decisions (2)")
        self.assertIn("Pick a name", decisions)
        self.assertIn("2026-11-01", decisions)
        self.assertIn(f"#{held}", decisions)
        ready = sections["Ready"]
        self.assertEqual(ready.splitlines()[0], "Ready (1)")
        self.assertNotIn("Pick a name", ready)
        self.assertTrue(os.path.isfile(os.path.join(self.root, ".agentic-team", "last-report")))
        self.assertNotIn("Open gates", self.ok("status").stdout)

    def test_56_json_report(self):
        self.running_task(session="task-1-1")
        out = self.ok("status", pre=["--json"])
        data = json.loads(out.stdout)
        self.assertEqual(data["project"], "demo")
        self.assertEqual(len(data["in_flight"]), 1)
        self.assertEqual(data["in_flight"][0]["Task"], "#1")

    def test_56_empty_project(self):
        out = self.run_cmd("status")
        self.assertEqual(out.returncode, 2)
        self.assertIn("has no tasks", out.stderr)

    # --- local mode never calls the host

    def test_66_local_mode_never_calls_the_host(self):
        bare = os.path.join(self.dir, "claude-only")
        os.makedirs(bare)
        os.symlink(os.path.join(self.bin, "claude"), os.path.join(bare, "claude"))
        env = dict(self.env, PATH=bare + os.pathsep + "/usr/bin" + os.pathsep + "/bin")
        self.assertIsNone(shutil.which("gh", path=env["PATH"]))
        self.assertIsNone(shutil.which("glab", path=env["PATH"]))
        self.orders("MERGE: verified branches into main\n")
        fresh = self.add_task(verdict="test-verified", verdict_ref="abc1234")
        self.assertEqual(len(self.named(self.events("launch", str(fresh), env=env), "launched")), 1)
        task = self.running_task()
        self.pass_report(task, wt=self.worktree("task-2"))
        self.agents(self.row("task-2"))
        events = self.events("close", str(task), "--verdict", "test-verified", "--ran", "make test", env=env)
        self.assertEqual(self.one(events, "merged")["task"], task)
        self.assertEqual(self.merges(), "Merge worktree-task-2 (task #2)")
        closed = self.add_task(attempt=1, verdict_ref=SHA_A, verdict="test-verified")
        self.tg("done", str(closed))
        self.assertEqual(self.one(self.events("merged", str(closed), env=env), "merged")["detail"], "recorded merged_by=operator")
        self.events("record", env=env)
        self.events("status", env=env)
        self.assertEqual((self.host_log("gh"), self.host_log("glab")), ([], []))

    # --- the change id

    def test_69_change_id_survives_a_rebase_and_nothing_else(self):
        import run as runner
        run = self.make_runner()
        lines = "".join(f"line {i}\n" for i in range(1, 11))
        base = self.commit_file("f.txt", lines)
        self.git("checkout", "-q", "-b", "task")
        task = self.commit_file("f.txt", lines.replace("line 6\n", "LINE 6\n"))
        self.git("checkout", "-q", "main")
        target = self.commit_file("f.txt", "new first line\n" + lines.replace("line 2\n", "target 2\n"))
        self.git("checkout", "-q", "task")
        self.git("rebase", "-q", "main")
        rebased = self.git("rev-parse", "HEAD")
        self.assertNotEqual(rebased, task)
        original = runner.change_id(run, base, task)
        self.assertEqual(runner.change_id(run, target, rebased), original)  # context moved, line numbers shifted
        # squash, split and reorder: one diff over the whole range
        self.git("checkout", "-q", "-b", "split", base)
        self.commit_file("f.txt", lines.replace("line 6\n", "LINE 6\n"), message="part one")
        self.commit_file("g.txt", "extra\n", message="part two")
        self.git("reset", "--soft", base)
        self.git("commit", "-q", "-m", "squashed")
        squashed = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "-b", "twin", base)
        self.commit_file("f.txt", lines.replace("line 6\n", "LINE 6\n"), message="a")
        self.commit_file("g.txt", "extra\n", message="b")
        self.assertEqual(runner.change_id(run, base, squashed), runner.change_id(run, base, self.git("rev-parse", "HEAD")))
        self.assertNotEqual(runner.change_id(run, base, squashed), original)
        # whitespace edit of a changed line, an appended commit, and a changed + line differ
        self.git("checkout", "-q", "-b", "space", base)
        spaced = self.commit_file("f.txt", lines.replace("line 6\n", "LINE 6 \n"))
        self.assertNotEqual(runner.change_id(run, base, spaced), original)
        appended = self.commit_file("h.txt", "more\n")
        self.assertNotEqual(runner.change_id(run, base, appended), original)
        self.git("checkout", "-q", "-b", "other", base)
        self.assertNotEqual(runner.change_id(run, base, self.commit_file("f.txt", lines.replace("line 6\n", "LINE SIX\n"))), original)
        # a binary file changed in the task and also on the target: the index line stays, so it differs
        self.git("checkout", "-q", "main")
        start = self.commit_file("b.dat", b"\x00\x01\x02", binary=True)
        self.git("checkout", "-q", "-b", "bin-task", start)
        first = self.commit_file("b.dat", b"\x00\x01\x09", binary=True)
        self.git("checkout", "-q", "-b", "bin-target", start)
        self.commit_file("b.dat", b"\x00\x01\x07", binary=True)
        second = self.commit_file("b.dat", b"\x00\x01\x09", binary=True)
        target_side = self.git("rev-parse", "HEAD~1")
        self.assertNotEqual(runner.change_id(run, start, first), runner.change_id(run, target_side, second))

    def test_70_close_accepts_a_rebased_branch_with_the_same_change(self):
        task = self.running_task(base=json.dumps(self.git("rev-parse", "HEAD")))
        wt, head = self.pass_report(task)
        self.commit_file("main.txt", "moved on\n")
        self.git("rebase", "-q", "main", cwd=wt)
        rebased = self.git("rev-parse", "HEAD", cwd=wt)
        self.assertNotEqual(rebased, head)
        events = self.events("close", str(task), "--verdict", "test-verified", "--ran", "make test")
        self.assertIn(f"same change at {rebased[:7]} (verified at {head[:7]})", self.one(events, "rebased")["detail"])
        self.assertEqual(self.meta(task)["verdict_ref"], rebased)
        self.assertIn(rebased, self.one(events, "closed")["detail"])
        filed = [r for r in self.results(task) if r["kind"] == "verify"][-1]
        self.assertIn(f"Head: {rebased}", filed["body"])
        self.assertEqual(self.status_of(task), "done")

    def test_70_a_rebased_branch_with_an_extra_commit_is_refused(self):
        task = self.running_task(base=json.dumps(self.git("rev-parse", "HEAD")))
        wt, head = self.pass_report(task)
        self.commit_file("main.txt", "moved on\n")
        self.git("rebase", "-q", "main", cwd=wt)
        self.wt_commit(wt, "extra.txt")
        out = self.run_cmd("close", str(task), "--verdict", "test-verified")
        self.assertEqual(out.returncode, 2)
        self.assertIn("the change differs (different diff)", out.stderr)
        self.assertEqual(self.status_of(task), "in_progress")

    def test_70_a_pruned_verified_commit_is_refused(self):
        task = self.running_task(base=json.dumps(self.git("rev-parse", "HEAD")))
        wt, head = self.pass_report(task)
        self.commit_file("main.txt", "moved on\n")
        self.git("rebase", "-q", "main", cwd=wt)
        for cwd in (wt, self.root):
            self.git("reflog", "expire", "--expire=now", "--all", cwd=cwd)
        self.git("gc", "-q", "--prune=now")
        out = self.run_cmd("close", str(task), "--verdict", "test-verified")
        self.assertEqual(out.returncode, 2)
        self.assertIn(f"the verified commit {head} is gone", out.stderr)

    # --- launch --base, adopt, unmanaged

    def test_71_launch_base_starts_from_any_commit(self):
        tip = self.feature_branch()
        self.git("push", "-q", "origin", "feature")
        self.git("fetch", "-q", "origin")
        before = (self.git("branch", "--show-current"), self.git("rev-parse", "HEAD"), self.git("status", "--porcelain"))
        task = self.add_task()
        self.assert_base(self.brief(task, "--base", tip), tip)
        events = self.events("launch", str(task), "--base", tip)
        self.assertIn(f"base {tip[:7]}", self.one(events, "launched")["detail"])
        meta = self.meta(task)
        self.assertEqual(meta["base"], tip)
        self.assertNotIn("target", meta)
        for ref in ("feature", "origin/feature"):
            other = self.add_task()
            self.ok("launch", str(other), "--base", ref)
            self.assertEqual((self.meta(other)["base"], self.meta(other)["target"]), (tip, "feature"), ref)
        out = self.run_cmd("launch", str(self.add_task()), "--base", "no-such-branch")
        self.assertEqual(out.returncode, 2)
        self.assertIn("--base no-such-branch is not a commit or branch in this repository; fetch it first", out.stderr)
        self.assertEqual((self.git("branch", "--show-current"), self.git("rev-parse", "HEAD"), self.git("status", "--porcelain")), before)

    def test_72_base_lifts_the_unmerged_dependency_refusal_only_when_it_contains_the_commit(self):
        tip = self.feature_branch()
        self.git("branch", "elsewhere", "main")
        up = self.add_task("Build base", "Why: base.\n- [ ] built", attempt=1, verdict_ref=tip)
        task = self.add_task("Use base", "Why: needs base.\n- [ ] used", depends=(up,))
        self.tg("done", str(up))
        out = self.run_cmd("launch", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("is not merged; merge it and run run.py merged", out.stderr)
        self.assertIn("pass --base <its branch>", out.stderr)
        self.assertEqual(self.run_cmd("launch", str(task), "--base", "elsewhere").returncode, 2)
        self.ok("launch", str(task), "--base", "feature")
        self.assertEqual(self.meta(task)["base"], tip)

    def test_73_pr_mode_starts_from_the_fetched_target_branch(self):
        self.pr_config()
        self.fake_host()
        clone = os.path.join(self.dir, "clone")
        subprocess.run(["git", "clone", "-q", self.origin, clone], check=True)
        for key, value in (("user.name", "t"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
            self.git("config", key, value, cwd=clone)
        ahead = self.commit_file("ahead.txt", "x\n", cwd=clone)
        self.git("push", "-q", "origin", "main", cwd=clone)
        task = self.add_task()
        self.assertNotEqual(self.git("rev-parse", "HEAD"), ahead)
        self.assert_base(self.brief(task), ahead)
        self.ok("launch", str(task))
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.wt_path("task-1")), ahead)
        self.assertEqual(self.meta(task)["base"], ahead)

    def adopt_setup(self, name="feat"):
        tip = self.feature_branch(name)
        return tip, self.add_task()

    def test_74_adopt_brings_a_branch_under_run_py(self):
        tip, task = self.adopt_setup()
        base = self.git("rev-parse", "HEAD")
        events = self.events("adopt", str(task), "--branch", "feat", "--head", tip[:10])
        adopted = self.one(events, "adopted")
        self.assertEqual((adopted["task"], adopted["attempt"]), (task, 1))
        self.assertIn(f"branch feat at {tip[:7]}", adopted["detail"])
        self.assertIn(f"run.py verify {task}", adopted["next"])
        self.assertEqual(self.status_of(task), "in_progress")
        meta = self.meta(task)
        self.assertEqual((meta["attempt"], meta["session"], meta["base"]), (1, "adopted", base))
        self.assertNotIn("model", meta)
        row = self.results(task)[0]
        self.assertEqual((row["kind"], row["status"], row["author"], row["attempt"]), ("task", "PASS", "manager", 1))
        for line in ("Branch: feat", f"Head: {tip}", "Worktree: None", "Ran: not stated (adopted)"):
            self.assertIn(line, row["body"])
        arrived = self.one(self.events("record"), "arrived")
        self.assertIn("PASS by manager", arrived["detail"])
        self.assertTrue(arrived["detail"].endswith("; adopted"))
        closed = self.events("close", str(task), "--verdict", "test-verified", "--ran", "x")
        self.assertEqual(self.one(closed, "tokens")["detail"], "no session recorded; none recorded")
        self.assertEqual(self.meta(task)["sessions"], [])
        self.assertEqual(self.status_of(task), "done")
        self.assertEqual(self.meta(task)["verdict_ref"], tip)

    def test_74_adopt_refusals(self):
        tip, task = self.adopt_setup()
        out = self.run_cmd("adopt", str(task), "--branch", "feat", "--head", "b" * 12)
        self.assertEqual(out.returncode, 2)
        self.assertIn(f"branch feat is at {tip}, not {'b' * 12}; adopt takes the branch tip", out.stderr)
        out = self.run_cmd("adopt", str(task), "--branch", "nope", "--head", tip[:7])
        self.assertIn("branch nope not found; fetch it: git fetch origin nope:nope", out.stderr)
        out = self.run_cmd("adopt", str(task), "--branch", "feat", "--head", "zzz")
        self.assertEqual(out.returncode, 2)
        out = self.run_cmd("adopt", str(task), "--branch", "feat", "--head", tip[:7], "--pr", "7")
        self.assertEqual(out.returncode, 2)
        self.assertIn('--pr needs merge.mode = "pr"', out.stderr)
        self.agents(self.row("task-1"))
        out = self.run_cmd("adopt", str(task), "--branch", "feat", "--head", tip[:7])
        self.assertIn("has a live session sess-task-1-1", out.stderr)
        self.assertIn("run run.py record first", out.stderr)
        self.agents()
        done = self.add_task()
        self.tg("done", str(done))
        self.assertIn(f"#{done} is done", self.run_cmd("adopt", str(done), "--branch", "feat", "--head", tip[:7]).stderr)
        gone = self.running_task(attempt=3, abandoned="died")
        out = self.run_cmd("adopt", str(gone), "--branch", "feat", "--head", tip[:7])
        self.assertIn(f"is abandoned (died); run.py launch {gone} --attempt 4 to try again", out.stderr)
        self.assertEqual(self.status_of(task), "open")
        self.assertEqual(self.results(task), [])

    def test_75_tasks_without_an_attempt_are_one_unmanaged_line(self):
        for _ in range(3):
            self.add_task(start=True)
        events = self.events("record")
        unmanaged = self.one(events, "unmanaged")
        self.assertEqual(unmanaged["detail"], "#1 #2 #3")
        self.assertIn("run.py adopt <id> --branch <b> --head <sha> [--pr <n>]", unmanaged["next"])
        self.assertEqual(self.named(events, "unknown"), [])
        self.assertIn("unmanaged: #1 #2 #3 | next: run.py adopt", self.ok("record").stdout)
        for task in (1, 2, 3):
            self.assertEqual(self.results(task), [])
        self.assertEqual(self.calls("--bg"), [])
        self.assertEqual(self.status_sections()["In flight"].count("not managed"), 3)

    # --- verifier override


    def test_76_override_upgrade_needs_evidence(self):
        task = self.verified_by("check-only")
        out = self.run_cmd("close", str(task), "--verdict", "artifact-verified")
        self.assertEqual(out.returncode, 2)
        self.assertIn('--override-verifier "<reason>"', out.stderr)
        out = self.run_cmd("close", str(task), "--verdict", "artifact-verified", "--override-verifier", "probe",
                           "--ran", "ran the probe")
        self.assertEqual(out.returncode, 2)
        self.assertIn("an upgrade from check-only to artifact-verified needs evidence in --ran", out.stderr)
        self.assertEqual(self.status_of(task), "in_progress")
        events = self.events("close", str(task), "--verdict", "artifact-verified", "--override-verifier", "probe",
                             "--ran", "see https://ci/run/1")
        self.assertEqual(self.one(events, "override")["detail"], "check-only by verify-1-1 -> artifact-verified; probe")
        self.one(events, "closed")
        filed = [r for r in self.results(task) if r["kind"] == "verify" and r["author"] == "manager"]
        self.assertEqual(len(filed), 1)
        for line in ("Verdict: artifact-verified", "Overrides: check-only (result #2 by verify-1-1)", "Reason: probe",
                     "Ran: see https://ci/run/1"):
            self.assertIn(line, filed[0]["body"])
        self.assertEqual(self.meta(task)["verdict"], "artifact-verified")
        second = self.verified_by("check-only")
        self.ok("close", str(second), "--verdict", "test-verified", "--override-verifier", "probe", "--ran", "run 123456789")
        self.assertEqual(self.meta(second)["verdict"], "test-verified")

    def test_76_override_downgrade_and_the_refusals(self):
        task = self.verified_by("test-verified")
        events = self.events("close", str(task), "--verdict", "check-only", "--override-verifier", "no runner")
        self.assertIn("check-only; not closed", self.one(events, "verdict")["detail"])
        self.assertEqual(self.status_of(task), "in_progress")
        self.assertIn("Ran: not stated", [r for r in self.results(task) if r["author"] == "manager"][0]["body"])
        failed = self.verified_by("verify-failed")
        out = self.run_cmd("close", str(failed), "--verdict", "test-verified", "--override-verifier", "x", "--ran", "https://x")
        self.assertEqual(out.returncode, 2)
        self.assertIn(f"a verify-failed verdict needs a fix round (run.py launch {failed}), not an override", out.stderr)
        lower = self.events("close", str(failed), "--verdict", "verify-blocked", "--override-verifier", "cannot run")
        self.assertIn("verify-blocked; not closed", self.one(lower, "verdict")["detail"])
        bare = self.running_task()
        self.pass_report(bare, wt=self.worktree(f"task-{bare}"))
        out = self.run_cmd("close", str(bare), "--verdict", "test-verified", "--override-verifier", "x")
        self.assertEqual(out.returncode, 2)
        self.assertIn(f"#{bare} has no verifier verdict to override; pass --verdict alone", out.stderr)

    def test_77_an_override_outranks_the_older_verifier_row_until_a_newer_one_arrives(self):
        task = self.verified_by("test-verified")
        self.ok("close", str(task), "--verdict", "check-only", "--override-verifier", "no runner")
        events = self.events("record")
        self.assertEqual(self.named(events, "verified"), [])
        self.assertIn("verdict check-only", self.one(events, "unclosed")["detail"])
        self.add_result(task, "PASS", "Status: PASS\nVerdict: test-verified\n", kind="verify", by="verify-1-1-2")
        again = self.events("record")
        self.assertIn("Verdict test-verified by verify-1-1-2", self.one(again, "verified")["detail"])

    # --- the permission-prompt hint, --root

    def test_78_a_stuck_session_gets_the_prompt_hint_not_a_model_change(self):
        worker = self.running_task()
        verifier = self.running_task()
        self.add_result(verifier, "PASS", f"Task: 2\nStatus: PASS\nHead: {SHA_A}\n")
        self.agents(self.row("task-1", status="waiting", state="working", waitingFor="permission prompt"),
                    self.row("verify-2-1", status="waiting", state="blocked", waitingFor="permission prompt"))
        stuck = {e["task"]: e for e in self.named(self.events("record"), "stuck")}
        self.assertIn("(permission prompt)", stuck[worker]["detail"])
        self.assertIn("filed verify BLOCKED (permission prompt)", stuck[verifier]["detail"])
        for task, sid, cmd in ((worker, "sess-task-1-1", "run.py launch 1"), (verifier, "sess-verify-2-1", "run.py verify 2 --again")):
            hint = stuck[task]["next"]
            for text in (f"claude logs {sid}", "verify_mode=ci", "A pinned old model id is one more possible cause", f"Then {cmd}."):
                self.assertIn(text, hint)
            self.assertNotIn("--model sonnet", hint)
        self.agents()
        again = {e["task"]: e for e in self.named(self.events("record"), "stuck")}
        self.assertEqual(again[worker]["detail"], "filed earlier")
        self.assertIn("claude logs sess-task-1-1", again[worker]["next"])
        self.assertIn("Then run.py launch 1.", again[worker]["next"])

    def test_79_a_root_without_the_toml_is_refused_before_the_config_is_read(self):
        other = os.path.join(self.dir, "other")
        os.makedirs(other)
        subprocess.run(["git", "-C", other, "init", "-q"], check=True)
        out = self.run_cmd("record", root=other)
        self.assertEqual(out.returncode, 2)
        self.assertIn(f"no .agentic-team.toml in {os.path.realpath(other)}; run from the repository root or pass --root <dir>", out.stderr)
        self.assertNotIn("taskgraph.project is empty", out.stderr)

    # --- one worktree, many sessions

    def test_23_the_recorded_session_id_comes_from_what_claude_printed(self):
        sessions = lambda task: self.meta(task).get("sessions")  # noqa: E731
        no_rows = self.add_task()
        detail = self.one(self.events("launch", str(no_rows)), "launched")["detail"]
        self.assertEqual([e["id"] for e in sessions(no_rows)], ["sess-task-1-1"])
        self.assertIn("claude agents does not list sess-task-1-1 yet", detail)
        listed = self.add_task()
        self.agents(self.finished("task-2"))
        detail = self.one(self.events("launch", str(listed)), "launched")["detail"]
        self.assertEqual([e["id"] for e in sessions(listed)], ["sess-task-2-1"])
        for note in ("does not list", "recorded the row", "no session id printed"):
            self.assertNotIn(note, detail)
        wrong = self.add_task()
        self.agents()
        row = json.dumps(self.row("task-3"))  # the session appears in `claude agents` when it starts
        env = dict(self.env, FAKE_CLAUDE_BG_SAID="backgrounded \u00b7 garbage \u00b7 task-3-1", FAKE_CLAUDE_BG_ROW=row)
        detail = self.one(self.events("launch", str(wrong), env=env), "launched")["detail"]
        self.assertEqual(sessions(wrong), [self.entry(wrong, 1)])
        self.assertIn("claude printed garbage; recorded the row sess-task-3-1 found in the worktree", detail)
        silent = self.add_task()
        self.agents()
        detail = self.one(self.events("launch", str(silent), env=dict(self.env, FAKE_CLAUDE_BG_SAID="")), "launched")["detail"]
        self.assertEqual(sessions(silent), [])
        self.assertIn("no session id printed; the row is matched by its folder", detail)
        self.assertNotIn("claude said", detail)
        text_only = self.add_task()  # no `backgrounded` line: a finished row in the folder is not the new session
        self.agents(self.finished("task-5"))
        detail = self.one(self.events("launch", str(text_only), env=dict(self.env, FAKE_CLAUDE_BG_SAID="garbage")),
                          "launched")["detail"]
        self.assertEqual(sessions(text_only), [])
        self.assertIn("no session id printed", detail)
        live_only = self.add_task()  # no `backgrounded` line, but exactly one live unrecorded row in the folder
        self.agents()
        env = dict(self.env, FAKE_CLAUDE_BG_SAID="garbage", FAKE_CLAUDE_BG_ROW=json.dumps(self.row("task-6")))
        detail = self.one(self.events("launch", str(live_only), env=env), "launched")["detail"]
        self.assertEqual(sessions(live_only), [self.entry(live_only, 1)])
        self.assertIn("no session id printed; recorded the row sess-task-6-1 found in the worktree", detail)
        stale = self.add_task()  # a printed id that is not listed, and only a finished row: the printed id stands
        self.agents(self.finished("task-7"))
        env = dict(self.env, FAKE_CLAUDE_BG_SAID="backgrounded \u00b7 abc123 \u00b7 x")
        detail = self.one(self.events("launch", str(stale), env=env), "launched")["detail"]
        self.assertEqual([e["id"] for e in sessions(stale)], ["abc123"])
        self.assertIn("claude agents does not list abc123 yet", detail)

    def two_rows(self):
        task = self.running_task(attempt=2, sessions=[self.entry(1, 1), self.entry(1, 2)])
        return task, self.task_wt(task)

    def test_36_two_finished_rows_in_one_folder_are_told_apart_by_id(self):
        task, wt = self.two_rows()
        self.agents(self.finished("task-1", 1), self.finished("task-1", 2))
        died = self.one(self.events("record"), "died")
        self.assertEqual((died["attempt"], died["session"]), (2, "sess-task-1-2"))
        body = self.results(task)[0]["body"]
        self.assertIn("sess-task-1-2", body)
        self.assertNotIn("sess-task-1-1", body)

    def test_36_close_reads_the_transcript_of_the_current_attempt(self):
        task, wt = self.two_rows()
        self.pass_report(task, attempt=2, wt=wt)
        self.agents(self.finished("task-1", 1), self.finished("task-1", 2))
        self.transcript_for(wt, "sess-task-1-1.jsonl", tokens=11)
        self.transcript_for(wt, "sess-task-1-2.jsonl", tokens=22)
        events = self.events("close", str(task), "--verdict", "test-verified")
        self.assertEqual(self.meta(task)["tokens"], "22/3")
        self.assertEqual(self.one(events, "tokens")["session"], "sess-task-1-2")

    def test_36_stop_stops_the_live_session_of_a_shared_folder_only(self):
        task, wt = self.two_rows()
        self.agents(self.finished("task-1", 1), self.row("task-1", 2))
        self.ok("stop", str(task))
        self.assertEqual(self.calls("stop"), [["stop", "sess-task-1-2"]])

    def test_36_an_unrecorded_finished_row_in_the_task_folder_is_the_current_attempts(self):
        task = self.running_task(attempt=2, sessions=[])
        self.agents(self.finished("task-1", 1))
        died = self.one(self.events("record"), "died")
        self.assertEqual((died["task"], died["attempt"], died["session"]), (task, 2, "sess-task-1-1"))
        self.assertEqual([(r["attempt"], r["status"]) for r in self.results(task)], [(2, "DIED")])

    def test_36_an_unrecorded_stopped_row_belongs_to_nobody(self):
        task = self.running_task(attempt=2, sessions=[self.entry(1, 1)])
        self.agents(self.stopped_row("task-1-2-smoke", sid="sess-task-1-2"))
        died = self.one(self.events("record"), "died")
        self.assertIsNone(died["session"])
        self.assertEqual(self.calls("stop"), [])

    def test_25_verify_again_records_each_verifier(self):
        task = self.running_task()
        self.add_result(task, "PASS", f"Task: 1\nStatus: PASS\nHead: {self.git('rev-parse', 'HEAD')}\n")
        self.add_result(task, "BLOCKED", "Verdict: verify-blocked\n", kind="verify", by="verify-1-1")
        self.ok("verify", str(task), "--again")
        self.agents(self.finished("verify-1-1"))
        self.ok("verify", str(task), "--again")
        self.assertEqual(self.meta(task)["sessions"], [self.entry(task, 1), self.entry(task, 1, "verify"),
                                                       self.entry(task, 1, "verify", "verify-1-1-2")])

    def test_53_cleanup_removes_the_first_session_last_and_each_once(self):
        entries = [self.entry(1, 1), self.entry(1, 2), self.entry(1, 1, "verify")]
        task = self.add_task(attempt=2, verdict_ref=SHA_A, merged_at="x", merged_by="operator", sessions=json.dumps(entries))
        self.tg("done", str(task))
        self.worktree("task-1")
        self.worktree("verify-1-1")
        self.agents(self.finished("task-1", 1), self.finished("task-1", 2), self.finished("verify-1-1"))
        with open(self.rm_file, "w") as fh:
            json.dump({"sess-task-1-2": {"row_only": True}}, fh)  # only the first session of a folder removes it
        events = self.events("merged", str(task))
        self.assertEqual([c[1] for c in self.calls("rm")], ["sess-verify-1-1", "sess-task-1-2", "sess-task-1-1"])
        self.assertEqual(sorted(e["session"] for e in self.named(events, "removed")),
                         ["sess-task-1-1", "sess-task-1-2", "sess-verify-1-1"])
        self.assertEqual(self.named(events, "kept"), [])
        self.assertEqual(self.worktree_state()[2], [])
        self.assertTrue(all("--force-remove-worktree" not in c for c in self.calls()))

    def test_53_a_discard_is_passed_back_on_the_owners_rm_only_for_a_merged_commit(self):
        entries = [self.entry(1, 1), self.entry(1, 2)]
        task = self.add_task(attempt=2, verdict_ref=SHA_A, merged_at="x", merged_by="operator", sessions=json.dumps(entries))
        self.tg("done", str(task))
        wt = self.worktree("task-1")
        head = self.git("rev-parse", "HEAD")
        side = self.wt_commit(wt)
        self.agents(self.finished("task-1", 1), self.finished("task-1", 2))

        def table(commit):
            with open(self.rm_file, "w") as fh:
                json.dump({"sess-task-1-2": {"row_only": True},
                           "sess-task-1-1": {"exit": 1, "stderr": f"unpushed commits; pass --discard-unpushed {commit}@wt-1"}}, fh)

        table(side)
        events = self.events("merged", str(task))
        self.assertEqual(self.one(events, "kept")["detail"], f"task-1: commit {side[:7]} is not merged")
        self.assertEqual(self.calls("rm"), [["rm", "sess-task-1-2"], ["rm", "sess-task-1-1"]])
        self.git("reset", "-q", "--hard", head, cwd=wt)  # the work is merged: the owner's rm may discard
        table(head)
        events = self.events("merged", str(task))
        self.assertIn("discarded", self.named(events, "removed")[-1]["detail"])
        self.assertEqual(self.calls("rm")[-1], ["rm", "sess-task-1-1", "--discard-unpushed", f"{head}@wt-1"])

    def legacy_task(self):
        """A task started under 0.6.0: attempt 1 in .claude/worktrees/task-1-1, no `sessions` meta."""
        task = self.add_task(start=True, attempt=1)
        wt = self.worktree("task-1-1")
        head = self.wt_commit(wt)
        self.add_result(task, "ISSUES", f"Task: 1\nStatus: ISSUES\nBranch: worktree-task-1-1\nHead: {head}\n")
        return task, wt, head

    def test_23_a_task_started_under_0_6_0_is_listed_and_refused_until_its_sessions_are_declared(self):
        task, wt, head = self.legacy_task()
        self.agents(self.row("task-1-1", name="task-1-1"))  # its live 0.6.0 row matches nothing
        events = self.events("record")
        legacy = self.one(events, "legacy")
        self.assertEqual((legacy["task"], legacy["attempt"]), (task, 1))
        self.assertIn("started under agentic-team 0.6.0 (worktree .claude/worktrees/task-1-1); "
                      "run.py does not manage it", legacy["detail"])
        self.assertIn("tg edit 1 --meta sessions='[]'", legacy["next"])
        for name in ("died", "stuck", "running", "unknown"):
            self.assertEqual(self.named(events, name), [])
        self.assertEqual(len(self.results(task)), 1)
        for command in (("launch",), ("verify",), ("close", "--verdict", "test-verified"), ("stop",), ("abandon", "died"),
                        ("adopt", "--branch", "main", "--head", "abc1234")):
            out = self.run_cmd(command[0], str(task), *command[1:])
            self.assertEqual(out.returncode, 2, command)
            self.assertIn("started under agentic-team 0.6.0", out.stderr)
            self.assertIn("tg edit 1 --meta sessions='[]'", out.stderr)
        self.assertEqual(self.calls("--bg"), [])
        self.tg("edit", str(task), "--meta", "sessions=[]")
        self.agents()
        self.assertEqual(self.named(self.events("record"), "legacy"), [])
        detail = self.one(self.events("launch", str(task)), "launched")["detail"]
        self.assertIn(f"created at Head {head[:7]} of attempt 1", detail)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.wt_path("task-1")), head)
        self.assertTrue(os.path.isdir(wt))  # the old folder stays

    # --- a merged task's worktrees are removed when they are safe to remove

    def merged_task(self, *entries, sessions=True, **meta):
        """A done, merged task. `entries` are the sessions run.py recorded (default: the first attempt's);
        sessions=False models a task started before 0.7.0 (no `sessions` meta)."""
        extra = {"sessions": json.dumps(list(entries) or [self.entry(1, 1)])} if sessions else {}
        task = self.add_task(attempt=1, verdict_ref=SHA_A, merged_at="x", merged_by="operator", **extra, **meta)
        self.tg("done", str(task))
        return task

    def rows_only(self, *sids):
        """`claude rm` of these sessions removes the row and leaves the folder, as for a later session of a folder."""
        with open(self.rm_file, "w") as fh:
            json.dump({sid: {"row_only": True} for sid in sids}, fh)

    def short(self, rev="HEAD", cwd=None):
        return self.git("rev-parse", rev, cwd=cwd)[:7]

    def no_force(self):
        self.assertTrue(all("--force-remove-worktree" not in c for c in self.calls()))

    def test_70_a_merged_clean_locked_folder_left_after_rm_is_unlocked_and_removed(self):
        task = self.merged_task(self.entry(1, 1), self.entry(1, 2))
        wt = self.worktree("task-1")
        self.claude_lock("task-1", self.dead_pid())
        self.agents(self.finished("task-1", 1), self.finished("task-1", 2))
        self.rows_only("sess-task-1-1", "sess-task-1-2")
        events = self.events("merged", str(task))
        self.assertEqual([e["detail"] for e in self.named(events, "removed") if e["session"] is None],
                         [f"worktree task-1 (merged at {self.short()})"])
        self.assertEqual(self.named(events, "kept"), [])
        self.assertEqual(self.worktree_state(), (1, "", []))  # folder, registration and branch are gone
        self.assertEqual([c[1] for c in self.calls("rm")], ["sess-task-1-2", "sess-task-1-1"])  # each row once
        self.no_force()

    def test_70_rows_that_name_a_removed_folder_go_and_a_refusal_is_reported_not_fatal(self):
        task = self.merged_task(self.entry(1, 1), self.entry(1, 2))
        self.worktree("task-1")
        self.agents(self.finished("task-1", 1), self.finished("task-1", 2))
        with open(self.rm_file, "w") as fh:
            json.dump({"sess-task-1-1": {"row_only": True}, "sess-task-1-2": {"exit": 1, "stderr": "boom\nmore"}}, fh)
        events = self.events("merged", str(task))
        self.assertEqual(len(self.named(events, "removed")), 2)  # the first session's row, then the folder
        self.assertEqual([e["detail"] for e in self.named(events, "kept")], ["task-1: claude rm said: boom"])
        self.assertEqual(self.worktree_state()[2], [])
        self.assertEqual([c[1] for c in self.calls("rm")], ["sess-task-1-2", "sess-task-1-1", "sess-task-1-2"])

    def test_70_a_task_started_before_0_7_0_loses_its_task_and_verifier_folders(self):
        task = self.merged_task(sessions=False)
        self.worktree("task-1-1")
        self.worktree("verify-1-1")
        self.agents(self.finished("task-1-1"), self.finished("verify-1-1"))
        self.rows_only("sess-task-1-1", "sess-verify-1-1")
        events = self.events("merged", str(task))
        short = self.short()
        self.assertEqual(sorted(e["detail"] for e in self.named(events, "removed") if e["session"] is None),
                         [f"worktree task-1-1 (merged at {short})", f"worktree verify-1-1 (merged at {short})"])
        self.assertEqual(self.named(events, "kept"), [])
        self.assertEqual(self.worktree_state(), (1, "", []))
        self.assertIn(["rm", "sess-task-1-1"], self.calls("rm"))  # the row of the old per-attempt folder
        self.no_force()

    def test_70_a_folder_that_fails_a_check_stays_with_one_line_that_names_it(self):
        self.commit_file("tracked.txt", "one\n")
        task = self.merged_task()
        untracked, modified = self.worktree("task-1"), self.worktree("verify-1-1")
        unmerged, live = self.worktree("verify-1-2"), self.worktree("verify-1-3")
        with open(os.path.join(untracked, "notes.txt"), "w") as fh:
            fh.write("mine\n")
        with open(os.path.join(modified, "tracked.txt"), "w") as fh:
            fh.write("two\n")
        side = self.wt_commit(unmerged)
        self.agents(self.row("verify-1-3"))
        events = self.events("merged", str(task))
        self.assertEqual(sorted(e["detail"] for e in self.named(events, "kept")), sorted([
            "task-1: uncommitted changes (?? notes.txt)",
            "verify-1-1: uncommitted changes (M tracked.txt)",
            f"verify-1-2: commit {side[:7]} is not merged",
            "verify-1-3: still running"]))
        self.assertEqual(self.named(events, "removed"), [])
        self.assertEqual(self.worktree_state()[2], ["task-1", "verify-1-1", "verify-1-2", "verify-1-3"])
        self.assertIn("worktree-verify-1-2", self.worktree_state()[1])
        self.assertEqual(self.calls("rm"), [])
        self.no_force()

    def test_70_an_ignored_file_does_not_keep_a_folder(self):
        self.commit_file(".gitignore", "build/\n")
        task = self.merged_task()
        wt = self.worktree("task-1")
        os.makedirs(os.path.join(wt, "build"))
        with open(os.path.join(wt, "build", "out.bin"), "w") as fh:
            fh.write("x\n")
        self.assertEqual(self.git("status", "--porcelain", cwd=wt), "")
        self.agents(self.finished("task-1"))
        self.rows_only("sess-task-1-1")
        events = self.events("merged", str(task))
        self.assertEqual(len(self.named(events, "removed")), 2)
        self.assertEqual(self.worktree_state()[2], [])

    def test_70_pr_mode_a_head_equal_to_pushed_is_merged_after_a_squash(self):
        self.pr_config()
        wt = self.worktree("task-1")
        pushed = self.wt_commit(wt)  # a squash merge leaves this commit out of main
        extra = self.worktree("verify-1-1")
        later = self.wt_commit(extra, "later.txt")
        task = self.merged_task(pushed=pushed)
        self.assertNotEqual(self.git("merge-base", "HEAD", pushed), pushed)
        self.agents(self.finished("task-1"), self.finished("verify-1-1"))
        self.rows_only("sess-task-1-1", "sess-verify-1-1")
        events = self.events("merged", str(task))
        self.assertEqual([e["detail"] for e in self.named(events, "removed") if e["session"] is None],
                         [f"worktree task-1 (merged at {pushed[:7]})"])
        self.assertEqual([e["detail"] for e in self.named(events, "kept")], [f"verify-1-1: commit {later[:7]} is not merged"])
        self.assertEqual(self.worktree_state()[2], ["verify-1-1"])
        self.assertNotIn("worktree-task-1", self.worktree_state()[1])
        self.assertIn("worktree-verify-1-1", self.worktree_state()[1])

    def test_70_a_branch_whose_tip_is_not_merged_stays_when_the_folder_goes(self):
        task = self.merged_task()
        wt = self.worktree("task-1")
        tip = self.wt_commit(wt)
        self.git("checkout", "-q", "--detach", "HEAD~1", cwd=wt)  # the folder is at a merged commit; the branch is not
        self.agents(self.finished("task-1"))
        self.rows_only("sess-task-1-1")
        events = self.events("merged", str(task))
        self.assertEqual(len(self.named(events, "removed")), 2)
        self.assertEqual([e["detail"] for e in self.named(events, "kept")],
                         [f"worktree-task-1: branch stays, commit {tip[:7]} is not merged"])
        self.assertEqual(self.worktree_state()[1].split()[-1], "worktree-task-1")

    def test_70_git_refusing_the_removal_keeps_the_folder_and_its_lock_without_force(self):
        sub = os.path.join(self.dir, "sub")
        os.makedirs(sub)
        self.git("init", "-q", "-b", "main", cwd=sub)
        self.git("commit", "-q", "--allow-empty", "-m", "s", cwd=sub)
        self.git("-c", "protocol.file.allow=always", "submodule", "add", "-q", sub, "libs")
        self.git("commit", "-q", "-m", "add libs")
        task = self.merged_task()
        wt = self.worktree("task-1")
        self.git("-c", "protocol.file.allow=always", "submodule", "update", "--init", "-q", cwd=wt)
        reason = self.claude_lock("task-1", self.dead_pid())
        self.assertEqual(self.git("status", "--porcelain", cwd=wt), "")
        self.agents(self.finished("task-1"))
        self.rows_only("sess-task-1-1")
        events = self.events("merged", str(task))
        (kept,) = self.named(events, "kept")
        self.assertEqual(kept["detail"], "task-1: git worktree remove said: fatal: working trees containing submodules "
                                         "cannot be moved or removed")
        self.assertEqual(self.named(events, "removed")[-1]["session"], "sess-task-1-1")
        self.assertTrue(os.path.isdir(wt))
        self.assertIn("locked " + reason, self.git("worktree", "list", "--porcelain"))
        self.assertIn("worktree-task-1", self.worktree_state()[1])
        self.no_force()

    def test_70_record_sweeps_a_merged_task_closed_before_0_7_0(self):
        task = self.merged_task(sessions=False)
        self.worktree("task-1-2")
        self.worktree("verify-1-1")
        self.agents()
        events = self.events("record")
        self.assertEqual(sorted(e["detail"] for e in self.named(events, "removed")),
                         [f"worktree task-1-2 (merged at {self.short()})", f"worktree verify-1-1 (merged at {self.short()})"])
        self.assertEqual(self.worktree_state(), (1, "", []))
        again = self.events("record")
        self.assertEqual((self.named(again, "removed"), self.named(again, "kept")), ([], []))
        self.assertEqual(task, 1)

    def test_70_record_with_nothing_to_remove_calls_no_claude_rm(self):
        self.merged_task()
        self.agents()
        events = self.events("record")
        self.assertEqual((self.named(events, "removed"), self.named(events, "kept")), ([], []))
        self.assertEqual(self.calls("rm"), [])

    def test_70_a_done_task_that_is_not_merged_keeps_its_worktree(self):
        task = self.closed_task()
        wt = self.worktree("task-1")
        self.agents(self.finished("task-1"))
        events = self.events("record")
        self.assertEqual(self.one(events, "unmerged")["task"], task)
        self.assertEqual((self.named(events, "removed"), self.named(events, "kept")), ([], []))
        self.assertTrue(os.path.isdir(wt))
        self.assertEqual(self.calls("rm"), [])

    # --- review fixes: what counts as merged, locks, processes, repeated lines

    def dead_pid(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        return child.pid

    def claude_lock(self, folder, pid):
        reason = f"claude session {folder} (pid {pid} start 2026-10-28T10:00:00)"
        self.git("worktree", "lock", "--reason", reason, self.wt_path(folder))
        return reason

    def closed_at(self, tip, merged=False, **meta):
        """A done task whose verified commit is `tip`, local mode."""
        task = self.add_task(attempt=1, verdict_ref=tip, verdict="test-verified", sessions="[]", **meta)
        if merged:
            self.tg("edit", str(task), "--meta", 'merged_at="2026-10-26 10:00 UTC"', "merged_by=operator")
        self.tg("done", str(task))
        return task

    def test_72_a_detached_head_at_the_task_tip_does_not_make_it_merged(self):
        wt = self.worktree("task-1")
        tip = self.wt_commit(wt)
        task = self.closed_at(tip)
        self.git("checkout", "-q", "--detach", tip)
        self.agents(self.finished("task-1"))
        events = self.events("record")
        self.assertEqual(self.one(events, "unmerged")["task"], task)
        self.assertEqual(self.named(events, "merged"), [])
        self.assertNotIn("merged_at", self.meta(task))
        self.assertEqual((self.named(events, "removed"), self.named(events, "kept")), ([], []))
        self.assertTrue(os.path.isdir(wt))
        self.assertIn("worktree-task-1", self.worktree_state()[1])
        self.assertEqual(self.calls("rm"), [])

    def test_72_a_feature_branch_that_holds_the_tip_is_not_the_target(self):
        self.write_config('[merge]\nbase = "main"\n')
        wt = self.worktree("task-1")
        tip = self.wt_commit(wt)
        task = self.closed_at(tip)
        self.git("checkout", "-q", "-b", "feature", tip)
        self.agents(self.finished("task-1"))
        events = self.events("record")
        self.assertEqual(self.one(events, "unmerged")["task"], task)
        self.assertNotIn("merged_at", self.meta(task))
        self.assertTrue(os.path.isdir(wt))
        self.write_config()  # no merge.base: the branch the main checkout is on is the target, and it holds the tip
        events = self.events("record")
        self.assertEqual(self.one(events, "merged")["task"], task)
        self.assertEqual(self.worktree_state()[2], [])

    def test_72_a_local_squash_merge_leaves_no_ancestor_so_the_verified_change_counts(self):
        wt = self.worktree("task-1")
        tip = self.wt_commit(wt, "feature.txt", "work\n")
        self.git("merge", "--squash", "-q", "worktree-task-1")
        self.git("commit", "-q", "-m", "squash task 1")
        self.assertNotEqual(self.git("merge-base", "HEAD", tip), tip)
        same = self.worktree("verify-1-1", base=tip)
        self.git("commit", "-q", "--amend", "-m", "same change, other message", cwd=same)
        copy = self.git("rev-parse", "HEAD", cwd=same)
        self.assertNotEqual(copy, tip)
        more = self.worktree("verify-1-2", base=tip)
        extra = self.wt_commit(more, "more.txt")
        task = self.closed_at(tip, merged=True)
        self.agents()
        events = self.events("record")
        self.assertEqual(sorted(e["detail"] for e in self.named(events, "removed")),
                         [f"worktree task-1 (merged at {tip[:7]})", f"worktree verify-1-1 (merged at {copy[:7]})"])
        self.assertEqual([e["detail"] for e in self.named(events, "kept")], [f"verify-1-2: commit {extra[:7]} is not merged"])
        self.assertEqual(self.worktree_state()[2], ["verify-1-2"])
        self.assertEqual(task, 1)

    def test_72_pr_mode_does_not_trust_the_main_checkouts_head(self):
        self.pr_config()
        self.fake_host()
        wt = self.worktree("task-1")
        tip = self.wt_commit(wt)
        self.git("merge", "--ff-only", "-q", "worktree-task-1")  # the operator's checkout holds the tip; the request did not
        task = self.merged_task(pushed=self.git("rev-parse", "HEAD~1"))
        self.agents(self.finished("task-1"))
        self.rows_only("sess-task-1-1")
        events = self.events("merged", str(task))
        self.assertEqual([e["detail"] for e in self.named(events, "kept")], [f"task-1: commit {tip[:7]} is not merged"])
        self.assertTrue(os.path.isdir(wt))

    def test_72_a_pushed_head_that_is_not_in_this_clone_says_to_fetch(self):
        self.pr_config()
        self.fake_host()
        wt = self.worktree("task-1")
        self.wt_commit(wt)
        task = self.merged_task(pushed="f" * 40)
        self.agents(self.finished("task-1"))
        self.rows_only("sess-task-1-1")
        events = self.events("merged", str(task))
        self.assertEqual([e["detail"] for e in self.named(events, "kept")],
                         ["task-1: pushed head fffffff is not in this clone; fetch origin/task-1"])
        self.assertTrue(os.path.isdir(wt))

    def test_73_only_the_lock_of_an_ended_claude_session_is_released(self):
        task = self.merged_task(self.entry(1, 1))
        operator, live, ended = (self.worktree(f"verify-1-{n}") for n in (1, 2, 3))
        self.git("worktree", "lock", "--reason", "do not touch", operator)
        self.claude_lock("verify-1-2", os.getpid())
        reason = self.claude_lock("verify-1-3", self.dead_pid())
        self.agents()
        events = self.events("merged", str(task))
        self.assertEqual(sorted(e["detail"] for e in self.named(events, "kept")), [
            "verify-1-1: locked (do not touch)",
            f"verify-1-2: still running (pid {os.getpid()} holds its lock)"])
        self.assertEqual([e["detail"] for e in self.named(events, "removed")],
                         [f"worktree verify-1-3 (merged at {self.short()})"])
        self.assertEqual(self.worktree_state()[2], ["verify-1-1", "verify-1-2"])
        listing = self.git("worktree", "list", "--porcelain")
        self.assertIn("locked do not touch", listing)
        self.assertNotIn(reason, listing)
        self.no_force()

    def test_73_a_lock_that_names_another_folder_is_not_claudes_for_this_one(self):
        task = self.merged_task()
        self.worktree("task-1")
        self.git("worktree", "lock", "--reason", f"claude session task-2 (pid {self.dead_pid()} start x)", self.wt_path("task-1"))
        self.agents()
        events = self.events("merged", str(task))
        (kept,) = self.named(events, "kept")
        self.assertTrue(kept["detail"].startswith("task-1: locked (claude session task-2 "), kept)
        self.assertTrue(os.path.isdir(self.wt_path("task-1")))

    def test_74_a_process_with_its_working_directory_in_the_folder_keeps_it(self):
        if not shutil.which("lsof"):
            self.skipTest("lsof is not installed")
        task = self.merged_task()
        wt = self.worktree("task-1")
        child = subprocess.Popen(["sleep", "30"], cwd=wt)
        self.addCleanup(lambda: (child.kill(), child.wait()))
        self.agents()
        events = self.events("merged", str(task))
        self.assertEqual([e["detail"] for e in self.named(events, "kept")], [f"task-1: process {child.pid} (sleep) uses it"])
        self.assertTrue(os.path.isdir(wt))
        child.kill()
        child.wait()
        events = self.events("merged", str(task))
        self.assertEqual(len(self.named(events, "removed")), 1)
        self.assertFalse(os.path.exists(wt))

    def test_74_without_lsof_the_process_check_is_skipped(self):
        task = self.merged_task()
        wt = self.worktree("task-1")
        bare = os.path.join(self.dir, "bare")  # python and git only: no lsof
        os.makedirs(bare)
        os.symlink(shutil.which("git"), os.path.join(bare, "git"))
        os.symlink(sys.executable, os.path.join(bare, "python3"))
        os.symlink(os.path.join(self.bin, "claude"), os.path.join(bare, "claude"))
        env = dict(self.env, PATH=bare)
        self.agents()
        out = self.run_cmd("merged", str(task), pre=["--json"], env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(len(self.named(json.loads(out.stdout), "removed")), 1)
        self.assertFalse(os.path.exists(wt))

    def test_74_the_session_list_is_read_again_before_the_folders_go(self):
        task = self.merged_task(self.entry(1, 1))
        wt = self.worktree("task-1")
        self.agents(self.finished("task-1", 1))
        self.rows_only("sess-task-1-1")
        with open(os.path.join(self.dir, "after.json"), "w") as fh:
            fh.write("[" + json.dumps(self.row("task-1", 2)) + "]")
        env = dict(self.env, FAKE_CLAUDE_AFTER_RM=os.path.join(self.dir, "after.json"))
        out = self.run_cmd("merged", str(task), pre=["--json"], env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        events = json.loads(out.stdout)
        self.assertEqual([e["detail"] for e in self.named(events, "kept")], ["task-1: still running"])
        self.assertTrue(os.path.isdir(wt))

    def test_75_a_kept_line_is_repeated_by_record_only_when_its_reason_changes(self):
        task = self.merged_task()
        wt = self.worktree("task-1")
        with open(os.path.join(wt, "a.txt"), "w") as fh:
            fh.write("x\n")
        self.agents()
        first = self.events("record")
        self.assertEqual([e["detail"] for e in self.named(first, "kept")], ["task-1: uncommitted changes (?? a.txt)"])
        self.assertEqual(self.meta(task)["cleanup_kept"], {"task-1": "uncommitted changes (?? a.txt)"})
        self.assertEqual(self.named(self.events("record"), "kept"), [])
        with open(os.path.join(wt, "b.txt"), "w") as fh:
            fh.write("y\n")
        changed = self.events("record")
        self.assertEqual([e["detail"] for e in self.named(changed, "kept")], ["task-1: uncommitted changes (?? a.txt, ?? b.txt)"])
        merged = self.events("merged", str(task))  # an explicit run.py merged always says it
        self.assertEqual(len(self.named(merged, "kept")), 1)
        os.remove(os.path.join(wt, "a.txt"))
        os.remove(os.path.join(wt, "b.txt"))
        removed = self.events("record")
        self.assertEqual(len(self.named(removed, "removed")), 1)
        self.assertEqual(self.meta(task)["cleanup_kept"], {})

    def test_76_the_removed_line_counts_the_ignored_files_it_took_with_the_folder(self):
        self.commit_file(".gitignore", "*.log\nbuild/\n")
        task = self.merged_task()
        wt = self.worktree("task-1")
        for n in range(6):
            with open(os.path.join(wt, f"f{n}.log"), "w") as fh:
                fh.write("x\n")
        self.agents()
        events = self.events("merged", str(task))
        self.assertEqual(self.one(events, "removed")["detail"],
                         f"worktree task-1 (merged at {self.short()}) (ignored files removed: 6: "
                         "f0.log, f1.log, f2.log, f3.log, f4.log, ...)")

    # --- merge.remove_worktrees = false

    def test_71_remove_worktrees_false_removes_nothing_and_says_so_once(self):
        self.write_config("[merge]\nremove_worktrees = false\n")
        task = self.merged_task(self.entry(1, 1))
        self.worktree("task-1")
        self.worktree("verify-1-1")
        self.agents(self.finished("task-1"), self.finished("verify-1-1"))
        events = self.events("merged", str(task))
        self.assertEqual(sorted(e["detail"] for e in self.named(events, "kept")),
                         ["task-1: merge.remove_worktrees is false", "verify-1-1: merge.remove_worktrees is false"])
        self.assertEqual(self.named(events, "removed"), [])
        self.assertEqual(self.calls("rm"), [])
        self.assertEqual(self.worktree_state()[2], ["task-1", "verify-1-1"])
        self.assertEqual(self.worktree_state()[0], 3)
        later = self.events("record")
        self.assertEqual((self.named(later, "kept"), self.named(later, "removed")), ([], []))
        self.assertEqual(self.calls("rm"), [])
        self.assertEqual(self.worktree_state()[2], ["task-1", "verify-1-1"])

    def test_71_remove_worktrees_false_at_a_merge_by_close(self):
        self.write_config("[merge]\nremove_worktrees = false\n")
        task = self.running_task()
        wt, _ = self.pass_report(task)
        self.agents(self.finished("task-1"))
        self.orders("MERGE: verified branches into main\n")
        events = self.events("close", str(task), "--verdict", "test-verified")
        self.assertEqual(self.one(events, "merged")["task"], task)
        self.assertEqual([e["detail"] for e in self.named(events, "kept")], ["task-1: merge.remove_worktrees is false"])
        self.assertTrue(os.path.isdir(wt))
        self.assertEqual(self.calls("rm"), [])

    def test_71_remove_worktrees_true_is_the_default(self):
        self.write_config("[merge]\nremove_worktrees = true\n")
        task = self.merged_task()
        self.worktree("task-1")
        self.agents(self.finished("task-1"))
        self.rows_only("sess-task-1-1")
        events = self.events("merged", str(task))
        self.assertEqual(len(self.named(events, "removed")), 2)
        self.assertEqual(self.worktree_state()[2], [])

    # --- review fixes

    def test_53_a_row_that_a_refused_rm_left_behind_is_finished_not_running(self):
        task = self.add_task(attempt=1, verdict_ref=SHA_A, merged_at="x", merged_by="operator",
                             sessions=json.dumps([self.entry(1, 1)]))
        self.tg("done", str(task))
        wt = self.worktree("task-1")
        head = self.git("rev-parse", "HEAD")
        side = self.wt_commit(wt)
        # What claude 2.1.311 lists after a refused `claude rm`: the session ended; no status, no pid, the repo root.
        left = {"id": "sess-task-1-1", "name": "task-1-1", "cwd": self.root, "state": "done"}
        self.agents(left)

        def table(commit):
            with open(self.rm_file, "w") as fh:
                json.dump({"sess-task-1-1": {"exit": 1, "stderr": f"unpushed commits; pass --discard-unpushed {commit}@wt-1"}}, fh)

        table(side)
        self.assertEqual(self.one(self.events("record"), "slots")["detail"], "0/2 live")
        events = self.events("merged", str(task))
        self.assertEqual([e["detail"] for e in self.named(events, "kept")], [f"task-1: commit {side[:7]} is not merged"])
        self.assertTrue(os.path.isdir(wt))
        self.git("reset", "-q", "--hard", head, cwd=wt)  # now the commit is merged: the owner's rm may discard it
        table(head)
        events = self.events("merged", str(task))
        self.assertNotIn("still running", json.dumps(events))
        self.assertIn("discarded", self.one(events, "removed")["detail"])
        self.assertEqual(self.calls("rm")[-1], ["rm", "sess-task-1-1", "--discard-unpushed", f"{head}@wt-1"])
        for row in ({"state": "done", "status": "busy"}, {"state": "blocked", "status": "idle"}):
            self.agents({**left, **row})  # a busy or asking session is still live
            self.assertEqual(self.one(self.events("record"), "slots")["detail"], "1/2 live")

    def stopped_for_commit(self, task=None):
        task = task or self.running_task()
        self.add_result(task, "STOPPED", "Session: s\nWorktree: w\nBranch: b\nStopped: now\nFiles: x\n", by="manager")
        return task

    def test_36_a_plain_folder_in_place_of_the_worktree_commits_nothing_to_main(self):
        task = self.stopped_for_commit()
        plain = self.wt_path("task-1")
        os.makedirs(plain)
        with open(os.path.join(self.root, "mine.txt"), "w") as fh:
            fh.write("the operator's file\n")
        before = self.git("rev-parse", "HEAD")
        stopped = self.one(self.events("record"), "stopped")
        self.assertIn("folder .claude/worktrees/task-1 is a plain folder, not a git worktree; move or delete it yourself",
                      stopped["detail"])
        self.assertEqual(self.git("rev-parse", "HEAD"), before)
        self.assertEqual(self.git("status", "--porcelain"), "?? mine.txt")
        self.assertIn("Head: None", self.results(task)[-1]["body"])
        self.assertEqual(len(self.named(self.events("record"), "stopped")), 1)

    def test_36_a_worktree_off_its_branch_is_never_committed_to(self):
        for how in ("branch", "detached"):
            with self.subTest(how):
                self.fresh()
                task = self.stopped_for_commit()
                wt = self.worktree("task-1")
                head = self.git("rev-parse", "HEAD", cwd=wt)
                if how == "branch":
                    self.git("switch", "-q", "-c", "elsewhere", cwd=wt)
                else:
                    self.git("checkout", "-q", "--detach", cwd=wt)
                with open(os.path.join(wt, "wip.txt"), "w") as fh:
                    fh.write("half\n")
                stopped = self.one(self.events("record"), "stopped")
                self.assertIn("is on elsewhere, not worktree-task-1" if how == "branch"
                              else f"is on a detached HEAD at {head[:7]}, not worktree-task-1", stopped["detail"])
                self.assertIn("nothing committed", stopped["detail"])
                self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt), head)
                self.assertEqual(self.git("status", "--porcelain", cwd=wt), "?? wip.txt")
                self.assertIn("Head: None", self.results(task)[-1]["body"])

    def test_23_a_detached_worktree_gets_a_fix_that_keeps_its_commits(self):
        task, wt, head = self.retry_ready()
        self.git("checkout", "-q", "--detach", cwd=wt)
        moved = self.wt_commit(wt, "more.txt")
        out = self.run_cmd("launch", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn(f"is on a detached HEAD at {moved[:7]}, which holds worktree-task-1 (at {head[:7]}); "
                      "run git -C .claude/worktrees/task-1 switch -C worktree-task-1 (this keeps the commits)", out.stderr)
        self.git("switch", "-C", "worktree-task-1", cwd=wt)  # the suggested command
        self.assertEqual(self.git("rev-parse", "worktree-task-1"), moved)
        self.ok("launch", str(task))
        # A detached commit that is not built on the branch: no switch is suggested.
        self.agents(self.finished("task-1", 2))
        self.add_result(task, "ISSUES", f"Task: 1\nStatus: ISSUES\nBranch: worktree-task-1\nHead: {moved}\n", attempt=2)
        self.git("checkout", "-q", "--detach", "HEAD~2", cwd=wt)
        side = self.wt_commit(wt, "side.txt")
        out = self.run_cmd("launch", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn(f"detached HEAD at {side[:7]}, which is not built on worktree-task-1 (at {moved[:7]})", out.stderr)
        self.assertIn(f"git -C .claude/worktrees/task-1 branch <name> {side[:7]}", out.stderr)
        self.assertNotIn("switch -C", out.stderr)
        self.assertEqual(self.git("rev-parse", "worktree-task-1"), moved)

    def test_36_an_unrecorded_row_is_recorded_for_the_attempt_it_was_filed_for(self):
        task = self.running_task(sessions=[])
        self.agents(self.finished("task-1"))
        self.one(self.events("record"), "died")
        entry = {"id": "sess-task-1-1", "kind": "task", "attempt": 1, "name": "task-1", "worktree": "task-1"}
        self.assertEqual(self.meta(task)["sessions"], [entry])
        self.tg("edit", str(task), "--meta", "attempt=2")  # a later attempt must not inherit the old row
        died = self.one(self.events("record"), "died")
        self.assertEqual((died["attempt"], died["session"]), (2, None))
        self.assertIn("no session recorded for attempt 2", self.results(task)[-1]["body"])
        stuck_task = self.running_task(sessions=[])
        self.agents(self.row("task-2", status="waiting", waitingFor="a permission"))
        self.one(self.events("record"), "stuck")
        self.assertEqual([e["id"] for e in self.meta(stuck_task)["sessions"]], ["sess-task-2-1"])

    def test_23_a_locked_stale_registration_gets_the_unlock_fix(self):
        task, wt, head = self.retry_ready()
        self.git("worktree", "lock", "--reason", "claude session task-1-1 (pid 1)", wt)
        shutil.rmtree(wt)
        out = self.run_cmd("launch", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("stale worktree registration that is locked; run git worktree unlock .claude/worktrees/task-1, "
                      "then git worktree prune, then rerun", out.stderr)
        self.assertNotIn("fatal", out.stderr)
        other = self.add_task()
        self.add_result(other, "ISSUES", "Task: 2\n")  # unrelated; the first attempt of task 2 meets a locked stale folder
        stale = self.worktree("task-2")
        self.git("worktree", "lock", "--reason", "claude session task-2-1 (pid 1)", stale)
        shutil.rmtree(stale)
        out = self.run_cmd("launch", str(other))
        self.assertEqual(out.returncode, 2)
        self.assertLess(out.stderr.index("`git worktree unlock .claude/worktrees/task-2`"),
                        out.stderr.index("`git worktree prune`"))

    def test_23_a_base_on_a_retry_whose_branch_remains_says_how_much_is_on_it(self):
        task, wt, head = self.retry_ready()
        self.git("worktree", "remove", "-f", wt)
        base = self.git("rev-parse", "main")
        out = self.run_cmd("launch", str(task), "--base", "main")
        self.assertEqual(out.returncode, 2)
        self.assertIn(f"continues on branch worktree-task-1 at {head[:7]} and holds 1 commit beyond {base[:7]}; "
                      "--base applies to a first attempt.", out.stderr)
        self.assertIn("git branch -D worktree-task-1, then rerun with --base.", out.stderr)

    def test_23_the_base_hint_names_the_pushed_branch_in_pr_mode_only(self):
        task = self.running_task()
        self.add_result(task, "ISSUES", "Task: 1\nStatus: ISSUES\n")
        text = "pass --base <sha|branch>"
        self.assertTrue(self.run_cmd("launch", str(task)).stderr.rstrip().endswith(text))
        self.pr_config()
        self.fake_host()
        out = self.run_cmd("launch", str(task))
        self.assertIn(f"{text} (in pr mode, --base replaces the pushed branch task-1)", out.stderr)



class PrTest(Base):
    """merge.mode = "pr": close pushes and opens the request, record merges it. Each test runs for gh and glab."""

    @property
    def ci(self):
        return "ci.yml" if self.host == "github" else "pipeline"

    def published(self, **meta):
        """A task that passed, was closed, and was pushed with an open request (state UNKNOWN)."""
        task, wt, head = self.pr_task(**meta)
        self.fake_host(head=head, merge_state="UNKNOWN")
        self.ok("close", str(task), "--verdict", "test-verified", "--ran", "make test")
        return task, wt, head

    def advance_main(self, name="moved.txt", text="x\n"):
        clone = os.path.join(self.dir, "clone")
        if not os.path.isdir(clone):
            subprocess.run(["git", "clone", "-q", self.origin, clone], check=True)
            for key, value in (("user.name", "t"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
                self.git("config", key, value, cwd=clone)
        else:
            self.git("pull", "-q", "origin", "main", cwd=clone)
        with open(os.path.join(clone, name), "w") as fh:
            fh.write(text)
        self.git("add", "-A", cwd=clone)
        self.git("commit", "-q", "-m", f"main: {name}", cwd=clone)
        self.git("push", "-q", "origin", "main", cwd=clone)
        return self.git("rev-parse", "HEAD", cwd=clone)

    # --- close and publish

    @both_hosts
    def test_80_close_pushes_and_opens_the_request_and_record_merges_it_under_the_merge_line(self):
        task, wt, head = self.pr_task()
        self.fake_host(head=head, merge_state="UNKNOWN")
        before = self.checkout()
        events = self.events("close", str(task), "--verdict", "test-verified", "--ran", "make test")
        for name in ("closed", "published", "pr-pending"):
            self.one(events, name)
        self.assertIn(f"{self.label()} ", self.one(events, "published")["detail"])
        self.assertIn(f"head {head[:7]} on origin/task-1, base main", self.one(events, "published")["detail"])
        self.assertEqual(self.remote_sha(), head)
        meta = self.meta(task)
        self.assertEqual((meta["pr"], meta["pr_branch"], meta["pushed"]), (1, "task-1", head))
        self.assertEqual(self.status_of(task), "done")
        self.assertEqual(self.merges(), "")
        self.assertEqual(self.checkout(), before)
        (create,) = self.create_calls()
        if self.host == "github":
            self.assertEqual(create[:7], ["pr", "create", "--head", "task-1", "--base", "main", "--title"])
            self.assertIn("(task #1)", create[7])
            self.assertIn("Taskgraph #1: Sweep domains", self.host_stdin()[0]["stdin"])
        else:
            for field in ("source_branch=task-1", "target_branch=main", "remove_source_branch=false"):
                self.assertIn(field, create)
        request = "#1" if self.host == "github" else "!1"
        self.assertRegex(self.status_sections()["Done, branch not merged"], rf"{head}\s*\|\s*{re.escape(request)}\s*\|")
        self.fake_host(head=head, merge_state="BLOCKED", checks=("pass", "fail"))
        blocked = self.one(self.events("record"), "pr-blocked")
        self.assertIn("1 fail" if self.host == "github" else "pipeline failed", blocked["detail"])
        self.fake_host(head=head, merge_state="CLEAN")
        ready = self.one(self.events("record"), "ready-to-merge")
        self.assertEqual(ready["detail"], f"{self.label()} is clean")
        self.assertEqual(self.merge_calls(), [])
        self.orders("# Standing orders\n\n1. MERGE: verified branches into main\n")
        self.fake_host(head=head, merge_state="CLEAN", then={"state": "MERGED", "merge_commit": "c" * 40})
        events = self.events("record")
        self.assertEqual(self.one(events, "merged")["detail"], f"{self.label()} merged (merge) at {'c' * 40}")
        (call,) = self.merge_calls()
        if self.host == "github":
            self.assertEqual(call, ["pr", "merge", "1", "--merge", "--match-head-commit", head])
        else:
            self.assertEqual(call, ["api", "-X", "PUT", f"projects/{self.project}/merge_requests/1/merge", "-f", f"sha={head}",
                                    "-f", "should_remove_source_branch=false"])
        meta = self.meta(task)
        self.assertEqual(meta["merged_by"], "manager")
        self.assertIn("merged_at", meta)
        self.assertIn(["rm", "sess-task-1-1"], self.calls("rm"))
        self.assertEqual(self.merges(), "")

    def merge_method(self, method):
        self.pr_config(f'method = "{method}"\n')
        task = self.running_task(base=json.dumps(self.git("rev-parse", "HEAD")))
        wt, head = self.pass_report(task)
        self.agents(self.finished("task-1"))
        self.fake_host(head=head, merge_state="UNKNOWN")
        self.ok("close", str(task), "--verdict", "test-verified")
        self.orders("MERGE: verified branches into main\n")
        self.fake_host(head=head, merge_state="CLEAN", then={"state": "MERGED", "merge_commit": "c" * 40})
        self.assertIn(f"merged ({method})", self.one(self.events("record"), "merged")["detail"])
        (call,) = self.merge_calls()
        return call, head

    @both_hosts
    def test_80_method_squash(self):
        call, head = self.merge_method("squash")
        self.assertIn("--squash" if self.host == "github" else "squash=true", call)
        self.assertNotIn("--merge", call)

    @both_hosts
    def test_80_method_rebase(self):
        call, head = self.merge_method("rebase")
        if self.host == "github":
            self.assertIn("--rebase", call)
        else:
            self.assertNotIn("squash=true", call)

    @both_hosts
    def test_81_stop_blocks_the_merge_and_a_failed_merge_changes_nothing(self):
        task, wt, head = self.published()
        before = self.checkout()
        self.orders("STOP: paused\nMERGE: verified branches into main\n")
        self.fake_host(head=head, merge_state="CLEAN")
        ready = self.one(self.events("record"), "ready-to-merge")
        self.assertEqual(ready["detail"], f"{self.label()} is clean; not merged during a pause")
        self.assertEqual(self.merge_calls(), [])
        self.orders("MERGE: verified branches into main\n")
        self.fake_host(head=head, merge_state="CLEAN", merge="Pull request is not mergeable")
        failed = self.one(self.events("record"), "merge-failed")
        self.assertEqual(failed["detail"], f"{self.label()}: Pull request is not mergeable")
        self.assertIn("run.py record", failed["next"])
        self.assertEqual(len(self.merge_calls()), 1)
        self.assertNotIn("merged_at", self.meta(task))
        self.assertEqual(self.checkout(), before)

    @both_hosts
    def test_82_a_merge_by_someone_else_is_recorded_and_its_commits_may_be_discarded(self):
        self.pr_config()
        task = self.running_task(base=json.dumps(self.git("rev-parse", "HEAD")))
        wt = self.worktree("task-1")
        first = self.wt_commit(wt, "a.txt")
        head = self.wt_commit(wt, "b.txt")
        self.pass_report(task, wt=wt, head=head)
        self.agents(self.finished("task-1"))
        self.fake_host(head=head, merge_state="UNKNOWN")
        before = self.checkout()
        self.ok("close", str(task), "--verdict", "test-verified")
        self.fake_host(head=head, state="MERGED", merge_state="UNKNOWN", merge_commit="c" * 40)
        with open(self.rm_file, "w") as fh:
            json.dump({"sess-task-1-1": {"exit": 1, "stderr": f"unpushed commits; pass --discard-unpushed {first}@wt-1"}}, fh)
        events = self.events("record")
        self.assertEqual(self.one(events, "merged")["detail"], f"{self.label()} merged at {'c' * 40}; recorded merged_by=operator")
        meta = self.meta(task)
        self.assertEqual((meta["merged_by"], meta["pushed"]), ("operator", head))
        self.assertIn("merged_at", meta)
        self.assertIn("discarded", self.one(events, "removed")["detail"])
        self.assertEqual(self.calls("rm"), [["rm", "sess-task-1-1"], ["rm", "sess-task-1-1", "--discard-unpushed", f"{first}@wt-1"]])
        self.assertEqual(self.merge_calls(), [])
        self.assertEqual(self.checkout(), before)

    @both_hosts
    def test_82_a_commit_outside_the_merged_head_is_kept(self):
        task, wt, head = self.published()
        self.git("checkout", "-q", "-b", "side")
        side = self.commit_side("side.txt")
        self.git("checkout", "-q", "main")
        self.fake_host(head=head, state="MERGED", merge_state="UNKNOWN")
        with open(self.rm_file, "w") as fh:
            json.dump({"sess-task-1-1": {"exit": 1, "stderr": f"unpushed commits; pass --discard-unpushed {side}@wt-1"}}, fh)
        events = self.events("record")
        self.one(events, "merged")
        self.assertEqual([e["detail"] for e in self.named(events, "kept")],
                         [f"task-1: claude rm said: unpushed commits; pass --discard-unpushed {side}@wt-1"])
        # The folder's HEAD is the merged head, so git removes the folder; the commit that is not merged is never discarded.
        self.assertEqual(self.one(events, "removed")["detail"], f"worktree task-1 (merged at {head[:7]})")
        self.assertEqual(self.calls("rm"), [["rm", "sess-task-1-1"], ["rm", "sess-task-1-1"]])

    def commit_side(self, name):
        with open(os.path.join(self.root, name), "w") as fh:
            fh.write("side\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", name)
        return self.git("rev-parse", "HEAD")

    def test_82_gitlab_merge_commit_falls_back_to_the_squash_commit_then_the_head(self):
        self.host = "gitlab"
        for fields, wanted in (({"merge_commit": "m" * 40, "squash_commit": "s" * 40}, "m" * 40),
                               ({"squash_commit": "s" * 40}, "s" * 40), ({}, None)):
            with self.subTest(fields=fields):
                self.fresh()
                task, wt, head = self.published()
                self.fake_host(head=head, state="MERGED", merge_state="UNKNOWN", **fields)
                self.assertIn(f"merged at {wanted or head};", self.one(self.events("record"), "merged")["detail"])

    @both_hosts
    def test_83_closed_draft_conflicting_and_moved_requests(self):
        task, wt, head = self.published()
        before = self.checkout()
        self.orders("MERGE: verified branches into main\n")
        self.fake_host(head=head, state="CLOSED")
        closed = self.one(self.events("record"), "pr-closed")
        self.assertEqual(closed["detail"], f"{self.label()} closed without a merge")
        self.assertIn(f'tg add "{self.label()} for #1 was closed: redo or drop?" --type decision --meta decider=operator', closed["next"])
        self.fake_host(head=head, merge_state="DRAFT")
        self.assertEqual(self.one(self.events("record"), "pr-draft")["detail"], f"{self.label()} is a draft")
        self.fake_host(head=head, merge_state="DIRTY")
        conflict = self.one(self.events("record"), "conflict")
        self.assertEqual(conflict["detail"], f"{self.label()} conflicts with main")
        self.assertIn("--type decision", conflict["next"])
        self.fake_host(head="e" * 40, merge_state="CLEAN")
        changed = self.one(self.events("record"), "pr-changed")
        self.assertIn(f"head is {'e' * 7}, not the pushed {head[:7]}; not merged by run.py", changed["detail"])
        self.assertIn("run.py merged 1 --by operator", changed["next"])
        self.assertEqual(self.merge_calls(), [])
        self.assertNotIn("merged_at", self.meta(task))
        self.assertEqual(self.checkout(), before)

    # --- the request is behind its target

    @both_hosts
    def test_84_a_behind_request_is_rebased_in_its_worktree_and_pushed_under_the_lease(self):
        task, wt, head = self.published()
        self.fake_host(head=head, merge_state="BEHIND")
        behind = self.one(self.events("record"), "pr-behind")
        self.assertEqual(behind["detail"], f"{self.label()} is behind main")
        self.assertIn("run.py close 1", behind["next"])
        moved = self.advance_main()
        before = self.checkout()
        events = self.events("close", str(task))
        new = self.git("rev-parse", "HEAD", cwd=wt)
        self.assertNotEqual(new, head)
        self.assertIn(f"onto origin/main at {new[:7]}; same change as {head[:7]}", self.one(events, "rebased")["detail"])
        self.assertIn(f"{new[:7]} to origin/task-1", self.one(events, "pushed")["detail"])
        self.assertEqual(self.git("merge-base", new, moved), moved)
        meta = self.meta(task)
        self.assertEqual((meta["verdict_ref"], meta["pushed"]), (new, new))
        self.assertEqual(self.remote_sha(), new)
        self.assertEqual(self.checkout(), before)

    @both_hosts
    def test_84_a_rebase_conflict_is_aborted(self):
        self.commit_file("f.txt", "one\n")
        task, wt, head = self.pr_task(files=("f.txt", "theirs\n"))
        self.fake_host(head=head, merge_state="UNKNOWN")
        self.ok("close", str(task), "--verdict", "test-verified")
        self.advance_main("f.txt", "ours\n")
        self.fake_host(head=head, merge_state="BEHIND")
        conflict = self.one(self.events("close", str(task)), "conflict")
        self.assertIn("rebasing worktree-task-1 onto origin/main conflicted; rebase aborted", conflict["detail"])
        self.assertIn("--type decision", conflict["next"])
        git_dir = self.git("rev-parse", "--git-dir", cwd=wt)
        self.assertFalse(os.path.exists(os.path.join(wt, git_dir, "REBASE_HEAD")) or os.path.isdir(os.path.join(wt, git_dir, "rebase-merge")))
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt), head)
        self.assertEqual(self.git("status", "--porcelain", cwd=wt), "")
        self.assertEqual(self.remote_sha(), head)
        self.assertEqual(self.one(self.events("record"), "pr-behind")["task"], task)

    @both_hosts
    def test_84_a_rebase_that_changes_the_diff_is_undone(self):
        task, wt, head = self.published()
        self.advance_main("out.txt", "x\n")  # the target already holds the task's change
        self.advance_main("later.txt", "y\n")
        self.fake_host(head=head, merge_state="BEHIND")
        changed = self.one(self.events("close", str(task)), "changed")
        self.assertIn("the rebase onto main changed the diff (different diff); restored " + head[:7], changed["detail"])
        self.assertIn("Rebase worktree-task-1 onto main by hand", changed["next"])
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt), head)
        self.assertEqual(self.remote_sha(), head)
        self.assertEqual(self.meta(task)["verdict_ref"], head)

    @both_hosts
    def test_84_a_dirty_worktree_or_a_live_session_is_not_rebased(self):
        task, wt, head = self.published()
        self.advance_main()
        self.fake_host(head=head, merge_state="BEHIND")
        with open(os.path.join(wt, "scratch.txt"), "w") as fh:
            fh.write("x\n")
        line = self.one(self.events("close", str(task)), "pr-behind")
        self.assertIn(f"{self.label()} is behind main; cannot rebase: worktree dirty", line["detail"])
        self.assertIn("rebase worktree-task-1 by hand, then run.py close 1", line["next"])
        os.remove(os.path.join(wt, "scratch.txt"))
        self.agents(self.row("task-1"))
        line = self.one(self.events("close", str(task)), "pr-behind")
        self.assertIn("cannot rebase: session live", line["detail"])
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt), head)

    @both_hosts
    def test_85_a_push_onto_a_moved_remote_branch_is_refused(self):
        task, wt, head = self.published()
        self.advance_main("moved.txt")
        self.git("fetch", "-q", "origin")
        self.git("rebase", "-q", "origin/main", cwd=wt)  # a hand rebase: the next close has a new head to push
        other = os.path.join(self.dir, "other")
        subprocess.run(["git", "clone", "-q", self.origin, other], check=True)
        for key, value in (("user.name", "t"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
            self.git("config", key, value, cwd=other)
        self.git("checkout", "-q", "-b", "task-1", "origin/task-1", cwd=other)
        stranger = self.commit_file("stranger.txt", "x\n", cwd=other)
        self.git("push", "-q", "origin", "task-1", cwd=other)
        self.fake_host(head=head, merge_state="UNKNOWN")
        before = self.checkout()
        events = self.events("close", str(task))
        self.assertEqual(self.checkout(), before)
        self.one(events, "rebased")
        refused = self.one(events, "push-refused")
        self.assertIn(f"origin/task-1 is not at {head[:7]}; someone else pushed", refused["detail"])
        self.assertIn("the operator decides", refused["next"])
        self.assertEqual(self.remote_sha(), stranger)
        meta = self.meta(task)
        self.assertEqual((meta["pushed"], meta["pr"]), (head, 1))
        self.assertEqual(len(self.create_calls()), 1)
        self.assertEqual(self.named(events, "pushed"), [])

    @both_hosts
    def test_86_a_half_closed_task_resumes_at_publish(self):
        self.pr_config()
        task = self.running_task(base=json.dumps(self.git("rev-parse", "HEAD")))
        wt, head = self.pass_report(task)
        self.agents(self.finished("task-1"))
        self.tg("edit", str(task), "--meta", f'verdict_ref="{head}"', "verdict=test-verified")
        self.tg("done", str(task))
        line = self.one(self.events("record"), "unpublished")
        self.assertEqual(line["detail"], f"closed at {head[:7]}, not pushed")
        self.assertEqual(line["next"], f"run.py close {task}")
        # the push happened and the tg edit was lost: a remote branch at our head is ours
        self.git("push", "-q", "origin", f"{head}:refs/heads/task-1")
        self.fake_host(head=head, merge_state="UNKNOWN")
        before = self.checkout()
        events = self.events("close", str(task))
        self.assertEqual(self.checkout(), before)
        self.assertEqual(self.one(events, "resumed")["detail"], "closed earlier; continuing at publish")
        self.one(events, "published")
        meta = self.meta(task)
        self.assertEqual((meta["pushed"], meta["pr"]), (head, 1))

    @both_hosts
    def test_88_a_remote_branch_that_is_not_ours_stops_the_publish(self):
        task, wt, head = self.pr_task()
        self.git("push", "-q", "origin", "main:refs/heads/task-1")
        self.fake_host(head=head)
        before = self.checkout()
        out = self.run_cmd("close", str(task), "--verdict", "test-verified")
        self.assertEqual(self.checkout(), before)
        self.assertEqual(out.returncode, 2)
        self.assertIn("delete or rename it on the host", out.stderr)
        self.assertIn("run.py adopt 1 --branch", out.stderr)
        self.assertEqual(self.status_of(task), "done")
        self.assertEqual(self.create_calls(), [])
        self.git("push", "-q", "-f", "origin", f"{head}:refs/heads/task-1")
        self.assertIn("published", [e["event"] for e in self.events("close", str(task))])

    @both_hosts
    def test_87_an_adopted_branch_is_pushed_without_a_worktree_and_a_hand_rebase_keeps_the_pin(self):
        self.pr_config()
        self.fake_host()
        tip = self.feature_branch("feat")
        task = self.add_task()
        self.ok("adopt", str(task), "--branch", "feat", "--head", tip)
        self.fake_host(head=tip, merge_state="UNKNOWN")
        before = self.checkout()
        events = self.events("close", str(task), "--verdict", "test-verified", "--ran", "x")
        self.one(events, "published")
        self.assertEqual(self.remote_sha(), tip)
        self.assertEqual(self.checkout(), before)
        self.advance_main()
        self.fake_host(head=tip, merge_state="BEHIND")
        behind = self.one(self.events("close", str(task)), "pr-behind")
        self.assertIn("cannot rebase: worktree missing", behind["detail"])
        self.git("fetch", "-q", "origin")
        self.git("checkout", "-q", "feat")
        self.git("rebase", "-q", "origin/main")
        new = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "main")
        events = self.events("close", str(task))
        self.assertIn(f"same change at {new[:7]} (verified at {tip[:7]})", self.one(events, "rebased")["detail"])
        self.assertEqual(self.meta(task)["verdict_ref"], new)
        self.assertEqual((self.meta(task)["pushed"], self.remote_sha()), (new, new))

    @both_hosts
    def test_87_a_fix_round_of_an_adopted_branch_starts_in_the_task_worktree_at_its_tip(self):
        self.pr_config()
        self.fake_host()
        tip = self.feature_branch("feat")
        task = self.add_task()
        self.ok("adopt", str(task), "--branch", "feat", "--head", tip)
        base = self.meta(task)["base"]
        self.assertEqual(self.worktree_state()[2], [])
        self.ok("launch", str(task))
        wt = self.wt_path("task-1")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt), tip)
        self.assertEqual(self.git("branch", "--show-current", cwd=wt), "worktree-task-1")
        self.assertEqual(self.meta(task)["base"], base)
        self.assertIn(f"Attempt 2. Your worktree is at `{tip}`", self.calls("--bg")[-1][-1])

    @both_hosts
    def test_87_adopt_with_an_open_request_takes_its_branch_and_target(self):
        self.pr_config()
        tip = self.feature_branch("feat")
        task = self.add_task()
        base = self.git("rev-parse", "HEAD")
        self.fake_host(number=7, head="f" * 40, branch="feat", base="main")
        out = self.run_cmd("adopt", str(task), "--branch", "feat", "--head", tip, "--pr", "7")
        self.assertEqual(out.returncode, 2)
        self.assertIn(f"{self.label(7)} head is {'f' * 40}, not {tip}", out.stderr)
        self.fake_host(number=7, head=tip, branch="feat", base="develop", state="MERGED")
        out = self.run_cmd("adopt", str(task), "--branch", "feat", "--head", tip, "--pr", "7")
        self.assertIn(f"{self.label(7)} is MERGED; adopt takes an open request", out.stderr)
        self.fake_host(number=7, head=tip, branch="feat", base="develop")
        self.git("branch", "develop", "main")
        self.git("push", "-q", "origin", "develop")
        events = self.events("adopt", str(task), "--branch", "feat", "--head", tip, "--pr", "7")
        self.assertIn(self.label(7), self.one(events, "adopted")["detail"])
        meta = self.meta(task)
        self.assertEqual((meta["pr"], meta["pr_branch"], meta["pushed"], meta["target"]), (7, "feat", tip, "develop"))
        self.assertEqual(meta["base"], base)

    @both_hosts
    def test_89_a_second_attempt_pushes_to_the_same_branch_and_opens_no_second_request(self):
        main = self.git("rev-parse", "HEAD")
        task, wt, head = self.pr_task(verify_mode=f"ci:{self.ci}")
        self.fake_host(head=head, merge_state="UNKNOWN", runs=[{"id": 11, "state": "failure"}])
        self.ok("verify", str(task))
        self.ok("close", str(task))
        pinned = {k: self.meta(task)[k] for k in ("pr", "pr_branch", "pushed")}
        self.assertEqual(pinned, {"pr": 1, "pr_branch": "task-1", "pushed": head})
        self.ok("launch", str(task))
        meta = self.meta(task)
        self.assertEqual({k: meta[k] for k in pinned}, pinned)
        self.assertEqual((meta["attempt"], meta["base"]), (2, main))  # the branch still forks from where it did
        wt2 = self.wt_path("task-1")  # attempt 2 continues in the one worktree
        self.assertEqual(wt2, wt)
        self.assertEqual(self.worktree_state()[2], ["task-1"])
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt2), head)
        head2 = self.wt_commit(wt2, "two.txt")
        self.pass_report(task, attempt=2, wt=wt2, head=head2)
        self.agents(self.finished("task-1"), self.finished("task-1", 2))
        self.fake_host(head=head2, merge_state="UNKNOWN")
        before, seen = self.checkout(), len(self.host_log())
        events = self.events("close", str(task), "--verdict", "test-verified", "--ran", "x")
        self.assertIn(f"{head2[:7]} to origin/task-1", self.one(events, "pushed")["detail"])
        self.assertEqual(self.named(events, "published"), [])
        self.assertEqual(self.remote_sha(), head2)
        self.assertEqual((self.meta(task)["pushed"], self.meta(task)["pr"]), (head2, 1))
        self.assertEqual(len(self.create_calls()), 1)
        lookup = ("pr list", "pr create") if self.host == "github" else (f"api projects/{self.project}/merge_requests?", "api -X POST")
        self.assertEqual([c for c in self.host_log()[seen:] if " ".join(c).startswith(lookup)], [])
        self.assertEqual(self.checkout(), before)

    # --- verify_mode = ci:<name>

    def ci_rows(self, task):
        return [r for r in self.results(task) if r["kind"] == "verify" and r["author"] == "ci"]

    def dispatch_calls(self):
        if self.host == "github":
            return self.host_calls("workflow run")
        return self.host_calls("api", "-X", "POST", f"projects/{self.project}/pipeline")

    @both_hosts
    def test_90_ci_mode_needs_pr_mode_and_a_name(self):
        task = self.add_task(verify_mode=f"ci:{self.ci}")
        out = self.run_cmd("launch", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn('verify_mode=ci needs merge.mode = "pr"; the run must be on a pushed branch', out.stderr)
        for bad in ("ci:", "ci", "CI:ci.yml", "nightly"):
            task = self.add_task(verify_mode=bad)
            out = self.run_cmd("launch", str(task))
            self.assertEqual(out.returncode, 2, bad)
            self.assertIn(f'#{task} verify_mode must be "session" or "ci:<workflow>" (GitLab: "ci:pipeline" or "ci:<job>"), not {bad}',
                          out.stderr)
        self.pr_config()
        self.fake_host()
        self.assertEqual(self.run_cmd("launch", str(self.add_task(verify_mode=f"ci:{self.ci}"))).returncode, 0)
        self.assertEqual(self.run_cmd("launch", str(self.add_task(verify_mode="session"))).returncode, 0)

    @both_hosts
    def test_91_a_passing_ci_mode_task_goes_to_verify_whatever_its_risk(self):
        task, wt, head = self.pr_task(verify_mode=f"ci:{self.ci}", risk="low")
        arrived = self.one(self.events("record"), "arrived")
        self.assertEqual(arrived["next"], f"run.py verify {task}")

    @both_hosts
    def test_92_verify_pushes_opens_the_request_and_dispatches(self):
        task, wt, head = self.pr_task(verify_mode=f"ci:{self.ci}")
        self.fake_host(head=head, merge_state="UNKNOWN", dispatch="ok")
        before, keys = self.checkout(), set(self.meta(task))
        events = self.events("verify", str(task))
        self.one(events, "published")
        dispatched = self.one(events, "ci-dispatched")
        self.assertEqual(dispatched["detail"], f"{self.ci} on task-1 at {head[:7]}")
        self.assertEqual(dispatched["next"], "run.py record")
        (call,) = self.dispatch_calls()
        if self.host == "github":
            self.assertEqual(call, ["workflow", "run", "ci.yml", "--ref", "task-1"])
        else:
            self.assertEqual(call[-2:], ["-f", "ref=task-1"])
        self.assertEqual(self.remote_sha(), head)
        self.assertEqual(set(self.meta(task)) - keys, {"pr", "pr_branch", "pushed"})
        self.assertEqual(self.calls("--bg"), [])
        self.assertEqual(self.status_of(task), "in_progress")
        self.assertEqual(self.checkout(), before)
        out = self.run_cmd("verify", str(task), "--model", "opus")
        self.assertEqual(out.returncode, 2)
        self.assertIn("verify_mode=ci runs on the branch head and starts no session; drop --ref/--model/--effort/--dry-run", out.stderr)
        self.assertEqual(self.run_cmd("verify", str(task), "--dry-run").returncode, 2)
        self.fake_host(head=head, merge_state="UNKNOWN", dispatch="none")
        waiting = self.one(self.events("verify", str(task)), "ci-waiting")
        self.assertIn(f"no run for {head[:7]} yet; {self.ci} has no manual trigger, the push or the request starts it", waiting["detail"])
        self.fake_host(head=head, merge_state="UNKNOWN", dispatch="error")
        failed = self.one(self.events("verify", str(task)), "ci-waiting")
        self.assertIn("dispatch failed:", failed["detail"])
        self.assertEqual(failed["next"], f"fix it, then run.py verify {task} --again")
        self.assertEqual(self.ci_rows(task), [])

    @both_hosts
    def test_93_a_finished_run_on_the_pushed_head_becomes_a_ci_verdict(self):
        task, wt, head = self.pr_task(verify_mode=f"ci:{self.ci}")
        self.fake_host(head=head, merge_state="UNKNOWN")
        self.ok("verify", str(task))
        self.fake_host(head=head, merge_state="UNKNOWN", runs=[{"id": 11, "state": "pending"}])
        pending = self.one(self.events("record"), "ci-pending")
        self.assertIn("run 11", pending["detail"])
        self.assertEqual(self.ci_rows(task), [])
        self.fake_host(head=head, merge_state="UNKNOWN", runs=[{"id": 11, "state": "success"}])
        events = self.events("record")
        self.assertEqual(self.one(events, "verified")["detail"].split(" (")[0], "Verdict test-verified by ci")
        (row,) = self.ci_rows(task)
        self.assertEqual((row["status"], row["attempt"]), ("PASS", 1))
        for line in ("Verdict: test-verified", f"Workflow: {self.ci}", "Run: 11/1 https://ci.example/", f"Head: {head}",
                     "Branch: origin/task-1", "Conclusion: success"):
            self.assertIn(line, row["body"])
        self.assertEqual(len(self.ci_rows(task)), 1)
        self.one(self.events("record"), "verified")
        self.assertEqual(len(self.ci_rows(task)), 1)
        closed = self.events("close", str(task))
        self.assertIn("test-verified at", self.one(closed, "closed")["detail"])
        self.assertEqual(self.meta(task)["verdict"], "test-verified")
        self.assertEqual([r for r in self.results(task) if r["author"] == "manager" and r["kind"] == "verify"], [])

    @both_hosts
    def test_93_a_ci_test_verified_does_not_close_a_schema_task(self):
        task, wt, head = self.pr_task(verify_mode=f"ci:{self.ci}", verify_kind="schema")
        self.fake_host(head=head, merge_state="UNKNOWN")
        self.ok("verify", str(task))
        self.fake_host(head=head, merge_state="UNKNOWN", runs=[{"id": 11, "state": "success"}])
        verified = self.one(self.events("record"), "verified")
        self.assertTrue(verified["detail"].startswith("Verdict test-verified by ci"))
        self.assertIn("does not close a schema task", verified["next"])
        before = self.checkout()
        verdict = self.one(self.events("close", str(task)), "verdict")
        self.assertEqual(verdict["detail"], "test-verified; not closed")
        self.assertEqual(self.status_of(task), "in_progress")
        self.assertEqual(self.remote_sha(), head)
        self.assertEqual(self.checkout(), before)
        events = self.events("close", str(task), "--verdict", "artifact-verified", "--override-verifier",
                             "CI recomputed the numbers", "--ran", "https://ci.example/runs/11")
        self.one(events, "override")
        self.one(events, "closed")
        self.assertEqual(self.status_of(task), "done")
        self.assertEqual(self.meta(task)["verdict"], "artifact-verified")

    @both_hosts
    def test_93_a_run_for_another_head_is_ignored(self):
        task, wt, head = self.pr_task(verify_mode=f"ci:{self.ci}")
        self.fake_host(head=head, merge_state="UNKNOWN")
        self.ok("verify", str(task))
        self.fake_host(head=head, merge_state="UNKNOWN", runs=[{"id": 12, "state": "success", "head": "9" * 40}])
        waiting = self.one(self.events("record"), "ci-waiting")
        self.assertEqual(waiting["detail"], f"no run for {head[:7]} on {self.ci} yet")
        self.assertEqual(self.ci_rows(task), [])

    @both_hosts
    def test_94_a_failed_run_is_a_fix_round_and_a_cancelled_run_is_a_retry(self):
        task, wt, head = self.pr_task(verify_mode=f"ci:{self.ci}")
        self.fake_host(head=head, merge_state="UNKNOWN")
        self.ok("verify", str(task))
        self.fake_host(head=head, merge_state="UNKNOWN", runs=[{"id": 11, "state": "failure"}])
        verified = self.one(self.events("record"), "verified")
        self.assertIn("Verdict verify-failed by ci", verified["detail"])
        self.assertIn(f"run run.py close {task} (records verify-failed)", verified["next"])
        self.assertIn(f"fix round: run.py launch {task}", verified["next"])
        (row,) = self.ci_rows(task)
        self.assertEqual((row["status"], row["body"].splitlines()[0]), ("ISSUES", "Verdict: verify-failed"))
        events = self.events("close", str(task))
        self.assertIn("verify-failed; not closed", self.one(events, "verdict")["detail"])
        self.ok("launch", str(task))
        with open(os.path.join(self.root, ".agentic-team", "briefs", "task-1-2.md")) as fh:
            self.assertIn(f"Attempt 2. Your worktree is at `{head}` on branch `worktree-task-1`.", fh.read())
        self.agents(self.row("task-1", 2))
        again = self.events("record")
        self.one(again, "running")
        self.assertEqual(self.named(again, "verified"), [])
        self.assertEqual(len(self.ci_rows(task)), 1)

    @both_hosts
    def test_94_a_cancelled_run_is_blocked_and_verify_again_files_each_new_run(self):
        task, wt, head = self.pr_task(verify_mode=f"ci:{self.ci}")
        self.fake_host(head=head, merge_state="UNKNOWN")
        self.ok("verify", str(task))
        self.fake_host(head=head, merge_state="UNKNOWN", runs=[{"id": 11, "state": "cancelled"}])
        verified = self.one(self.events("record"), "verified")
        self.assertIn("Verdict verify-blocked by ci", verified["detail"])
        self.assertEqual(verified["next"], f"run.py verify {task} --again")
        self.assertEqual(self.ci_rows(task)[0]["status"], "BLOCKED")
        refused = self.run_cmd("verify", str(task))
        self.assertEqual(refused.returncode, 2)
        self.assertIn(f"already has verify result #{self.ci_rows(task)[0]['id']} (Verdict: verify-blocked) from CI; "
                      f"run run.py close {task}, or pass --again to run it again", refused.stderr)
        self.fake_host(head=head, merge_state="UNKNOWN", runs=[{"id": 11, "state": "cancelled"}], dispatch="ok")
        seen = len(self.dispatch_calls())
        self.assertEqual(len(self.named(self.events("verify", str(task), "--again"), "ci-dispatched")), 1)
        self.assertEqual(len(self.dispatch_calls()), seen + 1)
        self.fake_host(head=head, merge_state="UNKNOWN", runs=[{"id": 12, "state": "success"}, {"id": 11, "state": "cancelled"}])
        self.assertIn("Verdict test-verified by ci", self.one(self.events("record"), "verified")["detail"])
        self.assertEqual([r["body"].splitlines()[0] for r in self.ci_rows(task)], ["Verdict: verify-blocked", "Verdict: test-verified"])
        self.assertIn("Run: 12/1", self.ci_rows(task)[1]["body"])

    def test_94_a_github_rerun_is_a_new_row(self):
        self.host = "github"
        task, wt, head = self.pr_task(verify_mode="ci:ci.yml")
        self.fake_host(head=head, merge_state="UNKNOWN")
        self.ok("verify", str(task))
        self.fake_host(head=head, merge_state="UNKNOWN", runs=[{"id": 11, "attempt": 1, "state": "failure"}])
        self.ok("record")
        self.fake_host(head=head, merge_state="UNKNOWN", runs=[{"id": 11, "attempt": 2, "state": "success"}])
        self.ok("record")
        self.assertEqual([re.search(r"Run: (\S+)", r["body"]).group(1) for r in self.ci_rows(task)], ["11/1", "11/2"])

    def test_95_a_gitlab_job_decides_when_the_mode_names_one(self):
        self.host = "gitlab"
        task, wt, head = self.pr_task(verify_mode="ci:unit")
        self.fake_host(head=head, merge_state="UNKNOWN")
        self.ok("verify", str(task))
        self.fake_host(head=head, merge_state="UNKNOWN", runs=[{"id": 11, "state": "pending"}],
                       jobs=[{"name": "lint", "status": "failed"}, {"name": "unit", "status": "success"}])
        self.assertIn("Verdict test-verified by ci", self.one(self.events("record"), "verified")["detail"])
        (row,) = self.ci_rows(task)
        self.assertIn("Run: 11/5001", row["body"])
        self.assertIn("Workflow: unit", row["body"])
        self.assertTrue(self.host_calls("api", f"projects/{self.project}/pipelines/11/jobs"))
        other = self.running_task(verify_mode="ci:integration", attempt=1)
        wt2, head2 = self.pass_report(other, wt=self.worktree(f"task-{other}"))
        self.fake_host(head=head2, merge_state="UNKNOWN")
        self.ok("verify", str(other))
        self.fake_host(head=head2, merge_state="UNKNOWN", runs=[{"id": 21, "state": "success"}],
                       jobs=[{"name": "unit", "status": "success"}])
        blocked = [e for e in self.events("record") if e["task"] == other and e["event"] == "verified"][0]
        self.assertIn("Verdict verify-blocked by ci", blocked["detail"])
        self.assertIn("Conclusion: no job integration", self.ci_rows(other)[0]["body"])

    @both_hosts
    def test_96_ci_verification_runs_under_stop(self):
        task, wt, head = self.pr_task(verify_mode=f"ci:{self.ci}")
        self.orders("STOP: paused\n")
        self.fake_host(head=head, merge_state="UNKNOWN", dispatch="ok")
        events = self.events("verify", str(task))
        self.one(events, "ci-dispatched")
        self.assertEqual(self.remote_sha(), head)
        self.fake_host(head=head, merge_state="UNKNOWN", runs=[{"id": 11, "state": "success"}])
        self.one(self.events("record"), "verified")
        self.assertEqual(len(self.ci_rows(task)), 1)

    # --- carry-over

    @both_hosts
    def test_98_cleanup_keeps_what_it_must_and_never_forces(self):
        task, wt, head = self.published()
        self.fake_host(head=head, state="MERGED", merge_state="UNKNOWN", merge_commit="c" * 40)
        self.agents(self.row("task-1"))
        events = self.events("record")
        self.assertIn("still running", self.one(events, "kept")["detail"])
        self.assertEqual(self.calls("rm"), [])
        self.agents(self.finished("task-1"))
        with open(os.path.join(wt, "wip.txt"), "w") as fh:
            fh.write("x\n")
        self.assertIn("uncommitted changes", self.one(self.events("record"), "kept")["detail"])
        self.assertEqual(self.calls("rm"), [])
        os.rename(os.path.join(wt, "wip.txt"), os.path.join(wt, "notes.txt"))
        with open(self.rm_file, "w") as fh:
            json.dump({"sess-task-1-1": {"exit": 1, "stderr": "worktree has untracked files"}}, fh)
        self.assertEqual(self.one(self.events("record"), "kept")["detail"], "task-1: uncommitted changes (?? notes.txt)")
        self.assertTrue(os.path.isfile(os.path.join(wt, "notes.txt")))
        self.assertTrue(all("--force-remove-worktree" not in c for c in self.calls()))

    @both_hosts
    def test_99_the_attempt_cap_holds_for_launch_and_adopt(self):
        self.pr_config()
        self.fake_host()
        task = self.running_task(attempt=3, verify_mode=f"ci:{self.ci}")
        self.add_result(task, "PASS", f"Task: 1\nBranch: worktree-task-1\nHead: {SHA_A}\n", attempt=3)
        self.add_result(task, "ISSUES", f"Verdict: verify-failed\nRun: 11/1 u\n", kind="verify", attempt=3, by="ci")
        tip = self.feature_branch("feat")
        for command in (("launch", str(task)), ("adopt", str(task), "--branch", "feat", "--head", tip)):
            out = self.run_cmd(*command)
            self.assertEqual(out.returncode, 2, command)
            self.assertIn("#1: attempt 3 has failed; run run.py abandon 1", out.stderr)
        self.assertEqual(self.calls("--bg"), [])

    @both_hosts
    def test_100_the_merge_line_is_the_only_permission_to_merge(self):
        task, wt, head = self.published()
        for merge_state in ("CLEAN", "BLOCKED", "UNKNOWN", "DRAFT", "BEHIND", "DIRTY"):
            self.fake_host(head=head, merge_state=merge_state)
            self.ok("record")
        self.assertEqual(self.merge_calls(), [])
        self.orders("MERGE: verified branches into main\n")
        for merge_state in ("BLOCKED", "UNKNOWN", "DRAFT", "BEHIND", "DIRTY"):
            self.fake_host(head=head, merge_state=merge_state)
            self.ok("record")
        for state in ("CLOSED", "OPEN"):
            self.fake_host(head="e" * 40 if state == "OPEN" else head, state=state, merge_state="CLEAN")
            self.ok("record")
        self.assertEqual(self.merge_calls(), [])
        self.assertNotIn("merged_at", self.meta(task))

    @both_hosts
    def test_abandon_names_the_request_that_stays_open(self):
        task, wt, head = self.pr_task()
        self.tg("edit", str(task), "--meta", "pr=1", "attempt=3")
        detail = self.one(self.events("abandon", str(task), "died"), "abandoned")["detail"]
        self.assertTrue(detail.endswith(f"; request {self.label()} stays open, close it on the host by hand"), detail)

    # --- review fixes

    def two_attempt_task(self):
        """Attempt 1 failed CI, attempt 2 passed and was closed and published. Returns (task, wt2, head2)."""
        task, wt, head = self.pr_task(verify_mode=f"ci:{self.ci}")
        self.fake_host(head=head, merge_state="UNKNOWN", runs=[{"id": 11, "state": "failure"}])
        self.ok("verify", str(task))
        self.ok("close", str(task))
        self.ok("launch", str(task))
        wt2 = self.wt_path("task-1")  # attempt 2 continues in the one worktree
        self.assertEqual(wt2, wt)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=wt2), head)
        head2 = self.wt_commit(wt2, "two.txt")
        self.pass_report(task, attempt=2, wt=wt2, head=head2)
        self.agents(self.finished("task-1"), self.finished("task-1", 2))
        self.fake_host(head=head2, merge_state="UNKNOWN")
        self.ok("close", str(task), "--verdict", "test-verified", "--ran", "x")
        return task, wt2, head2

    @both_hosts
    def test_84_a_branch_of_two_attempts_is_rebased_twice_and_by_hand(self):
        task, wt, head = self.two_attempt_task()
        for round_ in (1, 2):
            self.advance_main(f"moved{round_}.txt")
            self.fake_host(head=head, merge_state="BEHIND")
            events = self.events("close", str(task))
            new = self.git("rev-parse", "HEAD", cwd=wt)
            self.assertNotEqual(new, head, round_)
            self.one(events, "rebased")
            self.assertEqual((self.meta(task)["pushed"], self.remote_sha()), (new, new))
            head = new
        self.advance_main("moved3.txt")
        self.git("fetch", "-q", "origin")
        self.git("rebase", "-q", "origin/main", cwd=wt)
        by_hand = self.git("rev-parse", "HEAD", cwd=wt)
        self.fake_host(head=head, merge_state="UNKNOWN")
        events = self.events("close", str(task))
        self.assertIn(f"same change at {by_hand[:7]} (verified at {head[:7]})", self.one(events, "rebased")["detail"])
        self.assertEqual((self.meta(task)["verdict_ref"], self.remote_sha()), (by_hand, by_hand))

    @both_hosts
    def test_86_an_open_request_with_no_pushed_head_is_never_merged(self):
        task, wt, head = self.published()
        self.tg("edit", str(task), "--unset-meta", "pushed")
        self.orders("MERGE: verified branches into main\n")
        self.fake_host(head=head, merge_state="CLEAN")
        line = self.one(self.events("record"), "pr-unpinned")
        self.assertIn("no pushed head is recorded", line["detail"])
        self.assertEqual(line["next"], f"run.py close {task} (pushes the branch and records the head)")
        self.assertEqual(self.merge_calls(), [])
        self.fake_host(head=head, merge_state="UNKNOWN")
        self.one(self.events("close", str(task)), "resumed")
        self.assertEqual(self.meta(task)["pushed"], head)

    def test_84_no_required_checks_do_not_stop_the_drain(self):
        self.host = "github"
        task, wt, head = self.published()
        self.fake_host(head=head, merge_state="BLOCKED",
                       extra={"pr checks": {"stdout": "", "stderr": "no required checks reported on the 'task-1' branch\n", "exit": 1}})
        events = self.events("record")
        self.assertIn("no required checks reported", self.one(events, "pr-blocked")["detail"])
        self.one(events, "slots")

    def test_84_a_host_failure_is_one_tasks_line_and_the_drain_goes_on(self):
        self.host = "github"
        task, wt, head = self.published()
        second = self.add_task("Second", attempt=1, verdict_ref=SHA_A, pr=2, pr_branch="task-2", pushed=SHA_A)
        self.tg("done", str(second))
        self.fake_host(number=2, head=SHA_A, merge_state="UNKNOWN",
                       extra={"pr view 1": {"stdout": "", "stderr": "authentication lapsed\n", "exit": 4}})
        out = self.run_cmd("record", pre=["--json"])
        self.assertEqual(out.returncode, 1)
        events = json.loads(out.stdout)
        error = self.one(events, "host-error")
        self.assertEqual((error["task"], error["detail"], error["next"]),
                         (task, "gh pr view failed: authentication lapsed", "fix it and run.py record"))
        self.assertEqual(self.one(events, "pr-pending")["task"], second)
        self.one(events, "slots")
        self.one(events, "ready")

    def test_93_a_short_head_in_the_worker_report_still_files_the_ci_row(self):
        self.host = "github"
        self.pr_config()
        task = self.running_task(base=json.dumps(self.git("rev-parse", "HEAD")), verify_mode="ci:ci.yml")
        wt = self.worktree("task-1")
        head = self.wt_commit(wt)
        self.pass_report(task, wt=wt, head=head[:9])
        self.fake_host(head=head, merge_state="UNKNOWN")
        self.ok("verify", str(task))
        self.fake_host(head=head, merge_state="UNKNOWN", runs=[{"id": 11, "state": "success"}])
        self.one(self.events("record"), "verified")
        self.assertEqual(len(self.ci_rows(task)), 1)

    def test_76_an_unknown_verifier_word_can_be_overridden(self):
        task = self.verified_by("passed")
        out = self.run_cmd("close", str(task), "--verdict", "test-verified", "--override-verifier", "x", "--ran", "ran 123456789")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.meta(task)["verdict"], "test-verified")

    @both_hosts
    def test_85_a_deleted_remote_branch_is_named_not_blamed_on_someone_else(self):
        task, wt, head = self.published()
        self.advance_main("moved.txt")
        self.git("fetch", "-q", "origin")
        self.git("rebase", "-q", "origin/main", cwd=wt)
        self.git("push", "-q", "origin", ":refs/heads/task-1")
        self.fake_host(head=head, merge_state="UNKNOWN")
        out = self.run_cmd("close", str(task))
        self.assertEqual(out.returncode, 2)
        self.assertIn("remote branch origin/task-1 is gone", out.stderr)
        self.assertIn("unset the pr, pr_branch and pushed meta", out.stderr)

    @both_hosts
    def test_84_a_stacked_task_is_rebased_after_its_dependency_was_squash_merged(self):
        self.pr_config()
        dep = self.feature_branch("dep")  # the dependency's branch: fork0 -> D
        task = self.running_task(base=json.dumps(dep))  # launched with --base dep
        wt = self.worktree("task-1", base=dep)
        head = self.wt_commit(wt, "out.txt")  # fork0 -> D -> T
        self.pass_report(task, wt=wt, head=head)
        self.agents(self.finished("task-1"))
        self.fake_host(head=head, merge_state="UNKNOWN")
        self.ok("close", str(task), "--verdict", "test-verified", "--ran", "x")
        self.advance_main("dep.txt", "work\n")  # the dependency lands as S, the same patch as D
        self.fake_host(head=head, merge_state="BEHIND")
        events = self.events("close", str(task))
        new = self.git("rev-parse", "HEAD", cwd=wt)
        self.assertEqual(self.git("rev-list", "--count", f"origin/main..{new}"), "1")  # D was dropped
        self.one(events, "rebased")
        self.assertEqual((self.meta(task)["pushed"], self.remote_sha()), (new, new))

    @both_hosts
    def test_85_a_failing_ls_remote_is_reported_not_read_as_a_deleted_branch(self):
        task, wt, head = self.published()
        self.tg("edit", str(task), "--meta", f'pushed="{"b" * 40}"')
        self.git("remote", "set-url", "origin", os.path.join(self.dir, "no-such-remote.git"))
        out = self.run_cmd("close", str(task))
        self.assertEqual(out.returncode, 1)
        self.assertIn("ls-remote of origin failed:", out.stderr)
        self.assertNotIn("unset the pr", out.stderr)


if __name__ == "__main__":
    unittest.main()
