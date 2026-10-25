#!/usr/bin/env python3
"""Print an Agentic Team status report from Taskgraph data.

Usage:
    status.py --tg PATH [--project NAME] [--root .] [--since 7d|YYYY-MM-DD]
              [--run-dir <root>/.agentic-team] [--limit 25] [--mark]

--project defaults to `taskgraph.project` from the config in --root, read
through config.py.

Reads tasks, metadata, and the Taskgraph report, plus open gates from
<run-dir>/gates.md. Prints Markdown tables; every number comes from the data.
--since defaults to the time saved by the last --mark run, else 7 days.
--mark saves the current time to <run-dir>/last-report.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def tg(args, *cmd):
    out = subprocess.run(
        ["python3", args.tg, "--project", args.project, *cmd, "--json"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.exit(f"status.py: tg {' '.join(cmd)} failed: {out.stderr.strip()}")
    return json.loads(out.stdout or "null")


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
        days = int(match.group(1)) * (7 if match.group(2) == "w" else 1)
        return now - datetime.timedelta(days=days)
    moment = datetime.datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=datetime.timezone.utc)


def when(stamp):
    if not stamp:
        return None
    return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


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


def open_gates(run_dir):
    path = os.path.join(run_dir, "gates.md")
    if not os.path.isfile(path):
        return []
    with open(path) as fh:
        text = re.sub(r"<!--.*?-->", "", fh.read(), flags=re.S)
    gates = []
    for block in re.split(r"(?m)^## ", text)[1:]:
        title = block.splitlines()[0].strip()
        fields = dict(re.findall(r"(?m)^- (\w+): *(.*)$", block))
        if fields.get("Status", "").lower() == "open":
            gates.append((title, fields.get("Blocks"), fields.get("Default")))
    return gates


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tg", required=True, help="path to tg.py (from scripts/tg-path.sh)")
    parser.add_argument("--project", help="default: taskgraph.project from the config")
    parser.add_argument("--root", default=".", help="repository root holding .agentic-team.toml (default: .)")
    parser.add_argument("--since", help="7d, 2w, or an ISO date (default: last --mark, else 7d)")
    parser.add_argument("--run-dir", help="default: <root>/.agentic-team")
    parser.add_argument("--limit", type=int, default=25, help="max rows per table (default 25)")
    parser.add_argument("--mark", action="store_true", help="save now as the start of the next report")
    args = parser.parse_args()
    args.run_dir = args.run_dir or os.path.join(args.root, ".agentic-team")
    if not args.project:
        from config import load, problems, TODO
        config = load(args.root)
        project = config["taskgraph"]["project"]
        if config.errors or not isinstance(project, str) or project.strip() in ("", TODO):
            found = problems(config)
            print("status.py: config has problems; pass --project or run `config.py check`:\n  "
                  + "\n  ".join(found), file=sys.stderr)
            sys.exit(2)
        args.project = project

    since = parse_since(args.since, args.run_dir)
    tasks = tg(args, "ls", "--status", "open", "in_progress", "done")
    if not tasks:
        sys.exit(f"status.py: project '{args.project}' has no tasks (check the name with `tg projects`)")
    summary = tg(args, "report", "--since", since.date().isoformat())
    ready = tg(args, "ready")

    done, in_flight, waiting, failed = [], [], [], []
    for task in tasks:
        meta = task.get("meta") or {}
        tid = f"#{task['id']}"
        if task["status"] == "done":
            done_at = when(task.get("done_at"))
            if done_at and done_at >= since:
                tokens = None
                if meta.get("tokens_output") is not None:
                    tokens = f"{meta.get('tokens_output')} / {meta.get('tokens_input')}"
                done.append((tid, task["title"], meta.get("started_at"), meta.get("ended_at"),
                             tokens, meta.get("verdict")))
            continue
        if meta.get("failure"):
            failed.append((tid, task["title"], meta.get("failure"), meta.get("attempt"), meta.get("state_at")))
        elif meta.get("report_status") and not meta.get("verdict"):
            waiting.append((tid, task["title"], meta.get("report_status"), meta.get("session"), meta.get("state_at")))
        elif task["status"] == "in_progress":
            in_flight.append((tid, task["title"], meta.get("session"), meta.get("model"),
                              meta.get("attempt"), meta.get("state_at")))

    changes = summary.get("changes") or {}
    change_text = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in changes.items() if v) or "no changes"
    gates = open_gates(args.run_dir)

    print(f"# Status: {args.project}\n")
    print(f"Overall: {str(summary.get('overall', 'unknown')).upper()}. "
          f"Since {since:%Y-%m-%d %H:%M} UTC: {change_text}.\n")
    print(f"## Done since last report ({len(done)})\n")
    print(table(["Task", "Title", "Started", "Ended", "Tokens out / in", "Verdict"], done, args.limit))
    print(f"## In flight ({len(in_flight)})\n")
    print(table(["Task", "Title", "Session", "Model", "Attempt", "Checkpoint"], in_flight, args.limit))
    print(f"## Waiting for verification or triage ({len(waiting)})\n")
    print(table(["Task", "Title", "Report", "Session", "Checkpoint"], waiting, args.limit))
    print(f"## Failed or abandoned ({len(failed)})\n")
    print(table(["Task", "Title", "Failure", "Attempt", "Checkpoint"], failed, args.limit))
    print(f"## Open gates ({len(gates)})\n")
    print(table(["Gate", "Blocks", "Default"], gates, args.limit))
    print(f"## Ready ({len(ready or [])})\n")
    print(table(["Task", "Title"], [(f"#{t['id']}", t["title"]) for t in (ready or [])], 10))
    for key in ("risks", "issues", "asks"):
        items = summary.get(key) or []
        if items:
            print(f"Taskgraph {key}: {len(items)}. See `tg report`.")
    print("Token counts cover each session's own transcript only; end times are the last message.")

    if args.mark:
        os.makedirs(args.run_dir, exist_ok=True)
        with open(os.path.join(args.run_dir, "last-report"), "w") as fh:
            fh.write(datetime.datetime.now(datetime.timezone.utc).isoformat())


if __name__ == "__main__":
    main()
