#!/usr/bin/env python3
"""Render a worker brief for one Taskgraph task. Taskgraph is the only source
of task content; this script copies it and never invents it.

Usage:
    brief.py --tg PATH --task ID --session NAME [--kind task|verify]
             [--report FILE --verdict-ref REF] [--attempt N]
             [--root .] [--run-dir <root>/.agentic-team]

Sources:
    GOAL        task title, plus the prose in its notes ("why it is needed")
    ACCEPTANCE  `- [ ]` checklist items and `Exit test:` lines in the notes
    SCOPE       `scope` metadata, plus `serialization.rules` from the config
    VERIFY      `verify` metadata
    TIMEBOX     twice the `estimate` metadata (hours); 2 hours without one
    STATE_AT    `state_at` metadata, else a legacy `State at` line
    UPSTREAM    this task's previous report (fix rounds), then the latest
                saved report of each task this one depends on
    other       project config (read through config.py from <root>),
                standing orders, and the arguments

Writes <run-dir>/briefs/task-<id>-<attempt>[-verify].md and prints its path.
Exit 2 lists what to fix in Taskgraph or the config (see `config.py check`). Exit 3 means the
standing orders start with STOP. Exit 1 means Taskgraph failed.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load, problems as config_problems  # noqa: E402
FIELD_LINE = re.compile(r"^([A-Z][A-Za-z ]{1,24}):\s*(.*)$")
CHECK_ITEM = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+(.*)$")
LEGACY_STATE = re.compile(r"^State at\b[^:]*:\s*(.*)$")
DEFAULT_TIMEBOX_HOURS = 2
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
    goal, acceptance, legacy_state = [], [], None
    for line in (notes or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if m := CHECK_ITEM.match(line):
            acceptance.append(m.group(1).strip())
        elif m := LEGACY_STATE.match(stripped):
            legacy_state = stripped
        elif m := FIELD_LINE.match(stripped):
            if m.group(1).lower() in ("exit test", "exit tests", "acceptance"):
                acceptance.append(m.group(2).strip())
        elif not stripped.startswith("#"):
            goal.append(stripped)
    return " ".join(goal), acceptance, legacy_state


def latest_report(run_dir, task_id):
    reports = [p for p in glob.glob(os.path.join(run_dir, "reports", f"task-{task_id}-*.md"))
               if not p.endswith("-verify.md")]
    attempt = lambda p: int(re.search(r"-(\d+)\.md$", p).group(1)) if re.search(r"-(\d+)\.md$", p) else 0
    return max(reports, key=attempt) if reports else None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tg", required=True, help="path to tg.py (from scripts/tg-path.sh)")
    parser.add_argument("--task", required=True, type=int)
    parser.add_argument("--session", required=True, help="Manager session name for the report")
    parser.add_argument("--kind", choices=["task", "verify"], default="task")
    parser.add_argument("--report", help="worker report file (verify only)")
    parser.add_argument("--verdict-ref", help="commit SHA or output checksums (verify only)")
    parser.add_argument("--attempt", type=int, help="default: next attempt for task, current for verify")
    parser.add_argument("--root", default=".", help="repository root holding .agentic-team.toml (default: .)")
    parser.add_argument("--run-dir", help="default: <root>/.agentic-team")
    args = parser.parse_args()

    if args.kind == "verify" and not (args.report and args.verdict_ref):
        fail("--kind verify needs --report and --verdict-ref")
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

    out = subprocess.run(["python3", args.tg, "--project", project, "--json", "show", str(args.task)],
                         capture_output=True, text=True)
    if out.returncode != 0:
        fail(f"tg show {args.task} failed: {out.stderr.strip()}", 1)
    task = json.loads(out.stdout)
    meta = task.get("meta") or {}
    why, acceptance, legacy_state = parse_notes(task.get("notes"))
    tg_cmd = f"python3 {args.tg} --project {project}"
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

    state_at = meta.get("state_at") or legacy_state or "None"
    plan = config["taskgraph"]["plan"]
    plan_path = os.path.join(args.root, plan) if plan else ""
    if state_at == "None" and plan_path and os.path.isfile(plan_path):
        for line in read(plan_path).splitlines():
            if re.search(rf"#?\b{args.task}\b", line) and "State at" in line:
                state_at = line.strip()
                break

    upstream = []
    previous = latest_report(args.run_dir, args.task) if args.kind == "task" else None
    if previous:
        upstream.append(f"### Previous attempt ({os.path.basename(previous)})\n\n"
                        f"Start from this report. Fix what it lists; do not redo what passed.\n\n"
                        f"{strip_comments(read(previous)).strip()}")
    for dep in task.get("depends_on") or []:
        report = latest_report(args.run_dir, dep["id"])
        body = strip_comments(read(report)).strip() if report else "No report on file."
        upstream.append(f"### Upstream #{dep['id']}: {dep['title']} ({dep['status']})\n\n{body}")

    constraints = config["constraints"]
    forbidden = [f"- {label}: {constraints[key]}" for key, label in CONSTRAINT_LABELS
                 if constraints[key].strip()]
    forbidden += [f"- {item}" for item in constraints["other"] if item.strip()]
    autonomy_cfg = config["autonomy"]
    autonomy = [f"- Standing grant: {autonomy_cfg['grant'] or 'None. Report product decisions as BLOCKED.'}",
                f"- Always pause for: {'; '.join(autonomy_cfg['always_pause']) or 'None'}"]
    consultants = ", ".join(config["consultants"]["sessions"])

    current = int(meta.get("attempt") or 0)
    attempt = args.attempt or (current if args.kind == "verify" else current + 1) or 1
    values = {
        "TASK_ID": str(args.task),
        "TASK_TITLE": task["title"],
        "PROJECT": project,
        "SESSION_NAME": args.session,
        "TIMEZONE": config["sessions"]["timezone_label"] or config["sessions"]["timezone"],
        "GOAL": f"{task['title']}. {why}",
        "SCOPE": scope,
        "TASKGRAPH_COMMAND": tg_cmd,
        "PLAN_FILE": plan or "None",
        "STATE_AT": state_at,
        "CONSULTANTS": consultants or "None. Do not contact a consultant.",
        "UPSTREAM": "\n\n".join(upstream),
        "ACCEPTANCE": "\n".join(f"- {item}" for item in acceptance),
        "VERIFY": str(meta["verify"]).strip(),
        "TIMEBOX": timebox,
        "FORBIDDEN": "\n".join(forbidden) or "None beyond the worker rules.",
        "AUTONOMY": "\n".join(autonomy),
        "STANDING_ORDERS": orders or "None yet.",
        "REPORT_FILE": args.report or "",
        "VERDICT_REF": args.verdict_ref or "",
    }

    if args.kind == "verify":
        template = os.path.join(PLUGIN_ROOT, "templates", "verifier-brief.md")
    else:
        template = config["sessions"]["brief_template"]
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
    print(f"attempt={attempt}", file=sys.stderr)


if __name__ == "__main__":
    main()
