#!/usr/bin/env python3
"""The SessionStart(compact) hook: give the Manager its role and orders again after a context compaction.

Reads the hook input (JSON on stdin: session_id, cwd). Finds the project's run directory from cwd (the nearest
directory upward that holds .agentic-team.toml, then its .agentic-team/). Prints nothing unless session_id equals the
first line of <run dir>/manager-session, which run.py writes from $CLAUDE_CODE_SESSION_ID. Then it prints
hookSpecificOutput.additionalContext: the instruction to read agents/manager.md, the standing orders and the manager
orders (manager-orders.md, when it exists), a short status, and the instruction to run `run record` and `run wait`
again, in that order, in at most CONTEXT_MAX characters (Claude Code replaces a longer additionalContext with a
preview). An orders file that does not fit is not inlined: its absolute path is given, to Read in full.
Any error: exit 0, no output. It never blocks a session start. Stdlib only.
"""

import json
import os
import signal
import subprocess
import sys

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKED = ".agentic-team.toml"
RUN_DIR = ".agentic-team"
STATUS_TIMEOUT = 5  # seconds; on a timeout the status process group is killed
STATUS_RESERVE = 1500  # characters kept for the status
CONTEXT_MAX = 9000  # characters of additionalContext in all


def find_root(cwd):
    here = os.path.abspath(cwd)
    while True:
        if os.path.isfile(os.path.join(here, TRACKED)):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent


def status_command(root):
    return [sys.executable, os.path.join(PLUGIN, "scripts", "run.py"), "--root", root, "status", "--brief", "--limit", "8"]


def status_text(root, cap):
    text = ""
    try:
        proc = subprocess.Popen(status_command(root), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                cwd=root, stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            out, _ = proc.communicate(timeout=STATUS_TIMEOUT)
            text = out.strip() if proc.returncode == 0 else ""
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)  # run.py and the tg processes it started
            except OSError:
                pass
            proc.communicate()
    except (OSError, subprocess.SubprocessError, ValueError):
        text = ""
    if not text:
        return "(status unavailable; `run record` and `run status` show it)"
    return text if len(text) <= cap else text[:max(cap - 14, 0)] + "\n(status cut)"


def orders_section(run_dir, name, room):
    """(text, used): the file in full when it fits in `room` characters, else its path to Read in full."""
    path = os.path.join(run_dir, name)
    title = f"===== {RUN_DIR}/{name} ====="
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError):
        return (f"{title}\n(none)" if name == "manager-orders.md" else f"{title}\n(could not read {name})"), 0
    inline = f"{title}\n{text.rstrip()}"
    if len(inline) + 2 <= room:
        return inline, len(inline) + 2
    return f"{title}\nToo long to show here. Read {path} in full with the Read tool before you act.", 0


def build(root, run_dir):
    run = os.path.join(PLUGIN, "scripts", "run")
    head = "\n".join([
        "CONTEXT WAS JUST COMPACTED. This session is the Agentic Team Manager of this project. Before any other action:",
        f"1. Read {os.path.join(PLUGIN, 'agents', 'manager.md')} in full with the Read tool and follow it (ignore its "
        f"frontmatter). `${{CLAUDE_PLUGIN_ROOT}}` in it and in the files it names means {PLUGIN}. Write the real path "
        "in every Bash command.",
        "2. The standing orders and the manager orders follow. They override the summary where they differ.",
        f"3. After them: run `\"{run}\" record` to see what is in flight and act on its lines, then start `\"{run}\" wait` "
        "again in the background if none is running.",
    ])
    room = CONTEXT_MAX - len(head) - STATUS_RESERVE - 40
    parts = [head]
    for name in ("standing-orders.md", "manager-orders.md"):
        text, used = orders_section(run_dir, name, room)
        parts.append(text)
        room -= used
    spare = CONTEXT_MAX - len("\n\n".join(parts)) - len("\n\n===== Status: work not yet closed =====\n") - 1
    if spare > 100:
        parts.append("===== Status: work not yet closed =====\n" + status_text(root, spare))
    return "\n\n".join(parts) + "\n"


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
