#!/usr/bin/env python3
"""Run the Agentic Team workflow: one command per state change.

Usage:
    run.py [--root DIR] [--tg PATH] [--run-dir DIR] [--json] <command> ...

    launch <id>    render the brief, create the task worktree at the base (or
                   continue in it), start the worker, record the start
    adopt <id>     bring a branch started outside run.py under the Manager
    verify <id>    start a verifier session, in a worktree at the commit, for a
                   PASS result, or find the CI run on the pushed branch
                   (verify_mode ci:<name>)
    record         read the queue: results, dead and stuck sessions, merges,
                   open decisions, free slots, ready tasks
    close <id>     record the verdict and tokens, mark the task done, merge
                   (local) or push the branch and open a request (pr)
    merged <id>    record that the operator merged a task branch
    stop <id>      stop a worker for a pause and file a STOPPED result
    abandon <id>   mark a task abandoned after attempt 3 failed
    status         print the status report (tables)

Run from the repository root. Taskgraph is the only source of task content;
this script copies it and never invents it. Nothing in it waits, sleeps, or
polls: `claude --bg` returns at once, and the Manager runs `record` later.

merge.mode "local" merges a closed branch into the main checkout under a
MERGE: line. merge.mode "pr" pushes the branch `task-<id>` to merge.remote and
opens a pull request (gh) or merge request (glab) through host.py; `record`
merges it under the same MERGE: line once the host reports it clean, and
records a merge anyone else did. Local mode never runs gh or glab.

Text output is one line per event: `<event> #<id> attempt <n>: <detail>`, with
` | next: <step>` when a step follows. `--json` prints one JSON array of
{"event", "task", "attempt", "session", "detail", "next"} and nothing else
on stdout (`status --json` prints one object).

Exit codes: 0 the command ran (an event may still say `died` or `kept`);
1 a tool failed (tg, git, claude); 2 refused, the message names the fix;
3 the standing orders say STOP (launch only).

A session row belongs to a task by its session id. run.py records the id in the
task's `sessions` meta when it starts the session (the `<id>` that `claude --bg`
prints, checked against `claude agents --json --all`). A live or finished row
whose id is not recorded, and whose working directory is a worktree folder of
this repository (`.claude/worktrees/task-<id>` or `verify-<id>-<attempt>`),
belongs to the task of that folder, current attempt. A session that `claude stop`
ended shows `state` "stopped", no status, and the repository root as its
directory; only its recorded id ties it to a task. A stopped row that is not
recorded belongs to nobody. Names are never used: `claude agents --all` lists
every project on the machine. A task has one worktree and one branch for its
whole life (`.claude/worktrees/task-<id>`, `worktree-task-<id>`); every attempt
runs in it, on top of the earlier attempts' commits. The worktree path is always
derived from the task, never read from a row. The `Session:` lines in result
bodies are a record, not the match.
"""

import argparse
import datetime
import glob
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERIFY_SKILL = os.path.join(".claude", "skills", "verify", "SKILL.md")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import host as codehost  # noqa: E402
from config import ConfigError, load, problems as config_problems, resolve_model  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

# ------------------------------------------------------------------ common

MAX_ATTEMPTS = 3
DEFAULT_TIMEBOX_HOURS = 2
VERDICTS = ("artifact-verified", "test-verified", "check-only", "verify-blocked", "verify-failed")
CLOSING = ("artifact-verified", "test-verified")
VERIFY_KINDS = ("code", "schema", "design-doc")
PASSING = {"code": CLOSING, "schema": ("artifact-verified",), "design-doc": ("artifact-verified",)}
ABANDON_MODES = ("died", "tool-error", "stuck", "unknown")
TASK_WT = re.compile(r"^task-(\d+)$")
VERIFY_WT = re.compile(r"^verify-(\d+)-(\d+)(?:-(\d+))?$")
LEGACY_WT = re.compile(r"^task-(\d+)-(\d+)$")  # a worktree of agentic-team 0.6.0
BACKGROUNDED = re.compile(r"backgrounded\s*\u00b7\s*([0-9A-Za-z-]+)")
COMMIT_SHA = re.compile(r"[0-9a-f]{7,40}")
FIELD_LINE = re.compile(r"^(exit tests?|acceptance):\s*(.*)$", re.I)  # only these labels are fields
CHECK_ITEM = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+(.*)$")
CHECKPOINT_LINE = re.compile(r"(?m)^Checkpoint:\s*(.*)$")
HEAD_LINE = re.compile(r"(?m)^Head:\s*([0-9a-f]{7,40})\s*$")
HEAD_ANY = re.compile(r"(?m)^Head:\s*(.*?)\s*$")
BRANCH_LINE = re.compile(r"(?m)^Branch:\s*(.*?)\s*$")
WORKTREE_LINE = re.compile(r"(?m)^Worktree:\s*(.*?)\s*$")
SESSION_LINE = re.compile(r"(?m)^Session:\s*(.*?)\s*$")
VERDICT_LINE = re.compile(r"(?m)^Verdict:\s*(\S+)\s*$")
STATUS_LINE = re.compile(r"(?m)^Status:\s*(PASS|ISSUES|BLOCKED)\s*$")
TRUST_HINT = ("Run claude once in the repository and accept the trust prompt; "
              "a trusted parent folder does not count.")
SANDBOX_HINT = ("claude --bg writes session data under ~/.claude. Run run.py launch and run.py verify outside the "
                "Bash sandbox, or allow writes to ~/.claude. Either change needs the operator's agreement.")
PROMPT_HINT = ("claude logs {sid} shows the command it waited on. Remove the need for it: narrow the brief or "
               "SCOPE, keep the step for the Manager's integration list, or set verify_mode=ci:<workflow> when "
               "the check needs the runner. Then {cmd}. A pinned old model id is one more possible cause; use an alias.")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
RUN_LINE = re.compile(r"(?m)^Run:\s*(\S+)")
OVERRIDE_RANK = {"verify-blocked": 0, "check-only": 1, "test-verified": 2, "artifact-verified": 3}
EVIDENCE = re.compile(r"https?://\S+|\b\d{6,}\b")
REPORT_LABEL = re.compile(r"(?m)^(Task|Status|Verdict|Branch|Head|Worktree|Ran|Files|Issues|Deviations|Follow-ups|"
                          r"Checkpoint|Session|Stopped|Workflow|Run|Conclusion|Overrides|Reason):")
COMMENT_FIELDS = ("Ran", "Issues", "Follow-ups", "Run", "Conclusion", "Overrides", "Reason")
COMMENT_LIMIT = 8000  # characters of evidence in the request comment


class Refused(codehost.HostError):
    """A refusal or tool failure: `code` is the exit code, `message` goes to stderr."""

    def __init__(self, message, code=2):
        super().__init__(message, code)


def sh(cmd, cwd=None, input=None):
    try:  # no git call may wait on a credential prompt
        return subprocess.run(cmd, cwd=cwd, input=input, capture_output=True, text=True,
                              env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except FileNotFoundError as exc:
        raise Refused(f"cannot run {cmd[0]}: {exc.strerror}", 1)


def host_sh(cmd, cwd=None, input=None, env=None):
    """The process callback for host.py: it adds the host's environment and lets a missing program raise."""
    return subprocess.run(cmd, cwd=cwd, input=input, capture_output=True, text=True, stdin=subprocess.DEVNULL if input is None else None,
                          env={**os.environ, **(env or {})})


def strip_comments(text):
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def quote(value):
    """Double-quote a path for a shell command, as the brief shows it."""
    return '"' + re.sub(r'([\\"$`])', r"\\\1", str(value)) + '"'


def meta_arg(key, value):
    """A `--meta key=value` argument. The value is JSON, so tg stores a string as a string."""
    return f"{key}={json.dumps(value, ensure_ascii=False)}"


def is_sha(ref):
    return bool(COMMIT_SHA.fullmatch(str(ref or "")))


first_line = codehost.first_line


def tail_or_none(match):
    value = match.group(1).strip() if match else ""
    return None if value in ("", "None") else value


def task_worktree(run, tid):
    """The one worktree of a task: <root>/.claude/worktrees/task-<tid>."""
    return os.path.join(run.root, ".claude", "worktrees", f"task-{tid}")


def task_branch(tid):
    return f"worktree-task-{tid}"


def wt_kind(name):
    """("task", id) or ("verify", id) for a worktree folder name, else None."""
    if m := TASK_WT.match(name):
        return "task", int(m.group(1))
    if m := VERIFY_WT.match(name):
        return "verify", int(m.group(1))
    return None


class Run:
    """Everything one command needs: paths, config, Taskgraph, claude, git, output."""

    def __init__(self, args):
        self.root = os.path.abspath(args.root)
        self.json = args.json
        self.events = []
        self.payload = None  # `status` prints this instead of the events
        self.text = None
        top = sh(["git", "-C", self.root, "rev-parse", "--show-toplevel"])
        if top.returncode != 0 or os.path.realpath(top.stdout.strip()) != os.path.realpath(self.root):
            raise Refused(f"{self.root} is not a repository root; run from the repository root")
        self.tg_path = self.find_tg(args.tg)
        if not os.path.isfile(os.path.join(self.root, ".agentic-team.toml")):
            raise Refused(f"no .agentic-team.toml in {self.root}; run from the repository root or pass --root <dir>")
        self.config = load(self.root)
        found = config_problems(self.config)
        if found:
            raise Refused("fix the config before you continue (or run /agentic-team:setup):\n  " + "\n  ".join(found))
        self.project = self.config["taskgraph"]["project"]
        self.db = os.path.abspath(os.path.expanduser(os.environ.get("TASKGRAPH_DB") or "~/.taskgraph/tasks.db"))
        self.run_dir = os.path.abspath(args.run_dir or os.path.join(self.root, ".agentic-team"))
        self.wt_dir = os.path.realpath(os.path.join(self.root, ".claude", "worktrees"))
        self._sessions = None
        self._host = self._default = None
        self.host_failed = False
        self._fetched = set()

    def find_tg(self, given):
        if given:
            return os.path.abspath(given)
        env = os.environ.get("TASKGRAPH_TG")
        if env and os.path.isfile(env):
            return os.path.abspath(env)
        out = sh(["bash", os.path.join(PLUGIN_ROOT, "scripts", "tg-path.sh")])
        if out.returncode != 0:
            raise Refused(out.stderr.strip() or "cannot find tg.py", 1)
        return out.stdout.strip()

    # --- tools

    def tg(self, *cmd, input=None):
        out = sh([sys.executable, self.tg_path, "--db", self.db, "--project", self.project, "--json", *cmd],
                 cwd=self.root, input=input)
        if out.returncode != 0:
            raise Refused(f"tg {' '.join(cmd[:2])} failed: {out.stderr.strip()}", 1)
        return json.loads(out.stdout or "null")

    def claude(self, *cmd, check=True):
        out = sh(["claude", *cmd], cwd=self.root)
        if check and out.returncode != 0:
            raise Refused(f"claude {cmd[0]} failed: {out.stderr.strip() or out.stdout.strip()}", 1)
        return out

    def git(self, *cmd, cwd=None, check=True):
        out = sh(["git", "-C", cwd or self.root, *cmd])
        if check and out.returncode != 0:
            raise Refused(f"git {' '.join(cmd[:2])} failed: {out.stderr.strip()}", 1)
        return out

    # --- code host (pr mode only; local mode never builds one)

    @property
    def pr_mode(self):
        return self.config["merge"]["mode"] == "pr"

    def host_class(self):
        remote = self.config["merge"]["remote"]
        out = self.git("remote", "get-url", remote, check=False)
        if out.returncode != 0:
            raise Refused(f"merge.remote {remote} is not a git remote here; git remote -v lists them")
        return codehost.pick(self.config, out.stdout.strip()), out.stdout.strip()

    def host(self):
        if self._host is None:
            cls, url = self.host_class()
            self._host = cls(host_sh, self.root, self.config["merge"]["remote"], url)
        return self._host

    def label(self, number):
        return self.host_class()[0].label(number)

    def target(self, task):
        """The branch the task merges into: its target meta, merge.base, else the host's default branch."""
        meta = task.get("meta") or {}
        if meta.get("target"):
            return str(meta["target"])
        if self.config["merge"]["base"]:
            return self.config["merge"]["base"]
        if self._default is None:
            self._default = self.host().default_branch()
        return self._default

    def target_ref(self, task, target=None):
        """The ref a change is compared with: the fetched remote branch in pr mode, else HEAD."""
        if not self.pr_mode:
            return "HEAD"
        branch, remote = target or self.target(task), self.config["merge"]["remote"]
        if branch not in self._fetched:
            out = self.git("fetch", remote, branch, check=False)
            if out.returncode != 0:
                raise Refused(f"git fetch failed: {out.stderr.strip()}", 1)
            self._fetched.add(branch)
        return f"{remote}/{branch}"

    def set_meta(self, task, **meta):
        """Write meta to Taskgraph and to the task dict this command is holding."""
        self.edit_meta(task["id"], **meta)
        task.setdefault("meta", {}).update(meta)

    def add_result(self, tid, kind, attempt, by, status, body):
        return self.tg("result", "add", str(tid), "--kind", kind, "--attempt", str(attempt), "--by", by,
                       "--status", status, "--body-file", "-", input=body)

    def edit_meta(self, tid, **meta):
        self.tg("edit", str(tid), "--meta", *[meta_arg(k, v) for k, v in meta.items()])

    # --- data

    def show(self, tid):
        return self.tg("show", str(tid))

    def results_for(self, tid):
        return self.tg("result", "ls", str(tid)) or []

    def sessions(self):
        if self._sessions is None:
            out = self.claude("agents", "--json", "--all")
            try:
                rows = json.loads(out.stdout or "[]")
            except ValueError:
                raise Refused("claude agents failed: output is not JSON", 1)
            if not isinstance(rows, list):
                raise Refused("claude agents failed: output is not a list", 1)
            index = {}  # session id -> (task id, kind, attempt, worktree name), from the `sessions` meta run.py wrote
            for task in self.tg("ls", "--status", "open", "in_progress", "done") or []:
                entries = (task.get("meta") or {}).get("sessions")
                for entry in entries if isinstance(entries, list) else []:
                    if isinstance(entry, dict) and entry.get("id"):
                        index[str(entry["id"])] = (task["id"], entry.get("kind"), entry.get("attempt"),
                                                   entry.get("worktree") or f"task-{task['id']}")
            self._sessions = [Session(r, self.wt_dir, index) for r in rows if isinstance(r, dict)]
        return self._sessions

    def orders(self):
        path = os.path.join(self.run_dir, "standing-orders.md")
        text = strip_comments(open(path).read()) if os.path.isfile(path) else ""
        text = re.sub(r"(?m)^# .*$", "", text).strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        stop = lines[0] if lines and re.match(r"^(\d+\.\s*)?STOP\b", lines[0]) else None
        merge = any(re.match(r"^(\d+\.\s*)?MERGE:", line) for line in lines)
        return Orders(text or "None yet.", stop, merge)

    def now(self):
        tz = self.config["sessions"]["timezone"]
        label = self.config["sessions"]["timezone_label"] or tz
        return f"{datetime.datetime.now(ZoneInfo(tz)):%Y-%m-%d %H:%M} {label}"

    def zone_time(self, stamp):
        if not stamp:
            return None
        tz = self.config["sessions"]["timezone"]
        label = self.config["sessions"]["timezone_label"] or tz
        moment = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(ZoneInfo(tz))
        return f"{moment:%Y-%m-%d %H:%M} {label}"

    # --- output

    def emit(self, event, task=None, attempt=None, session=None, detail="", next=None):
        self.events.append({"event": event, "task": task, "attempt": attempt, "session": session,
                            "detail": detail, "next": next})

    def flush(self):
        if self.json:
            print(json.dumps(self.payload if self.payload is not None else self.events, ensure_ascii=False))
        elif self.text is not None:
            print(self.text, end="")
        else:
            for e in self.events:
                head = e["event"] + (f" #{e['task']}" if e["task"] is not None else "")
                head += f" attempt {e['attempt']}" if e["attempt"] is not None else ""
                print(f"{head}: {e['detail']}" + (f" | next: {e['next']}" if e["next"] else ""))


class Orders:
    def __init__(self, text, stop_line, merge):
        self.text, self.stop_line, self.merge = text, stop_line, merge

    @property
    def stop(self):
        return self.stop_line is not None


class Session:
    """One row of `claude agents --json --all`, tied to a task.

    A row is tied by its session id when run.py recorded the id in the task's
    `sessions` meta (`index`). A live or finished row that is not recorded is tied
    by its working directory, a worktree folder inside this repository's
    .claude/worktrees/; a task folder is shared by every attempt, so its attempt is
    None. A stopped row (what `claude stop` leaves) has no status and the
    repository root as its directory: only a recorded id ties it. Names never count."""

    def __init__(self, row, wt_dir, index):
        self.row = row
        self.sid = str(row.get("id") or "")
        self.name = row.get("name") or ""
        self.cwd = row.get("cwd") or ""
        self.status = row.get("status")
        self.state = row.get("state")
        self.waiting = row.get("waitingFor")
        self.kind = self.task_id = self.attempt = self.wtname = None
        known = index.get(self.sid) if self.sid else None
        self.recorded = known is not None
        if known:
            self.task_id, self.kind, self.attempt, self.wtname = known
        elif self.state != "stopped" and self.cwd:
            real = os.path.realpath(self.cwd)
            folder = os.path.basename(real)
            if os.path.dirname(real) == wt_dir:
                if m := TASK_WT.match(folder):
                    self.kind, self.task_id, self.wtname = "task", int(m.group(1)), folder
                elif m := VERIFY_WT.match(folder):
                    self.kind, self.task_id, self.attempt, self.wtname = "verify", int(m.group(1)), int(m.group(2)), folder
        # A row with state "stopped", or state "done" with status idle or none, has ended. (A `claude rm` that
        # refuses still ends the session and leaves a "done" row with no status.) idle/blocked and the like
        # stay live: the session asked the user.
        self.finished = self.state == "stopped" or (self.state == "done" and self.status in ("idle", None, ""))
        self.live = not self.finished
        self.stuck = self.live and (bool(self.waiting) or self.state == "blocked")
        self.unknown = self.live and not self.stuck and self.status != "busy"

    def worktree(self, root):
        """The worktree path, derived from the folder name, never from the row."""
        return os.path.join(root, ".claude", "worktrees", self.wtname)

    def describe(self):
        return f"{self.sid} ({self.name}, {self.status}/{self.state})"


def own_sessions(run, tid, kind=None, attempt=None):
    """The task's session rows. A row with no attempt (an unrecorded one in the shared task folder) is the
    current attempt's, so it matches any attempt."""
    return [s for s in run.sessions() if s.task_id == tid and (kind is None or s.kind == kind)
            and (attempt is None or s.attempt is None or s.attempt == attempt)]


def live_count(run):
    return sum(1 for s in run.sessions() if s.kind and s.live)


def wanted_attempt(task):
    value = (task.get("meta") or {}).get("attempt")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_legacy(task):
    """A task in progress with an attempt and no `sessions` meta was started under agentic-team 0.6.0."""
    return (task["status"] == "in_progress" and (wanted_attempt(task) or 0) >= 1
            and "sessions" not in (task.get("meta") or {}))


LEGACY_NEXT = ("finish it with 0.6.0 before you upgrade; or, once its session has ended and its result is filed, "
               "tg edit {tid} --meta sessions='[]' and run.py record")


def legacy_detail(task):
    n = wanted_attempt(task)
    return (f"started under agentic-team 0.6.0 (worktree .claude/worktrees/task-{task['id']}-{n}); "
            "run.py does not manage it")


def refuse_legacy(task):
    if is_legacy(task):
        raise Refused(f"#{task['id']} attempt {wanted_attempt(task)}: {legacy_detail(task)}; "
                      + LEGACY_NEXT.format(tid=task["id"]))


# ------------------------------------------------- shared result predicates

def is_worker_result(r):
    """A report from a worker: not DIED, STOPPED, or ABANDONED, not the Manager's BLOCKED note.

    A report the Manager salvaged from the logs keeps the worker's status and counts."""
    return (r["kind"] == "task" and r["status"] not in ("DIED", "STOPPED", "ABANDONED")
            and not (r["status"] == "BLOCKED" and r.get("author") == "manager"))


def task_rows(rows, attempt=None, kind="task"):
    return [r for r in rows if r["kind"] == kind and (attempt is None or r.get("attempt") == attempt)]


def latest_worker(rows, attempt=None):
    found = [r for r in rows if is_worker_result(r) and (attempt is None or r.get("attempt") == attempt)]
    return found[-1] if found else None


def verifier_rows(rows, attempt):
    return [r for r in task_rows(rows, attempt, "verify") if r.get("author") != "manager"]


def verdict_of(row):
    match = VERDICT_LINE.search(row.get("body") or "")
    return match.group(1) if match else None


def arrived(task, rows):
    """The current attempt has a result that is not a pause marker, and no verdict is recorded."""
    attempt = wanted_attempt(task)
    latest = task_rows(rows, attempt)
    return bool(attempt is not None and latest and latest[-1]["status"] != "STOPPED"
                and not (task.get("meta") or {}).get("verdict"))


def unclosed(task):
    return task["status"] == "in_progress" and bool((task.get("meta") or {}).get("verdict"))


def unmerged(task):
    meta = task.get("meta") or {}
    return task["status"] == "done" and is_sha(meta.get("verdict_ref")) and not meta.get("merged_at")


def unclosed_next(task_id, verdict, kind="code"):
    if verdict == "verify-blocked":
        return f"retry the check when its cause is fixed, then run.py close {task_id}"
    if verdict == "verify-failed":
        return f"fix round: run.py launch {task_id}"
    if verdict == "test-verified" and verdict not in PASSING[kind]:
        return (f"test-verified does not close a {kind} task; run.py verify {task_id} --again for artifact-verified, "
                f'or run.py close {task_id} --verdict artifact-verified --override-verifier "<why>" --ran "<run id or URL>"')
    if verdict == "check-only":
        return f"run.py verify {task_id} --again for a stronger verdict, or accept it"
    return f"run run.py close {task_id}"


class Snapshot:
    """Taskgraph state that `record` and `status` both read."""

    def __init__(self, run):
        everything = run.tg("ls", "--status", "open", "in_progress", "done") or []
        self.by_id = {t["id"]: t for t in everything}
        self.in_progress = [t for t in everything if t["status"] == "in_progress" and t["type"] == "task"]
        self.done = [t for t in everything if t["status"] == "done" and t["type"] == "task"]
        self.results = {}
        for row in run.tg("result", "ls") or []:
            self.results.setdefault(row["task_id"], []).append(row)
        self.decisions = run.tg("ls", "--type", "decision", "--status", "open", "in_progress") or []
        self.ready = run.tg("ready") or []

    def rows(self, tid):
        return self.results.get(tid, [])

    def waiting_decisions(self, task):
        open_ids = {d["id"] for d in self.decisions}
        return [d for d in task.get("waits_for") or [] if d in open_ids]

    def ready_tasks(self):
        """(ready task ids, [(task id, unmerged dependency id)])"""
        free, waits = [], []
        for task in (t for t in self.ready if t["type"] == "task"):
            behind = [d for d in task.get("depends_on") or []
                      if d in self.by_id and unmerged(self.by_id[d])]
            if behind:
                waits.append((task["id"], behind[0]))
            else:
                free.append(task["id"])
        return free, waits


def ids_text(ids):
    return " ".join(f"#{i}" for i in ids) or "none"


# ------------------------------------------------------------------- brief

def parse_notes(notes):
    goal, acceptance = [], []
    for line in (notes or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if m := CHECK_ITEM.match(line):
            acceptance.append(m.group(1).strip())
        elif m := FIELD_LINE.match(stripped):
            if m.group(2).strip():
                acceptance.append(m.group(2).strip())
        elif not stripped.startswith("#"):
            goal.append(stripped)
    return " ".join(goal), acceptance


def describe_result(result):
    attempt = f", attempt {result['attempt']}" if result.get("attempt") is not None else ""
    return f"result #{result['id']}, {result['status']}{attempt}"


def result_command(py, tg, db, project, task_id, kind, attempt, session):
    """The command the worker runs last. The worker fills in only the status and the body."""
    return (f"{quote(py)} {quote(tg)} --db {quote(db)} --project {shlex.quote(project)} "
            f"result add {task_id} --kind {kind} --attempt {attempt} --by {shlex.quote(session)} "
            f"--status <STATUS> --body-file - <<'REPORT'\n<your report>\nREPORT")


def render(run, task, kind, attempt, session, ref=None, worker=None, base=None, retry=False):
    """The brief text. Taskgraph is the only source of task content."""
    tid = task["id"]
    meta = task.get("meta") or {}
    tg_cmd = f"{quote(sys.executable)} {quote(run.tg_path)} --db {quote(run.db)} --project {shlex.quote(run.project)}"
    edit = f"{tg_cmd} edit {tid}"
    why, acceptance = parse_notes(task.get("notes"))
    missing = []
    if not why:
        missing.append(f"GOAL: add a sentence on why the task is needed to its notes ({edit} --notes ...)")
    if not acceptance:
        missing.append(f"ACCEPTANCE: add `- [ ]` items or an `Exit test:` line to its notes ({edit} --notes ...)")
    if not str(meta.get("scope", "")).strip():
        missing.append(f'SCOPE: {edit} --meta scope="<paths it may write; paths it may not>"')
    if not str(meta.get("verify", "")).strip():
        missing.append(f'VERIFY: {edit} --meta verify="<exact commands or checks>"')
    if missing:
        raise Refused(f"task {tid} is not scoped; fix it in Taskgraph, then rerun:\n  " + "\n  ".join(missing))
    try:
        timebox = f"{float(meta['estimate']) * 2:g} hours (twice the {meta['estimate']}-hour estimate)"
    except (KeyError, TypeError, ValueError):
        timebox = f"{DEFAULT_TIMEBOX_HOURS} hours (no estimate set)"
    config = run.config
    forbidden = [f"- {item}" for item in config["constraints"]["forbidden"] if item.strip()]
    orders = run.orders()
    values = {
        "TASK_ID": str(tid),
        "TASK_TITLE": task["title"],
        "PROJECT": run.project,
        "TIMEZONE": config["sessions"]["timezone_label"] or config["sessions"]["timezone"],
        "TASKGRAPH_COMMAND": tg_cmd,
        "ACCEPTANCE": "\n".join(f"- {item}" for item in acceptance),
        "VERIFY": str(meta["verify"]).strip(),
        "TIMEBOX": timebox,
        "FORBIDDEN": "\n".join(forbidden) or "None beyond the worker rules.",
        "STANDING_ORDERS": orders.text,
        "RESULT_COMMAND": result_command(sys.executable, run.tg_path, run.db, run.project, tid, kind, attempt, session),
    }
    if kind == "verify":
        vkind = verify_kind(run, task)
        setup = (f"Output under review: {ref}. Your worktree is already at `{ref}`. Do not check out another "
                 f"commit. If `git rev-parse HEAD` is not `{ref}`, report BLOCKED."
                 if is_sha(ref) else
                 f"Output under review: {ref}. If it is a list of checksums, the output is outside git: compare "
                 "the files against the checksums and check nothing out.")
        if is_sha(ref):
            base_sha, how = verify_base(run, task, ref)
            if base_sha:
                setup += ("\n- " + f"Base commit: {base_sha} ({how}). Head commit: {ref}. The change under review is "
                          f"`git diff {base_sha} {ref}`; `git log --oneline {base_sha}..{ref}` lists its commits. To run "
                          f'anything at the base commit, export it read only: `git archive {base_sha} | tar -x -C '
                          '"$(mktemp -d)"`, install what the run needs there (the export holds tracked files only), '
                          "work in that folder, and delete it before you report. Never check out, reset, or add a "
                          "worktree.")
            else:
                setup += ("\n- " + f"Base commit: unknown ({how}). Head commit: {ref}. Judge the head against ACCEPTANCE "
                          "alone; skip the steps that need the base commit and say so under Ran:.")
        else:
            setup += ("\n- Base commit: none; the output is outside git. Skip the steps that need the base commit and "
                      "say so under Ran:.")
        with open(os.path.join(PLUGIN_ROOT, "templates", f"verify-{vkind}.md")) as fh:
            method = fh.read().strip()
        where, place = verify_skill(run, ref)
        use = ("Its sections say how to prove this project's artifacts: Launch, Doctor, Drive, Evidence and Cleanup "
               "for a code change; Sources, Recompute, Consistency, Render and Review for a schema or a design "
               "document. Use them to carry out the method below, and collect the evidence they name for each "
               "ACCEPTANCE line. The skill never lifts a rule in your agent instructions or in FORBIDDEN.")
        if where == "head":
            skill = (f"### Project verify skill\n\n`{place}`, in your worktree. Read it by that path before you run "
                     f"anything. {use}")
        elif where == "root":
            skill = (f"### Project verify skill\n\n`{place}` (the main checkout; the output under review has none). "
                     f"Read it by that path, read only, before you run anything; write nothing there. {use}")
        else:
            skill = ("### Project verify skill\n\nNone: no `.claude/skills/verify/SKILL.md` at the output under review "
                     "or in the main checkout. Follow the method below with what the repository shows. Report the "
                     "highest level you can prove, and say under `Ran:` which step of the method you could not carry "
                     "out without the skill (for example: no launch recipe, so the application was not driven). The "
                     "operator creates the skill with /agentic-team:setup.")
        values.update({
            "GOAL": (f"Judge whether the output of task {tid} ({task['title']}) meets every ACCEPTANCE line. "
                     "Check the real artifact, not the worker's report. Do not fix anything."),
            "SCOPE": "Read only. You run in your own worktree. Change nothing: do not edit, commit, or delete anything.",
            "SETUP": setup,
            "CHECKPOINT": "None",
            "UPSTREAM": (f"### Worker report ({describe_result(worker)})\n\n"
                         f"{strip_comments(worker['body']).strip()}"),
            "VERIFY": values["VERIFY"] + "\n\n" + skill + "\n\n" + method,
            "AUTONOMY": "- None. You judge the output; you decide nothing.",
            "REPORT_NOTE": ("Add a `Verdict:` line after `Status:`: artifact-verified, test-verified, check-only, "
                            "verify-blocked, or verify-failed."),
        })
    else:
        rows = run.results_for(tid)
        previous = latest_worker(rows)
        upstream, checkpoint = [], "None"
        if previous:
            if m := CHECKPOINT_LINE.search(previous["body"]):
                checkpoint = m.group(1).strip() or "None"
            upstream.append(f"### Previous attempt ({describe_result(previous)})\n\n"
                            "Start from this report. Fix what it lists; do not redo what passed.\n\n"
                            f"{strip_comments(previous['body']).strip()}")
        for dep in task.get("depends_on") or []:
            node = run.show(dep["id"])
            if node["type"] == "decision":
                upstream.append(f"### Decision #{dep['id']}: {dep['title']} ({dep['status']})\n\n"
                                f"{strip_comments(node.get('notes') or '').strip() or 'No notes on file.'}")
                continue
            found = [r for r in run.results_for(dep["id"]) if is_worker_result(r)]
            body = (f"{describe_result(found[-1])}\n\n{strip_comments(found[-1]['body']).strip()}"
                    if found else "No report on file.")
            upstream.append(f"### Upstream #{dep['id']}: {dep['title']} ({dep['status']})\n\n{body}")
        autonomy = config["autonomy"]
        values.update({
            "GOAL": f"{task['title']}. {why}",
            "SCOPE": str(meta["scope"]).strip(),
            "SETUP": (f"Attempt {attempt}. Your worktree is at `{base}` on branch `{task_branch(tid)}`. It holds the "
                      "commits of the earlier attempts of this task. Read the previous report under UPSTREAM and build "
                      "on it; do not redo what passed. Do not reset the worktree or check out another commit. If "
                      f"`git rev-parse HEAD` is not `{base}`, report BLOCKED and change nothing."
                      if retry else
                      f"Base commit: {base}. Your worktree is already at the base commit `{base}`, on branch "
                      f"`{task_branch(tid)}`. Do not reset it or check out another commit. If "
                      f"`git rev-parse HEAD` is not `{base}`, report BLOCKED and change nothing."),
            "CHECKPOINT": checkpoint,
            "UPSTREAM": "\n\n".join(upstream),
            "AUTONOMY": (f"- Standing grant: {autonomy['grant'] or 'None. Report product decisions as BLOCKED.'}\n"
                         f"- Always pause for: {'; '.join(autonomy['always_pause']) or 'None'}"),
            "REPORT_NOTE": "",
        })
    path = os.path.join(PLUGIN_ROOT, "templates", "task-brief.md")
    with open(path) as fh:
        template = fh.read()
    assert "{{RESULT_COMMAND}}" in template, f"{path} has no RESULT_COMMAND; the worker could not report"
    text = re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: values.get(m.group(1), m.group(0)), template)
    return re.sub(r"[ \t]+(?=\n)", "", re.sub(r"\n{3,}", "\n\n", text))


def write_brief(run, name, text):
    path = os.path.join(run.run_dir, "briefs", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    return path


def session_args(run, worktree, name, model, effort):
    cmd = ["--bg", "--worktree", worktree, "--agent", "agentic-team:worker", "--model", model]
    if effort:
        cmd += ["--effort", effort]
    return cmd + ["--permission-mode", run.config["sessions"]["permission_mode"], "--name", name]


def start_session(run, worktree, name, model, effort, text):
    """Run `claude --bg`. Returns what it printed."""
    out = run.claude(*session_args(run, worktree, name, model, effort), text, check=False)
    if out.returncode != 0:
        message = out.stderr.strip() or out.stdout.strip()
        if "not trusted" in message:
            message += "\n" + TRUST_HINT
        if any(word in message for word in ("Operation not permitted", "EPERM", "Read-only file system")):
            message += "\n" + SANDBOX_HINT
        raise Refused(message, 1)
    return out.stdout.strip()


def registered_worktrees(run):
    """Real paths of the worktrees git has registered, including stale ones whose folder is gone."""
    out = run.git("worktree", "list", "--porcelain", check=False).stdout
    return {os.path.realpath(line[len("worktree "):]) for line in out.splitlines() if line.startswith("worktree ")}


def commit_of(run, ref):
    out = run.git("rev-parse", "--verify", "-q", f"{ref}^{{commit}}", check=False)
    return out.stdout.strip() if out.returncode == 0 else None


def add_worktree(run, name, ref):
    """Create .claude/worktrees/<name> on branch worktree-<name> at ref, where `claude --bg --worktree <name>`
    reuses it. An existing branch or folder is refused, never reused or reset."""
    path, branch = os.path.join(run.wt_dir, name), f"worktree-{name}"
    rel, facts, steps = f".claude/worktrees/{name}", [], []
    registered = path in registered_worktrees(run)
    if os.path.lexists(path):
        if registered:
            facts.append(f"folder {rel} is a git worktree")
            steps.append(f"`git worktree remove {rel}`")
        else:
            facts.append(f"folder {rel} is a plain folder, not a git worktree")
            steps.append(f"move or delete {rel} yourself")
    elif registered:
        facts.append(f"{rel} is a stale worktree registration (the folder is gone)")
        if path in worktree_locks(run):  # prune skips a locked registration
            steps.append(f"`git worktree unlock {rel}`")
        steps.append("`git worktree prune`")
    tip = commit_of(run, f"refs/heads/{branch}")
    if tip:
        want = commit_of(run, ref)
        count = run.git("rev-list", "--count", f"{want or ref}..{branch}", check=False)
        short = (want or ref)[:7]
        if tip == want:
            note = f"is at {short}; nothing is on it"
        elif count.returncode == 0 and count.stdout.strip() == "0":
            note = f"holds no commits beyond {short}; nothing is on it"
        elif count.returncode == 0:
            note = (f"holds {count.stdout.strip()} commit{'s' * (count.stdout.strip() != '1')} beyond {short}; "
                    "remove it only if you do not need them")
        else:
            note = "exists"
        facts.append(f"branch {branch} {note}")
        if not (registered and not os.path.lexists(path)):  # `branch -D` fails until the stale registration is pruned
            steps.append(f"`git branch -D {branch}`")
    if facts:
        raise Refused("; ".join(facts) + ". Nothing was created. To reuse this name: "
                      + ", then ".join(steps) + ", then rerun.")
    out = run.git("worktree", "add", "-q", "-b", branch, path, ref, check=False)
    if out.returncode != 0:
        raise Refused(f"git worktree add failed: {out.stderr.strip() or out.stdout.strip()}", 1)


def remove_worktree(run, name, ref):
    """Undo add_worktree after a failed start, only when nothing else lives there. Returns None when it
    removed them, else why it kept them. Best effort: the caller reports the original error."""
    path, branch = os.path.join(run.wt_dir, name), f"worktree-{name}"
    want = commit_of(run, ref)
    if not want or commit_of(run, f"refs/heads/{branch}") != want:
        return f"branch {branch} is no longer at {(want or ref)[:7]}"
    if os.path.isdir(path) and run.git("status", "--porcelain", cwd=path, check=False).stdout.strip():
        return "it has uncommitted changes"
    run._sessions = None  # the failed start may have left a row
    try:
        real = os.path.realpath(path)
        if any(s.cwd and os.path.realpath(s.cwd) == real for s in run.sessions()):
            return "a session row uses it"
    except Refused:
        pass  # claude may be what failed; the checks above still held
    run.git("worktree", "remove", "--force", path, check=False)
    run.git("branch", "-D", branch, check=False)
    return None


def started_or_cleaned(run, name, ref, exc, created=True):
    """Called when the brief or `claude --bg` failed. When this launch created the worktree it removes it if
    that is safe, then raises the original error, with a note when the worktree stays. A worktree this launch
    only reused holds earlier attempts: nothing is removed."""
    if not created:
        raise exc
    kept = remove_worktree(run, name, ref)
    if kept is None:
        raise exc
    raise Refused(f"{exc}\nkept .claude/worktrees/{name}: {kept}", getattr(exc, "code", 1)) from exc


def drift_warning(run, name, ref, branch=True):
    """"" when the session's worktree is still at ref (and on its branch), else the warning for the event."""
    path = os.path.join(run.wt_dir, name)
    head = run.git("rev-parse", "HEAD", cwd=path, check=False).stdout.strip()
    on = run.git("branch", "--show-current", cwd=path, check=False).stdout.strip() == f"worktree-{name}"
    if head and head == commit_of(run, ref) and (on or not branch):
        return ""
    return f"the session's worktree is not at {ref[:7]}; claude may no longer reuse a prepared worktree"


def detached_or_wrong(run, wt, rel, on, branch):
    """The refusal for a task worktree that is not on its branch, with a fix that loses no commit."""
    if on:
        return f"{rel} is on {on}, not {branch}; run git -C {rel} switch {branch}"
    head = run.git("rev-parse", "HEAD", cwd=wt, check=False).stdout.strip()
    tip = commit_of(run, f"refs/heads/{branch}")
    if not tip:
        return f"{rel} is on a detached HEAD at {head[:7]} and {branch} does not exist; run git -C {rel} switch -c {branch}"
    if head == tip or run.git("merge-base", "--is-ancestor", tip, head, check=False).returncode == 0:
        return (f"{rel} is on a detached HEAD at {head[:7]}, which holds {branch} (at {tip[:7]}); "
                f"run git -C {rel} switch -C {branch} (this keeps the commits)")
    return (f"{rel} is on a detached HEAD at {head[:7]}, which is not built on {branch} (at {tip[:7]}). Both hold "
            f"commits the other lacks, so a plain switch would lose one: keep the detached commit with "
            f"git -C {rel} branch <name> {head[:7]}, then decide which one {branch} should be")


def last_head(run, rows, attempt=None):
    """(commit, attempt) of the latest worker or STOPPED result whose Head: is a commit in this repository."""
    for r in reversed(rows):
        if r["kind"] != "task" or not (is_worker_result(r) or r["status"] == "STOPPED"):
            continue
        if attempt is not None and r.get("attempt") != attempt:
            continue
        match = HEAD_LINE.search(r.get("body") or "")
        full = commit_of(run, match.group(1)) if match else None
        if full:
            return full, r.get("attempt")
    return None


def resolve_base(run, ref):
    """(sha, target branch or None) for --base: a commit or a branch of this repository."""
    out = run.git("rev-parse", "--verify", "-q", f"{ref}^{{commit}}", check=False)
    if out.returncode != 0:
        raise Refused(f"--base {ref} is not a commit or branch in this repository; fetch it first")
    remote = run.config["merge"]["remote"]
    for full, branch in ((f"refs/heads/{ref}", ref), (f"refs/remotes/{ref}", ref.split("/", 1)[-1]),
                         (f"refs/remotes/{remote}/{ref}", ref)):
        if run.git("rev-parse", "--verify", "-q", full, check=False).returncode == 0:
            return out.stdout.strip(), branch
    return out.stdout.strip(), None


def check_cap(run):
    live, cap = live_count(run), run.config["sessions"]["max_parallel"]
    if live >= cap:
        raise Refused(f"cap full: {live}/{cap} sessions live; run run.py record and refill after it")


def waiting_for(run, task):
    blockers = []
    for wid in task.get("waits_for") or []:
        node = run.show(wid)
        if node["derived_status"] != "done":
            blockers.append(f"#{wid}" + (f" ({node['type']})" if node["type"] != "task" else ""))
    return blockers


# ------------------------------------------------- verify_mode, change id

def verify_mode(run, task):
    """"session" or "ci:<name>". Refuses any other value, and ci outside pr mode."""
    value = (task.get("meta") or {}).get("verify_mode")
    if value is None or value == "session":
        return "session"
    text = str(value)
    if not (text.startswith("ci:") and text[3:].strip()):
        raise Refused(f'#{task["id"]} verify_mode must be "session" or "ci:<workflow>" '
                      f'(GitLab: "ci:pipeline" or "ci:<job>"), not {text}')
    if not run.pr_mode:
        raise Refused('verify_mode=ci needs merge.mode = "pr"; the run must be on a pushed branch')
    return text


def verify_kind(run, task, strict=True):
    """"code", "schema" or "design-doc": the task's verify_kind meta, else verify.kind from the config.
    strict refuses any other value; record passes strict=False and falls back to the config default."""
    value = (task.get("meta") or {}).get("verify_kind")
    if value is None or value == "":
        return run.config["verify"]["kind"]
    text = str(value)
    if text in VERIFY_KINDS:
        return text
    if not strict:
        return run.config["verify"]["kind"]
    raise Refused(f'#{task["id"]} verify_kind must be "code", "schema" or "design-doc", not {text}')


def verify_base(run, task, head):
    """(sha, how) for the verifier brief: the task's base meta when it is an ancestor of head, else the merge
    base of head with the target; (None, reason) when neither exists."""
    meta_base = str((task.get("meta") or {}).get("base") or "")
    if meta_base and run.git("merge-base", "--is-ancestor", meta_base, head, check=False).returncode == 0:
        return commit_of(run, meta_base), "the task's base meta"
    try:
        target = run.target_ref(task)
    except Refused as exc:
        return None, f"the target branch could not be fetched: {exc}"
    out = run.git("merge-base", head, target, check=False)
    if out.returncode == 0 and out.stdout.strip():
        return out.stdout.strip(), f"merge base with {target}"
    return None, f"no base meta is an ancestor of {head[:7]}, and it has no merge base with {target}"


def verify_skill(run, ref):
    """Where the project verify skill is: ("head", relative path) when the commit under review holds it,
    ("root", absolute path) when only the main checkout holds it, (None, "") when neither does. A checksum
    ref has no commit, so the checkout decides."""
    rel = VERIFY_SKILL.replace(os.sep, "/")
    if is_sha(ref) and run.git("cat-file", "-e", f"{ref}:{rel}", check=False).returncode == 0:
        return "head", rel
    path = os.path.join(run.root, VERIFY_SKILL)
    if os.path.isfile(path):
        return "root", path
    return None, ""


def change_id(run, base, tip):
    """A hash of the change base..tip that survives a rebase: the -U0 diff without
    line numbers or blob ids. A binary file keeps its index line."""
    out = subprocess.run(["git", "-C", run.root, "diff", "-U0", "--no-color", "--no-ext-diff", "--no-renames", base, tip],
                         capture_output=True, text=True, errors="surrogateescape")
    if out.returncode != 0:
        raise Refused(f"git diff failed: {first_line(out.stderr)}", 1)
    kept = []
    for block in re.split(r"(?m)^(?=diff --git )", out.stdout):
        lines = block.splitlines(keepends=True)
        binary = any(line.startswith("Binary files ") for line in lines)
        for line in lines:
            if line.startswith("index ") and not binary:
                continue
            kept.append("@@\n" if re.match(r"@@ -\d+(,\d+)? \+\d+(,\d+)? @@", line) else line)
    return hashlib.sha256("".join(kept).encode("utf-8", "surrogateescape")).hexdigest()


def same_change(run, task, old_head, new_head, ref=None):
    """(True, "") when new_head carries the same change as old_head, else (False, reason).
    `ref` is what the change is compared with; the default is run.target_ref(task)."""
    ref = ref or run.target_ref(task)
    base_new = run.git("merge-base", new_head, ref, check=False).stdout.strip()
    if not base_new:
        return False, f"{new_head[:7]} shares no history with {ref}"
    if run.git("cat-file", "-e", f"{old_head}^{{commit}}", check=False).returncode != 0:
        return False, f"the verified commit {old_head} is gone"
    # Two spans of the old change. The merge base with the target covers every attempt on the branch and
    # survives repeated rebases. The attempt's base meta covers a stacked task (--base a dependency's
    # branch) whose dependency was merged and dropped by the rebase. Either may match the new span.
    bases = [run.git("merge-base", old_head, ref, check=False).stdout.strip()]
    meta_base = (task.get("meta") or {}).get("base")
    if meta_base and run.git("merge-base", "--is-ancestor", meta_base, old_head, check=False).returncode == 0:
        bases.append(meta_base)
    bases = [b for i, b in enumerate(bases) if b and b not in bases[:i]]
    if not bases:
        return False, "no base meta"
    try:
        new_id = change_id(run, base_new, new_head)
        same = any(change_id(run, base, old_head) == new_id for base in bases)
    except Refused as exc:
        return False, str(exc)
    return (True, "") if same else (False, "different diff")


def open_blocks(task, snap=None):
    """Ids of the tasks that wait on this one and are not done."""
    found = []
    for b in task.get("blocks") or []:
        if isinstance(b, dict):  # from `tg show`
            if b["derived_status"] != "done":
                found.append(b["id"])
        elif snap is None or b not in snap.by_id or snap.by_id[b]["status"] != "done":  # from `tg ls`
            found.append(b)
    return found


def decision_text(text, task, snap=None, extra=""):
    blocks = open_blocks(task, snap)
    return f'tg add "{text}" --type decision --meta decider=operator{extra}' + (f" --blocks {' '.join(map(str, blocks))}" if blocks else "")


# ------------------------------------------------------------------ launch

def session_entry(run, tid, kind, attempt, name, worktree, said):
    """(entry, note) for the session `claude --bg` just started. The entry is what goes into the task's
    `sessions` meta, or None when no id is known. It never fails the launch: the session runs.

    A row that is not recorded yet and is live in the folder can be the session just started; a finished
    one cannot."""
    run._sessions = None
    try:
        rows = run.sessions()
    except Refused:
        rows = []
    match = BACKGROUNDED.search(said or "")
    printed = match.group(1) if match else None
    fresh = [s for s in rows if not s.recorded and s.live and s.task_id == tid
             and s.kind == kind and s.wtname == worktree]
    if printed and any(s.sid == printed for s in rows):
        sid, note = printed, ""
    elif len(fresh) == 1:
        sid = fresh[0].sid
        note = (f"claude printed {printed}; recorded the row {sid} found in the worktree" if printed else
                f"no session id printed; recorded the row {sid} found in the worktree")
    elif printed:
        sid, note = printed, f"claude agents does not list {printed} yet"
    else:
        return None, "no session id printed; the row is matched by its folder"
    return {"id": sid, "kind": kind, "attempt": attempt, "name": name, "worktree": worktree}, note


def recorded_sessions(task):
    found = (task.get("meta") or {}).get("sessions")
    return [e for e in found if isinstance(e, dict)] if isinstance(found, list) else []


def cmd_launch(run, args):
    tid = args.id
    orders = run.orders()
    if orders.stop:
        raise Refused(f"standing orders say {orders.stop_line!r}; launch nothing", 3)
    if args.keyword and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", args.keyword):
        raise Refused(f"keyword {args.keyword!r} may hold letters, digits, and hyphens only")
    task = run.show(tid)
    meta = task.get("meta") or {}
    if task["type"] != "task":
        raise Refused(f'#{tid} is a {task["type"]}, not a task; a decision is answered with '
                      f'tg edit {tid} --notes "<answer>", then tg done {tid}')
    if task["derived_status"] == "done":
        raise Refused(f"#{tid} is done")
    refuse_legacy(task)
    verify_mode(run, task)
    verify_kind(run, task)
    blockers = waiting_for(run, task)
    if blockers:
        raise Refused(f"#{tid} waits for {' '.join(blockers)}; finish or decide them first")
    current = wanted_attempt(task) or 0
    if meta.get("abandoned") and not args.attempt:
        raise Refused(f"#{tid} is abandoned ({meta['abandoned']}); pass --attempt {current + 1} to try again")
    given, given_target = resolve_base(run, args.base) if args.base else (None, None)
    retry = current >= 1  # the task has a worktree, or had one
    wt, branch = task_worktree(run, tid), task_branch(tid)
    rel = f".claude/worktrees/task-{tid}"
    wt_there = retry and os.path.lexists(wt)
    wt_head = (run.git("rev-parse", "HEAD", cwd=wt, check=False).stdout.strip()
               if wt_there and os.path.isdir(wt) else "")
    holds = wt_head or given  # the commit the worker builds on
    for dep in task.get("depends_on") or []:
        if dep["derived_status"] == "done" or dep["status"] == "done":
            found = run.show(dep["id"])
            dmeta = found.get("meta") or {}
            if is_sha(dmeta.get("verdict_ref")) and not dmeta.get("merged_at"):
                if holds and run.git("merge-base", "--is-ancestor", str(dmeta["verdict_ref"]), holds, check=False).returncode == 0:
                    continue  # the worker builds on the dependency's branch
                dep_branch = (dmeta.get("pr_branch") if run.pr_mode else None) or task_branch(dep["id"])
                raise Refused(f"#{tid} depends on #{dep['id']}, whose branch {dep_branch} is not merged; merge it and run "
                              f"run.py merged {dep['id']} --by operator, wait, or pass --base <its branch>")
    live = [s for s in own_sessions(run, tid, "task") if s.live]
    if live and task["status"] == "open":
        # An earlier launch started the session but died before it recorded the start.
        s = live[0]
        if not args.dry_run:
            run.tg("start", str(tid))
            sessions = recorded_sessions(task)
            if not any(e.get("id") == s.sid for e in sessions):
                sessions.append({"id": s.sid, "kind": "task", "attempt": 1, "name": s.name or s.wtname,
                                 "worktree": f"task-{tid}"})
            run.tg("edit", str(tid), "--meta", meta_arg("session", s.name or s.wtname), meta_arg("attempt", s.attempt or 1),
                   meta_arg("started_at", run.now()), meta_arg("sessions", sessions))
        run.emit("repaired", tid, s.attempt or 1, s.sid, f"live session {s.sid} found for an open task; "
                 f"recorded the start", "run.py record")
        return
    live = [s for s in run.sessions() if s.task_id == tid and s.live]
    if live:
        raise Refused(f"#{tid} has a live session {live[0].describe()}; run run.py record, or run.py stop {tid}")
    rows = run.results_for(tid)
    latest = task_rows(rows, current)
    nxt = args.attempt or current + 1
    if latest and latest[-1]["status"] == "STOPPED" and not HEAD_ANY.search(latest[-1]["body"]):
        raise Refused(f"#{tid} attempt {current} is stopped and its WIP is not committed yet; run run.py record first")
    refuse_past_cap(tid, nxt, latest, args.attempt)
    # THE WORKTREE. A first attempt creates it at the base: --base, else the fetched target branch (pr) or HEAD
    # (local). A retry continues in it, at its HEAD. `mode` says which, and what a failed start may undo.
    notes = []
    if not retry:
        mode = "first"
        base = given or run.git("rev-parse", "--verify", f"{run.target_ref(task)}^{{commit}}").stdout.strip()
    elif wt_there:
        if os.path.realpath(wt) not in registered_worktrees(run):
            raise Refused(f"folder {rel} is a plain folder, not a git worktree; move or delete it yourself")
        on = run.git("branch", "--show-current", cwd=wt, check=False).stdout.strip()
        if on != branch:
            raise Refused(detached_or_wrong(run, wt, rel, on, branch))
        if not wt_head:
            raise Refused(f"cannot read HEAD of {rel}; check it with git -C {rel} status")
        if given:
            raise Refused(f"#{tid} continues in {rel} at {wt_head[:7]}; --base applies to a first attempt. To restart from "
                          f"{args.base}: git worktree remove -f -f {rel} && git branch -D {branch}, then rerun with --base.")
        mode, base = "continue", wt_head
        reported = last_head(run, rows, current)
        if reported and reported[0] != wt_head:
            notes.append(f"worktree HEAD {wt_head[:7]} is not the last report's Head {reported[0][:7]}")
    else:
        tip = commit_of(run, f"refs/heads/{branch}")
        reported = last_head(run, rows)
        if tip:
            if given:
                count = run.git("rev-list", "--count", f"{given}..{branch}", check=False).stdout.strip()
                holds_n = f" and holds {count} commit{'s' * (count != '1')} beyond {given[:7]}" if count.isdigit() and count != "0" else ""
                raise Refused(f"#{tid} continues on branch {branch} at {tip[:7]}{holds_n}; --base applies to a first attempt. "
                              f"To restart from {args.base} (the commits on {branch} are lost unless you keep them): "
                              f"git branch -D {branch}, then rerun with --base.")
            mode, base = "reattach", tip
        elif given:
            mode, base = "base", given
        elif reported:
            mode, base = "head", reported[0]
            notes.append(f"created at Head {base[:7]} of attempt {reported[1] or current}")
        else:
            raise Refused(f"#{tid} attempt {current} left no worktree, branch or Head in this repository; "
                          "pass --base <sha|branch>"
                          + (f" (in pr mode, --base replaces the pushed branch task-{tid})" if run.pr_mode else ""))
    base = commit_of(run, base) or base  # a full SHA for the brief, the meta and the worktree check
    continuing = mode in ("continue", "reattach", "head")
    session = f"task-{tid}-{nxt}" + (f"-{args.keyword}" if args.keyword else "")
    text = render(run, task, "task", nxt, session, base=base, retry=continuing)
    check_cap(run)
    if args.model:
        model, effort = args.model, args.effort
    else:
        try:
            chosen = resolve_model(run.config, args.tier or str(meta.get("tier") or "implementation"))
        except ConfigError as exc:
            raise Refused(str(exc))
        if not chosen["model"]:
            raise Refused("tier 'verifier' has no model; use mechanical, implementation, judgement "
                          "or a models.overrides key")
        model, effort = chosen["model"], args.effort or chosen["effort"]
    worktree = f"task-{tid}"
    if args.dry_run:
        print("claude " + " ".join(session_args(run, worktree, session, model, effort)) + " <brief>", file=sys.stderr)
        if run.json:
            run.emit("dry-run", tid, nxt, session, text)
        else:
            print(text, end="")
        return
    if mode == "continue":
        # A dirty worktree never reaches a worker silently: commit what the last attempt left.
        porcelain = run.git("status", "--porcelain", cwd=wt).stdout.splitlines()
        if porcelain:
            status = latest[-1]["status"] if latest else "uncommitted"
            run.git("add", "-A", cwd=wt)
            run.git("commit", "-q", "-m", f"WIP task {tid} attempt {current}: {status}", cwd=wt)
            base = run.git("rev-parse", "HEAD", cwd=wt).stdout.strip()
            names = [line[3:] for line in porcelain]
            shown = ", ".join(names[:5]) + (f", and {len(names) - 5} more" if len(names) > 5 else "")
            notes.insert(0, f"committed {len(porcelain)} uncommitted files of attempt {current} as {base[:7]} ({shown}); "
                            "this includes every untracked file that is not ignored, and in pr mode it is pushed with the branch")
            text = render(run, task, "task", nxt, session, base=base, retry=True)
    elif mode == "reattach":
        if os.path.realpath(wt) in worktree_locks(run):  # prune skips a locked registration
            raise Refused(f"{rel} is a stale worktree registration that is locked; run git worktree unlock {rel}, "
                          "then git worktree prune, then rerun")
        run.git("worktree", "prune")
        out = run.git("worktree", "add", "-q", os.path.join(run.wt_dir, worktree), branch, check=False)
        if out.returncode != 0:
            raise Refused(f"git worktree add failed: {out.stderr.strip() or out.stdout.strip()}", 1)
        notes.append(f"reattached {branch} at {base[:7]}")
    else:
        add_worktree(run, worktree, base)
    created = mode in ("first", "base", "head")
    try:
        path = write_brief(run, f"task-{tid}-{nxt}.md", text)
        said = start_session(run, worktree, session, model, effort, text)
    except Exception as exc:
        started_or_cleaned(run, worktree, base, exc, created)
    drift = drift_warning(run, worktree, base)
    entry, id_note = session_entry(run, tid, "task", nxt, session, worktree, said)
    sessions = recorded_sessions(task) + ([entry] if entry else [])
    if task["status"] == "open":
        run.tg("start", str(tid))
    # Never unset pr, pr_branch, pushed or target: one request per task across attempts. `base` is the commit the
    # task branch forked from: the first launch writes it, a retry keeps it.
    keep = [meta_arg("target", given_target)] if given_target and given_target != run.config["merge"]["base"] else []
    if not meta.get("base") and mode in ("first", "base", "head"):
        keep.append(meta_arg("base", base))
    run.tg("edit", str(tid), "--meta", meta_arg("session", session), meta_arg("model", model),
           meta_arg("attempt", nxt), meta_arg("started_at", run.now()), meta_arg("sessions", sessions), *keep,
           "--unset-meta", "verdict", "verdict_ref", "abandoned")
    where = f"base {base[:7]}" if mode in ("first", "base") else f"continues at {base[:7]}"
    detail = (f"{model}{'/' + effort if effort else ''} session {session} worktree {rel} {where} brief {path}"
              + "".join(f"; {n}" for n in notes)
              + (f"; claude said: {first_line(said)}" if said else "") + (f"; {id_note}" if id_note else "")
              + (f"; {drift}" if drift else ""))
    run.emit("launched", tid, nxt, session, detail)


def refuse_past_cap(tid, nxt, latest, override):
    if not override and nxt > MAX_ATTEMPTS and not (latest and latest[-1]["status"] == "STOPPED"):
        raise Refused(f"#{tid}: attempt {MAX_ATTEMPTS} has failed; run run.py abandon {tid} "
                      f"<died|tool-error|stuck|unknown>, or pass --attempt {nxt} to override")


# ------------------------------------------------------------------- adopt

def cmd_adopt(run, args):
    """Bring a finished branch that was started outside run.py under the Manager. Launches nothing."""
    tid, branch = args.id, args.branch
    task = run.show(tid)
    meta = task.get("meta") or {}
    if task["type"] != "task":
        raise Refused(f'#{tid} is a {task["type"]}, not a task')
    if task["derived_status"] == "done":
        raise Refused(f"#{tid} is done")
    refuse_legacy(task)
    current = wanted_attempt(task) or 0
    if meta.get("abandoned"):
        raise Refused(f"#{tid} is abandoned ({meta['abandoned']}); run.py launch {tid} --attempt {current + 1} to try again")
    live = [s for s in own_sessions(run, tid) if s.live]
    if live:
        raise Refused(f"#{tid} has a live session {live[0].describe()}; run run.py record first")
    blockers = waiting_for(run, task)
    if blockers:
        raise Refused(f"#{tid} waits for {' '.join(blockers)}; finish or decide them first")
    verify_mode(run, task)
    verify_kind(run, task)
    refuse_past_cap(tid, current + 1, task_rows(run.results_for(tid), current), None)
    if not re.fullmatch(r"[0-9a-f]{7,40}", args.head):
        raise Refused(f"--head {args.head} is not a commit SHA (7 to 40 hex characters)")
    tip = run.git("rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False).stdout.strip()
    if not tip:
        raise Refused(f"branch {branch} not found; fetch it: git fetch {run.config['merge']['remote']} {branch}:{branch}")
    if not tip.startswith(args.head):
        raise Refused(f"branch {branch} is at {tip}, not {args.head}; adopt takes the branch tip")
    head, extra, label = tip, {}, ""
    if args.pr is not None:
        if not run.pr_mode:
            raise Refused('--pr needs merge.mode = "pr"')
        p = run.host().pr(args.pr)
        label = run.host().label(p.number)
        if p.state != "OPEN":
            raise Refused(f"{label} is {p.state}; adopt takes an open request")
        if p.head != head:
            raise Refused(f"{label} head is {p.head}, not {head}")
        extra = {"pr": p.number, "pr_branch": p.head_branch, "pushed": head}
        if p.base_branch != run.config["merge"]["base"]:
            extra["target"] = p.base_branch
    base = args.base
    if base:
        base = run.git("rev-parse", "--verify", "-q", f"{base}^{{commit}}", check=False).stdout.strip()
    else:
        base = run.git("merge-base", head, run.target_ref(task, extra.get("target")), check=False).stdout.strip()
    if not base:
        raise Refused(f"cannot find a base for {head[:7]}; pass --base <sha>")
    nxt, now = current + 1, run.now()
    if task["status"] == "open":
        run.tg("start", str(tid))
    fresh = {} if "sessions" in meta else {"sessions": []}
    run.tg("edit", str(tid), "--meta", *[meta_arg(k, v) for k, v in {"attempt": nxt, "session": "adopted", "started_at": now,
           "base": base, **fresh, **extra}.items()], "--unset-meta", "verdict", "verdict_ref", "abandoned")
    run.add_result(tid, "task", nxt, "manager", "PASS",
                   f"Task: {tid}\nStatus: PASS\nBranch: {branch}\nHead: {head}\nWorktree: None\nRan: not stated (adopted)\n"
                   f"Files: None\nIssues: None\nDeviations: adopted by the Manager at {now}; the work was done outside run.py\n"
                   f"Follow-ups: None\nCheckpoint: {now} \u2014 adopted; next: verify\n")
    run.emit("adopted", tid, nxt, None, f"branch {branch} at {head[:7]}" + (f"; {label}" if label else ""),
             f'run.py verify {tid}, or rerun VERIFY on {branch} and run.py close {tid} --verdict L --ran "..."')


# ------------------------------------------------------------------ verify

def refuse_unless_running(task):
    tid = task["id"]
    meta = task.get("meta") or {}
    if task["status"] != "in_progress" or wanted_attempt(task) is None:
        raise Refused(f"#{tid} is not in progress with an attempt")
    if meta.get("abandoned"):
        raise Refused(f"#{tid} is abandoned ({meta['abandoned']})")
    return wanted_attempt(task)


def worker_for(run, tid, attempt, result_id=None):
    rows = run.results_for(tid)
    if result_id is not None:
        found = [r for r in rows if r["id"] == result_id and r["kind"] == "task"]
        worker = found[0] if found else None
    else:
        worker = latest_worker(rows, attempt)
    if worker is None:
        raise Refused(f"#{tid} has no worker result for attempt {attempt}; run run.py record")
    if worker["status"] != "PASS":
        raise Refused(f"#{tid} attempt {attempt} reported {worker['status']}, not PASS; "
                      f"a fix round is run.py launch {tid}")
    return rows, worker


def cmd_verify(run, args):
    tid = args.id
    task = run.show(tid)
    refuse_legacy(task)
    mode = verify_mode(run, task)
    kind = verify_kind(run, task)
    if mode != "session":
        return verify_ci(run, args, task, mode[3:])
    attempt = refuse_unless_running(task)
    rows, worker = worker_for(run, tid, attempt, args.result)
    ref = args.ref or tail_or_none(HEAD_ANY.search(worker["body"]))
    if not ref:
        raise Refused(f"result #{worker['id']} has no Head: line; pass --ref")
    earlier = verifier_rows(rows, attempt)
    if earlier and not args.again:
        last = earlier[-1]
        raise Refused(f"#{tid} attempt {attempt} already has verify result #{last['id']} "
                      f"(Verdict: {verdict_of(last) or 'none'}); run run.py close {tid}, "
                      "or pass --again once a verify-blocked cause is fixed")
    running = [s for s in own_sessions(run, tid, "verify", attempt) if s.live]
    if running:
        raise Refused(f"verifier {running[0].describe()} is still running")
    names = {s.wtname for s in own_sessions(run, tid, "verify", attempt)}
    if os.path.isdir(run.wt_dir):
        for entry in os.listdir(run.wt_dir):
            m = VERIFY_WT.match(entry)
            if m and int(m.group(1)) == tid and int(m.group(2)) == attempt:
                names.add(entry)
    stale = run.git("branch", "--list", "--format=%(refname:short)", f"worktree-verify-{tid}-{attempt}",
                    f"worktree-verify-{tid}-{attempt}-*", check=False).stdout.split()
    names |= {b[len("worktree-"):] for b in stale}  # a branch left behind counts like a folder
    k = 1
    while f"verify-{tid}-{attempt}" + (f"-{k}" if k > 1 else "") in names:
        k += 1
    name = f"verify-{tid}-{attempt}" + (f"-{k}" if k > 1 else "")
    verifier = run.config["models"]["verifier"]
    if args.model:
        model, effort = args.model, args.effort
    elif verifier:
        model, effort = verifier["model"], args.effort or verifier["effort"]
    else:
        model = "sonnet" if str((task.get("meta") or {}).get("model") or "").startswith("opus") else "opus"
        effort = args.effort
    check_cap(run)
    if is_sha(ref):  # the verifier compares HEAD with this text, so give the full SHA
        full = run.git("rev-parse", "--verify", "-q", f"{ref}^{{commit}}", check=False)
        ref = full.stdout.strip() if full.returncode == 0 else ref
    where = verify_skill(run, ref)[0] or "none"
    text = render(run, task, "verify", attempt, name, ref=ref, worker=worker)
    if args.dry_run:
        print("claude " + " ".join(session_args(run, name, name, model, effort)) + " <brief>", file=sys.stderr)
        if run.json:
            run.emit("dry-run", tid, attempt, name, text)
        else:
            print(text, end="")
        return
    suffix = "-verify" if k == 1 else f"-verify-{k}"
    if is_sha(ref):
        add_worktree(run, name, ref)
    try:
        write_brief(run, f"task-{tid}-{attempt}{suffix}.md", text)
        said = start_session(run, name, name, model, effort, text)
    except Exception as exc:
        if is_sha(ref):
            started_or_cleaned(run, name, ref, exc)
        raise
    drift = drift_warning(run, name, ref, branch=False) if is_sha(ref) else ""
    entry, id_note = session_entry(run, tid, "verify", attempt, name, name, said)
    if entry:  # the only meta verify writes
        run.edit_meta(tid, sessions=recorded_sessions(task) + [entry])
    run.emit("verifying", tid, attempt, name, f"{model} session {name} ref {ref} kind {kind} skill {where}"
             + (f"; {id_note}" if id_note else "") + (f"; {drift}" if drift else ""))


def verify_ci(run, args, task, name):
    """verify_mode ci:<name>: push the branch, open the request, and let the CI run on its head decide."""
    tid = task["id"]
    if args.ref or args.model or args.effort or args.dry_run:
        raise Refused("verify_mode=ci runs on the branch head and starts no session; drop --ref/--model/--effort/--dry-run")
    attempt = refuse_unless_running(task)
    rows, worker = worker_for(run, tid, attempt, args.result)
    head = tail_or_none(HEAD_ANY.search(worker["body"]))
    if not is_sha(head):
        raise Refused(f"ci verification needs a commit on the branch; result #{worker['id']} has no Head:")
    earlier = [r for r in task_rows(rows, attempt, "verify") if r.get("author") == "ci"]
    if earlier and not args.again:
        raise Refused(f"#{tid} attempt {attempt} already has verify result #{earlier[-1]['id']} "
                      f"(Verdict: {verdict_of(earlier[-1]) or 'none'}) from CI; run run.py close {tid}, "
                      "or pass --again to run it again")
    branch, head = branch_at(run, tid, attempt, worker, head)
    if not publish(run, task, branch, head):
        return
    head, pr_branch = task["meta"]["pushed"], task["meta"]["pr_branch"]  # the full SHA
    runs = run.host().runs(pr_branch, head, name)
    if runs and not args.again:
        rows = ci_evaluate(run, task, rows, attempt, name, head, pr_branch, runs)
        if rows is not None:
            emit_verified(run, tid, attempt, [r for r in task_rows(rows, attempt, "verify") if r.get("author") == "ci"][-1],
                          verify_kind(run, task, strict=False))
        return
    where = f"{name} on {pr_branch} at {head[:7]}"
    ok, why = run.host().dispatch(pr_branch, name)
    if ok:
        run.emit("ci-dispatched", tid, attempt, None, where, "run.py record")
    elif why == "no manual trigger":
        run.emit("ci-waiting", tid, attempt, None, f"no run for {head[:7]} yet; {name} has no manual trigger, "
                 "the push or the request starts it", "run.py record")
    else:
        run.emit("ci-waiting", tid, attempt, None, f"no run for {head[:7]} yet; dispatch failed: {why}",
                 f"fix it, then run.py verify {tid} --again")


def ci_evaluate(run, task, rows, attempt, name, head, pr_branch, runs):
    """Judge the newest CI run on `head`. None while it is pending (the event is printed). Else the
    result rows, with a `ci` verify row filed for a finished run that has none."""
    tid, newest = task["id"], runs[0]
    if newest.status == "pending":
        run.emit("ci-pending", tid, attempt, None, f"run {newest.id} {newest.raw} {newest.url}")
        return None
    key = f"{newest.id}/{newest.attempt}"
    for row in task_rows(rows, attempt, "verify"):
        if row.get("author") == "ci" and (m := RUN_LINE.search(row.get("body") or "")) and m.group(1) == key:
            return rows
    level, status = {"success": ("test-verified", "PASS"), "failure": ("verify-failed", "ISSUES")}.get(
        newest.status, ("verify-blocked", "BLOCKED"))
    run.add_result(tid, "verify", attempt, "ci", status,
                   f"Verdict: {level}\nWorkflow: {name}\nRun: {key} {newest.url}\nHead: {head}\n"
                   f"Branch: {run.config['merge']['remote']}/{pr_branch}\nConclusion: {newest.raw}\n")
    return run.results_for(tid)


def emit_verified(run, tid, attempt, row, kind):
    level = verdict_of(row)
    nxt = f"run run.py close {tid}"
    if row["author"] == "ci" and level == "verify-failed":
        nxt += f" (records verify-failed), then fix round: run.py launch {tid}"
    elif row["author"] == "ci" and level == "verify-blocked":
        nxt = f"run.py verify {tid} --again"
    if level == "test-verified" and kind != "code":
        nxt += f" (records test-verified; it does not close a {kind} task)"
    run.emit("verified", tid, attempt, None, f"Verdict {level} by {row['author']} (result #{row['id']})", nxt)


# ------------------------------------------------------------------ record

def record_row(run, task, session, attempt):
    """Record a row that run.py did not start, under the attempt it was filed for. An unrecorded row in the
    shared task folder counts for the current attempt; recording it keeps a later attempt from inheriting it."""
    if session.recorded or not session.sid:
        return
    entry = {"id": session.sid, "kind": session.kind, "attempt": session.attempt or attempt,
             "name": session.name or session.wtname, "worktree": session.wtname}
    run.set_meta(task, sessions=recorded_sessions(task) + [entry])
    session.recorded, session.attempt = True, entry["attempt"]


def file_stuck(run, tid, attempt, kind, session, label):
    reason = session.waiting or session.state
    run.claude("stop", session.sid)
    run.add_result(tid, kind, attempt, "manager", "BLOCKED",
                   f"Session: {session.sid}\nWorktree: {session.worktree(run.root)}\n"
                   f"{label} {session.sid} stopped: waiting on {reason}")
    return "permission prompt" if "prompt" in str(reason).lower() else f"waiting on {reason}"


def record_arrived(run, snap, task, attempt, result):
    tid, status = task["id"], result["status"]
    held = snap.waiting_decisions(task)
    if held:
        title = next((d["title"] for d in snap.decisions if d["id"] == held[0]), "")
        run.emit("gated", tid, attempt, None, f'{status}; waits for decision #{held[0]} "{title}"')
        return
    if status == "BLOCKED" and result.get("author") == "manager":
        sid = tail_or_none(SESSION_LINE.search(result.get("body") or "")) or "<sid>"
        run.emit("stuck", tid, attempt, None, "filed earlier", PROMPT_HINT.format(sid=sid, cmd=f"run.py launch {tid}"))
        return
    answered = [d for d in task.get("depends_on") or []
                if d in snap.by_id and snap.by_id[d]["type"] == "decision" and snap.by_id[d]["status"] == "done"]
    meta = task.get("meta") or {}
    if status == "BLOCKED" and answered:
        run.emit("arrived", tid, attempt, None, f"BLOCKED by {result.get('author') or 'unknown'} (result #{result['id']})",
                 f"decision #{answered[0]} answered; run.py launch {tid}")
        return
    detail = f"{status} by {result.get('author') or 'unknown'} (result #{result['id']})"
    if status == "PASS":
        nxt = (f"run.py verify {tid}" if str(meta.get("verify_mode") or "").startswith("ci:") or meta.get("risk") == "high"
               or verify_kind(run, task, strict=False) != "code"
               else f"rerun VERIFY in <Worktree:>, then run.py close {tid} --verdict L --ran \"...\"")
        adopted = WORKTREE_LINE.search(result.get("body") or "")
        detail += "; adopted" if adopted and adopted.group(1).strip() == "None" else ""
    elif status == "ISSUES":
        nxt = (f"fix round: run.py launch {tid}" if attempt < MAX_ATTEMPTS
               else f"attempt {MAX_ATTEMPTS} failed: run.py abandon {tid} <mode>")
    else:
        nxt = (f'answer it and run.py launch {tid}, or tg add "<question>" --type decision '
               f"--meta decider=operator --blocks {tid}")
    run.emit("arrived", tid, attempt, None, detail, nxt)


def salvage(run, tid, attempt, session):
    text = ""
    if session is not None:
        out = run.claude("logs", session.sid, check=False)
        text = out.stdout if out.returncode == 0 else ""
    lines = text.splitlines()
    marks = [i for i, line in enumerate(lines) if line.strip() == f"Task: {tid}"]
    if not marks:
        return None
    rest = lines[marks[-1]:]
    ends = [i for i, line in enumerate(rest) if line.startswith("Checkpoint:")]
    report = "\n".join(rest[:ends[0] + 1] if ends else rest).strip() + "\n"
    status = STATUS_LINE.search(report)
    if not status or not CHECKPOINT_LINE.search(report):
        return None
    return status.group(1), report


def commit_stopped(run, tid, attempt, rows, sessions):
    """Phase 2 of a pause: commit the WIP of a stopped worker that has exited."""
    stopped = [r for r in task_rows(rows, attempt) if r["status"] == "STOPPED"]
    if any(s.status in ("busy", "waiting") for s in sessions):
        run.emit("stopping", tid, attempt, None, f"session {sessions[0].sid} has not exited yet")
        return
    sid = sessions[0].sid if sessions else (tail_or_none(SESSION_LINE.search(stopped[-1]["body"])) or "none")
    wt = task_worktree(run, tid)
    if not os.path.isdir(wt):
        run.add_result(tid, "task", attempt, "manager", "STOPPED",
                       f"Session: {sid}\nWorktree: {wt}\nBranch: None\nHead: None\nFiles: None")
        run.emit("stopped", tid, attempt, sid, "worktree missing; nothing to commit")
        return
    rel = f".claude/worktrees/task-{tid}"
    if os.path.realpath(wt) not in registered_worktrees(run):  # git would find the main checkout from here
        run.add_result(tid, "task", attempt, "manager", "STOPPED",
                       f"Session: {sid}\nWorktree: {wt}\nBranch: None\nHead: None\nFiles: None")
        run.emit("stopped", tid, attempt, sid, f"folder {rel} is a plain folder, not a git worktree; move or delete "
                 "it yourself; nothing committed", f"run.py launch {tid} after the pause")
        return
    on = run.git("branch", "--show-current", cwd=wt, check=False).stdout.strip()
    if on != task_branch(tid):  # a commit here would not be on the task branch
        at = run.git("rev-parse", "HEAD", cwd=wt, check=False).stdout.strip()
        where = f"on {on}" if on else f"on a detached HEAD at {at[:7]}"
        run.add_result(tid, "task", attempt, "manager", "STOPPED",
                       f"Session: {sid}\nWorktree: {wt}\nBranch: {on or 'None'}\nHead: None\nFiles: None")
        run.emit("stopped", tid, attempt, sid, f"{rel} is {where}, not {task_branch(tid)}; nothing committed; "
                 "its uncommitted work stays there", f"fix the branch (launch says how), then run.py launch {tid}")
        return
    porcelain = run.git("status", "--porcelain", cwd=wt).stdout.rstrip("\n")
    if porcelain:
        run.git("add", "-A", cwd=wt)
        run.git("commit", "-q", "-m", f"WIP task {tid} attempt {attempt}: stopped by pause", cwd=wt)
    head = run.git("rev-parse", "HEAD", cwd=wt).stdout.strip()
    branch = run.git("branch", "--show-current", cwd=wt).stdout.strip() or "None"
    run.add_result(tid, "task", attempt, "manager", "STOPPED",
                   f"Session: {sid}\nWorktree: {wt}\nBranch: {branch}\nHead: {head}\nFiles: {porcelain or 'None'}")
    run.emit("stopped", tid, attempt, sid,
             (f"WIP committed {head} on {branch}" if porcelain else f"worktree clean at {head} on {branch}"),
             f"run.py launch {tid} after the pause")


def record_in_progress(run, snap, task, unmanaged):
    tid, meta = task["id"], task.get("meta") or {}
    attempt = wanted_attempt(task)
    if meta.get("abandoned"):
        return
    if attempt is None:
        unmanaged.append(tid)
        return
    if is_legacy(task):
        run.emit("legacy", tid, attempt, None, legacy_detail(task), LEGACY_NEXT.format(tid=tid))
        return
    rows = snap.rows(tid)
    verifiers = own_sessions(run, tid, "verify", attempt)
    live = [s for s in verifiers if s.live]
    if live:
        for s in live:
            if s.stuck:
                record_row(run, task, s, attempt)
                reason = file_stuck(run, tid, attempt, "verify", s, "Verifier")
                run.emit("stuck", tid, attempt, s.sid, f"stopped verifier {s.sid}; filed verify BLOCKED ({reason})",
                         PROMPT_HINT.format(sid=s.sid, cmd=f"run.py verify {tid} --again"))
            else:
                run.emit("verifying", tid, attempt, s.sid, f"session {s.sid} ({s.name}, {s.status})")
        return
    mode, pushed, worker = str(meta.get("verify_mode") or ""), meta.get("pushed"), latest_worker(rows, attempt)
    seen = tail_or_none(HEAD_ANY.search(worker["body"])) if worker else None
    if (mode.startswith("ci:") and run.pr_mode and pushed and worker and worker["status"] == "PASS"
            and is_sha(seen) and str(pushed).startswith(seen)):
        pr_branch = meta.get("pr_branch") or f"task-{tid}"
        runs = run.host().runs(pr_branch, pushed, mode[3:])
        if not runs:
            run.emit("ci-waiting", tid, attempt, None, f"no run for {pushed[:7]} on {mode[3:]} yet",
                     f"run.py record later, or run.py verify {tid} --again")
            return
        rows = ci_evaluate(run, task, rows, attempt, mode[3:], pushed, pr_branch, runs)
        if rows is None:
            return
    verdicts = verifier_rows(rows, attempt)
    newest_manager = max((r["id"] for r in task_rows(rows, attempt, "verify") if r.get("author") == "manager"), default=0)
    with_verdict = [r for r in verdicts if verdict_of(r) and r["id"] > newest_manager]  # an override outranks older rows
    if with_verdict and (not meta.get("verdict") or verdict_of(with_verdict[-1]) != meta.get("verdict")):
        emit_verified(run, tid, attempt, with_verdict[-1], verify_kind(run, task, strict=False))
        return
    if verdicts and not any(verdict_of(r) for r in verdicts) and not meta.get("verdict"):
        run.emit("verified", tid, attempt, None, f"no Verdict line (result #{verdicts[-1]['id']} by {verdicts[-1]['author']})",
                 f"run run.py close {tid} --verdict L")
        return
    if meta.get("verdict"):
        run.emit("unclosed", tid, attempt, None, f"verdict {meta['verdict']}", unclosed_next(tid, meta["verdict"], verify_kind(run, task, strict=False)))
        return
    finished = [s for s in verifiers if s.finished]
    if finished and not task_rows(rows, attempt, "verify"):
        s = finished[-1]
        run.add_result(tid, "verify", attempt, "manager", "DIED", f"verifier {s.sid} ({s.name}) ended with no result")
        run.emit("verifier-died", tid, attempt, s.sid, s.name, f"run run.py verify {tid}")
    mine = own_sessions(run, tid, "task", attempt)
    results = task_rows(rows, attempt)
    if not results:
        stuck = [s for s in mine if s.stuck]
        busy = [s for s in mine if s.live and s.status == "busy" and not s.stuck]
        unknown = [s for s in mine if s.unknown]
        if stuck:
            s = stuck[0]
            record_row(run, task, s, attempt)
            reason = file_stuck(run, tid, attempt, "task", s, "Session")
            run.emit("stuck", tid, attempt, s.sid, f"stopped {s.sid}; filed BLOCKED ({reason})",
                     PROMPT_HINT.format(sid=s.sid, cmd=f"run.py launch {tid}"))
        elif busy:
            run.emit("running", tid, attempt, busy[0].sid, f"session {busy[0].sid} ({busy[0].name})")
        elif unknown:
            s = unknown[0]
            run.emit("unknown", tid, attempt, s.sid, f"session {s.sid} status={s.status} state={s.state}; not filed as DIED",
                     f"claude logs {s.sid}")
        else:
            s = mine[-1] if mine else None
            found = salvage(run, tid, attempt, s)
            if s is not None:  # filed for this attempt, either way
                record_row(run, task, s, attempt)
            if found:
                added = run.add_result(tid, "task", attempt, "manager", found[0], found[1])
                run.emit("salvaged", tid, attempt, s.sid,
                         f"{found[0]} from claude logs {s.sid} (result #{added['id']})")
                record_arrived(run, snap, task, attempt, added)
            else:
                where = (f"session {s.sid} {s.status}/{s.state}" if s
                         else f"no session recorded for attempt {attempt}")
                run.add_result(tid, "task", attempt, "manager", "DIED", f"{where}, no result")
                nxt = (f"run.py launch {tid}" if attempt < MAX_ATTEMPTS
                       else f"attempt {MAX_ATTEMPTS} failed: run.py abandon {tid} died")
                run.emit("died", tid, attempt, s.sid if s else None, "filed DIED", nxt)
        return
    latest = results[-1]
    if latest["status"] == "STOPPED":
        if HEAD_ANY.search(latest["body"]):
            run.emit("stopped", tid, attempt, None, f"head {tail_or_none(HEAD_ANY.search(latest['body'])) or 'None'}",
                     f"run.py launch {tid} after the pause")
        else:
            commit_stopped(run, tid, attempt, rows, mine)
    elif latest["status"] == "DIED":
        nxt = (f"run.py launch {tid}" if attempt < MAX_ATTEMPTS
               else f"attempt {MAX_ATTEMPTS} failed: run.py abandon {tid} died")
        run.emit("died", tid, attempt, None, "filed earlier", nxt)
    else:
        record_arrived(run, snap, task, attempt, latest)


def record_done(run, snap, task):
    tid, meta = task["id"], task.get("meta") or {}
    if meta.get("abandoned"):
        return
    if unmerged(task) and run.pr_mode:
        if not meta.get("pr"):
            run.emit("unpublished", tid, None, None, f"closed at {str(meta['verdict_ref'])[:7]}, not pushed", f"run.py close {tid}")
        else:
            pr_status(run, snap, task, run.host().pr(int(meta["pr"])))
    elif unmerged(task):
        sha = str(meta["verdict_ref"])
        if merged_into(run, task, sha):
            run.tg("edit", str(tid), "--meta", meta_arg("merged_at", run.now()), meta_arg("merged_by", "operator"))
            run.emit("merged", tid, None, None, f"{sha} is in HEAD; recorded merged_by=operator")
            cleanup(run, task)
        else:
            waits = [b for b in task.get("blocks") or [] if b in snap.by_id and snap.by_id[b]["status"] != "done"]
            run.emit("unmerged", tid, None, None,
                     f"branch {task_branch(tid)} at {sha} is ready to merge; blocks {ids_text(waits)}")
    elif meta.get("merged_at"):
        cleanup(run, task, sweep=True)


def ready_events(run, snap):
    free, waits = snap.ready_tasks()
    for c, d in waits:
        run.emit("waits", c, None, None, f"dependency #{d} not merged")
    run.emit("ready", None, None, None, " ".join(f"#{i}" for i in free) or "none")


def host_guard(run, task, fn, *args):
    """Run one task's part of the drain. A code host failure is that task's line, not the drain's end."""
    try:
        fn(*args)
    except Refused:
        raise
    except codehost.HostError as exc:
        run.host_failed = True
        run.emit("host-error", task["id"], None, None, str(exc), "fix it and run.py record")


def cmd_record(run, args):
    snap = Snapshot(run)
    unmanaged = []
    for task in sorted(snap.in_progress, key=lambda t: t["id"]):
        host_guard(run, task, record_in_progress, run, snap, task, unmanaged)
    if unmanaged:
        run.emit("unmanaged", None, None, None, ids_text(unmanaged), "run.py adopt <id> --branch <b> --head <sha> [--pr <n>] "
                 "for work to bring under run.py; the others can stay")
    for task in sorted(snap.done, key=lambda t: t["id"]):
        host_guard(run, task, record_done, run, snap, task)
    for d in sorted(snap.decisions, key=lambda t: t["id"]):
        blocks = [b for b in d.get("blocks") or [] if b not in snap.by_id or snap.by_id[b]["status"] != "done"]
        run.emit("decision", d["id"], None, None,
                 f'"{d["title"]}" decider {(d.get("meta") or {}).get("decider") or "none"} '
                 f"by {d.get('due') or 'no date'} blocks {ids_text(blocks)}")
    run.emit("slots", None, None, None, f"{live_count(run)}/{run.config['sessions']['max_parallel']} live")
    ready_events(run, snap)


# ----------------------------------------------------------------- cleanup

def worktree_locks(run):
    """{real path: lock reason} for the locked worktrees git lists. The reason is "" for a lock without one."""
    out = run.git("worktree", "list", "--porcelain", check=False).stdout
    locks, path = {}, None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = os.path.realpath(line[len("worktree "):])
        elif line == "locked" or line.startswith("locked "):
            locks[path] = line[len("locked"):].strip()
    return locks


def task_folders(run, tid):
    """(task and verifier folders of this task, 0.6.0 folders of this task) that exist under .claude/worktrees."""
    entries = sorted(os.listdir(run.wt_dir)) if os.path.isdir(run.wt_dir) else []
    current = [e for e in entries if (wt_kind(e) or (None, None))[1] == tid]
    legacy = [e for e in entries if (m := LEGACY_WT.match(e)) and int(m.group(1)) == tid]
    return current, legacy


def merge_refs(run, task):
    """The refs that hold merged work. Local mode: the local branch the task merges into (its `target` meta, else
    merge.base, else the branch the main checkout is on); a detached or unknown target gives none, so nothing
    counts as merged. pr mode: the head the request merged (`pushed`) and the fetched target branch; never the
    main checkout's HEAD."""
    meta, refs = task.get("meta") or {}, []
    if run.pr_mode:
        if meta.get("pushed"):
            refs.append(str(meta["pushed"]))
        try:
            branch = run.target(task)
        except codehost.HostError:
            branch = None
        if branch:
            refs.append(f"refs/remotes/{run.config['merge']['remote']}/{branch}")
    else:
        branch = (meta.get("target") or run.config["merge"]["base"]
                  or run.git("branch", "--show-current", check=False).stdout.strip())
        if branch:
            refs.append(f"refs/heads/{branch}")
    return [r for r in refs if run.git("rev-parse", "--verify", "-q", f"{r}^{{commit}}", check=False).returncode == 0]


def merged_into(run, task, commit):
    """True when `commit` is an ancestor of one of merge_refs."""
    return any(run.git("merge-base", "--is-ancestor", commit, ref, check=False).returncode == 0
               for ref in merge_refs(run, task))


def not_merged_reason(run, task, head):
    """None when `head` (a folder's HEAD commit) is merged, else why not. Besides ancestry, in local mode a squash
    or rebase merge leaves the commit out of the target: the task's verified commit (`verdict_ref`) or a commit with
    the same change then counts, because cleanup only runs for a task recorded as merged."""
    meta = task.get("meta") or {}
    if merged_into(run, task, head):
        return None
    if run.pr_mode:
        pushed = meta.get("pushed")
        if pushed and not commit_of(run, str(pushed)):
            branch = meta.get("pr_branch") or "task-" + str(task["id"])
            return f"pushed head {str(pushed)[:7]} is not in this clone; fetch {run.config['merge']['remote']}/{branch}"
    else:
        verdict = commit_of(run, str(meta["verdict_ref"])) if is_sha(meta.get("verdict_ref")) else None
        refs = merge_refs(run, task)
        if verdict and (head == verdict or (refs and same_change(run, task, verdict, head, ref=refs[0])[0])):
            return None
    return f"commit {head[:7]} is not merged"


def files_text(lines, limit=10):
    shown = [line.strip() for line in lines[:limit]]
    return ", ".join(shown) + (f", and {len(lines) - limit} more" if len(lines) > limit else "")


def cwd_in(cwd, path):
    """True when a session's working directory is the folder or inside it."""
    real = os.path.realpath(cwd) if cwd else ""
    return real == path or real.startswith(path + os.sep)


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def cwd_users():
    """[(pid, command, cwd)] of the processes `lsof` shows with a working directory; None when lsof is missing."""
    if not shutil.which("lsof"):
        return None
    try:
        out = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fpcn"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    except OSError:
        return None
    found, pid, command = [], None, ""
    for line in out.stdout.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid, command = int(line[1:]), ""
        elif line.startswith("c"):
            command = line[1:]
        elif line.startswith("n") and pid is not None and pid != os.getpid():
            found.append((pid, command, line[1:]))
    return found


def folder_check(run, task, folder, path, registered, live, locks, users):
    """Why a worktree folder is not safe to remove, else None. Three checks, in this order: no live session or
    process uses it, `git status --porcelain` prints nothing, and its HEAD commit is merged. A lock must be
    Claude Code's own for a session that has ended. Returns (reason, session, head, ignored files)."""
    if path not in registered:
        return "not a registered git worktree; inspect it and remove it yourself if you do not need it", None, None, []
    for s in live:
        if s.wtname == folder or cwd_in(s.cwd, path):
            return "still running", s.sid, None, []
    lock = locks.get(path)
    if lock is not None:
        m = re.match(rf"claude session {re.escape(folder)} \(pid (\d+)\b", lock)
        if not m:
            return f"locked ({lock or 'no reason'})", None, None, []
        if pid_alive(int(m.group(1))):
            return f"still running (pid {m.group(1)} holds its lock)", None, None, []
    for pid, command, cwd in users or []:
        if cwd_in(cwd, path):
            return f"process {pid} ({command}) uses it", None, None, []
    status = run.git("status", "--porcelain", "--ignored", cwd=path, check=False)
    if status.returncode != 0:
        return f"git status said: {first_line(status.stderr or status.stdout)}", None, None, []
    lines = status.stdout.splitlines()
    changed = [line for line in lines if not line.startswith("!!")]
    if changed:
        return f"uncommitted changes ({files_text(changed)})", None, None, []
    head = run.git("rev-parse", "HEAD", cwd=path, check=False).stdout.strip()
    if not head:
        return "cannot read its HEAD commit", None, None, []
    why = not_merged_reason(run, task, head)
    if why:
        return why, None, None, []
    return None, None, head, [line[3:] for line in lines]


def remove_folder(run, task, folder, path, locks, head, ignored, rows, gone, note):
    """Remove one safe folder: unlock (a lock of an ended Claude session, checked by folder_check), a plain
    `git worktree remove` (never forced), the branch when its tip is merged, then the session rows that name
    the folder. Says `removed` for the folder, or `kept` with the reason."""
    reason = locks.get(path)
    if reason is not None:
        undone = run.git("worktree", "unlock", path, check=False)
        if undone.returncode != 0:
            note(folder, f"git worktree unlock said: {first_line(undone.stderr or undone.stdout)}")
            return
    out = run.git("worktree", "remove", path, check=False)
    if out.returncode != 0:
        if reason is not None:  # put Claude Code's lock back: the folder stays as it was
            run.git("worktree", "lock", *(["--reason", reason] if reason else []), path, check=False)
        note(folder, f"git worktree remove said: {first_line(out.stderr or out.stdout)}")
        return
    tid = task["id"]
    branch = f"worktree-{folder}"
    tip = run.git("rev-parse", "--verify", "-q", f"refs/heads/{branch}^{{commit}}", check=False).stdout.strip()
    if tip and not_merged_reason(run, task, tip):
        run.emit("kept", tid, None, None, f"{branch}: branch stays, commit {tip[:7]} is not merged")
    elif tip:
        out = run.git("branch", "-D", branch, check=False)
        if out.returncode != 0:
            run.emit("kept", tid, None, None, f"{branch}: branch stays, git said: {first_line(out.stderr or out.stdout)}")
    for s in rows:
        if s.sid and s.sid not in gone and (s.wtname == folder or cwd_in(s.cwd, path)):
            out = run.claude("rm", s.sid, check=False)
            if out.returncode == 0:
                gone.add(s.sid)
            else:
                run.emit("kept", tid, None, s.sid, f"{folder}: claude rm said: {first_line(out.stderr or out.stdout)}")
    extra = ""
    if ignored:
        extra = f" (ignored files removed: {len(ignored)}: {', '.join(ignored[:5])}{', ...' if len(ignored) > 5 else ''})"
    run.emit("removed", tid, None, None, f"worktree {folder} (merged at {head[:7]}){extra}")


def cleanup(run, task, sweep=False):
    """Remove the sessions and worktrees of a merged task. Never deletes a file, never forces.

    `claude rm` locks in the first session that used a worktree (even after it stopped). `claude rm` of any later
    session removes only its row; `claude rm` of the first session removes the folder, when the tree is clean
    and pushed. So the sessions go newest first and the task's first session goes last. Then every task folder
    still present goes when it is safe: no live session, a clean `git status`, a merged HEAD (`folder_check`).
    `sweep` is `record` coming back to a task that was merged earlier: it prints a folder's `kept` line only when
    the reason differs from the last one stored in the task's `cleanup_kept` meta."""
    tid = task["id"]
    if (task.get("meta") or {}).get("abandoned"):
        return
    folders, legacy = task_folders(run, tid)
    if not run.config["merge"]["remove_worktrees"]:
        if not sweep:  # said once, at the merge
            for folder in folders + legacy:
                run.emit("kept", tid, None, None, f"{folder}: merge.remove_worktrees is false")
        return
    rows = own_sessions(run, tid)
    if not rows and not folders and not legacy:
        return
    entries = recorded_sessions(task)
    order = [e["id"] for e in entries if e.get("id")]
    first = next((e["id"] for e in entries if e.get("kind") == "task" and e.get("id")), None)
    recorded = sorted((s for s in rows if s.recorded and s.sid in order),
                      key=lambda s: (s.sid == first, -order.index(s.sid)))
    sessions = [s for s in rows if s not in recorded] + recorded
    in_use = {s.wtname for s in rows if s.live}
    meta = task.get("meta") or {}
    before = meta.get("cleanup_kept") if isinstance(meta.get("cleanup_kept"), dict) else {}
    after = {}  # folder -> why it was kept this time

    def note(folder, detail, sid=None):
        after[folder] = detail
        if not (sweep and before.get(folder) == detail):
            run.emit("kept", tid, None, sid, f"{folder}: {detail}")

    dirty = {}  # folder -> has changes
    held, gone = {}, set()  # folder -> what a refused claude rm said; session ids already removed
    for s in sessions:
        wt = s.worktree(run.root)
        if s.live or s.wtname in in_use:  # claude rm refuses while a live session uses the worktree
            continue
        if os.path.isdir(wt):
            if s.wtname not in dirty:
                dirty[s.wtname] = bool(run.git("status", "--porcelain", cwd=wt, check=False).stdout.strip())
            if dirty[s.wtname]:
                continue
        out = run.claude("rm", s.sid, check=False)
        if out.returncode == 0:
            gone.add(s.sid)
            run.emit("removed", tid, None, s.sid, f"session {s.sid} worktree {s.wtname}")
            continue
        message = (out.stderr + "\n" + out.stdout).strip()
        m = re.search(r"--discard-unpushed\s+([0-9A-Za-z]+)@(\S+)", message)
        if m:
            commit, wtid = m.groups()
            if merged_into(run, task, commit):
                again = run.claude("rm", s.sid, "--discard-unpushed", f"{commit}@{wtid}", check=False)
                if again.returncode == 0:
                    gone.add(s.sid)
                    held.pop(s.wtname, None)
                    run.emit("removed", tid, None, s.sid,
                             f"session {s.sid} worktree {s.wtname} (discarded {commit}, which is merged)")
                else:
                    held.setdefault(s.wtname, (s.sid, f"claude rm said: {first_line(again.stderr or again.stdout)}"))
            else:
                held.setdefault(s.wtname, (s.sid, f"commit {commit} is not merged"))
        else:
            held.setdefault(s.wtname, (s.sid, f"claude rm said: {first_line(message)}"))
    run._sessions = None  # the pass changed the rows; look again before the sweep
    registered, locks = registered_worktrees(run), worktree_locks(run)
    live = [s for s in run.sessions() if s.live]
    present = [f for f in sum(task_folders(run, tid), []) if os.path.isdir(os.path.join(run.wt_dir, f))]
    users = cwd_users() if present else None
    swept = set()
    for folder in sorted(present):
        path = os.path.join(run.wt_dir, folder)
        swept.add(folder)
        reason, sid, head, ignored = folder_check(run, task, folder, path, registered, live, locks, users)
        if reason:
            note(folder, reason, sid)
        else:
            remove_folder(run, task, folder, path, locks, head, ignored, run.sessions(), gone, note)
    for folder, (sid, detail) in held.items():  # a session whose folder the sweep did not see
        if folder not in swept:
            note(folder, detail, sid)
    noted = set()
    for s in rows:  # a live session whose folder is gone or never existed
        if s.live and s.wtname not in swept and s.wtname not in noted:
            noted.add(s.wtname)
            note(s.wtname, "still running", s.sid)
    if after != before:
        run.set_meta(task, cleanup_kept=after)


# ---------------------------------------------------- pull and merge requests

def request_body(run, task, head):
    """The request description: what it is, which attempt, and how it was or will be verified."""
    tid, meta = task["id"], task.get("meta") or {}
    attempt = wanted_attempt(task) or 1
    mode = str(meta.get("verify_mode") or "")
    if mode.startswith("ci:"):
        how = f"Verification: CI ({mode[3:]})"
    else:
        rows = [r for r in task_rows(run.results_for(tid), attempt, "verify") if meta.get("verdict") and verdict_of(r) == meta["verdict"]]
        how = f"Verdict: {meta['verdict']} by {rows[-1]['author']} (result #{rows[-1]['id']})" if rows else "Verdict pending"
    return (f"Taskgraph #{tid}: {task['title']}\nAttempt {attempt}, head {head}, base {str(meta.get('base') or 'none')[:7]}.\n"
            f"{how}\nOpened by agentic-team run.py.\n")


def report_field(body, name):
    """The text of the `<name>:` field of a report: the rest of its line and the lines up to the next label,
    stripped. "" when the report has no such field."""
    match = re.search(rf"(?m)^{re.escape(name)}:[ \t]*(.*)$", body or "")
    if not match:
        return ""
    rest = body[match.end():]
    following = REPORT_LABEL.search(rest)
    return (match.group(1) + (rest[:following.start()] if following else rest)).strip()


def verdict_marker(tid):
    return f"<!-- agentic-team verdict task={tid} -->"


def verdict_comment(run, task, attempt, level, ref, kind, source):
    """The Markdown body of the verdict comment. The first line is the hidden marker that a later verdict finds
    the comment by. `source` is the verify result the verdict comes from, or None."""
    tid = task["id"]
    closes = level in PASSING[kind]
    state = "The task is closed." if closes else f"The task stays in progress; next: {unclosed_next(tid, level, kind)}."
    by = f"by {source['author']} (verify result #{source['id']})" if source else "with no verify result on file"
    evidence = ""
    if source:
        body = strip_comments(source.get("body") or "")
        parts = [f"{name}: {report_field(body, name)}" for name in COMMENT_FIELDS if report_field(body, name)]
        evidence = "\n".join(parts).replace("```", "'''")
        if len(evidence) > COMMENT_LIMIT:
            evidence = evidence[:COMMENT_LIMIT] + f"\n[... cut at {COMMENT_LIMIT} characters; the full report is Taskgraph result #{source['id']}]"
    lines = [verdict_marker(tid),
             f"**Verdict: {level}** for Taskgraph #{tid} ({task['title']}), attempt {attempt}, verify kind `{kind}`, {by}.",
             f"Verified at: `{ref}`. {state}", "", "Evidence:", "```text", evidence or "none on file", "```", "",
             "Posted by agentic-team run.py. A later verdict on this task replaces this comment."]
    return "\n".join(lines) + "\n"


def post_verdict(run, task, attempt, level, ref, kind):
    """pr mode: put the verdict on the request as one comment, found by its marker and edited in place. No
    request yet (a verdict that does not close, before any push): nothing. A host failure is one event
    line; it never stops close."""
    tid, meta = task["id"], task.get("meta") or {}
    number = meta.get("pr")
    if not run.pr_mode or not number:
        return
    rows = [r for r in task_rows(run.results_for(tid), attempt, "verify") if verdict_of(r) == level]
    source = rows[-1] if rows else None
    host = run.host()
    label = host.label(number)
    try:
        where, replaced = host.comment(int(number), verdict_marker(tid), verdict_comment(run, task, attempt, level, ref, kind, source))
    except codehost.HostError as exc:
        run.emit("comment-failed", tid, attempt, None, f"{label}: {exc}",
                 f"fix the cause, then run.py close {tid} (it posts the verdict again while the task is not merged); "
                 f"else tell the operator to post it on {label} by hand")
        return
    run.emit("commented", tid, attempt, None, f"{label} {where}; verdict {level} at {ref[:7]}"
             + ("; replaced the earlier verdict comment" if replaced else ""))


def publish(run, task, branch, head, catch_up=False):
    """Push `head`, the tip of local `branch`, to <remote>/<pr_branch> and make sure a request exists.
    With catch_up (from close) it then reads the request: rebase when behind, merge when clean.
    Returns False when the push was refused."""
    tid, meta = task["id"], task.setdefault("meta", {})
    attempt = wanted_attempt(task) or 1
    host, remote = run.host(), run.config["merge"]["remote"]
    head = run.git("rev-parse", "--verify", f"{head}^{{commit}}").stdout.strip()
    pr_branch, pushed, pushed_now = meta.get("pr_branch") or f"task-{tid}", meta.get("pushed"), False
    if not pushed:
        ok, why = host.push(f"refs/heads/{branch}", pr_branch, "")
        if not ok:
            seen = run.git("ls-remote", remote, f"refs/heads/{pr_branch}", check=False).stdout.split()
            if not seen:
                raise Refused(f"push of {branch} to {remote}/{pr_branch} failed: {why}", 1)
            if seen[0] != head:  # equal: an earlier publish pushed and died before the tg edit
                raise Refused(f"remote branch {remote}/{pr_branch} is at {seen[0][:7]}, not ours; delete or rename it on the "
                              f"host, then run.py close {tid}; or fetch it and run.py adopt {tid} --branch <b> --head <sha>")
        run.set_meta(task, pushed=head, pr_branch=pr_branch)
    elif pushed != head:
        ok, why = host.push(f"refs/heads/{branch}", pr_branch, pushed)
        if not ok:
            seen = run.git("ls-remote", remote, f"refs/heads/{pr_branch}", check=False)
            if seen.returncode != 0:
                raise Refused(f"ls-remote of {remote} failed: {first_line(seen.stderr)}; the push was refused: {why}", 1)
            if not seen.stdout.split():
                raise Refused(f"remote branch {remote}/{pr_branch} is gone (the host may delete it after a merge or a close); "
                              f"unset the pr, pr_branch and pushed meta of #{tid} to publish again")
            push_refused(run, task, pushed)
            return False
        run.set_meta(task, pushed=head)
        run.emit("pushed", tid, attempt, None, f"{head[:7]} to {remote}/{pr_branch}", "run.py record")
        pushed_now = True
    target, number = run.target(task), meta.get("pr")
    if not number:
        found = host.find_pr(pr_branch)
        request = found if found and found.state == "OPEN" else host.create_pr(
            pr_branch, target, f"{task['title']} (task #{tid})", request_body(run, task, head))
        number = request.number
        run.set_meta(task, pr=number, pr_branch=pr_branch)
        run.emit("published", tid, attempt, None, f"{host.label(number)} {request.url}; head {head[:7]} on "
                 f"{remote}/{pr_branch}, base {target}")
    if catch_up and not pushed_now:  # right after a push the host may still show the old head
        p = host.pr(int(number))
        if p.state == "OPEN" and p.merge_state == "BEHIND" and p.head == meta["pushed"]:
            rebase_branch(run, task, branch, head, p)
        else:
            pr_status(run, None, task, p)
    return True


def push_refused(run, task, pushed):
    tid, meta = task["id"], task["meta"]
    run.emit("push-refused", tid, wanted_attempt(task), None,
             f"{run.config['merge']['remote']}/{meta.get('pr_branch') or f'task-{tid}'} is not at {pushed[:7]}; someone else pushed",
             f"the operator decides: reset the remote branch to {pushed[:7]}, or merge by hand and run.py merged {tid} --by operator")


def rebase_branch(run, task, branch, head, p):
    """The request is behind its target: rebase the task branch in its idle worktree and push it again."""
    tid, meta = task["id"], task["meta"]
    attempt, host, remote = wanted_attempt(task) or 1, run.host(), run.config["merge"]["remote"]
    label, target = host.label(p.number), p.base_branch
    wt = task_worktree(run, tid)
    why = None
    if not os.path.isdir(wt):
        why = "worktree missing"
    elif any(s.live for s in own_sessions(run, tid, "task")):
        why = "session live"
    elif run.git("status", "--porcelain", cwd=wt, check=False).stdout.strip():
        why = "worktree dirty"
    elif run.git("branch", "--show-current", cwd=wt, check=False).stdout.strip() != branch:
        why = f"{branch} is not checked out there"
    if why:
        run.emit("pr-behind", tid, attempt, None, f"{label} is behind {target}; cannot rebase: {why}",
                 f"rebase {branch} by hand, then run.py close {tid}")
        return
    if run.git("rebase", run.target_ref(task), cwd=wt, check=False).returncode != 0:
        run.git("rebase", "--abort", cwd=wt, check=False)
        run.emit("conflict", tid, attempt, None, f"rebasing {branch} onto {remote}/{target} conflicted; rebase aborted",
                 decision_text(f"Rebase {branch} onto {target} for {label}", task))
        return
    new = run.git("rev-parse", "HEAD", cwd=wt).stdout.strip()
    same, reason = same_change(run, task, head, new)
    if not same:
        run.git("reset", "--keep", head, cwd=wt)
        run.emit("changed", tid, attempt, None, f"the rebase onto {target} changed the diff ({reason}); restored {head[:7]}",
                 decision_text(f"Rebase {branch} onto {target} by hand for {label}", task))
        return
    run.set_meta(task, verdict_ref=new)
    run.emit("rebased", tid, attempt, None, f"onto {remote}/{target} at {new[:7]}; same change as {head[:7]}")
    ok, _ = host.push(f"refs/heads/{branch}", meta["pr_branch"], meta["pushed"])
    if not ok:
        push_refused(run, task, meta["pushed"])
        return
    run.set_meta(task, pushed=new)
    run.emit("pushed", tid, attempt, None, f"{new[:7]} to {remote}/{meta['pr_branch']}")


def pr_status(run, snap, task, p):
    """Print what the request's state means for a closed task, and merge it when it is clean and allowed."""
    tid, meta = task["id"], task["meta"]
    host = run.host()
    label, target, pushed = host.label(p.number), p.base_branch, meta.get("pushed")
    if p.state == "OPEN" and not pushed:
        run.emit("pr-unpinned", tid, None, None, f"{label} is open but no pushed head is recorded for #{tid}; nothing is merged",
                 f"run.py close {tid} (pushes the branch and records the head)")
    elif p.state == "MERGED":
        run.set_meta(task, merged_at=run.now(), merged_by="operator", pushed=p.head)
        run.emit("merged", tid, None, None, f"{label} merged at {p.merge_commit or 'unknown commit'}; recorded merged_by=operator")
        cleanup(run, task)
    elif p.state == "CLOSED":
        run.emit("pr-closed", tid, None, None, f"{label} closed without a merge",
                 f"reopen it on the host and run.py record, or " + decision_text(f"{label} for #{tid} was closed: redo or drop?", task, snap))
    elif p.head != pushed:
        run.emit("pr-changed", tid, None, None, f"{label} head is {p.head[:7]}, not the pushed {pushed[:7]}; not merged by run.py",
                 f"the operator decides: reset the branch to {pushed[:7]} and push, or merge by hand and run.py merged {tid} --by operator")
    elif p.merge_state == "UNKNOWN":
        run.emit("pr-pending", tid, None, None, f"{label} state {p.raw_state}", "run.py record later")
    elif p.merge_state == "DRAFT":
        run.emit("pr-draft", tid, None, None, f"{label} is a draft", "mark it ready on the host")
    elif p.merge_state == "DIRTY":
        run.emit("conflict", tid, None, None, f"{label} conflicts with {target}",
                 decision_text(f"Resolve {label} conflicts with {target}", task, snap))
    elif p.merge_state == "BEHIND":
        run.emit("pr-behind", tid, None, None, f"{label} is behind {target}",
                 f"run.py close {tid} (rebases onto {run.config['merge']['remote']}/{target} and pushes again)")
    elif p.merge_state == "BLOCKED":
        run.emit("pr-blocked", tid, None, None, f"{label} {p.raw_state}; {host.blockers(p.number)}",
                 "run.py record later; a failed check is evidence for a fix task")
    else:  # CLEAN
        orders, method = run.orders(), run.config["merge"]["method"]
        if orders.stop:
            run.emit("ready-to-merge", tid, None, None, f"{label} is clean; not merged during a pause")
        elif not orders.merge:
            run.emit("ready-to-merge", tid, None, None, f"{label} is clean", "merge it on the host, then run.py record")
        else:
            ok, why = host.merge(p.number, method, pushed)
            if ok:
                run.set_meta(task, merged_at=run.now(), merged_by="manager")
                done = host.pr(p.number)
                run.emit("merged", tid, None, None, f"{label} merged ({method}) at {done.merge_commit or 'unknown commit'}")
                cleanup(run, task)
            else:
                run.emit("merge-failed", tid, None, None, f"{label}: {why}",
                         "fix the cause (permission, protection, method) and run.py record")


# ------------------------------------------------------------------- close

def transcript_usage(path):
    """(out, in, cache-read, cache-write) summed over the transcript."""
    usage = {}
    with open(path) as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            message = record.get("message") or {}
            # Streaming writes one record per content block; keep the last usage per message.
            if record.get("type") == "assistant" and message.get("usage") and message.get("id"):
                usage[message["id"]] = message["usage"]
    return tuple(sum(u.get(key, 0) for u in usage.values()) for key in
                 ("output_tokens", "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))


def find_tokens(run, tid, sid, row):
    """(out, in, cache-read, cache-write), or the reason there is none. Every session of a task shares its
    worktree, so they share one transcript folder; the id prefix tells them apart."""
    cwd = os.path.abspath(task_worktree(run, tid))
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    folder = os.path.join(base, "projects", re.sub(r"[^A-Za-z0-9]", "-", cwd))
    row = row or {}
    ids = [str(i) for i in dict.fromkeys(filter(None, (row.get("sessionId"), row.get("id"), sid)))
           if re.fullmatch(r"[0-9A-Za-z-]+", str(i))]
    if not ids:
        return "no session id recorded"
    for prefix in ids:
        found = glob.glob(os.path.join(glob.escape(folder), glob.escape(prefix) + "*.jsonl"))
        if len(found) > 1:
            return "the session id matches several transcripts"
        if found:
            return transcript_usage(found[0])
    # The worktree's folder has no transcript. A full session id (a UUID) may be filed under another folder.
    for prefix in ids:
        if UUID.fullmatch(prefix):
            elsewhere = glob.glob(os.path.join(glob.escape(base), "projects", "*", glob.escape(prefix) + ".jsonl"))
            if len(elsewhere) > 1:
                return f"session id {prefix} matches several transcripts under {os.path.join(base, 'projects')}"
            if elsewhere:
                return transcript_usage(elsewhere[0])
    if not os.path.isdir(folder):
        return f"transcript folder {folder} not found"
    return f"no transcript {ids[0]}*.jsonl in {folder}"


def stop_live(run, tid, attempt, branch):
    """Stop the task's live worker sessions, of any attempt. A failure is housekeeping: report it and go on."""
    for s in own_sessions(run, tid, "task"):
        if not s.live:
            continue
        out = run.claude("stop", s.sid, check=False)
        if out.returncode != 0:
            run.emit("kept", tid, attempt, s.sid,
                     f"session {s.sid} still live; claude stop said: {first_line(out.stderr or out.stdout)}")
            continue
        run.add_result(tid, "task", attempt, "manager", "STOPPED",
                       f"Session: {s.sid}\nWorktree: {s.worktree(run.root)}\nBranch: {branch}\n"
                       f"Stopped: {run.now()}\nFiles: None")
        run._sessions = None  # the stopped row no longer counts as live


def branch_at(run, tid, attempt, worker, ref, task=None):
    """(branch, ref): the task branch, checked to still be at `ref`. With `task`, a branch at another
    head is accepted when it carries the same change, and the new head is returned."""
    branch = (tail_or_none(BRANCH_LINE.search(worker["body"])) if worker else None) or task_branch(tid)
    out = run.git("rev-parse", "--verify", f"refs/heads/{branch}", check=False)
    if out.returncode != 0:
        raise Refused(f"branch {branch} not found; the output is gone, re-verify or pass --ref with checksums")
    tip = out.stdout.strip()
    if tip.startswith(ref):
        return branch, ref
    if task is None:
        raise Refused(f"branch {branch} is at {tip}, not {ref}: the output changed after the verdict; re-verify")
    same, why = same_change(run, task, ref, tip)
    if not same:
        raise Refused(f"branch {branch} is at {tip[:7]}, not {ref[:7]}: the change differs ({why}); re-verify")
    return branch, tip


def resume_close(run, task):
    """A close that stopped after `tg done`: finish the merge step, or the publish step in pr mode."""
    tid, ref = task["id"], str(task["meta"]["verdict_ref"])
    attempt = wanted_attempt(task) or 1
    worker = latest_worker(run.results_for(tid), attempt)
    branch, now = branch_at(run, tid, attempt, worker, ref, task)
    if now != ref:
        run.emit("rebased", tid, attempt, None, f"same change at {now[:7]} (verified at {ref[:7]}); verdict_ref moves")
        run.set_meta(task, verdict_ref=now)
    stop_live(run, tid, attempt, branch)
    if run.pr_mode:
        run.emit("resumed", tid, attempt, None, "closed earlier; continuing at publish")
        if publish(run, task, branch, now, catch_up=True):
            post_verdict(run, task, attempt, str(task["meta"]["verdict"]),
                         str(task["meta"].get("verdict_ref") or now), verify_kind(run, task, strict=False))
    else:
        run.emit("resumed", tid, attempt, None, f"closed earlier; continuing at the merge of {branch}")
        merge_branch(run, task, branch)
    ready_events(run, Snapshot(run))


def choose_verdict(run, args, task, rows, attempt):
    """(level, manual, override) from the verifier's verdict V and the --verdict and --override-verifier options."""
    tid, reason = task["id"], args.override_verifier
    found = [r for r in verifier_rows(rows, attempt) if verdict_of(r)]
    if not found:
        if reason:
            raise Refused(f"#{tid} has no verifier verdict to override; pass --verdict alone")
        if not args.verdict:
            wt = tail_or_none(WORKTREE_LINE.search(latest_worker(rows, attempt)["body"])) or "the worker's worktree"
            raise Refused(f"#{tid} has no verifier verdict; rerun VERIFY in {wt} and pass --verdict L, "
                          f"or run run.py verify {tid}")
        return args.verdict, True, None
    last, level = found[-1], verdict_of(found[-1])
    if not args.verdict or args.verdict == level:
        return level, False, None
    if not reason:
        raise Refused(f"verifier {last['author']} said {level} (result #{last['id']}); to change it, pass "
                      f'--override-verifier "<reason>" with evidence in --ran, or run run.py verify {tid} --again')
    wanted = args.verdict
    if wanted not in ("verify-failed", "verify-blocked"):
        if level == "verify-failed":
            raise Refused(f"a verify-failed verdict needs a fix round (run.py launch {tid}), not an override")
        if OVERRIDE_RANK[wanted] > OVERRIDE_RANK.get(level, -1) and not EVIDENCE.search(args.ran or ""):
            raise Refused(f"an upgrade from {level} to {wanted} needs evidence in --ran: a CI run id or URL, or an artifact link")
    return wanted, True, (level, last)


def cmd_close(run, args):
    tid = args.id
    task = run.show(tid)
    meta = task.get("meta") or {}
    if (task["status"] == "done" and is_sha(meta.get("verdict_ref")) and not meta.get("merged_at")
            and not meta.get("abandoned")):
        return resume_close(run, task)
    refuse_legacy(task)
    attempt = refuse_unless_running(task)
    rows, worker = worker_for(run, tid, attempt)
    kind = verify_kind(run, task)
    branch_line = tail_or_none(BRANCH_LINE.search(worker["body"]))
    level, manual, override = choose_verdict(run, args, task, rows, attempt)
    ref = args.ref or tail_or_none(HEAD_ANY.search(worker["body"]))
    if not ref:
        raise Refused(f"no Head: in result #{worker['id']}; pass --ref")
    branch = branch_line or task_branch(tid)
    if is_sha(ref):
        branch, new = branch_at(run, tid, attempt, worker, ref, task)
        if new != ref:
            run.emit("rebased", tid, attempt, None, f"same change at {new[:7]} (verified at {ref[:7]}); verdict_ref moves")
            ref = new
    if manual:
        status = {"verify-failed": "ISSUES", "verify-blocked": "BLOCKED"}.get(level, "PASS")
        body = f"Verdict: {level}\nRan: {args.ran or 'not stated'}\nHead: {ref}"
        if override:
            body = (f"Verdict: {level}\nOverrides: {override[0]} (result #{override[1]['id']} by {override[1]['author']})\n"
                    f"Reason: {args.override_verifier}\nRan: {args.ran or 'not stated'}\nHead: {ref}")
        earlier = [r for r in task_rows(rows, attempt, "verify") if r.get("author") == "manager"]
        if not (earlier and earlier[-1]["status"] == status and earlier[-1]["body"] == body):
            run.add_result(tid, "verify", attempt, "manager", status, body)
        if override:
            run.emit("override", tid, attempt, None,
                     f"{override[0]} by {override[1]['author']} -> {level}; {args.override_verifier}")
    run.edit_meta(tid, verdict=level, verdict_ref=ref)
    entry = next((e for e in reversed(recorded_sessions(task)) if e.get("kind") == "task" and e.get("attempt") == attempt), None)
    if entry:  # the session run.py recorded for this attempt, and its row if claude still lists it
        sid, row = entry["id"], next((s for s in run.sessions() if s.sid == entry["id"]), None)
    else:  # an unrecorded row in the task folder is the current attempt's
        own = own_sessions(run, tid, "task", attempt)
        row = own[-1] if own else None
        sid = row.sid if row else ""
    if not entry and not row:
        run.emit("tokens", tid, None, None, "no session recorded; none recorded")
    else:
        found = find_tokens(run, tid, sid, row.row if row else None)
        if isinstance(found, str):
            run.emit("tokens", tid, None, sid or None, f"{found}; none recorded")
        else:
            run.edit_meta(tid, tokens=f"{found[0]}/{found[1]}")
            run.emit("tokens", tid, None, sid or None,
                     f"out {found[0]} in {found[1]} cache-read {found[2]} cache-write {found[3]}")
    if level not in PASSING[kind]:
        run.emit("verdict", tid, attempt, None, f"{level}; not closed", unclosed_next(tid, level, kind))
        post_verdict(run, task, attempt, level, ref, kind)
        return
    run.tg("done", str(tid))
    stop_live(run, tid, attempt, branch)
    run.emit("closed", tid, attempt, None, f"{level} at {ref}; branch {branch}")
    meta.update(verdict=level, verdict_ref=ref)
    if not is_sha(ref):
        cleanup(run, task)  # outside git: there is no branch to merge
    elif run.pr_mode:
        if publish(run, task, branch, ref, catch_up=True):
            post_verdict(run, task, attempt, level, str(task["meta"].get("verdict_ref") or ref), kind)
    else:
        merge_branch(run, task, branch)
    ready_events(run, Snapshot(run))


def merge_branch(run, task, branch):
    tid = task["id"]
    orders = run.orders()
    if orders.stop:
        run.emit("ready-to-merge", tid, None, None, f"branch {branch}; not merged during a pause")
        return
    if not orders.merge:
        run.emit("ready-to-merge", tid, None, None, f"branch {branch}", f"merge it, then run.py merged {tid} --by operator")
        return
    if run.git("status", "--porcelain", check=False).stdout.strip():
        run.emit("ready-to-merge", tid, None, None, f"branch {branch}; main checkout is not clean")
        return
    target = run.git("branch", "--show-current").stdout.strip()
    if not target:
        run.emit("ready-to-merge", tid, None, None, f"branch {branch}; main checkout is detached")
        return
    out = run.git("merge", "--no-ff", "-m", f"Merge {branch} (task #{tid})", branch, check=False)
    if out.returncode == 0:
        run.tg("edit", str(tid), "--meta", meta_arg("merged_at", run.now()), meta_arg("merged_by", "manager"))
        run.emit("merged", tid, None, None,
                 f"{branch} into {target} at {run.git('rev-parse', 'HEAD').stdout.strip()}")
        cleanup(run, task)
        return
    run.git("merge", "--abort", check=False)
    blocks = [str(b["id"]) for b in task.get("blocks") or [] if b["derived_status"] != "done"]
    run.emit("conflict", tid, None, None, f"merging {branch} into {target} conflicted; merge aborted",
             f'tg add "Resolve merge of {branch} into {target}" --type decision --meta decider=operator'
             + (f" --blocks {' '.join(blocks)}" if blocks else ""))


# ------------------------------------------------- merged, stop, abandon

def cmd_merged(run, args):
    tid = args.id
    task = run.show(tid)
    meta = task.get("meta") or {}
    if task["status"] != "done" or not meta.get("verdict_ref"):
        raise Refused(f"#{tid} is not a closed task")
    if meta.get("merged_at"):
        run.emit("merged", tid, None, None, f"already recorded ({meta['merged_at']}, {meta.get('merged_by')})")
    else:
        run.tg("edit", str(tid), "--meta", meta_arg("merged_at", run.now()), meta_arg("merged_by", args.by))
        run.emit("merged", tid, None, None, f"recorded merged_by={args.by}")
    cleanup(run, task)


def cmd_stop(run, args):
    tid = args.id
    task = run.show(tid)
    refuse_legacy(task)
    attempt = wanted_attempt(task)
    live = [s for s in own_sessions(run, tid, "task", attempt) if s.live] if attempt is not None else []
    if not live:
        raise Refused(f"#{tid} attempt {attempt or 0} has no live session")
    s = live[0]
    run.claude("stop", s.sid)
    wt = s.worktree(run.root)
    files = run.git("status", "--porcelain", cwd=wt, check=False).stdout.rstrip("\n") if os.path.isdir(wt) else ""
    branch = (run.git("branch", "--show-current", cwd=wt, check=False).stdout.strip() if os.path.isdir(wt) else "") or "None"
    run.add_result(tid, "task", attempt, "manager", "STOPPED",
                   f"Session: {s.sid}\nWorktree: {wt}\nBranch: {branch}\nStopped: {run.now()}\nFiles: {files or 'None'}")
    run.emit("stopped", tid, attempt, s.sid, f"session {s.sid}; run.py record commits its WIP once it has exited")


def cmd_abandon(run, args):
    tid = args.id
    task = run.show(tid)
    if task["status"] != "in_progress":
        raise Refused(f"#{tid} is not in progress")
    refuse_legacy(task)
    meta = task.get("meta") or {}
    attempt = wanted_attempt(task)
    for s in own_sessions(run, tid, "task"):
        if s.live:
            run.claude("stop", s.sid)
            run.add_result(tid, "task", attempt, "manager", "ABANDONED",
                           f"Session: {s.sid}\nWorktree: {s.worktree(run.root)}\nAbandoned: {args.mode}")
    run.edit_meta(tid, abandoned=args.mode)
    names = {s.wtname for s in own_sessions(run, tid)}
    if os.path.isdir(run.wt_dir):
        names |= {e for e in os.listdir(run.wt_dir) if (wt_kind(e) or (None, None))[1] == tid or
                  ((m := LEGACY_WT.match(e)) and int(m.group(1)) == tid)}
    request = (f"; request {run.label(int(meta['pr']))} stays open, close it on the host by hand"
               if run.pr_mode and meta.get("pr") else "")
    run.emit("abandoned", tid, attempt, None,
             f"({args.mode}): worktrees kept: {', '.join(sorted(names)) or 'none'}; "
             "list them in the report for the operator to remove" + request)


# ------------------------------------------------------------------ status

def cell(value):
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ") or "—"


def table(headers, rows, limit):
    if not rows:
        return "None.\n"
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows[:limit]]
    if len(rows) > limit:
        lines.append(f"\n…and {len(rows) - limit} more.")
    return "\n".join(lines) + "\n"


def parse_since(value, run_dir):
    now = datetime.datetime.now(datetime.timezone.utc)
    if value is None:
        marker = os.path.join(run_dir, "last-report")
        if os.path.isfile(marker):
            with open(marker) as fh:
                return datetime.datetime.fromisoformat(fh.read().strip())
        value = "7d"
    match = re.fullmatch(r"(\d+)([dw])", value)
    if match:
        return now - datetime.timedelta(days=int(match.group(1)) * (7 if match.group(2) == "w" else 1))
    try:
        moment = datetime.datetime.fromisoformat(value)
    except ValueError:
        raise Refused(f"--since takes 7d, 2w, or a date such as 2026-10-01, not {value!r}")
    return moment if moment.tzinfo else moment.replace(tzinfo=datetime.timezone.utc)


def last_checkpoint(rows):
    for row in reversed(rows):
        if m := CHECKPOINT_LINE.search(row.get("body") or ""):
            return m.group(1).strip()
    return None


def result_label(row):
    return row["status"] if row["kind"] == "task" else f"{row['kind']} {row['status']}"


def cmd_status(run, args):
    since = parse_since(args.since, run.run_dir)
    snap = Snapshot(run)
    if not snap.by_id:
        raise Refused(f"project '{run.project}' has no tasks (check the name with `tg projects`)")
    summary = run.tg("report", "--since", since.date().isoformat()) or {}
    done, in_flight, waiting, failed, closing, unmerged_rows = [], [], [], [], [], []
    gitlab = (run.pr_mode and any(unmerged(t) and (t.get("meta") or {}).get("pr") for t in snap.done)
              and run.host_class()[0].prefix == "!")
    for task in snap.done:
        meta = task.get("meta") or {}
        tid = f"#{task['id']}"
        stamp = None
        if task.get("done_at"):
            stamp = datetime.datetime.fromisoformat(task["done_at"].replace("Z", "+00:00"))
        if stamp and stamp >= since:
            attempt = wanted_attempt(task)
            verifiers = task_rows(snap.rows(task["id"]), attempt, "verify")
            tokens = " / ".join(str(meta["tokens"]).split("/", 1)) if meta.get("tokens") else None
            done.append((tid, task["title"], meta.get("started_at"), run.zone_time(task.get("done_at")), tokens,
                         meta.get("verdict"), verifiers[-1]["author"] if verifiers else None))
        if unmerged(task):
            request = f"{'!' if gitlab else '#'}{meta['pr']}" if meta.get("pr") else None
            unmerged_rows.append((tid, task["title"], meta.get("verdict_ref"), request, meta.get("verdict")))
    for task in snap.in_progress:
        meta = task.get("meta") or {}
        tid = f"#{task['id']}"
        rows = snap.rows(task["id"])
        last = result_label(rows[-1]) if rows else None
        checkpoint = last_checkpoint(rows)
        attempt = meta.get("attempt")
        if meta.get("abandoned"):
            failed.append((tid, task["title"], meta.get("abandoned"), attempt, last, checkpoint))
        elif unclosed(task):
            closing.append((tid, task["title"], meta.get("verdict"), attempt, last))
        elif arrived(task, rows):
            waiting.append((tid, task["title"], last, meta.get("session"), checkpoint))
        else:
            in_flight.append((tid, task["title"], meta.get("session") or ("not managed" if attempt is None else None),
                              meta.get("model"), attempt,
                              meta.get("started_at"), last, checkpoint))
    changes = summary.get("changes") or {}
    change_text = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in changes.items() if v) or "no changes"
    decisions = [(f"#{d['id']} {d['title']}", (d.get("meta") or {}).get("decider"), d.get("due"),
                  ids_text([b for b in d.get("blocks") or [] if b not in snap.by_id or snap.by_id[b]["status"] != "done"]))
                 for d in snap.decisions]
    free, waits = snap.ready_tasks()
    ready = [(f"#{i}", snap.by_id[i]["title"] if i in snap.by_id else "") for i in free]
    ready += [(f"#{c}", f"waits: dependency #{d} not merged") for c, d in waits]
    limit = args.limit
    sections = [
        ("done", "Done since last report", ["Task", "Title", "Started", "Done", "Tokens out / in", "Verdict", "Verified by"], done),
        ("in_flight", "In flight", ["Task", "Title", "Session", "Model", "Attempt", "Started", "Last result", "Checkpoint"], in_flight),
        ("waiting", "Waiting for verification or triage", ["Task", "Title", "Result", "Session", "Checkpoint"], waiting),
        ("verdict_not_closed", "Verdict recorded, not closed", ["Task", "Title", "Verdict", "Attempt", "Last result"], closing),
        ("failed", "Failed or abandoned", ["Task", "Title", "Abandoned", "Attempt", "Last result", "Checkpoint"], failed),
        ("unmerged", "Done, branch not merged", ["Task", "Title", "Commit", "Request", "Verdict"], unmerged_rows),
        ("decisions", "Open decisions", ["Decision", "Decider", "By", "Blocks"], decisions),
        ("ready", "Ready", ["Task", "Title"], ready),
    ]
    overall = str(summary.get("overall", "unknown")).upper()
    out = [f"# Status: {run.project}\n", f"Overall: {overall}. Since {since:%Y-%m-%d %H:%M} UTC: {change_text}.\n"]
    for key, title, headers, rows in sections:
        out.append(f"## {title} ({len(rows)})\n")
        out.append(table(headers, rows, 10 if key == "ready" else limit))
    for key in ("risks", "issues", "asks"):
        items = summary.get(key) or []
        if items:
            out.append(f"Taskgraph {key}: {len(items)}. See `tg report`.")
    out.append("Token counts cover each session's own transcript only, not its sub-agents.")
    run.text = "\n".join(out) + "\n"
    run.payload = {"project": run.project, "overall": overall, "since": since.isoformat(), "changes": changes,
                   **{key: [dict(zip(headers, row)) for row in rows] for key, _, headers, rows in sections}}
    if args.mark:
        os.makedirs(run.run_dir, exist_ok=True)
        with open(os.path.join(run.run_dir, "last-report"), "w") as fh:
            fh.write(datetime.datetime.now(datetime.timezone.utc).isoformat())


# -------------------------------------------------------------------- main

def build_parser():
    parser = argparse.ArgumentParser(prog="run.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", help="repository root holding .agentic-team.toml (default: .)")
    parser.add_argument("--tg", help="path to tg.py (default: $TASKGRAPH_TG, else scripts/tg-path.sh)")
    parser.add_argument("--run-dir", help="default: <root>/.agentic-team")
    parser.add_argument("--json", action="store_true", help="print events as one JSON array")
    sub = parser.add_subparsers(dest="command", required=True, metavar="{launch,adopt,verify,record,close,merged,stop,abandon,status}")

    p = sub.add_parser("launch", help="start a worker for a task")
    p.add_argument("id", type=int)
    p.add_argument("--keyword", help="one or two hyphenated words added to the session name")
    p.add_argument("--tier", help="a tier or a models.overrides key (overrides the task's tier meta)")
    p.add_argument("--model", help="model alias (overrides the tier)")
    p.add_argument("--effort", help="effort level (with --model, or to override the tier's)")
    p.add_argument("--attempt", type=int, help="override the next attempt and lift the cap")
    p.add_argument("--dry-run", action="store_true", help="print the brief and the claude command; write nothing")
    p.add_argument("--base", help="start from this commit or branch instead of the default (a fix on an unmerged branch)")

    p = sub.add_parser("adopt", help="bring a branch started outside run.py under the Manager")
    p.add_argument("id", type=int)
    p.add_argument("--branch", required=True, help="the local branch that holds the work")
    p.add_argument("--head", required=True, help="the branch tip (7 to 40 hex characters)")
    p.add_argument("--pr", type=int, help="its open pull or merge request (merge.mode = pr)")
    p.add_argument("--base", help="the commit the work started from (default: the merge base with the target)")

    p = sub.add_parser("verify", help="start a verifier for a PASS result")
    p.add_argument("id", type=int)
    p.add_argument("--ref", help="the output under review (default: the result's Head:)")
    p.add_argument("--result", type=int, help="worker result id (default: the latest for the current attempt)")
    p.add_argument("--model")
    p.add_argument("--effort")
    p.add_argument("--again", action="store_true", help="allow a new verifier after a verify-blocked verdict")
    p.add_argument("--dry-run", action="store_true")

    sub.add_parser("record", help="read the queue and print one line per event")

    p = sub.add_parser("close", help="record the verdict and tokens, mark done, merge")
    p.add_argument("id", type=int)
    p.add_argument("--verdict", choices=VERDICTS)
    p.add_argument("--ref")
    p.add_argument("--ran", help="what you ran and saw (stored in your verify result)")
    p.add_argument("--override-verifier", metavar="REASON", help="change the verifier's verdict; an upgrade needs a run id or link in --ran")

    p = sub.add_parser("merged", help="record that a task branch is merged")
    p.add_argument("id", type=int)
    p.add_argument("--by", choices=("operator", "manager"), default="operator")

    p = sub.add_parser("stop", help="stop a worker for a pause")
    p.add_argument("id", type=int)

    p = sub.add_parser("abandon", help="abandon a task after attempt 3 failed")
    p.add_argument("id", type=int)
    p.add_argument("mode", choices=ABANDON_MODES)

    p = sub.add_parser("status", help="print the status report")
    p.add_argument("--since", help="7d, 2w, or an ISO date (default: last --mark, else 7d)")
    p.add_argument("--limit", type=int, default=25, help="max rows per table (default 25)")
    p.add_argument("--mark", action="store_true", help="save now as the start of the next report")
    return parser


COMMANDS = {"launch": cmd_launch, "adopt": cmd_adopt, "verify": cmd_verify, "record": cmd_record, "close": cmd_close,
            "merged": cmd_merged, "stop": cmd_stop, "abandon": cmd_abandon, "status": cmd_status}


def main(argv=None):
    args = build_parser().parse_args(argv)
    run = None
    try:
        run = Run(args)
        COMMANDS[args.command](run, args)
    except codehost.HostError as exc:  # Refused is one
        if run is not None:
            run.flush()
        elif args.json:
            print("[]")
        print(f"run.py: {exc}", file=sys.stderr)
        sys.exit(exc.code)
    run.flush()
    if run.host_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
