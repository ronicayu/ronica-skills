#!/usr/bin/env python3
"""The SessionStart(compact) hook: give the Manager its role and orders again after a context compaction.

Reads the hook input (JSON on stdin: session_id, cwd). Finds the project's run directory from cwd (the nearest
directory upward that holds .agentic-team.toml, then its .agentic-team/). Prints nothing unless session_id equals the
first line of <run dir>/manager-session, which the manager skill writes at Start. Then it prints
hookSpecificOutput.additionalContext: the instruction to read agents/manager.md, the standing orders and the manager
orders (manager-orders.md, when it exists) in full, a short status, and the instruction to run `run record` and
`run wait` again. Any error: exit 0, no output. It never blocks a session start. Stdlib only.
"""

import json
import os
import subprocess
import sys

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKED = ".agentic-team.toml"
RUN_DIR = ".agentic-team"
STATUS_TIMEOUT = 20  # seconds
STATUS_CAP = 4000  # characters of status text
ORDERS_CAP = 60000  # characters of one orders file; a larger file is cut and says so


def find_root(cwd):
    here = os.path.abspath(cwd)
    while True:
        if os.path.isfile(os.path.join(here, TRACKED)):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent


def read(path, cap=ORDERS_CAP):
    with open(path, encoding="utf-8") as fh:
        text = fh.read(cap + 1)
    return text[:cap] + f"\n(cut at {cap} characters; read {path} in full)\n" if len(text) > cap else text


def status_text(root):
    try:
        out = subprocess.run([sys.executable, os.path.join(PLUGIN, "scripts", "run.py"), "--root", root, "status",
                              "--brief", "--limit", "8"], capture_output=True, text=True, timeout=STATUS_TIMEOUT,
                             cwd=root, stdin=subprocess.DEVNULL)
        text = out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        text = ""
    if not text:
        return "(status unavailable; `run record` and `run status` show it)"
    return text[:STATUS_CAP] + ("\n(status cut)" if len(text) > STATUS_CAP else "")


def build(root, run_dir):
    run = os.path.join(PLUGIN, "scripts", "run")
    parts = [
        "CONTEXT WAS JUST COMPACTED. This session is the Agentic Team Manager of this project. Before any other action:",
        f"1. Read {os.path.join(PLUGIN, 'agents', 'manager.md')} in full with the Read tool and follow it (ignore its "
        f"frontmatter). `${{CLAUDE_PLUGIN_ROOT}}` in it and in the files it names means {PLUGIN}. Write the real path "
        "in every Bash command.",
        "2. The standing orders and the manager orders are below in full. They override the summary where they differ.",
        f"3. Run `\"{run}\" record` to see what is in flight and act on its lines, then start `\"{run}\" wait` again in "
        "the background if none is running.",
        "",
        "===== Status: work not yet closed =====",
        status_text(root),
    ]
    for name in ("standing-orders.md", "manager-orders.md"):
        path = os.path.join(run_dir, name)
        parts += ["", f"===== {RUN_DIR}/{name} ====="]
        try:
            parts.append(read(path))
        except (OSError, UnicodeDecodeError):
            parts.append("(none)" if name == "manager-orders.md" else f"(could not read {name})")
    return "\n".join(parts) + "\n"


def main():
    data = json.load(sys.stdin)
    session, cwd = data.get("session_id"), data.get("cwd")
    if not isinstance(session, str) or not session or not isinstance(cwd, str):
        return
    root = find_root(cwd)
    if not root:
        return
    run_dir = os.path.join(root, RUN_DIR)
    with open(os.path.join(run_dir, "manager-session"), encoding="utf-8") as fh:
        if fh.read().strip() != session:
            return
    text = build(root, run_dir)
    sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
