from __future__ import annotations

import json
import re
import uuid

from tgstore.github.body import LIMIT, dumps

MARKER = re.compile(r"^<!-- taskgraph:(result|claim|void) v1 (\{.*\}) -->\r?$")
LINE = re.compile(r"[^\n]*\n|[^\n]+")


def marker(kind, data):
    return f"<!-- taskgraph:{kind} v1 {dumps(data)} -->"


def split_text(text, size):
    # Parts end at line ends; one line longer than `size` bytes is cut at a character boundary. "".join(parts) == text.
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


def render_result(row, at, key=None):
    """The comment bodies (parts) of one result. row has status, kind, attempt, author, body."""
    key = key or uuid.uuid4().hex[:12]

    def head(part, parts):
        return marker("result", {"at": at, "attempt": row.attempt, "by": row.author, "key": key, "kind": row.kind, "part": part, "parts": parts, "status": row.status})

    room = LIMIT - len(head(999, 999).encode("utf-8")) - 1
    chunks = split_text(row.body, room)
    return [f"{head(i, len(chunks))}\n{chunk}" for i, chunk in enumerate(chunks, 1)]


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
        found["result"] = dict(data, text=rest)
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
                    "attempt": first.get("attempt"), "author": first.get("by"), "body": body})
    return sorted(out, key=lambda r: r["id"])
