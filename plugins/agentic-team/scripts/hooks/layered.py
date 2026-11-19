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
FAILED lines and the assert, error, crash and linker lines first, then file:line references, then the last lines, all
copied from the full output; a count says how many matching lines were left out. The same rules run at exit 0 when a
FAILED or error line matches, and always for log commands (`gh run view --log`, `docker logs`), which exit 0 whatever the
log says. When no rule matches and the output is above large_chars, summarize_fallback (default off) asks Haiku. The full
output stays in a file whose path the reduced text names. `pre` fails safe: any error prints nothing and exits 0.
`reduce` prints nothing and exits 1 on an error or after REDUCE_SECONDS, and the wrapper then prints the file.
"""

import argparse
import base64
import fnmatch
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time

ENV_ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
WRAPPERS = ("with-slot.sh", "env", "time")  # words that start a command and leave its output as it is
GLOB_CHARS = "*?["
KEEP_DAYS = 3
LINE_CAP = 2000  # a line is read, matched and shown up to this length: no pattern runs on more
KEY_MAX = 60  # the FAILED and error lines kept (the first half and the last half when there are more)
MAX_LINES = 90  # all matching lines kept; the rest of the room goes to file:line references
TAIL_LINES = 15
RESULT_LINES = 5
REDUCE_SECONDS = 5
FILE_CAP = 20 * 1024 * 1024  # the saved output is cut to its head and tail above this size
LOG_COMMANDS = (("gh", "run", "view"), ("docker", "logs"), ("kubectl", "logs"), ("journalctl",))
FOLLOWING = ("--watch", "--follow", "--ui", "show-report", "--debug", "--watchAll")  # never end, or wait for a person

RESULT = re.compile(
    r"\d+ (passed|failed|skipped|errors?|passing|failing)\b|^\s*Tests?:? +\d|Test Files|Test Suites|Ran \d+ tests?|"
    r"^(OK|PASS|ok)\b|BUILD (SUCCESS|FAIL)|^Done in|^\s*Finished\b|\d+ (flaky|did not run)")
FAILED = re.compile(
    r"^\s*(FAILED|FAIL|ERROR)\b|^\s*(✘|×|✗|✖)|^\s*\d+\) .*›|^=+ (FAILURES|ERRORS) =+|^_{3,} [^_]+ _{3,}$")
ERROR = re.compile(
    r"^E\s|AssertionError|\b[A-Za-z]*(Error|Exception)\b[:(]|^\s*(Expected|Received)\b|\bexpect\(|panicked at|"
    r"^error(\[\w+\])?:|\berror TS\d+|^make[^:\n]*: \*\*\*|: (fatal )?error:|: ERROR:|\bld: |linker command failed|"
    r"undefined reference|symbol\(s\) not found|Segmentation fault|Fatal Python error|\bKilled\b|\bAborted\b|core dumped|"
    r"##\[error\]|Test timeout of")
PASSED_LINE = re.compile(r"^\s*(✓|✔|√)|^\S+::\S+ PASSED\b")
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
    """A pattern with * ? or [ is a glob over the whole command. Any other pattern is a prefix: its words up to the last
    one that does not start with `-` must begin the command, and each later word (a flag) must be one of the command's
    words, so `gh run view --log` matches `gh run view 123 --log` and `python -m pytest` matches `python -m pytest -x`."""
    words_of = target.split()
    for pattern in patterns:
        if any(ch in pattern for ch in GLOB_CHARS):
            if fnmatch.fnmatchcase(target, pattern):
                return True
            continue
        parts = pattern.split()
        last = max((i for i, w in enumerate(parts) if not w.startswith("-")), default=-1)
        if last >= 0 and words_of[:last + 1] == parts[:last + 1] and all(f in words_of for f in parts[last + 1:]):
            return True
    return False


def never_ends(target):
    """A command that follows or watches, or that waits for a person: its output would stay hidden until a timeout."""
    words_of = target.split()
    if any(w in FOLLOWING or w.startswith("--follow=") or "watch" in w.lower() for w in words_of):
        return True
    if "vitest" in words_of and "-w" in words_of:
        return True
    if "pytest" in words_of and any(w in ("-f", "--looponfail", "--pdb", "--trace") for w in words_of):
        return True
    return "-f" in words_of and "logs" in words_of[:3]


def is_log(target):
    words_of = tuple(target.split())
    return any(words_of[:len(c)] == c for c in LOG_COMMANDS)


def wrap(cmd, cfg, tool_use_id):
    """The wrapped command, or None when it must run as it is."""
    target = target_of(cmd)
    if not target or not matches(target, cfg.get("commands") or []) or never_ends(target):
        return None
    out = os.path.join(cfg["saved_dir"], re.sub(r"[^A-Za-z0-9_-]", "_", tool_use_id) + ".txt")
    q = shlex.quote
    reduce = (f"{q(sys.executable)} -S {q(os.path.abspath(__file__))} reduce --config {q(cfg['config_file'])} "
              f"--file {q(out)} --rc \"$__at_rc\" --cmd-b64 {base64.b64encode(cmd.encode()).decode()}"
              + (" --log" if is_log(target) else ""))
    notice = q(f"[agentic-team hook: the full output is saved to {out} when the output is reduced]")
    return (f"printf '%s\\n' {notice}; __at_rc=0; {{ {cmd}\n}} > {q(out)} 2>&1 || __at_rc=$?; "
            f"{reduce} || cat {q(out)}; (exit \"$__at_rc\")")


def read_lines(path):
    """The lines of the saved output, each cut to LINE_CAP. A file over FILE_CAP is first cut in place to its head and
    tail with a marker line, and only those are read."""
    size = os.path.getsize(path)
    if size > FILE_CAP:
        half = FILE_CAP // 2
        with open(path, "rb") as fh:
            head = fh.read(half)
            fh.seek(size - half)
            tail = fh.read(half)
        marker = f"\n[agentic-team hook: {size - 2 * half} bytes cut from the middle of the output]\n".encode()
        with open(path + ".cut", "wb") as fh:
            fh.write(head + marker + tail)
        os.replace(path + ".cut", path)
    with open(path, encoding="utf-8", errors="replace") as fh:
        return [ln if len(ln) <= LINE_CAP else ln[:LINE_CAP] + " [line cut]" for ln in fh.read().splitlines()]


LOG_PREFIX = re.compile(r"^(?:[^\t]*\t[^\t]*\t)?(?:\d{4}-\d\d-\d\dT[\d:.]+Z )?")


ROOT = re.compile(r"^E\s|Error:|Traceback|Caused by")
SAME = re.compile(r"\d+|(?:[\w.-]*/)+[\w.-]*")


def extract(lines, log=False):
    """(kept, omitted, key, useful, summary). `kept` is the lines to show in their order: the FAILED and error lines first (at
    most KEY_MAX), then file:line references up to MAX_LINES, then the last TAIL_LINES lines. `omitted` counts the
    matching lines left out; `key` is the number of FAILED and error lines kept, `useful` those and the references.
    `summary` holds the result lines at the end."""
    keys, refs, root = [], [], None
    for i, line in enumerate(lines):
        head = line[:LINE_CAP]
        if log:  # `gh run view --log` puts job and step columns and a timestamp before the text
            head = head[LOG_PREFIX.match(head).end():]
        if PASSED_LINE.search(head):
            continue
        if FAILED.search(head) or ERROR.search(head):
            keys.append(i)
            if root is None and ROOT.search(head):
                root = i
        elif FILE_LINE.search(head):
            refs.append(i)
    total = len(keys) + len(refs)
    first, counts = {}, {}  # near-duplicate key lines (digits and paths normalised) count once, with their number
    for i in keys:
        same = SAME.sub("#", lines[i][:LINE_CAP])
        first.setdefault(same, i)
        counts[first[same]] = counts.get(first[same], 0) + 1
    keys = sorted(counts)
    if len(keys) > KEY_MAX:
        keep = keys[:KEY_MAX // 2] + keys[-(KEY_MAX // 2):] + ([root] if root in counts else [])
        keys = sorted(set(keep))
    refs = refs[:max(MAX_LINES - len(keys), 0)]
    chosen = sorted(set(keys + refs) | set(range(max(len(lines) - TAIL_LINES, 0), len(lines))))
    seen, kept = set(), []
    for i in chosen:
        if lines[i] not in seen:
            seen.add(lines[i])
            kept.append(lines[i] + (f" (×{counts[i]})" if counts.get(i, 1) > 1 else ""))
    useful = len(set(keys + refs))
    shown = sum(counts.get(i, 1) for i in keys) + len(refs)
    return kept, total - shown, len(keys), useful, [ln for ln in lines[::-1] if RESULT.search(ln)][:RESULT_LINES][::-1]


def summarize(text, cmd, seconds=30):
    prompt = ("A coding agent ran a command that failed. The output is long and no rule found an error line. Summarize "
              "what failed in at most 10 lines. Do not invent lines.\n"
              f"Command: {cmd}\n--- OUTPUT (head and tail) ---\n{text[:30000]}\n...\n{text[-30000:]}")
    done = subprocess.run(["claude", "-p", "--model", "haiku", "--no-session-persistence", "--tools=", prompt],
                          capture_output=True, text=True, timeout=seconds, cwd=os.path.expanduser("~"))
    return done.stdout.strip() if done.returncode == 0 else ""


def reduce_output(lines, size, rc, cfg, cmd, path, log=False):
    """(the text the session sees, what was done). `lines` and `size` describe the full output, which is in `path` and
    stays there when the text is reduced; the other outcome is the full text, which the caller prints as it is."""
    if size < cfg["passthrough_chars"]:
        return None, "pass-through"
    pointer = f"[full output, {len(lines)} lines, {size} characters: {path}; read it with Read or sed -n if you need more]"
    kept, omitted, key, useful, summary = extract(lines, log)
    if rc == 0 and not key and not log:
        shown = summary or lines[-3:]
        return "[agentic-team hook: exit 0; result lines only]\n" + "\n".join(shown) + "\n" + pointer, "pass"
    if rc == 0 and not key:
        return None, "pass-through"
    if useful and (key or rc != 0):
        copied = "lines below are verbatim from the full output" if not omitted else (
            f"lines below are copied from the full output; {omitted} matching lines omitted")
        shown = kept + [s for s in summary if s not in kept]
        return f"[agentic-team hook: exit {rc}; {copied}]\n" + "\n".join(shown) + "\n" + pointer, "fail-rules"
    if cfg.get("summarize_fallback") and size > cfg["large_chars"]:
        signal.alarm(0)  # the fallback has its own timeout
        try:
            said = summarize("\n".join(lines), cmd, cfg.get("summarize_seconds", 30))
        except (OSError, subprocess.SubprocessError):
            said = ""
        if said:
            return f"[agentic-team hook: exit {rc}; Haiku summary, it can miss lines]\n{said}\n{pointer}", "fail-summary"
        return "[agentic-team hook: exit " + f"{rc}; no summary; the last lines]\n" + "\n".join(kept) + "\n" + pointer, "fail-tail"
    return None, "fail-unchanged"


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


def too_slow(signum, frame):
    raise TimeoutError("reduce took too long")


def cmd_reduce(args):
    signal.signal(signal.SIGALRM, too_slow)
    signal.alarm(REDUCE_SECONDS)
    cfg = load_config(args.config)
    cmd = base64.b64decode(args.cmd_b64).decode()
    if os.path.getsize(args.file) < cfg["passthrough_chars"]:  # small: print it as it is, and keep no file
        with open(args.file, encoding="utf-8", errors="replace") as fh:
            sys.stdout.write(fh.read())
        os.remove(args.file)
        return
    lines = read_lines(args.file)
    out, _ = reduce_output(lines, os.path.getsize(args.file), args.rc, cfg, cmd, args.file, args.log)
    signal.alarm(0)
    if out is None:
        with open(args.file, encoding="utf-8", errors="replace") as fh:
            shutil.copyfileobj(fh, sys.stdout)
        os.remove(args.file)
        return
    sys.stdout.write(out if out.endswith("\n") else out + "\n")


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
    p.add_argument("--log", action="store_true")
    args = parser.parse_args(argv)
    try:
        (cmd_pre if args.cmd == "pre" else cmd_reduce)(args)
    except Exception:
        return 0 if args.cmd == "pre" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
