from __future__ import annotations

import json
import re
import uuid

from tgstore.base import StoreError
from tgstore.github.body import LIMIT, dumps

MARKER = re.compile(r"^<!-- taskgraph:(result|claim|void) v1 (\{.*\}) -->\r?$")
LINE = re.compile(r"[^\n]*\n|[^\n]+")


def marker(kind, data):
    return f"<!-- taskgraph:{kind} v1 {dumps(data)} -->"


def split_text(text, size):
    # Parts end at line ends; one line longer than `size` bytes is cut at a character boundary. "".join(parts) == text.
    if size <= 0:
        raise StoreError("no room for text in a comment: the summary is too large")
    parts, cur, used = [], [], 0
    for line in LINE.findall(text):
        while len(line.encode("utf-8")) > size:
            piece = line.encode("utf-8")[:size].decode("utf-8", "ignore")
            if cur:
                parts.append("".join(cur))
                cur, used = [], 0
            parts.append(piece)
            line = line[len(piece):]
        n = len(line.encode("utf-8"))
        if used + n > size and cur:
            parts.append("".join(cur))
            cur, used = [], 0
        cur.append(line)
        used += n
    if cur or not parts:
        parts.append("".join(cur))
    return parts


DETAILS_END = "</details>"


def fence_for(body):
    longest = max((len(run) for run in re.findall(r"`+", body)), default=0)
    return max(3, longest + 1)


def details_label(part, parts):
    return "Full result" if parts == 1 else f"Full result (part {part} of {parts})"


def visible(summary):
    # The summary is shown as Markdown: "<!--" or a tag in it would hide or change the rest of the comment.
    return summary.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def details_edges(summary, part, parts, fence, eol="\n"):
    """The text before and after a part's chunk when the result has a summary. fence is the backtick count, 0 for none.
    `summary` is the exact text; the edges show it escaped. eol is the line break (GitHub gives \r\n after a browser edit)."""
    lead = f"{visible(summary)}\n\n" if part == 1 else ""
    mark = "`" * fence
    open_ = f"{lead}<details><summary>{details_label(part, parts)}</summary>\n\n" + (f"{mark}\n" if fence else "")
    close = (f"\n{mark}" if fence else "") + f"\n\n{DETAILS_END}"
    return open_.replace("\n", eol), close.replace("\n", eol)


def render_result(row, at, key=None):
    """The comment bodies (parts) of one result. row has status, kind, attempt, author, body, summary.
    With a summary, each part shows it (part 1 only) above the chunk in a <details> block; the meta keeps the summary
    and the fence length, so parse_comment cuts the same text away."""
    key = key or uuid.uuid4().hex[:12]
    summary = row.summary
    fence = fence_for(row.body) if summary else 0

    def head(part, parts):
        data = {"at": at, "attempt": row.attempt, "by": row.author, "key": key, "kind": row.kind, "part": part, "parts": parts, "status": row.status}
        if summary:
            data["fence"] = fence
            if part == 1:
                data["summary"] = summary
        return marker("result", data)

    room = LIMIT - len(head(1, 999).encode("utf-8")) - 1
    if summary:
        before, after = details_edges(summary, 1, 999, fence)
        room -= len((before + after).encode("utf-8"))
    chunks = split_text(row.body, room)
    if not summary:
        return [f"{head(i, len(chunks))}\n{chunk}" for i, chunk in enumerate(chunks, 1)]
    out = []
    for i, chunk in enumerate(chunks, 1):
        before, after = details_edges(summary, i, len(chunks), fence)
        out.append(f"{head(i, len(chunks))}\n{before}{chunk}{after}")
    return out


def unwrap(text, data):
    # Undo details_edges; a comment somebody edited on GitHub no longer fits and is read as it stands.
    fence = data.get("fence")
    if not isinstance(fence, int) or fence < 0:
        return text
    for eol in ("\n", "\r\n"):
        before, after = details_edges(data.get("summary") or "", data["part"], data["parts"], fence, eol)
        if text.startswith(before) and text.endswith(after) and len(text) >= len(before) + len(after):
            return text[len(before): len(text) - len(after)]
    return text


def render_claim(token, claimant, at, voids=()):
    lines = [marker("void", {"of": i}) for i in voids]
    lines.append(marker("claim", {"at": at, "claimant": claimant, "token": token}))
    return "\n".join(lines) + f"\nClaimed by {claimant}."


def parse_comment(comment):
    """None for a human comment, else {id, at, user, result?, claim?, voids}."""
    body = comment.get("body") or ""
    first, _, rest = body.partition("\n")
    found = {"id": comment["id"], "at": comment.get("created_at"), "user": (comment.get("user") or {}).get("login"), "voids": []}
    m = MARKER.match(first)
    if not m:
        return None
    try:
        data = json.loads(m[2])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    if m[1] == "result":
        if not isinstance(data.get("part"), int) or not isinstance(data.get("parts"), int) or not data.get("key") or not data.get("status"):
            return None
        found["result"] = dict(data, text=unwrap(rest, data))
        return found
    for line in body.split("\n"):
        m = MARKER.match(line)
        if not m or m[1] == "result":
            break
        try:
            data = json.loads(m[2])
        except ValueError:
            break
        if m[1] == "void" and isinstance(data.get("of"), int):
            found["voids"].append(data["of"])
        elif m[1] == "claim" and data.get("token") and data.get("claimant"):
            found["claim"] = data
    return found if found["voids"] or "claim" in found else None


def join_parts(parsed):
    """Results from parsed result comments, ordered by id: one per key, parts joined in order."""
    groups = {}
    for p in parsed:
        if "result" in p:
            groups.setdefault(p["result"]["key"], []).append(p)
    out = []
    for parts in groups.values():
        parts.sort(key=lambda p: p["result"]["part"])
        first = parts[0]["result"]
        body = "".join(p["result"]["text"] for p in parts)
        if len(parts) != first["parts"]:
            body += f"\n[incomplete: {len(parts)} of {first['parts']} parts]"
        out.append({"id": parts[0]["id"], "at": parts[0]["at"], "status": first["status"], "kind": first.get("kind") or "task",
                    "attempt": first.get("attempt"), "author": first.get("by"), "body": body, "summary": first.get("summary") or ""})
    return sorted(out, key=lambda r: r["id"])
