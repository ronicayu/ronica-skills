#!/usr/bin/env python3
"""Worker hook: keep the essentials of the task through a context compaction. Stdlib only.

  compact.py --config FILE      PreCompact or SessionStart (matcher compact); stdin is the hook input.

PreCompact prints the compaction instructions: the summary must keep the pinned facts verbatim. SessionStart prints
the same facts as additionalContext once the compaction is done. The facts are read from what run.py wrote: the
attempt's brief (task, GOAL, SCOPE, ACCEPTANCE, VERIFY), the open `finding` steers of the task's mailbox (F1..Fn), and
git in the worker's folder (Head, uncommitted changes). Together they stay below LIMIT characters: Claude Code
replaces a longer additionalContext with a preview, and caps the PreCompact output at 10,000. Any error: exit 0 and
print nothing.
"""

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys

LIMIT = 9000
SECTIONS = ("GOAL", "SCOPE", "ACCEPTANCE", "VERIFY")
CUT = "\n[cut: the brief has the rest]"
STATUS_LINES = 40


def sections(brief):
    """{NAME: text} of the `## NAME` sections of a brief."""
    found, name = {}, None
    for line in brief.splitlines():
        m = re.match(r"## ([A-Z ]+)\s*$", line)
        if m:
            name = m.group(1)
            found[name] = []
        elif name:
            found[name].append(line)
    return {k: "\n".join(v).strip() for k, v in found.items()}


def finding_lines(ctx_path):
    """The F<n> lines of the open `finding` steers of the attempt, one block per steer. Empty when none, or on any error."""
    try:
        spec = importlib.util.spec_from_file_location(
            "agentic_team_mailbox", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mailbox.py"))
        mbx = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mbx)
        steers, _ = mbx.unacked_steers(mbx.read_ctx(ctx_path))
    except Exception:
        return []
    blocks = []
    for steer in steers:
        if mbx.is_finding_steer(steer):
            found = re.findall(r"(?m)^F[1-9][0-9]*:.*$", steer.get("body") or "")
            blocks.append(f"steer #{steer['id']}:\n" + "\n".join(found))
    return blocks


def git(cwd, *args):
    done = subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=cwd, capture_output=True, text=True, timeout=10)
    return done.stdout.strip() if done.returncode == 0 else ""


def fit(blocks, room):
    """Cut the longest blocks until all fit in `room` characters; a block that fits is never cut."""
    texts = dict(blocks)
    while sum(len(t) for t in texts.values()) > room:
        name = max(texts, key=lambda k: len(texts[k]))
        over = sum(len(t) for t in texts.values()) - room
        keep = max(len(texts[name]) - over - len(CUT), 200)
        if keep >= len(texts[name]):
            break
        texts[name] = texts[name][:keep].rstrip() + CUT
    return texts


def pins(cfg, cwd):
    """The pinned facts as text, at most LIMIT - 800 characters (the callers add a short frame)."""
    try:
        with open(cfg["brief"], encoding="utf-8") as fh:
            brief = fh.read()
    except OSError:
        brief = ""
    title = brief.splitlines()[0] if brief.startswith("# ") else ""
    parts = sections(brief)
    blocks = [(n, parts[n]) for n in SECTIONS if parts.get(n)]
    findings = finding_lines(cfg["ctx"]) if cfg.get("ctx") else []
    if findings:
        blocks.append(("OPEN FINDINGS (ack each F<n> before you report)", "\n".join(findings)))
    status = ""
    try:
        head, branch = git(cwd, "rev-parse", "HEAD"), git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
        changed = git(cwd, "status", "--porcelain").splitlines()
        status = f"Head: {head} (branch {branch})\nUncommitted changes: " + (
            "none" if not changed else f"{len(changed)}\n" + "\n".join(changed[:STATUS_LINES])
            + (f"\n... and {len(changed) - STATUS_LINES} more" if len(changed) > STATUS_LINES else ""))
    except (OSError, subprocess.SubprocessError):
        pass
    if status:
        blocks.append(("GIT", status))
    texts = fit(blocks, LIMIT - 800 - 120)
    head = f"{title}\nTask id {cfg['task']}, attempt {cfg['attempt']}".strip()
    return head + "\n\n" + "\n\n".join(f"{n}\n{texts[n]}" if n == "GIT" else f"## {n}\n{texts[n]}" for n, _ in blocks)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    try:
        data = json.load(sys.stdin)
        with open(args.config, encoding="utf-8") as fh:
            cfg = json.load(fh)
        event = data["hook_event_name"]
        if event not in ("PreCompact", "SessionStart") or (event == "SessionStart" and data.get("source") != "compact"):
            return 0
        text = pins(cfg, data.get("cwd") or os.getcwd())
        if event == "PreCompact":
            out = ("The summary must keep the facts below verbatim, in a section titled PINNED FACTS: the task id and "
                   "attempt, GOAL, SCOPE, the ACCEPTANCE lines, VERIFY, the open findings F1..Fn with their exact text, "
                   "the Head and the uncommitted changes. Do not shorten or reword them.\n\n" + text)
        else:
            out = json.dumps({"hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "CONTEXT WAS JUST COMPACTED. These facts of your task are pinned and exact; they "
                                     "override the summary where they differ.\n\n" + text}})
    except Exception:
        return 0
    sys.stdout.write(out + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
