#!/usr/bin/env python3
"""Render a worker brief for one Taskgraph task. Taskgraph is the only source
of task content; this script copies it and never invents it.

Usage:
    brief.py --tg PATH --task ID --keyword WORDS [--kind task|verify]
             [--report RESULT_ID] --verdict-ref REF (verify only) [--attempt N]
             [--session NAME] [--root .] [--run-dir <root>/.agentic-team]

The worker's own session name, which the Manager launches it under, is
task-<id>-<attempt>-<keyword>, or verify-<id>-<attempt> for a verifier.
brief.py builds it from --keyword and the attempt it picks, writes it into the
worker's result command, and prints `session=` and `attempt=` on stderr.
--session overrides the name. A task brief refuses a next attempt beyond 3
(exit 2) unless --attempt is given.

Sources:
    GOAL        task title, plus the prose in its notes ("why it is needed").
                A `Word: text` line stays in the prose unless it is an
                `Exit test:` or `Acceptance:` line.
    ACCEPTANCE  `- [ ]` checklist items and `Exit test:` lines in the notes
    SCOPE       `scope` metadata, plus `serialization.rules` from the config
    VERIFY      `verify` metadata
    TIMEBOX     twice the `estimate` metadata (hours); 2 hours without one
    CHECKPOINT  the `Checkpoint:` line of this task's latest task result
    UPSTREAM    this task's previous report (fix rounds), then the latest
                task result of each task this one depends on. Both come
                from the Taskgraph result log. Notes the Manager wrote itself
                are skipped: DIED, and BLOCKED written --by manager. A worker
                report the Manager filed from the logs counts.
    REPORT      the exact `tg result add` command the worker runs last, with
                the report on stdin in a quoted heredoc. It pins the
                interpreter, tg.py, and the database ($TASKGRAPH_DB, else
                ~/.taskgraph/tasks.db) by absolute path.
    BASE        the commit the worker's worktree must start from. A worktree
                starts from the default branch, so the brief tells the worker
                to run `git reset --keep <BASE>`. BASE is the `Head:` commit of
                this task's previous worker result (a fix round builds on it),
                else the Manager's `git rev-parse HEAD` in <root>.
    other       project config (read through config.py from <root>),
                standing orders, and the arguments

For --kind verify, --report is the id of the worker's result (default: the
latest task result for the current attempt). Its body goes into the brief.

Writes <run-dir>/briefs/task-<id>-<attempt>[-verify].md and prints its path.
Exit 2 lists what to fix in Taskgraph or the config (see `config.py check`). Exit 3 means the
standing orders start with STOP. Exit 1 means Taskgraph failed.
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load, problems as config_problems  # noqa: E402

# Only these labels are fields. Any other `Word: text` line is goal prose.
FIELD_LINE = re.compile(r"^(exit tests?|acceptance):\s*(.*)$", re.I)
CHECK_ITEM = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+(.*)$")
CHECKPOINT_LINE = re.compile(r"(?m)^Checkpoint:\s*(.*)$")
HEAD_LINE = re.compile(r"(?m)^Head:\s*([0-9a-f]{7,40})\s*$")
DEFAULT_TIMEBOX_HOURS = 2
MAX_ATTEMPTS = 3
CONSTRAINT_LABELS = [
    ("read_only", "Read-only sources"),
    ("pinned_versions", "Pinned versions"),
    ("do_not_send", "Do not send"),
    ("do_not_modify", "Do not modify"),
]


def strip_comments(text):
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def fail(message, code=2):
    print(f"brief.py: {message}", file=sys.stderr)
    sys.exit(code)


def read(path):
    with open(path) as fh:
        return fh.read()


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


def quote(value):
    """Double-quote a path for a shell command, as the brief shows it."""
    return '"' + re.sub(r'([\\"$`])', r"\\\1", str(value)) + '"'


def database_path():
    """The database tg.py uses: $TASKGRAPH_DB, else ~/.taskgraph/tasks.db."""
    return os.path.abspath(os.path.expanduser(os.environ.get("TASKGRAPH_DB") or "~/.taskgraph/tasks.db"))


def run_tg(tg, db, project, *cmd):
    out = subprocess.run([sys.executable, tg, "--db", db, "--project", project, "--json", *cmd],
                         capture_output=True, text=True)
    if out.returncode != 0:
        fail(f"tg {' '.join(cmd)} failed: {out.stderr.strip()}", 1)
    return json.loads(out.stdout or "null")


def task_results(tg, db, project, task_id):
    """A task's worker results, oldest first, without the Manager's own notes.

    Those are DIED, and BLOCKED written by the Manager for a stuck session. A
    report the Manager salvaged from the logs keeps its real status and counts."""
    found = run_tg(tg, db, project, "result", "ls", str(task_id), "--kind", "task") or []
    return [r for r in found
            if r["status"] != "DIED" and not (r["status"] == "BLOCKED" and r.get("author") == "manager")]


def describe(result):
    attempt = f", attempt {result['attempt']}" if result.get("attempt") is not None else ""
    return f"result #{result['id']}, {result['status']}{attempt}"


def head_of(root):
    out = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True)
    if out.returncode != 0:
        fail(f"cannot read HEAD in {root}: {out.stderr.strip()}; run from the repository root", 1)
    return out.stdout.strip()


def result_command(py, tg, db, project, task_id, kind, attempt, session):
    """The command the worker runs last. The worker fills in only the status and the body."""
    return (f"{quote(py)} {quote(tg)} --db {quote(db)} --project {shlex.quote(project)} "
            f"result add {task_id} --kind {kind} --attempt {attempt} --by {shlex.quote(session)} "
            f"--status <STATUS> --body-file - <<'REPORT'\n<your report>\nREPORT")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tg", required=True, help="path to tg.py (from scripts/tg-path.sh)")
    parser.add_argument("--task", required=True, type=int)
    parser.add_argument("--keyword", help="one or two words naming the work; builds task-<id>-<attempt>-<keyword>")
    parser.add_argument("--session", help="override the session name (default: built from --keyword and the attempt)")
    parser.add_argument("--kind", choices=["task", "verify"], default="task")
    parser.add_argument("--report", type=int, help="id of the worker's result (verify only; default: latest for the current attempt)")
    parser.add_argument("--verdict-ref", help="the worker's Head: commit SHA, or output checksums (verify only)")
    parser.add_argument("--attempt", type=int, help="default: next attempt for task, current for verify")
    parser.add_argument("--root", default=".", help="repository root holding .agentic-team.toml (default: .)")
    parser.add_argument("--run-dir", help="default: <root>/.agentic-team")
    args = parser.parse_args()

    if args.kind == "verify" and not args.verdict_ref:
        fail("--kind verify needs --verdict-ref")
    config = load(args.root)
    problems = [f"config: {p}" for p in config_problems(config)]
    if problems:
        fail("fix before launch (or run /agentic-team:setup):\n  " + "\n  ".join(problems))
    project = config["taskgraph"]["project"]
    args.run_dir = args.run_dir or os.path.join(args.root, ".agentic-team")

    orders_path = os.path.join(args.run_dir, "standing-orders.md")
    orders = strip_comments(read(orders_path)) if os.path.isfile(orders_path) else ""
    orders = re.sub(r"(?m)^# .*$", "", orders).strip() or "None yet."
    first = orders.splitlines()[0].strip() if orders else ""
    if args.kind == "task" and re.match(r"^(\d+\.\s*)?STOP\b", first):
        fail(f"standing orders say {first!r}; launch nothing", 3)

    tg = os.path.abspath(args.tg)
    db = database_path()
    task = run_tg(tg, db, project, "show", str(args.task))
    meta = task.get("meta") or {}
    why, acceptance = parse_notes(task.get("notes"))
    tg_cmd = f"{quote(sys.executable)} {quote(tg)} --db {quote(db)} --project {shlex.quote(project)}"
    edit = f"{tg_cmd} edit {args.task}"

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
        fail(f"task {args.task} is not scoped; fix it in Taskgraph, then rerun:\n  " + "\n  ".join(missing))

    scope = str(meta["scope"]).strip()
    rules = config["serialization"]["rules"]
    if rules:
        scope += "\n\nShared-file rules:\n" + "\n".join(f"- {rule}" for rule in rules)

    try:
        timebox = f"{float(meta['estimate']) * 2:g} hours (twice the {meta['estimate']}-hour estimate)"
    except (KeyError, TypeError, ValueError):
        timebox = f"{DEFAULT_TIMEBOX_HOURS} hours (no estimate set)"

    plan = config["taskgraph"]["plan"]
    own = task_results(tg, db, project, args.task)
    current = int(meta.get("attempt") or 0)
    attempt = args.attempt or (current if args.kind == "verify" else current + 1) or 1
    if args.kind == "task" and not args.attempt and attempt > MAX_ATTEMPTS:
        fail(f"task {args.task} has used attempts 1 to {MAX_ATTEMPTS}; abandon it "
             f"(drain playbook, step 4) or pass --attempt to override")
    if args.session:
        session = args.session
    elif args.kind == "verify":
        session = f"verify-{args.task}-{attempt}"
    elif args.keyword and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", args.keyword):
        session = f"task-{args.task}-{attempt}-{args.keyword}"
    else:
        fail("a task brief needs --keyword (letters, digits, and hyphens) or --session")

    upstream, checkpoint, base = [], "None", ""
    previous = own[-1] if own and args.kind == "task" else None
    if args.kind == "task":
        base = head_of(args.root)
    if previous:
        if m := CHECKPOINT_LINE.search(previous["body"]):
            checkpoint = m.group(1).strip() or "None"
        if m := HEAD_LINE.search(previous["body"]):
            base = m.group(1)
        upstream.append(f"### Previous attempt ({describe(previous)})\n\n"
                        f"Start from this report. Fix what it lists; do not redo what passed.\n\n"
                        f"{strip_comments(previous['body']).strip()}")
    for dep in task.get("depends_on") or []:
        found = task_results(tg, db, project, dep["id"])
        body = (f"{describe(found[-1])}\n\n{strip_comments(found[-1]['body']).strip()}"
                if found else "No report on file.")
        upstream.append(f"### Upstream #{dep['id']}: {dep['title']} ({dep['status']})\n\n{body}")

    worker_report = ""
    if args.kind == "verify":
        if args.report is not None:
            chosen = [r for r in own if r["id"] == args.report]
        else:
            chosen = [r for r in own if r.get("attempt") == current][-1:]
        if not chosen:
            fail(f"task {args.task} has no worker result to verify"
                 + (f" with id {args.report}" if args.report is not None else f" for attempt {current}"), 1)
        worker_report = f"{describe(chosen[0])}\n\n{strip_comments(chosen[0]['body']).strip()}"

    constraints = config["constraints"]
    forbidden = [f"- {label}: {constraints[key]}" for key, label in CONSTRAINT_LABELS
                 if constraints[key].strip()]
    forbidden += [f"- {item}" for item in constraints["other"] if item.strip()]
    autonomy_cfg = config["autonomy"]
    autonomy = [f"- Standing grant: {autonomy_cfg['grant'] or 'None. Report product decisions as BLOCKED.'}",
                f"- Always pause for: {'; '.join(autonomy_cfg['always_pause']) or 'None'}"]
    consultants = ", ".join(config["consultants"]["sessions"])

    values = {
        "TASK_ID": str(args.task),
        "TASK_TITLE": task["title"],
        "PROJECT": project,
        "SESSION_NAME": session,
        "TIMEZONE": config["sessions"]["timezone_label"] or config["sessions"]["timezone"],
        "GOAL": f"{task['title']}. {why}",
        "SCOPE": scope,
        "TASKGRAPH_COMMAND": tg_cmd,
        "PLAN_FILE": plan or "None",
        "CHECKPOINT": checkpoint,
        "BASE": base,
        "CONSULTANTS": consultants or "None. Do not contact a consultant.",
        "UPSTREAM": "\n\n".join(upstream),
        "ACCEPTANCE": "\n".join(f"- {item}" for item in acceptance),
        "VERIFY": str(meta["verify"]).strip(),
        "TIMEBOX": timebox,
        "FORBIDDEN": "\n".join(forbidden) or "None beyond the worker rules.",
        "AUTONOMY": "\n".join(autonomy),
        "STANDING_ORDERS": orders or "None yet.",
        "WORKER_REPORT": worker_report,
        "RESULT_COMMAND": result_command(sys.executable, tg, db, project, args.task, args.kind, attempt, session),
        "VERDICT_REF": args.verdict_ref or "",
    }

    if args.kind == "verify":
        template = os.path.join(PLUGIN_ROOT, "templates", "verifier-brief.md")
    else:
        template = config["sessions"]["brief_template"]
    if "{{RESULT_COMMAND}}" not in read(template):
        fail(f"{template} has no {{{{RESULT_COMMAND}}}}; the worker could not report")
    text = re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: values.get(m.group(1), m.group(0)), read(template))
    unknown = sorted(set(re.findall(r"\{\{[A-Z_]+\}\}", text)))
    if unknown:
        fail(f"{template} uses unknown placeholders: {', '.join(unknown)}")

    suffix = "-verify" if args.kind == "verify" else ""
    path = os.path.join(args.run_dir, "briefs", f"task-{args.task}-{attempt}{suffix}.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(re.sub(r"\n{3,}", "\n\n", text))
    print(path)
    print(f"attempt={attempt}\nsession={session}", file=sys.stderr)


if __name__ == "__main__":
    main()
