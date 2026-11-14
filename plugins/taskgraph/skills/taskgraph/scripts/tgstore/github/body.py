from __future__ import annotations

import json
import re
from urllib.parse import quote

from tgstore.base import StoreError

START = "<!-- taskgraph:meta v1"
END = "taskgraph:end -->"
LIMIT = 260_000  # tg refuses above this; GitHub truncates silently above 262,144 bytes
START_LINE = re.compile(r"^<!-- taskgraph:meta v1[ \t]*\r?$", re.M)
END_LINE = re.compile(r"^taskgraph:end -->[ \t]*\r?$", re.M)
WAITING_MARK = "<!-- taskgraph:waiting -->"
# The visible line of the open gates that have a ref, between the notes and the block. parse drops it; render writes it again from the meta.
WAITING_LINE = re.compile(r"(?:\A|\r?\n\r?\n)Waiting for: [^\r\n]* " + re.escape(WAITING_MARK) + r"[ \t]*\Z")
MARKDOWN = re.compile(r"([\\\[\]<>`*_])")  # escaped in a label
URL_SAFE = ":/?#@!$&'*+,;=%~"  # kept in a ref; a space, a parenthesis or a newline is percent-encoded


def dumps(value):
    # One line; "-->" and "<!--" stay valid JSON escapes, so the HTML comment cannot close or reopen early.
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return text.replace("-->", "--\\u003e").replace("<!--", "\\u003c!--")


def waiting(meta):
    """The visible line for the open gates that have a ref, as Markdown links; "" when none has one. GitHub reads a link to an issue
    or a pull request in the body as a cross-reference, so the request shows the task that waits for it."""
    gates = meta.get("gates")
    if not isinstance(gates, dict):
        return ""
    links = []
    for key, gate in sorted(gates.items()):
        ref = gate.get("ref") if isinstance(gate, dict) else None
        if isinstance(ref, str) and ref.strip():
            label = MARKDOWN.sub(r"\\\1", " ".join(str(gate.get("label") or key).split()))
            links.append(f"[{label}]({quote(ref.strip(), safe=URL_SAFE)})")
    return f"Waiting for: {', '.join(links)} {WAITING_MARK}" if links else ""


def render(notes, meta, keep=False):
    # keep: the issue already had a block, so an empty meta is written as {} instead of removing it
    if not meta and not keep:
        return notes
    block = f"{START}\n{dumps(meta)}\n{END}\n"
    head = "\n\n".join(part for part in (notes, waiting(meta)) if part)
    return f"{head}\n\n{block}" if head else block


def trim(text):
    for tail in ("\n\n", "\r\n\r\n"):
        if text.endswith(tail):
            return text[: -len(tail)]
    return text


def parse(body):
    """(notes, meta, problems). problems: "broken" (tg must not write the body) or "two_blocks" (the last block counts)."""
    body = body or ""
    starts = list(START_LINE.finditer(body))
    if not starts:
        return body, {}, []
    start = starts[-1]
    notes = trim(body[: start.start()])
    line = WAITING_LINE.search(notes)
    if line:
        notes = notes[: line.start()]
    end = END_LINE.search(body, start.end())
    if end is None or body[end.end():].strip():
        return notes, {}, ["broken"]
    try:
        meta = json.loads(body[start.end(): end.start()])
    except ValueError:
        return notes, {}, ["broken"]
    if not isinstance(meta, dict):
        return notes, {}, ["broken"]
    return notes, meta, ["two_blocks"] if len(starts) > 1 else []


def size(body):
    return len(body.encode("utf-8"))


def check_size(label, body):
    n = size(body)
    if n > LIMIT:
        raise StoreError(f"{label} body would be {n:,} bytes; GitHub truncates above 262,144")


def conflicts(number, problems):
    text = {"broken": f"meta block on #{number} is broken; fix or delete it on GitHub", "two_blocks": f"#{number} has 2 meta blocks; the last one counts",
            "two_priorities": f"#{number} has more than one priority label; the highest counts"}
    return [text.get(p) or (f"#{number} has the label {p[9:]}, which is not a priority" if p.startswith("priority:") else f"#{number} has the label {p[5:]}, which is not a task type") for p in problems]
