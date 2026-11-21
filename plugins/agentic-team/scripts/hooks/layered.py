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
FAILED lines (every distinct test id) and the assert, error, crash and linker lines, then file:line references, then the last
lines, all copied from the full output; a count says how many matching lines were left out. Only identical lines merge
into one line with a count (`(×N)`); lines that name different tests never do. For the first failures it also keeps the
detail block: the vitest `- Expected / + Received` diff, and the Playwright locator, call log and source frame. The same
rules run at exit 0 when a FAILED or error line matches, and always for log commands (`gh run view --log`, `docker logs`,
`docker compose logs`, `kubectl logs`, `journalctl`), which exit 0 whatever the log says; for those, `ERROR:`, `FATAL:`,
`PANIC:` and `LOG: ... error` lines (the postgres style) are error lines too, and a log with no error line shows its last
lines. When no rule matches and the output is above large_chars, summarize_fallback (default off) asks Haiku. The full
output stays in a file whose path the reduced text names; it is never deleted when it is above passthrough_chars. `pre` fails
safe: any error prints nothing and exits 0. When `reduce` cannot reduce (an error, no matching rule, or REDUCE_SECONDS
passed) it prints one line that says why and then the full output.
"""

import argparse
import base64
import fnmatch
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time

ENV_ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
WRAPPERS = ("with-slot.sh", "env", "time")  # words that start a command and leave its output as it is
GLOB_CHARS = "*?["
KEEP_DAYS = 3
LINE_CAP = 2000  # a line is read, matched and shown up to this length: no pattern runs on more
KEY_MAX = 60  # the error lines kept (the first half and the last half when there are more)
ID_MAX = 200  # the distinct FAILED lines (test ids) kept, the same way
MAX_LINES = 90  # error lines and file:line references kept; FAILED lines come first, the rest of the room goes to references
DIFF_LINES = 30  # per failure: the vitest diff block
CALL_LOG_LINES = 15  # per failure: the Playwright call log
FRAME_LINES = 12  # per failure: the source frame
BLOCK_FAILURES = 8  # detail blocks are kept for this many failures; the rest are counted
BLOCK_LINES = 200  # and for at most this many lines in all
REDUCED_MAX_CHARS = 20000  # the reduced text stays below this: blocks, then ids and error lines, then line width are cut
VARIANT_VALUES = 3  # a number with at most this many values in a group of similar lines tells its variants apart
VARIANTS_SHOWN = 3  # a group of similar lines shows its first line and up to this many variants
TAIL_LINES = 15
RESULT_LINES = 5
REDUCE_SECONDS = 5
FILE_CAP = 20 * 1024 * 1024  # the saved output is cut to its head and tail above this size
DOCKER_LIKE = ("docker", "podman", "nerdctl", "docker-compose", "podman-compose")
DOCKER_SUBCOMMANDS = ("compose", "container", "service", "stack")
VALUE_FLAGS = ("-n", "--namespace", "--context", "-H", "--host", "-f", "--file", "-p", "--project-name", "--profile",
               "--env-file", "--kubeconfig", "-c", "--container", "--config")  # global options before `logs` that take a word
FOLLOW_CLUSTER = re.compile(r"-[A-Za-z]*f[A-Za-z]*")  # -f, -tf, -fu, -xef
FOLLOWING = ("--watch", "--follow", "--ui", "show-report", "--debug", "--watchAll")  # never end, or wait for a person

RESULT = re.compile(
    r"\d+ (passed|failed|skipped|errors?|passing|failing)\b|^\s*Tests?:? +\d|Test Files|Test Suites|Ran \d+ tests?|"
    r"^(OK|PASS|ok)\b|BUILD (SUCCESS|FAIL)|^\s*✖ \d+ problems?|^Done in|^\s*Finished\b|\d+ (flaky|did not run)")
FAILED = re.compile(
    r"^\s*(FAILED|FAIL|ERROR)\b|^\s*(✘|×|✗|✖)|^\s*\d+\) .*›|^=+ (FAILURES|ERRORS) =+|^_{3,} [^_]+ _{3,}$")
ERROR = re.compile(
    r"^E\s|AssertionError|\b[A-Za-z]*(Error|Exception)\b[:(]|^\s*(Expected|Received)\b|\bexpect\(|panicked at|"
    r"^error(\[\w+\])?:|\berror TS\d+|^make[^:\n]*: \*\*\*|: (fatal )?error:|: ERROR:|\bld: |linker command failed|"
    r"undefined reference|symbol\(s\) not found|Segmentation fault|Fatal Python error|\bKilled\b|\bAborted\b|core dumped|"
    r"##\[error\]|Test timeout of|^\s+\d+:\d+\s+error\s")
LOG_ERROR = re.compile(  # postgres `ERROR:  ` (two spaces), `FATAL:`, `PANIC:`, `LOG:  ... error`, and logfmt or JSON levels
    r"(?:^|[\s\]])(?:ERROR|FATAL|PANIC):|\bLOG:\s.*\b[Ee]rror\b|\blevel[=\"': ]+(?:error|fatal|panic|critical)\b")
LOG_CONTEXT = re.compile(r"^(DETAIL|HINT|CONTEXT|STATEMENT|QUERY|LOCATION):")
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
    shapes = [words_of]
    if "logs" in words_of:  # `kubectl -n ns logs pod` and `docker compose -f a.yml logs svc` are `kubectl logs`, `docker compose logs`
        at = words_of.index("logs")
        shapes.append(positional(words_of[:at]) + words_of[at:])
    for pattern in patterns:
        if any(ch in pattern for ch in GLOB_CHARS):
            if fnmatch.fnmatchcase(target, pattern):
                return True
            continue
        parts = pattern.split()
        last = max((i for i, w in enumerate(parts) if not w.startswith("-")), default=-1)
        for shape in shapes:
            if last >= 0 and shape[:last + 1] == parts[:last + 1] and all(f in shape for f in parts[last + 1:]):
                return True
    return False


def never_ends(target):
    """A command that follows or watches, or that waits for a person: its output would stay hidden until a timeout."""
    words_of = target.split()
    log = is_log(target)

    def watching(w):  # a container or a pod named `watchtower` is not a watch mode: for a log command only an option is
        return "watch" in w.lower() and not (log and not w.startswith("-"))

    for w in words_of:
        if w.startswith("--follow="):
            if w.split("=", 1)[1].lower() not in ("false", "0", "no", "off"):
                return True
        elif w in FOLLOWING or watching(w):
            return True
    if "vitest" in words_of and "-w" in words_of:
        return True
    if "pytest" in words_of and any(w in ("-f", "--looponfail", "--pdb", "--trace") for w in words_of):
        return True
    if os.path.basename(words_of[0]) == "journalctl" and any(FOLLOW_CLUSTER.fullmatch(w) for w in words_of):
        return True
    if "logs" in words_of:  # `-f` before `logs` is a compose file, after it the follow flag (also as `-tf`)
        return any(FOLLOW_CLUSTER.fullmatch(w) for w in words_of[words_of.index("logs") + 1:])
    return False


def positional(words_of):
    """The words that are not options or the values of the options in VALUE_FLAGS."""
    found, skip = [], False
    for w in words_of:
        if skip:
            skip = False
        elif w in VALUE_FLAGS:
            skip = True
        elif not w.startswith("-"):
            found.append(w)
    return found


def is_log(target):
    """A command whose output is a log: it exits 0 whatever the log says. Options may stand anywhere, so
    `docker logs --tail 3000 name` and `kubectl -n ns logs pod` both count."""
    words_of = target.split()
    if not words_of:
        return False
    if "logs" in words_of:
        before = positional(words_of[:words_of.index("logs")])
        prog = os.path.basename(before[0]) if before else ""
        if prog in DOCKER_LIKE:
            return all(w in DOCKER_SUBCOMMANDS for w in before[1:])
        if prog in ("kubectl", "oc"):
            return len(before) == 1
    first = positional(words_of)
    if first[:1] and os.path.basename(first[0]) == "journalctl":
        return True
    return [os.path.basename(first[0])] + first[1:3] == ["gh", "run", "view"] if first else False


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
    stays = f"; the full output follows and stays in {out}]"
    # exit 126 and 127: the shell could not start the reducer; any other code: it ran and failed. It prints its text in one
    # write at the end, so nothing is printed twice here.
    return (f"printf '%s\\n' {notice}; __at_rc=0; {{ {cmd}\n}} > {q(out)} 2>&1 || __at_rc=$?; __at_rd=0; "
            f"{reduce} || __at_rd=$?; "
            f"if [ \"$__at_rd\" -ge 126 ] && [ \"$__at_rd\" -le 127 ]; then printf '%s\\n' {q('[agentic-team hook: the reducer did not run' + stays)}; cat {q(out)}; "
            f"elif [ \"$__at_rd\" -ne 0 ]; then printf '%s\\n' {q('[agentic-team hook: the reducer ran and failed (exit ')}\"$__at_rd\"{q(')' + stays)}; cat {q(out)}; fi; "
            f"(exit \"$__at_rc\")")


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


ZONE = r"(?:Z|\s?(?:UTC|GMT|[ECMP][SD]T|CES?T|EES?T|BST|IST|JST|KST|HKT|AES?T|NZ[SD]T|WIB)|\s?[+-]\d\d:?\d\d)"
LOG_PREFIX = re.compile(  # job and step columns, up to two timestamps (`docker logs -t` adds one), a process number
    r"^(?:[^\t]*\t[^\t]*\t)?(?:\d{4}-\d\d-\d\d[T ][\d:.]+" + ZONE + r"?\s?){0,2}(?:\[\d+\]\s)?")
ESLINT_ROW = re.compile(r"^\s+\d+:\d+\s+error\b")
ROOT = re.compile(r"^E\s|Error:|Traceback|Caused by")
DIGITS = re.compile(r"\d+")
NAMES_A_PLACE = re.compile(  # a line that names a test or a place: it never merges with a line that differs
    r"::|\btest_|_test\b|\.(test|spec)\.[jt]sx?|[\w./\\-]+\.\w+:\d+|\(\d+,\d+\)| › | > |^\s+\d+:\d+\s")
DIFF_START = re.compile(r"^\s*-\s*Expected\b")
DIFF_HEADER_END = re.compile(r"^\s*\+\s*Received\b")
DETAIL_STOP = re.compile(r"^\s*(❯|⎯|FAIL\b|[✓×✗✔✘])")
GROUP_START = re.compile(r"^\s*(\d+\) \[|FAIL\s+\S)")
FRAME_START = re.compile(r"^\s*(>\s*)?\d+ ?\|")
FRAME = re.compile(r"^\s*(>\s*)?\d+ ?\||^\s+\|\s")  # a code line, or the line with the ^ pointer
PW_FIELD = re.compile(r"^\s+(Locator|Timeout):")
CALL_LOG = re.compile(r"^\s+Call log:")
ATTACHMENT = re.compile(r"^\s+attachment #\d+")


def detail_groups(lines):
    """For each failure, the indexes of its detail lines: the vitest diff block (`- Expected` to the blank line after the
    changes, at most DIFF_LINES), and the Playwright `Locator:` and `Timeout:` lines, the call log (CALL_LOG_LINES), the
    source frame (FRAME_LINES) and the attachment lines. A failure starts at a `FAIL  file > test` or `N) [project] ›` line."""
    groups, cur, i, n = [], None, 0, len(lines)

    while i < n:
        text = lines[i][:LINE_CAP]
        if GROUP_START.match(text):
            cur = []
            groups.append(cur)
        elif DIFF_START.match(text):
            take, j, started, header = [i], i + 1, False, False
            while j < n and len(take) < DIFF_LINES and not DETAIL_STOP.match(lines[j]):
                if header and started and not lines[j].strip():
                    break
                if header and lines[j].strip():
                    started = True
                header = header or bool(DIFF_HEADER_END.match(lines[j]))
                take.append(j)
                j += 1
            if cur is None:
                cur = []
                groups.append(cur)
            cur.extend(take)
            i = j
            continue
        elif cur is not None and PW_FIELD.match(text):
            cur.append(i)
        elif cur is not None and CALL_LOG.match(text):
            j = i + 1
            while j < n and lines[j].strip() and j - i <= CALL_LOG_LINES:
                j += 1
            cur.extend(range(i, j))
            i = j
            continue
        elif cur is not None and FRAME_START.match(text):
            j = i
            while j < n and j - i < FRAME_LINES and FRAME.match(lines[j]):
                j += 1
            cur.extend(range(i, j))
            i = j
            continue
        elif cur is not None and ATTACHMENT.match(text):
            cur.extend(range(i, min(i + 2, n)))
            i += 2
            continue
        i += 1
    return [g for g in groups if g]


def collapse(indexes, norm, heads):
    """Group the line indexes by norm(index): ({first index: count}, {first index: all indexes of the group})."""
    first, members = {}, {}
    for i in indexes:
        at = first.setdefault(norm(i), i)
        members.setdefault(at, []).append(i)
    return {at: len(m) for at, m in members.items()}, members


def variants(members, heads):
    """The members of a group of similar lines (they differ in digits), split into variants: the numbers that take at most
    VARIANT_VALUES different values in the group tell the variants apart (a port, an errno), numbers that vary on
    every line (a case or a row number) do not. [(first index of the variant, its size)], in order of the lines."""
    tokens = {i: DIGITS.findall(heads[i]) for i in members}
    width = len(tokens[members[0]])
    same = [i for i in members if len(tokens[i]) == width]
    fixed = [k for k in range(width) if len({tokens[i][k] for i in same}) <= VARIANT_VALUES]
    found = {}
    for i in members:
        key = ("n", len(tokens[i])) if i not in same else tuple(tokens[i][k] for k in fixed)
        found.setdefault(key, []).append(i)
    return [(m[0], len(m)) for m in found.values()]


def halves(found, limit, keep_extra=None):
    """`found` (sorted indexes) cut to its first and last half when over `limit`; `keep_extra` always stays."""
    if len(found) <= limit:
        return found
    keep = found[:limit // 2] + found[-(limit // 2):] + ([keep_extra] if keep_extra in found else [])
    return sorted(set(keep))


def extract(lines, log=False, cap=None):
    """(kept, omitted, key, useful, summary). `kept` is the lines to show in their order: the FAILED lines (each distinct test
    id), the error lines (at most KEY_MAX), the detail blocks of the first failures, then file:line references up to
    MAX_LINES, then the last TAIL_LINES lines. Only identical lines merge, with a count; when there are still more than
    KEY_MAX error lines, lines that differ only in digits and name no test or place merge too (`similar`), and the group
    shows its first line and each variant up to VARIANTS_SHOWN. When the text is longer than `cap` characters, the detail
    blocks go first, then the ids and error lines beyond the first ones, then the line width: kept[0] says what was cut.
    `omitted` counts the matching lines left out; `key` is the number of FAILED and error lines kept, `useful` those and
    the references. `summary` holds the result lines at the end."""
    cap = cap or REDUCED_MAX_CHARS
    ids, keys, refs, root, heads = [], [], [], None, {}
    for i, line in enumerate(lines):
        head = line[:LINE_CAP]
        if log:  # `gh run view --log` puts job and step columns and a timestamp before the text
            head = head[LOG_PREFIX.match(head).end():]
        heads[i] = head
        if PASSED_LINE.search(head):
            continue
        if log and LOG_ERROR.search(head):  # a postgres ERROR: line is an error, not a test id
            keys.append(i)
        elif FAILED.search(head):
            ids.append(i)
        elif ERROR.search(head):
            keys.append(i)
        else:
            if FILE_LINE.search(head):
                refs.append(i)
            continue
        if root is None and ROOT.search(head):
            root = i
    total = len(ids) + len(keys) + len(refs)

    def exact(i):
        return heads[i]

    def loose(i):
        head = heads[i]
        return head if NAMES_A_PLACE.search(head) else DIGITS.sub("#", head)

    id_counts, _ = collapse(ids, exact, heads)
    key_counts, key_members = collapse(keys, exact, heads)
    similar = {}  # first index of a group of similar lines: its variants [(index, size)]
    if len(key_counts) > KEY_MAX:
        key_counts, key_members = collapse(keys, loose, heads)
        for at, members in key_members.items():
            if any(heads[i] != heads[at] for i in members):
                similar[at] = variants(members, heads)
    groups = detail_groups(lines)
    starts = {lines[i].strip() for i in range(len(lines)) if GROUP_START.match(lines[i][:LINE_CAP])}
    failures = max(len(starts), len(groups))
    blocks, used = set(), 0
    for group in groups[:BLOCK_FAILURES]:
        if used and used + len(group) > BLOCK_LINES:
            break
        blocks.update(group)
        used += len(group)
    kept_groups = sum(1 for g in groups if blocks.issuperset(g))
    cut_groups = len(groups) - kept_groups
    tail = set(range(max(len(lines) - TAIL_LINES, 0), len(lines)))
    room = max(cap - 600, 1000)  # the header, the pointer and the result lines come on top

    def build(with_blocks, id_limit, key_limit, width):
        id_list = halves(sorted(id_counts), id_limit)
        key_list = halves(sorted(key_counts), key_limit, root)
        shown_keys = id_list + key_list
        shown_refs = refs[:max(MAX_LINES - len(key_list) - len(id_list), 0)]
        extra, counts, mark, notes = set(), dict(id_counts), set(), {}
        for at in key_list:
            if at not in similar:
                counts[at] = key_counts[at]
                continue
            shown = similar[at][:VARIANTS_SHOWN]
            for i, n in shown:
                counts[i] = n
                mark.add(i)
                extra.add(i)
            more = key_counts[at] - sum(n for _, n in shown)
            if more:
                notes[shown[-1][0]] = (f"[agentic-team hook: {more} more similar lines in "
                                       f"{len(similar[at]) - len(shown)} other variants]")
        context = set()  # a postgres error line is followed by its DETAIL, HINT, CONTEXT and STATEMENT lines
        if log:
            for i in sorted(set(shown_keys) | extra):
                j = i + 1
                while j < len(lines) and j - i <= 3 and LOG_CONTEXT.match(heads[j]):
                    context.add(j)
                    j += 1
        for at in key_list:  # an eslint error row is shown under its file name
            if ESLINT_ROW.match(heads[at]):
                j = at - 1
                while j >= 0 and (not lines[j].strip() or ESLINT_ROW.match(lines[j])):
                    j -= 1
                if j >= 0 and not lines[j].startswith(" "):
                    context.add(j)
        shown_blocks = blocks if with_blocks else set()
        chosen = sorted(set(shown_keys + shown_refs) | extra | context | shown_blocks | tail)
        seen, kept = set(), []
        for i in chosen:
            if i in shown_blocks or i in context:
                kept.append(lines[i])
                continue
            if lines[i] in seen:
                continue
            seen.add(lines[i])
            n = counts.get(i, 1)
            kept.append(lines[i] + ((f" (×{n} similar)" if i in mark else f" (×{n})") if n > 1 else ""))
            if i in notes:
                kept.append(notes[i])
        if width:
            kept = [ln if len(ln) <= width else ln[:width] + " [line cut]" for ln in kept]
        shown = sum(counts.get(i, 1) for i in id_list) + sum(key_counts[i] for i in key_list) + len(shown_refs)
        return kept, total - shown, len(shown_keys), len(set(shown_keys + shown_refs))

    stages = [(True, ID_MAX, KEY_MAX, None, ""), (False, ID_MAX, KEY_MAX, None, "the detail blocks are dropped"),
              (False, 100, 30, None, "at most 100 failure lines and 30 error lines are listed"),
              (False, 40, 16, None, "at most 40 failure lines and 16 error lines are listed"),
              (False, 16, 8, 300, "at most 16 failure lines and 8 error lines are listed, and lines are cut to 300 characters")]
    for with_blocks, id_limit, key_limit, width, said in stages:
        kept, omitted, key, useful = build(with_blocks, id_limit, key_limit, width)
        if sum(len(ln) + 1 for ln in kept) <= room:
            break
    if said:
        kept.insert(0, f"[agentic-team hook: the text was cut to fit {cap} characters: {said}]")
    elif cut_groups:
        kept.insert(0, f"[agentic-team hook: the detail blocks are kept for the first {kept_groups} of "
                       f"{failures} failures; the other {cut_groups} are in the full output]")
    return kept, omitted, key, useful, [ln for ln in lines[::-1] if RESULT.search(ln)][:RESULT_LINES][::-1]


def summarize(text, cmd, seconds=30):
    prompt = ("A coding agent ran a command that failed. The output is long and no rule found an error line. Summarize "
              "what failed in at most 10 lines. Do not invent lines.\n"
              f"Command: {cmd}\n--- OUTPUT (head and tail) ---\n{text[:30000]}\n...\n{text[-30000:]}")
    done = subprocess.run(["claude", "-p", "--model", "haiku", "--no-session-persistence", "--tools=", prompt],
                          capture_output=True, text=True, timeout=seconds, cwd=os.path.expanduser("~"))
    return done.stdout.strip() if done.returncode == 0 else ""


def log_tail(lines, rc, pointer):
    shown = [ln if len(ln) <= LINE_CAP // 4 else ln[:LINE_CAP // 4] + " [line cut]" for ln in lines[-2 * TAIL_LINES:]]
    return f"[agentic-team hook: exit {rc}; no error line matched in the log; the last lines]\n" + "\n".join(shown) + "\n" + pointer


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
    if rc == 0 and not key:  # a log with no error line: its last lines, not the whole log
        return log_tail(lines, rc, pointer), "log-tail"
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
    if log:
        return log_tail(lines, rc, pointer), "log-tail"
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


def print_full(path, why):
    """The reducer's fallback: one line that says why, then the full output. The file stays."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    sys.stdout.write(f"[agentic-team hook: {why}; the full output follows and stays in {path}]\n" + text)


NOT_REDUCED = {"fail-unchanged": "no reduction rule matched this output"}


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
    try:
        lines = read_lines(args.file)
        out, how = reduce_output(lines, os.path.getsize(args.file), args.rc, cfg, cmd, args.file, args.log)
        signal.alarm(0)
        why = NOT_REDUCED.get(how, "the output was not reduced")
    except Exception as err:  # the full output is better than none, and the file stays
        signal.alarm(0)
        out, why = None, (f"the reducer timed out after {REDUCE_SECONDS} s" if isinstance(err, TimeoutError)
                          else f"the reducer failed ({type(err).__name__})")
    if out is None:
        print_full(args.file, why)
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
