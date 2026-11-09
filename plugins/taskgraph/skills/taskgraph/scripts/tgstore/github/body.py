from __future__ import annotations

import json
import re

from tgstore.base import StoreError

START = "<!-- taskgraph:meta v1"
END = "taskgraph:end -->"
LIMIT = 260_000  # tg refuses above this; GitHub truncates silently above 262,144 bytes
START_LINE = re.compile(r"^<!-- taskgraph:meta v1[ \t]*\r?$", re.M)
END_LINE = re.compile(r"^taskgraph:end -->[ \t]*\r?$", re.M)


def dumps(value):
    # One line; "-->" and "<!--" stay valid JSON escapes, so the HTML comment cannot close or reopen early.
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return text.replace("-->", "--\\u003e").replace("<!--", "\\u003c!--")


def render(notes, meta, keep=False):
    # keep: the issue already had a block, so an empty meta is written as {} instead of removing it
    if not meta and not keep:
        return notes
    block = f"{START}\n{dumps(meta)}\n{END}\n"
    return f"{notes}\n\n{block}" if notes else block


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
    text = {"broken": f"meta block on #{number} is broken; fix or delete it on GitHub", "two_blocks": f"#{number} has 2 meta blocks; the last one counts"}
    return [text.get(p) or f"#{number} has the label {p[5:]}, which is not a task type" for p in problems]
