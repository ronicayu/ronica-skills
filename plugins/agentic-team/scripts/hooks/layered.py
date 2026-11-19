#!/usr/bin/env python3
"""Worker hook: reduce the output of test, build and log commands. Stdlib only.

  layered.py pre --config FILE      PreToolUse (Bash): stdin is the hook input. When the command is one of the
                                    configured commands and safe to wrap, print an updatedInput that runs it through
                                    the wrapper below.
  layered.py reduce --config FILE --file OUT --rc N --cmd-b64 TEXT
                                    The tail of the wrapped command: read the full output that the command wrote to OUT
                                    and print the reduced text. The wrapper exits with the command's own code.

The wrapper is needed because only the command itself sees its full output and its exit code: a failed Bash call goes to
PostToolUseFailure, which cannot replace the output. The command runs in the session's own shell, inside braces, so
its environment, functions and `cd` stay as they are.

Policy: output below passthrough_chars is left unchanged. A pass (exit 0) keeps the result lines. A failure keeps the
failing test names, assert and error lines, file:line references and FAILED lines of the full output, verbatim. When
no rule matches and the output is above large_chars, summarize_fallback (default off) asks Haiku. The full output stays
in a file whose path the reduced text names. `pre` fails safe: any error prints nothing and exits 0. `reduce` prints
nothing and exits 1 on an error, and the wrapper then prints the file.
"""

import argparse
import base64
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
import time

ENV_ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
WRAPPERS = ("with-slot.sh", "env", "time")  # words that start a command and leave its output as it is
GLOB_CHARS = "*?["
KEEP_DAYS = 3
LINE_CAP = 1000
MAX_LINES = 80
RESULT_LINES = 5

RESULT = re.compile(
    r"\d+ (passed|failed|skipped|errors?|passing|failing)\b|^\s*Tests?:? +\d|Test Files|Test Suites|Ran \d+ tests?|"
    r"^(OK|PASS|ok)\b|BUILD (SUCCESS|FAIL)|^Done in|^\s*Finished\b|\d+ (flaky|did not run)")
FAILED = re.compile(
    r"^\s*(FAILED|FAIL|ERROR)\b|^\s*(✘|×|✗|✖)|^\s*\d+\) .*›|^=+ (FAILURES|ERRORS) =+|^_{3,} .* _{3,}$")
ASSERT = re.compile(
    r"^E\s|AssertionError|\b[A-Za-z]*(Error|Exception)\b[:(]|^\s*(Expected|Received)\b|\bexpect\(|panicked at|^error(\[\w+\])?:")
PASSED_LINE = re.compile(r"^\s*(✓|✔|√)|\bPASSED\b")
FILE_LINE = re.compile(r"[\w./\\-]+\.(py|js|jsx|ts|tsx|mjs|cjs|rs|go|java|kt|rb|c|cc|cpp|h|swift):\d+")


def split_command(cmd):
    """The `&&`, `;` and newline separated parts of a command, or None when anything in it is not simple: a pipe, a
    redirect other than 2>&1 and 2>/dev/null, background `&`, `||`, a substitution, a group or subshell, a comment,
    a here-document or a trailing backslash. When in doubt: None."""
    parts, cur, i, n = [], [], 0, len(cmd)
    while i < n:
        c = cmd[i]
        if c == "\\":
            if i + 1 >= n or cmd[i + 1] == "\n":
                return None
            cur.append(cmd[i:i + 2])
            i += 2
            continue
        if c == "'":
            end = cmd.find("'", i + 1)
            if end < 0:
                return None
            cur.append(cmd[i:end + 1])
            i = end + 1
            continue
        if c == '"':
            j = i + 1
            while j < n and cmd[j] != '"':
                if cmd[j] == "`" or cmd.startswith("$(", j):
                    return None
                j += 2 if cmd[j] == "\\" else 1
            if j >= n:
                return None
            cur.append(cmd[i:j + 1])
            i = j + 1
            continue
        if c in "`(){}|!" or cmd.startswith("$(", i):
            return None
        if c == "2" and (not cur or cur[-1][-1:].isspace()):
            for ok in ("2>&1", "2>/dev/null"):
                if cmd.startswith(ok, i) and cmd[i + len(ok):i + len(ok) + 1] in ("", " ", "\t", "\n", ";", "&"):
                    cur.append(ok)
                    i += len(ok)
                    break
            else:
                cur.append(c)
                i += 1
            continue
        if c == "#" and (not cur or cur[-1][-1:].isspace()):
            return None
        if c in "<>":
            return None
        if c == "&":
            if not cmd.startswith("&&", i):
                return None
            parts.append("".join(cur))
            cur, i = [], i + 2
            continue
        if c in ";\n":
            parts.append("".join(cur))
            cur, i = [], i + 1
            continue
        cur.append(c)
        i += 1
    parts.append("".join(cur))
    parts = [p.strip() for p in parts if p.strip()]
    return parts or None


def words(part):
    try:
        return shlex.split(part)
    except ValueError:
        return None


def target_of(cmd):
    """The command whose output matters, as one normalized string: the last part, without leading assignments and
    wrapper words. None unless every earlier part is a `cd` or an assignment."""
    parts = split_command(cmd)
    if not parts:
        return None
    for part in parts[:-1]:
        tokens = words(part)
        if tokens is None or not tokens:
            return None
        if tokens[0] == "export":
            tokens = tokens[1:]
        if not ((tokens[0] == "cd" and len(tokens) == 2) or (tokens and all(ENV_ASSIGN.match(t) for t in tokens))):
            return None
    tokens = words(parts[-1])
    if not tokens:
        return None
    while tokens:
        if ENV_ASSIGN.match(tokens[0]) or os.path.basename(tokens[0]) in WRAPPERS:
            tokens = tokens[1:]
        else:
            break
    return " ".join(tokens) or None


def matches(target, patterns):
    """A pattern with * ? or [ is a glob over the whole command. Any other pattern is a prefix: its words that do not
    start with `-` must begin the command, and each word that starts with `-` must be one of the command's words, so
    `gh run view --log` matches `gh run view 123 --log`."""
    words_of = target.split()
    for pattern in patterns:
        if any(ch in pattern for ch in GLOB_CHARS):
            if fnmatch.fnmatchcase(target, pattern):
                return True
            continue
        plain = [w for w in pattern.split() if not w.startswith("-")]
        flags = [w for w in pattern.split() if w.startswith("-")]
        if plain and words_of[:len(plain)] == plain and all(f in words_of for f in flags):
            return True
    return False


def wrap(cmd, cfg, tool_use_id):
    """The wrapped command, or None when it must run as it is."""
    target = target_of(cmd)
    if not target or not matches(target, cfg.get("commands") or []):
        return None
    out = os.path.join(cfg["saved_dir"], re.sub(r"[^A-Za-z0-9_-]", "_", tool_use_id) + ".txt")
    q = shlex.quote
    reduce = (f"{q(sys.executable)} -S {q(os.path.abspath(__file__))} reduce --config {q(cfg['config_file'])} "
              f"--file {q(out)} --rc \"$__at_rc\" --cmd-b64 {base64.b64encode(cmd.encode()).decode()}")
    return f"{{ {cmd}\n}} > {q(out)} 2>&1; __at_rc=$?; {reduce} || cat {q(out)}; (exit \"$__at_rc\")"


def pick(lines, rx, limit, skip=None):
    found, seen = [], set()
    for line in lines:
        if rx.search(line) and line not in seen and not (skip and skip.search(line)):
            seen.add(line)
            found.append(line if len(line) <= LINE_CAP else line[:LINE_CAP] + " [line cut]")
    return found[:limit]


def extract(lines):
    """(useful, summary): the failure lines of the full output in their order, and the result lines at its end."""
    rx = re.compile("|".join(r.pattern for r in (FAILED, ASSERT, FILE_LINE)))
    useful = pick(lines, rx, MAX_LINES, PASSED_LINE)
    summary = pick(lines[::-1], RESULT, RESULT_LINES)[::-1]
    return useful, [s for s in summary if s not in useful]


def summarize(text, cmd):
    prompt = ("A coding agent ran a command that failed. The output is long and no rule found an error line. Summarize "
              "what failed in at most 10 lines. Do not invent lines.\n"
              f"Command: {cmd}\n--- OUTPUT (head and tail) ---\n{text[:30000]}\n...\n{text[-30000:]}")
    done = subprocess.run(["claude", "-p", "--model", "haiku", "--no-session-persistence", "--tools=", prompt],
                          capture_output=True, text=True, timeout=90, cwd=os.path.expanduser("~"))
    return done.stdout.strip() if done.returncode == 0 else ""


def reduce_output(text, rc, cfg, cmd, path):
    """(the text the session sees, what was done). `path` holds the full output; it stays when the text is reduced."""
    if len(text) < cfg["passthrough_chars"]:
        return text, "pass-through"
    lines = text.splitlines()
    pointer = f"[full output, {len(lines)} lines, {len(text)} characters: {path}; read it with Read or sed -n if you need more]"
    useful, summary = extract(lines)
    if rc == 0:
        kept = summary or lines[-3:]
        return "[agentic-team hook: exit 0; result lines only]\n" + "\n".join(kept) + "\n" + pointer, "pass"
    if useful:
        head = f"[agentic-team hook: exit {rc}; lines below are verbatim from the full output]\n"
        return head + "\n".join(useful + summary) + "\n" + pointer, "fail-rules"
    if cfg.get("summarize_fallback") and len(text) > cfg["large_chars"]:
        try:
            said = summarize(text, cmd)
        except (OSError, subprocess.SubprocessError):
            said = ""
        if said:
            return f"[agentic-team hook: exit {rc}; Haiku summary, it can miss lines]\n{said}\n{pointer}", "fail-summary"
    return text, "fail-unchanged"


def prune(directory):
    cutoff = time.time() - KEEP_DAYS * 86400
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        if os.path.getmtime(path) < cutoff:
            os.remove(path)


def load_config(path):
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg["config_file"] = os.path.abspath(path)
    return cfg


def cmd_pre(args):
    data = json.load(sys.stdin)
    tool_input = data.get("tool_input")
    if data.get("tool_name") != "Bash" or not isinstance(tool_input, dict) or tool_input.get("run_in_background"):
        return
    cmd = tool_input.get("command")
    cfg = load_config(args.config)
    if not isinstance(cmd, str) or not cfg.get("layered") or not isinstance(data.get("tool_use_id"), str):
        return
    wrapped = wrap(cmd, cfg, data["tool_use_id"])
    if wrapped is None:
        return
    os.makedirs(cfg["saved_dir"], exist_ok=True)
    try:
        prune(cfg["saved_dir"])
    except OSError:
        pass
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "updatedInput": {**tool_input, "command": wrapped}}}))


def cmd_reduce(args):
    cfg = load_config(args.config)
    with open(args.file, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    cmd = base64.b64decode(args.cmd_b64).decode()
    out, how = reduce_output(text, args.rc, cfg, cmd, args.file)
    sys.stdout.write(out if out.endswith("\n") else out + "\n")
    if how in ("pass-through", "fail-unchanged"):
        os.remove(args.file)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pre")
    p.add_argument("--config", required=True)
    p = sub.add_parser("reduce")
    p.add_argument("--config", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--rc", type=int, required=True)
    p.add_argument("--cmd-b64", required=True)
    args = parser.parse_args(argv)
    try:
        (cmd_pre if args.cmd == "pre" else cmd_reduce)(args)
    except Exception:
        return 0 if args.cmd == "pre" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
