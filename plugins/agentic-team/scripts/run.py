#!/usr/bin/env python3
"""Run the Agentic Team workflow: one command per state change.

Usage:
    run.py [--root DIR] [--tg PATH] [--run-dir DIR] [--json] <command> ...

    launch <id>    render the brief, start the worker, record the start
    verify <id>    start a verifier session for a PASS result
    record         read the queue: results, dead and stuck sessions, merges,
                   open decisions, free slots, ready tasks
    close <id>     record the verdict and tokens, mark the task done, merge
    merged <id>    record that the operator merged a task branch
    stop <id>      stop a worker for a pause and file a STOPPED result
    abandon <id>   mark a task abandoned after attempt 3 failed
    status         print the status report (tables)

Run from the repository root. Taskgraph is the only source of task content;
this script copies it and never invents it. Nothing in it waits, sleeps, or
polls: `claude --bg` returns at once, and the Manager runs `record` later.

Text output is one line per event: `<event> #<id> attempt <n>: <detail>`, with
` | next: <step>` when a step follows. `--json` prints one JSON array of
{"event", "task", "attempt", "session", "detail", "next"} and nothing else
on stdout (`status --json` prints one object).

Exit codes: 0 the command ran (an event may still say `died` or `kept`);
1 a tool failed (tg, git, claude); 2 refused, the message names the fix;
3 the standing orders say STOP (launch only).

A live session row belongs to a task by its working directory, which ends
`.claude/worktrees/<task|verify>-<id>-<attempt>` inside this repository. Names
are never used: `claude agents --all` lists every project on the machine. A
session that `claude stop` ended shows `state` "stopped", no status, and an
unrelated directory. It belongs to the task whose result carries its
`Session: <id>` line, which run.py files whenever it stops a session. A stopped
row with no such line belongs to nobody. The worktree path is always derived
from the task and attempt, never read from a stopped row.
"""

import argparse
import datetime
import glob
import json
import os
import re
import shlex
import subprocess
import sys

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import ConfigError, load, problems as config_problems, resolve_model  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

# ------------------------------------------------------------------ common

MAX_ATTEMPTS = 3
DEFAULT_TIMEBOX_HOURS = 2
VERDICTS = ("artifact-verified", "test-verified", "check-only", "verify-blocked", "verify-failed")
CLOSING = ("artifact-verified", "test-verified")
ABANDON_MODES = ("died", "tool-error", "stuck", "unknown")
WT_NAME = re.compile(r"^(task|verify)-(\d+)-(\d+)(-\d+)?$")
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


class Refused(Exception):
    """A refusal or tool failure: `code` is the exit code, `message` goes to stderr."""

    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


def sh(cmd, cwd=None, input=None):
    try:
        return subprocess.run(cmd, cwd=cwd, input=input, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise Refused(f"cannot run {cmd[0]}: {exc.strerror}", 1)


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


def first_line(text):
    lines = (text or "").strip().splitlines()
    return lines[0].strip() if lines else ""


def tail_or_none(match):
    value = match.group(1).strip() if match else ""
    return None if value in ("", "None") else value


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
        self.config = load(self.root)
        found = config_problems(self.config)
        if found:
            raise Refused("fix the config before you continue (or run /agentic-team:setup):\n  " + "\n  ".join(found))
        self.project = self.config["taskgraph"]["project"]
        self.db = os.path.abspath(os.path.expanduser(os.environ.get("TASKGRAPH_DB") or "~/.taskgraph/tasks.db"))
        self.run_dir = os.path.abspath(args.run_dir or os.path.join(self.root, ".agentic-team"))
        self.wt_dir = os.path.realpath(os.path.join(self.root, ".claude", "worktrees"))
        self._sessions = None

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
            stopped = {}  # session id -> worktree name, from the Session: lines run.py filed
            for row in self.tg("result", "ls") or []:
                sid = tail_or_none(SESSION_LINE.search(row.get("body") or ""))
                wt = os.path.basename(tail_or_none(WORKTREE_LINE.search(row.get("body") or "")) or "")
                if not WT_NAME.match(wt) and row["kind"] == "task" and row.get("attempt"):
                    wt = f"task-{row['task_id']}-{row['attempt']}"
                if sid and WT_NAME.match(wt):
                    stopped[sid] = wt
            self._sessions = [Session(r, self.wt_dir, stopped) for r in rows if isinstance(r, dict)]
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

    A live row is tied by its working directory, inside this repository's
    .claude/worktrees/. A row with state "stopped" (what `claude stop` leaves) has
    no status and an unrelated directory; `stopped` maps its id to the worktree
    name that run.py recorded when it stopped the session. Names never count."""

    def __init__(self, row, wt_dir, stopped):
        self.row = row
        self.sid = str(row.get("id") or "")
        self.name = row.get("name") or ""
        self.cwd = row.get("cwd") or ""
        self.status = row.get("status")
        self.state = row.get("state")
        self.waiting = row.get("waitingFor")
        self.kind = self.task_id = self.attempt = self.wtname = None
        if self.state == "stopped":
            self.wtname = stopped.get(self.sid)
        elif self.cwd:
            real = os.path.realpath(self.cwd)
            if os.path.dirname(real) == wt_dir and WT_NAME.match(os.path.basename(real)):
                self.wtname = os.path.basename(real)
        if self.wtname:
            match = WT_NAME.match(self.wtname)
            self.kind, self.task_id, self.attempt = match.group(1), int(match.group(2)), int(match.group(3))
        self.finished = (self.status == "idle" and self.state == "done") or self.state == "stopped"
        self.live = not self.finished
        self.stuck = self.live and (bool(self.waiting) or self.state == "blocked")
        self.unknown = self.live and not self.stuck and self.status != "busy"

    def worktree(self, root):
        """The worktree path, derived from the task and attempt, never from the row."""
        return os.path.join(root, ".claude", "worktrees", self.wtname)

    def describe(self):
        return f"{self.sid} ({self.name}, {self.status}/{self.state})"


def own_sessions(run, tid, kind=None, attempt=None):
    return [s for s in run.sessions() if s.task_id == tid and (kind is None or s.kind == kind)
            and (attempt is None or s.attempt == attempt)]


def live_count(run):
    return sum(1 for s in run.sessions() if s.kind and s.live)


def wanted_attempt(task):
    value = (task.get("meta") or {}).get("attempt")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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


def unclosed_next(task_id, verdict):
    if verdict == "verify-blocked":
        return f"retry the check when its cause is fixed, then run.py close {task_id}"
    if verdict == "verify-failed":
        return f"fix round: run.py launch {task_id}"
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


def render(run, task, kind, attempt, session, ref=None, worker=None):
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
        values.update({
            "GOAL": (f"Judge whether the output of task {tid} ({task['title']}) meets every ACCEPTANCE line. "
                     "Check the real artifact, not the worker's report. Do not fix anything."),
            "SCOPE": "Read only. You run in your own worktree. Change nothing: do not edit, commit, or delete anything.",
            "SETUP": (f"Output under review: {ref}. If it is a commit SHA, run `git checkout --detach {ref}` in your "
                      "worktree first. If it is a list of checksums, the output is outside git: compare the files "
                      "against the checksums and check nothing out."),
            "CHECKPOINT": "None",
            "UPSTREAM": (f"### Worker report ({describe_result(worker)})\n\n"
                         f"{strip_comments(worker['body']).strip()}"),
            "VERIFY": values["VERIFY"] + ("\n\nThen exercise the real output: run it, open it, or read the values it\n"
                                          "produced. Report every failure you can prove, not only the first."),
            "AUTONOMY": "- None. You judge the output; you decide nothing.",
            "REPORT_NOTE": ("Add a `Verdict:` line after `Status:`: artifact-verified, test-verified, check-only, "
                            "verify-blocked, or verify-failed."),
        })
    else:
        rows = run.results_for(tid)
        previous = latest_worker(rows)
        base_rows = [r for r in rows if is_worker_result(r) or (r["status"] == "STOPPED" and r["kind"] == "task")]
        base = None
        if base_rows and (m := HEAD_LINE.search(base_rows[-1]["body"])):
            base = m.group(1)
        if base is None:
            base = run.git("rev-parse", "HEAD").stdout.strip()
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
            "SETUP": (f"Base commit: {base}. Your worktree starts from the default branch. Before anything else, "
                      f"run `git reset --keep {base}` in your worktree."),
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
        raise Refused(message, 1)
    return out.stdout.strip()


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


# ------------------------------------------------------------------ launch

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
    blockers = waiting_for(run, task)
    if blockers:
        raise Refused(f"#{tid} waits for {' '.join(blockers)}; finish or decide them first")
    current = wanted_attempt(task) or 0
    if meta.get("abandoned") and not args.attempt:
        raise Refused(f"#{tid} is abandoned ({meta['abandoned']}); pass --attempt {current + 1} to try again")
    for dep in task.get("depends_on") or []:
        if dep["derived_status"] == "done" or dep["status"] == "done":
            found = run.show(dep["id"])
            dmeta = found.get("meta") or {}
            if is_sha(dmeta.get("verdict_ref")) and not dmeta.get("merged_at"):
                raise Refused(f"#{tid} depends on #{dep['id']}, whose branch worktree-task-{dep['id']}-"
                              f"{wanted_attempt(found) or 1} is not merged; merge it and run "
                              f"run.py merged {dep['id']} --by operator, or wait")
    live = [s for s in own_sessions(run, tid, "task") if s.live]
    if live and task["status"] == "open":
        # An earlier launch started the session but died before it recorded the start.
        s = live[0]
        if not args.dry_run:
            run.tg("start", str(tid))
            run.tg("edit", str(tid), "--meta", meta_arg("session", s.name or s.wtname), meta_arg("attempt", s.attempt),
                   meta_arg("started_at", run.now()))
        run.emit("repaired", tid, s.attempt, s.sid, f"live session {s.sid} found for an open task; "
                 f"recorded the start", "run.py record")
        return
    rows = run.results_for(tid)
    latest = task_rows(rows, current)
    nxt = args.attempt or current + 1
    if latest and latest[-1]["status"] == "STOPPED" and not HEAD_ANY.search(latest[-1]["body"]):
        raise Refused(f"#{tid} attempt {current} is stopped and its WIP is not committed yet; run run.py record first")
    if not args.attempt and nxt > MAX_ATTEMPTS and not (latest and latest[-1]["status"] == "STOPPED"):
        raise Refused(f"#{tid}: attempt {MAX_ATTEMPTS} has failed; run run.py abandon {tid} "
                      f"<died|tool-error|stuck|unknown>, or pass --attempt {nxt} to override")
    session = f"task-{tid}-{nxt}" + (f"-{args.keyword}" if args.keyword else "")
    text = render(run, task, "task", nxt, session)
    live = [s for s in run.sessions() if s.task_id == tid and s.live]
    if live:
        raise Refused(f"#{tid} has a live session {live[0].describe()}; run run.py record, or run.py stop {tid}")
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
    worktree = f"task-{tid}-{nxt}"
    if args.dry_run:
        print("claude " + " ".join(session_args(run, worktree, session, model, effort)) + " <brief>", file=sys.stderr)
        if run.json:
            run.emit("dry-run", tid, nxt, session, text)
        else:
            print(text, end="")
        return
    path = write_brief(run, f"task-{tid}-{nxt}.md", text)
    said = start_session(run, worktree, session, model, effort, text)
    if task["status"] == "open":
        run.tg("start", str(tid))
    run.tg("edit", str(tid), "--meta", meta_arg("session", session), meta_arg("model", model),
           meta_arg("attempt", nxt), meta_arg("started_at", run.now()),
           "--unset-meta", "verdict", "verdict_ref", "abandoned")
    detail = (f"{model}{'/' + effort if effort else ''} session {session} worktree .claude/worktrees/{worktree} "
              f"brief {path}" + (f"; claude said: {said}" if said else ""))
    run.emit("launched", tid, nxt, session, detail)


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
            m = WT_NAME.match(entry)
            if m and m.group(1) == "verify" and int(m.group(2)) == tid and int(m.group(3)) == attempt:
                names.add(entry)
    k = 1 + len(names)
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
    text = render(run, task, "verify", attempt, name, ref=ref, worker=worker)
    if args.dry_run:
        print("claude " + " ".join(session_args(run, name, name, model, effort)) + " <brief>", file=sys.stderr)
        if run.json:
            run.emit("dry-run", tid, attempt, name, text)
        else:
            print(text, end="")
        return
    suffix = "-verify" if k == 1 else f"-verify-{k}"
    write_brief(run, f"task-{tid}-{attempt}{suffix}.md", text)
    start_session(run, name, name, model, effort, text)
    run.emit("verifying", tid, attempt, name, f"{model} session {name} ref {ref}")


# ------------------------------------------------------------------ record

def file_stuck(run, tid, attempt, kind, session, label):
    reason = session.waiting or session.state
    run.claude("stop", session.sid)
    run.add_result(tid, kind, attempt, "manager", "BLOCKED",
                   f"Session: {session.sid}\nWorktree: {session.worktree(run.root)}\n"
                   f"{label} {session.sid} stopped: waiting on {reason}")
    return reason


def record_arrived(run, snap, task, attempt, result):
    tid, status = task["id"], result["status"]
    held = snap.waiting_decisions(task)
    if held:
        title = next((d["title"] for d in snap.decisions if d["id"] == held[0]), "")
        run.emit("gated", tid, attempt, None, f'{status}; waits for decision #{held[0]} "{title}"')
        return
    if status == "BLOCKED" and result.get("author") == "manager":
        run.emit("stuck", tid, attempt, None, "filed earlier", f"run.py launch {tid} --model sonnet")
        return
    answered = [d for d in task.get("depends_on") or []
                if d in snap.by_id and snap.by_id[d]["type"] == "decision" and snap.by_id[d]["status"] == "done"]
    risk = (task.get("meta") or {}).get("risk")
    if status == "BLOCKED" and answered:
        run.emit("arrived", tid, attempt, None, f"BLOCKED by {result.get('author') or 'unknown'} (result #{result['id']})",
                 f"decision #{answered[0]} answered; run.py launch {tid}")
        return
    if status == "PASS":
        nxt = (f"run.py verify {tid}" if risk == "high"
               else f"rerun VERIFY in <Worktree:>, then run.py close {tid} --verdict L --ran \"...\"")
    elif status == "ISSUES":
        nxt = (f"fix round: run.py launch {tid}" if attempt < MAX_ATTEMPTS
               else f"attempt {MAX_ATTEMPTS} failed: run.py abandon {tid} <mode>")
    else:
        nxt = (f'answer it and run.py launch {tid}, or tg add "<question>" --type decision '
               f"--meta decider=operator --blocks {tid}")
    run.emit("arrived", tid, attempt, None, f"{status} by {result.get('author') or 'unknown'} (result #{result['id']})", nxt)


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
    wt = os.path.join(run.root, ".claude", "worktrees", f"task-{tid}-{attempt}")
    if not os.path.isdir(wt):
        run.add_result(tid, "task", attempt, "manager", "STOPPED",
                       f"Session: {sid}\nWorktree: {wt}\nBranch: None\nHead: None\nFiles: None")
        run.emit("stopped", tid, attempt, sid, "worktree missing; nothing to commit")
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


def record_in_progress(run, snap, task):
    tid, meta = task["id"], task.get("meta") or {}
    attempt = wanted_attempt(task)
    if meta.get("abandoned"):
        return
    if attempt is None:
        run.emit("unknown", tid, None, None, "in progress with no attempt meta", f"run.py launch {tid}")
        return
    rows = snap.rows(tid)
    verifiers = own_sessions(run, tid, "verify", attempt)
    live = [s for s in verifiers if s.live]
    if live:
        for s in live:
            if s.stuck:
                reason = file_stuck(run, tid, attempt, "verify", s, "Verifier")
                run.emit("stuck", tid, attempt, s.sid, f"stopped verifier {s.sid}; filed verify BLOCKED ({reason})",
                         f"use a model alias: run.py verify {tid} --model sonnet")
            else:
                run.emit("verifying", tid, attempt, s.sid, f"session {s.sid} ({s.name}, {s.status})")
        return
    verdicts = verifier_rows(rows, attempt)
    with_verdict = [r for r in verdicts if verdict_of(r)]
    if with_verdict and (not meta.get("verdict") or verdict_of(with_verdict[-1]) != meta.get("verdict")):
        last = with_verdict[-1]
        run.emit("verified", tid, attempt, None,
                 f"Verdict {verdict_of(last)} by {last['author']} (result #{last['id']})", f"run run.py close {tid}")
        return
    if verdicts and not with_verdict and not meta.get("verdict"):
        run.emit("verified", tid, attempt, None, f"no Verdict line (result #{verdicts[-1]['id']} by {verdicts[-1]['author']})",
                 f"run run.py close {tid} --verdict L")
        return
    if meta.get("verdict"):
        run.emit("unclosed", tid, attempt, None, f"verdict {meta['verdict']}", unclosed_next(tid, meta["verdict"]))
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
            reason = file_stuck(run, tid, attempt, "task", s, "Session")
            run.emit("stuck", tid, attempt, s.sid, f"stopped {s.sid}; filed BLOCKED ({reason})",
                     f"use a model alias and run.py launch {tid} --model sonnet, or decide")
        elif busy:
            run.emit("running", tid, attempt, busy[0].sid, f"session {busy[0].sid} ({busy[0].name})")
        elif unknown:
            s = unknown[0]
            run.emit("unknown", tid, attempt, s.sid, f"session {s.sid} status={s.status} state={s.state}; not filed as DIED",
                     f"claude logs {s.sid}")
        else:
            s = mine[-1] if mine else None
            found = salvage(run, tid, attempt, s)
            if found:
                added = run.add_result(tid, "task", attempt, "manager", found[0], found[1])
                run.emit("salvaged", tid, attempt, s.sid,
                         f"{found[0]} from claude logs {s.sid} (result #{added['id']})")
                record_arrived(run, snap, task, attempt, added)
            else:
                where = (f"session {s.sid} {s.status}/{s.state}" if s
                         else f"no session for .claude/worktrees/task-{tid}-{attempt}")
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
    if unmerged(task):
        sha = str(meta["verdict_ref"])
        if run.git("merge-base", "--is-ancestor", sha, "HEAD", check=False).returncode == 0:
            run.tg("edit", str(tid), "--meta", meta_arg("merged_at", run.now()), meta_arg("merged_by", "operator"))
            run.emit("merged", tid, None, None, f"{sha} is in HEAD; recorded merged_by=operator")
            cleanup(run, task)
        else:
            waits = [b for b in task.get("blocks") or [] if b in snap.by_id and snap.by_id[b]["status"] != "done"]
            run.emit("unmerged", tid, None, None,
                     f"branch worktree-task-{tid}-{wanted_attempt(task) or 1} at {sha} is ready to merge; blocks {ids_text(waits)}")
    elif meta.get("merged_at"):
        cleanup(run, task)


def ready_events(run, snap):
    free, waits = snap.ready_tasks()
    for c, d in waits:
        run.emit("waits", c, None, None, f"dependency #{d} not merged")
    run.emit("ready", None, None, None, " ".join(f"#{i}" for i in free) or "none")


def cmd_record(run, args):
    snap = Snapshot(run)
    for task in sorted(snap.in_progress, key=lambda t: t["id"]):
        record_in_progress(run, snap, task)
    for task in sorted(snap.done, key=lambda t: t["id"]):
        record_done(run, snap, task)
    for d in sorted(snap.decisions, key=lambda t: t["id"]):
        blocks = [b for b in d.get("blocks") or [] if b not in snap.by_id or snap.by_id[b]["status"] != "done"]
        run.emit("decision", d["id"], None, None,
                 f'"{d["title"]}" decider {(d.get("meta") or {}).get("decider") or "none"} '
                 f"by {d.get('due') or 'no date'} blocks {ids_text(blocks)}")
    run.emit("slots", None, None, None, f"{live_count(run)}/{run.config['sessions']['max_parallel']} live")
    ready_events(run, snap)


# ----------------------------------------------------------------- cleanup

def cleanup(run, task):
    """Remove the sessions and worktrees of a merged task. Never deletes a file."""
    tid = task["id"]
    if (task.get("meta") or {}).get("abandoned"):
        return
    rows = own_sessions(run, tid)
    leftover = [e for e in sorted(os.listdir(run.wt_dir))
                if (m := WT_NAME.match(e)) and int(m.group(2)) == tid] if os.path.isdir(run.wt_dir) else []
    if not rows and not leftover:
        return
    known = set()
    for s in rows:
        known.add(s.wtname)
        wt = s.worktree(run.root)
        if s.live:
            run.emit("kept", tid, None, s.sid, f"{s.wtname}: still running")
            continue
        if os.path.isdir(wt):
            if run.git("status", "--porcelain", cwd=wt, check=False).stdout.strip():
                run.emit("kept", tid, None, s.sid, f"{s.wtname}: uncommitted changes")
                continue
        out = run.claude("rm", s.sid, check=False)
        if out.returncode == 0:
            run.emit("removed", tid, None, s.sid, f"session {s.sid} worktree {s.wtname}")
            continue
        message = (out.stderr + "\n" + out.stdout).strip()
        m = re.search(r"--discard-unpushed\s+([0-9A-Za-z]+)@(\S+)", message)
        if m:
            commit, wtid = m.groups()
            if run.git("merge-base", "--is-ancestor", commit, "HEAD", check=False).returncode == 0:
                again = run.claude("rm", s.sid, "--discard-unpushed", f"{commit}@{wtid}", check=False)
                if again.returncode == 0:
                    run.emit("removed", tid, None, s.sid,
                             f"session {s.sid} worktree {s.wtname} (discarded {commit}, which is in HEAD)")
                else:
                    run.emit("kept", tid, None, s.sid,
                             f"{s.wtname}: claude rm said: {first_line(again.stderr or again.stdout)}")
            else:
                run.emit("kept", tid, None, s.sid, f"{s.wtname}: commit {commit} is not in HEAD")
        elif "untracked" in message.lower():
            files = ""
            if os.path.isdir(wt):
                listing = run.git("status", "--porcelain", cwd=wt, check=False).stdout.splitlines()
                files = " (" + ", ".join(line[3:] for line in listing if line.startswith("??")) + ")"
            run.emit("kept", tid, None, s.sid,
                     f"{s.wtname}: untracked files{files}; delete only files you created, then run run.py merged {tid}")
        else:
            run.emit("kept", tid, None, s.sid, f"{s.wtname}: claude rm said: {first_line(message)}")
    for entry in leftover:
        if entry not in known:
            run.emit("kept", tid, None, None, f"{entry}: no session; remove it by hand if you want")


# ------------------------------------------------------------------- close

def find_tokens(run, session):
    """(out, in, cache-read, cache-write), or the reason there is none."""
    cwd = os.path.abspath(session.worktree(run.root))
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    folder = os.path.join(base, "projects", re.sub(r"[^A-Za-z0-9]", "-", cwd))
    ids = [i for i in (session.row.get("sessionId"), session.row.get("id")) if i]
    for prefix in dict.fromkeys(str(i) for i in ids):
        if not re.fullmatch(r"[0-9A-Za-z-]+", prefix):
            continue
        found = glob.glob(os.path.join(glob.escape(folder), glob.escape(prefix) + "*.jsonl"))
        if len(found) > 1:
            return "the session id matches several transcripts"
        if found:
            usage = {}
            with open(found[0]) as fh:
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
    return "no transcript found"


def stop_live(run, tid, attempt, branch):
    """Stop the task's live worker session. A failure is housekeeping: report it and go on."""
    for s in own_sessions(run, tid, "task", attempt):
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


def branch_at(run, tid, attempt, worker, ref):
    """The task branch, checked to still be at `ref`."""
    branch = (tail_or_none(BRANCH_LINE.search(worker["body"])) if worker else None) or f"worktree-task-{tid}-{attempt}"
    out = run.git("rev-parse", "--verify", f"refs/heads/{branch}", check=False)
    if out.returncode != 0:
        raise Refused(f"branch {branch} not found; the output is gone, re-verify or pass --ref with checksums")
    if not out.stdout.strip().startswith(ref):
        raise Refused(f"branch {branch} is at {out.stdout.strip()}, not {ref}: "
                      "the output changed after the verdict; re-verify")
    return branch


def resume_close(run, task):
    """A close that stopped after `tg done`: finish the merge step."""
    tid, ref = task["id"], str(task["meta"]["verdict_ref"])
    attempt = wanted_attempt(task) or 1
    worker = latest_worker(run.results_for(tid), attempt)
    branch = branch_at(run, tid, attempt, worker, ref)
    stop_live(run, tid, attempt, branch)
    run.emit("resumed", tid, attempt, None, f"closed earlier; continuing at the merge of {branch}")
    merge_branch(run, task, branch)
    ready_events(run, Snapshot(run))


def cmd_close(run, args):
    tid = args.id
    task = run.show(tid)
    meta = task.get("meta") or {}
    if (task["status"] == "done" and is_sha(meta.get("verdict_ref")) and not meta.get("merged_at")
            and not meta.get("abandoned")):
        return resume_close(run, task)
    attempt = refuse_unless_running(task)
    rows, worker = worker_for(run, tid, attempt)
    branch_line = tail_or_none(BRANCH_LINE.search(worker["body"]))
    heads = verifier_rows(rows, attempt)
    heads = [r for r in heads if verdict_of(r)]
    if heads:
        level = verdict_of(heads[-1])
        if args.verdict and args.verdict != level:
            raise Refused(f"verifier {heads[-1]['author']} said {level} (result #{heads[-1]['id']}); "
                          f"to change it, run run.py verify {tid} --again")
        manual = False
    else:
        if not args.verdict:
            wt = tail_or_none(WORKTREE_LINE.search(worker["body"])) or "the worker's worktree"
            raise Refused(f"#{tid} has no verifier verdict; rerun VERIFY in {wt} and pass --verdict L, "
                          f"or run run.py verify {tid}")
        level, manual = args.verdict, True
    ref = args.ref or tail_or_none(HEAD_ANY.search(worker["body"]))
    if not ref:
        raise Refused(f"no Head: in result #{worker['id']}; pass --ref")
    branch = branch_line or f"worktree-task-{tid}-{attempt}"
    if is_sha(ref):
        branch = branch_at(run, tid, attempt, worker, ref)
    if manual:
        status = {"verify-failed": "ISSUES", "verify-blocked": "BLOCKED"}.get(level, "PASS")
        body = f"Verdict: {level}\nRan: {args.ran or 'not stated'}\nHead: {ref}"
        earlier = [r for r in task_rows(rows, attempt, "verify") if r.get("author") == "manager"]
        if not (earlier and earlier[-1]["status"] == status and earlier[-1]["body"] == body):
            run.add_result(tid, "verify", attempt, "manager", status, body)
    run.edit_meta(tid, verdict=level, verdict_ref=ref)
    own = own_sessions(run, tid, "task", attempt)
    if not own:
        run.emit("tokens", tid, None, None, "no session row; none recorded")
    else:
        found = find_tokens(run, own[-1])
        if isinstance(found, str):
            run.emit("tokens", tid, None, own[-1].sid, f"{found}; none recorded")
        else:
            run.edit_meta(tid, tokens=f"{found[0]}/{found[1]}")
            run.emit("tokens", tid, None, own[-1].sid,
                     f"out {found[0]} in {found[1]} cache-read {found[2]} cache-write {found[3]}")
    if level not in CLOSING:
        run.emit("verdict", tid, attempt, None, f"{level}; not closed", unclosed_next(tid, level))
        return
    run.tg("done", str(tid))
    stop_live(run, tid, attempt, branch)
    run.emit("closed", tid, attempt, None, f"{level} at {ref}; branch {branch}")
    if is_sha(ref):
        merge_branch(run, task, branch)
    else:
        cleanup(run, task)  # outside git: there is no branch to merge
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
    attempt = wanted_attempt(task)
    for s in own_sessions(run, tid, "task", attempt):
        if s.live:
            run.claude("stop", s.sid)
            run.add_result(tid, "task", attempt, "manager", "ABANDONED",
                           f"Session: {s.sid}\nWorktree: {s.worktree(run.root)}\nAbandoned: {args.mode}")
    run.edit_meta(tid, abandoned=args.mode)
    names = {s.wtname for s in own_sessions(run, tid)}
    if os.path.isdir(run.wt_dir):
        names |= {e for e in os.listdir(run.wt_dir) if (m := WT_NAME.match(e)) and int(m.group(2)) == tid}
    run.emit("abandoned", tid, attempt, None,
             f"({args.mode}): worktrees kept: {', '.join(sorted(names)) or 'none'}; "
             "list them in the report for the operator to remove")


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
            unmerged_rows.append((tid, task["title"], meta.get("verdict_ref"), meta.get("verdict")))
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
            in_flight.append((tid, task["title"], meta.get("session"), meta.get("model"), attempt,
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
        ("unmerged", "Done, branch not merged", ["Task", "Title", "Commit", "Verdict"], unmerged_rows),
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
    sub = parser.add_subparsers(dest="command", required=True, metavar="{launch,verify,record,close,merged,stop,abandon,status}")

    p = sub.add_parser("launch", help="start a worker for a task")
    p.add_argument("id", type=int)
    p.add_argument("--keyword", help="one or two hyphenated words added to the session name")
    p.add_argument("--tier", help="a tier or a models.overrides key (overrides the task's tier meta)")
    p.add_argument("--model", help="model alias (overrides the tier)")
    p.add_argument("--effort", help="effort level (with --model, or to override the tier's)")
    p.add_argument("--attempt", type=int, help="override the next attempt and lift the cap")
    p.add_argument("--dry-run", action="store_true", help="print the brief and the claude command; write nothing")

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


COMMANDS = {"launch": cmd_launch, "verify": cmd_verify, "record": cmd_record, "close": cmd_close,
            "merged": cmd_merged, "stop": cmd_stop, "abandon": cmd_abandon, "status": cmd_status}


def main(argv=None):
    args = build_parser().parse_args(argv)
    run = None
    try:
        run = Run(args)
        COMMANDS[args.command](run, args)
    except Refused as exc:
        if run is not None:
            run.flush()
        elif args.json:
            print("[]")
        print(f"run.py: {exc}", file=sys.stderr)
        sys.exit(exc.code)
    run.flush()


if __name__ == "__main__":
    main()
