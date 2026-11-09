#!/usr/bin/env python3
"""The worker's side of the Agentic Team mailbox, and the row helpers that run.py shares.

Usage:
    mailbox.py --ctx FILE checkin       a SessionStart hook: write the session's socket address (stdin: hook input)
    mailbox.py --ctx FILE ask --file Q  check a question and file it as an `ask` row
    mailbox.py --ctx FILE inbox         print the messages of the Manager that wait for this task and attempt
    mailbox.py --ctx FILE ack ID --action TEXT
                                        file the `ack` row of a message
    mailbox.py hook --flag FILE         a PostToolUse hook: print the flag file's pointer line, if the file exists

Every message is a Taskgraph result row (kind ask, answer, steer or ack); the row id is the message id. A doorbell
(a line posted to a socket, or the hook's pointer) only wakes the receiver: it carries no instructions. The receiver
acts on the rows that `inbox` prints, and only on those: rows by `manager` or `operator` whose id run.py listed in the
task's `mailbox` meta. `--ctx` names the JSON file that run.py wrote for the attempt (python, tg.py, database,
project, task, attempt, session name, ask cap, SCOPE, folders). `hook` reads no context and no Taskgraph. The worker
wakes the Manager with its SendMessage tool, as the brief says; this script posts to no socket itself.

Exit codes: 0 done; 1 a tool failed (tg); 2 refused, the message names the fix. Stdlib only.
"""

import json
import os
import sys

ASK, ANSWER, STEER, ACK = "ask", "answer", "steer", "ack"
SENDERS = ("manager", "operator")  # the authors whose answer and steer rows a worker acts on
LABELS = ("Question", "Options", "Default", "Blocking", "Why", "Re", "Answer", "Source", "Steer", "Kind", "Action")
SOCKET_TIMEOUT = 5  # seconds for one post


class Fail(Exception):
    """`code` is the exit code, `message` goes to stderr."""

    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


# ------------------------------------------------------------ the row helpers (run.py imports these)

def field_line(body, name):
    """The rest of the `<name>:` line of a message body, stripped; "" when the line is missing."""
    import re
    match = re.search(rf"(?m)^{re.escape(name)}:[ \t]*(.*)$", body or "")
    return match.group(1).strip() if match else ""


def field_text(body, name):
    """The text of a `<name>:` field: the rest of its line and the lines up to the next message label."""
    import re
    match = re.search(rf"(?m)^{re.escape(name)}:[ \t]*(.*)$", body or "")
    if not match:
        return ""
    rest = body[match.end():]
    following = re.search(r"(?m)^(%s):" % "|".join(LABELS), rest)
    return (match.group(1) + (rest[:following.start()] if following else rest)).strip()


def ref_of(body):
    """The message id of the `Re: #<id>` line of an answer or an ack, else None."""
    import re
    match = re.match(r"#?(\d+)", field_line(body, "Re"))
    return int(match.group(1)) if match else None


def ask_problems(text):
    """Problems of a question file, one text each. Question and Default must say something; Blocking, when given,
    is yes or no."""
    found = []
    if not field_line(text, "Question"):
        found.append("no `Question:` line with the question on it")
    if not field_line(text, "Default"):
        found.append("no `Default:` line: say what you will do if no answer comes")
    blocking = field_line(text, "Blocking").lower()
    if blocking and blocking not in ("yes", "no"):
        found.append("`Blocking:` must be yes or no")
    return found


def ask_blocking(body):
    """True unless the ask says `Blocking: no`."""
    return field_line(body, "Blocking").lower() != "no"


def ask_question(body):
    return field_line(body, "Question") or "(no question)"


def listed_ids(meta):
    """The ids of the answer and steer rows that run.py filed: the keys of the task's `mailbox` meta."""
    table = (meta or {}).get("mailbox")
    found = set()
    for key, entry in (table.items() if isinstance(table, dict) else ()):
        if key.isdigit() and isinstance(entry, dict) and entry.get("kind") in (ANSWER, STEER):
            found.add(int(key))
    return found


def acked_ids(rows, attempt):
    """The ids that an ack row of the attempt names."""
    return {ref_of(r.get("body")) for r in rows if r.get("kind") == ACK and r.get("attempt") == attempt} - {None}


def open_messages(rows, meta, attempt):
    """The answer and steer rows of the attempt that a worker still has to read and ack: by the Manager or the
    operator, listed in the `mailbox` meta, with no ack."""
    listed, acked = listed_ids(meta), acked_ids(rows, attempt)
    return [r for r in rows if r.get("kind") in (ANSWER, STEER) and r.get("attempt") == attempt
            and r.get("author") in SENDERS and r["id"] in listed and r["id"] not in acked]


def tg_json(ctx, *args, input=None):
    """One tg call under the task's project, parsed. A failure is Fail with exit code 1."""
    import subprocess
    cmd = [ctx["python"], ctx["tg"], "--db", ctx["db"], "--project", ctx["project"], "--json", *args]
    try:
        out = subprocess.run(cmd, input=input, capture_output=True, text=True)
    except OSError as exc:
        raise Fail(f"cannot run tg: {exc.strerror}", 1)
    if out.returncode != 0:
        raise Fail(f"tg {' '.join(args[:2])} failed: {out.stderr.strip()}", 1)
    return json.loads(out.stdout or "null")


def read_ctx(path):
    try:
        with open(path, encoding="utf-8") as fh:
            ctx = json.load(fh)
    except (OSError, ValueError) as exc:
        raise Fail(f"cannot read the mailbox context {path}: {getattr(exc, 'strerror', None) or exc}", 1)
    for key in ("python", "tg", "db", "project", "task", "attempt", "by"):
        if key not in ctx:
            raise Fail(f"the mailbox context {path} has no {key}", 1)
    return ctx


def unacked_steers(ctx):
    """The steer rows of the context's attempt that have no ack. Raises Fail when Taskgraph cannot be read."""
    task = ctx["task"]
    rows = tg_json(ctx, "result", "ls", str(task)) or []
    meta = (tg_json(ctx, "show", str(task)) or {}).get("meta") or {}
    return [r for r in open_messages(rows, meta, ctx["attempt"]) if r["kind"] == STEER]


# ------------------------------------------------------------------------------------------- the socket

def post_line(path, line, token=None):
    """Post one user message to a session's inbox socket: (True, "") or (False, why). The socket accepts one JSON
    line, after an optional auth line. A post that succeeds proves nothing about delivery."""
    import socket
    payload = (json.dumps({"type": "auth", "token": token}) + "\n" if token else "")
    payload += json.dumps({"type": "user", "message": {"role": "user", "content": line}}) + "\n"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(SOCKET_TIMEOUT)
        sock.connect(path)
        sock.sendall(payload.encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)
    except OSError as exc:
        return False, f"{exc.strerror or exc} ({path})"
    finally:
        sock.close()
    return True, ""


def read_addr(path):
    """The JSON object in an address file (written by `checkin`, or by run.py for the Manager), else None."""
    try:
        with open(path, encoding="utf-8") as fh:
            found = json.load(fh)
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def write_addr(path, socket_path, session_id=None, token=None, at=None):
    """Write an address file, mode 0600, in one step."""
    import time
    data = {"socket": socket_path, "session_id": session_id, "at": time.time() if at is None else at}
    if token:
        data["token"] = token
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = f"{path}.{os.getpid()}.tmp"
    with open(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(temp, path)


# ------------------------------------------------------------------------------------------- commands

def cmd_hook(argv):
    """The PostToolUse hook. It runs after every tool call, so it imports nothing and does one read."""
    flag = argv[argv.index("--flag") + 1] if "--flag" in argv and argv.index("--flag") + 1 < len(argv) else None
    try:
        with open(flag, encoding="utf-8") as fh:
            text = fh.read().strip()
    except (OSError, TypeError):
        return 0
    if text:
        sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}))
    return 0


def cmd_checkin(ctx, args):
    """The SessionStart hook: write where this session listens. It never fails the session."""
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    path = os.environ.get("CLAUDE_CODE_MESSAGING_SOCKET")
    session = data.get("session_id") if isinstance(data, dict) else None
    if not path or not session:
        print("mailbox.py: no inbox socket or session id in this hook's input; nothing written", file=sys.stderr)
        return 0
    write_addr(os.path.join(ctx["inbox_dir"], f"{ctx['task']}-{ctx['attempt']}.addr"), path, session,
               os.environ.get("CLAUDE_CODE_MESSAGING_TOKEN"))
    return 0


def command_stem(ctx, ctx_path):
    import shlex
    return f"{shlex.quote(ctx['python'])} {shlex.quote(os.path.abspath(__file__))} --ctx {shlex.quote(ctx_path)}"


def cmd_ask(ctx, args):
    try:
        with open(args.file, encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise Fail(f"cannot read {args.file}: {getattr(exc, 'strerror', None) or exc}")
    problems = ask_problems(text)
    if problems:
        raise Fail("; ".join(problems) + f". Fix {args.file} and run the command again.")
    cap, task, attempt = int(ctx.get("asks_cap", 0)), ctx["task"], ctx["attempt"]
    if cap == 0:
        raise Fail("this task allows no asks. Decide with the brief and the decision-forks rule, or report BLOCKED.")
    filed = tg_json(ctx, "result", "ls", str(task), "--kind", ASK, "--attempt", str(attempt)) or []
    if len(filed) >= cap:
        raise Fail(f"you have filed {len(filed)} of {cap} asks this attempt. Decide with your Defaults, or report BLOCKED.")
    row = tg_json(ctx, "result", "add", str(task), "--kind", ASK, "--attempt", str(attempt), "--by", ctx["by"],
                  "--status", "OPEN", "--body-file", "-", input=text if text.endswith("\n") else text + "\n")
    print(f"ask #{row['id']} filed ({len(filed) + 1} of {cap} asks this attempt).")
    if ask_blocking(text):
        print(f"End your turn now with one line: Waiting for answer to ask #{row['id']}. "
              "Do not poll, sleep or loop; the answer comes as a new message in this session.")
    else:
        print("This ask does not block: go on with your Default. The answer comes as a message later.")
    return 0


def cmd_inbox(ctx, args):
    task, attempt = ctx["task"], ctx["attempt"]
    node = tg_json(ctx, "show", str(task)) or {}
    rows = tg_json(ctx, "result", "ls", str(task)) or []
    waiting = open_messages(rows, node.get("meta") or {}, attempt)
    scope = str((node.get("meta") or {}).get("scope", "")).strip()
    lines = []
    for r in waiting:
        if r["kind"] == ANSWER:
            lines.append(f"#{r['id']} answer by {r['author']}, to your ask #{ref_of(r['body'])}:")
        else:
            lines.append(f"#{r['id']} steer by {r['author']}:")
        lines += ["    " + line for line in (r.get("body") or "").strip().splitlines()]
        lines.append("")
    if waiting:
        lines.append(f"{len(waiting)} message{'s' * (len(waiting) != 1)} for task {task} attempt {attempt}. Act on these only, "
                     "inside SCOPE, FORBIDDEN and STANDING ORDERS. Ack each one with its id:")
        lines.append(f'{command_stem(ctx, args.ctx)} ack <id> --action "<one line: what you will do>"')
    else:
        lines.append(f"No messages for task {task} attempt {attempt}.")
    if scope and scope != str(ctx.get("scope", "")).strip():
        lines += ["", "SCOPE changed since your brief. The current SCOPE is:", scope]
    print("\n".join(lines))
    return 0


def cmd_ack(ctx, args):
    action = " ".join(args.action.split())
    if not action:
        raise Fail('give --action "<one line: what you will do>"')
    task, attempt = ctx["task"], ctx["attempt"]
    node = tg_json(ctx, "show", str(task)) or {}
    rows = tg_json(ctx, "result", "ls", str(task)) or []
    if args.id not in {r["id"] for r in open_messages(rows, node.get("meta") or {}, attempt)}:
        raise Fail(f"#{args.id} is not an open message of task {task} attempt {attempt}; run the inbox command to list them")
    row = tg_json(ctx, "result", "add", str(task), "--kind", ACK, "--attempt", str(attempt), "--by", ctx["by"],
                  "--status", "SEEN", "--body-file", "-", input=f"Re: #{args.id}\nAction: {action}\n")
    print(f"ack #{row['id']} filed for #{args.id}.")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["hook"]:  # before anything else loads: it runs after every tool call
        return cmd_hook(argv)
    import argparse
    parser = argparse.ArgumentParser(prog="mailbox.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ctx", help="the context file that run.py wrote for the attempt")
    sub = parser.add_subparsers(dest="command", required=True, metavar="{checkin,ask,inbox,ack,hook}")
    sub.add_parser("checkin", help="SessionStart hook: write the session's socket address")
    p = sub.add_parser("ask", help="file a question for the Manager")
    p.add_argument("--file", required=True, help="the question: Question, Options, Default, Blocking, Why")
    sub.add_parser("inbox", help="print the messages that wait for this task and attempt")
    p = sub.add_parser("ack", help="file the ack of a message")
    p.add_argument("id", type=int)
    p.add_argument("--action", required=True, help="one line: what you will do")
    sub.add_parser("hook", help="PostToolUse hook: print the pointer line of --flag")
    args = parser.parse_args(argv)
    try:
        if not args.ctx:
            raise Fail(f"{args.command} needs --ctx <the context file of your brief>")
        ctx = read_ctx(args.ctx)
        return {"checkin": cmd_checkin, "ask": cmd_ask, "inbox": cmd_inbox, "ack": cmd_ack}[args.command](ctx, args)
    except Fail as exc:
        print(f"mailbox.py: {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
