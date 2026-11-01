"""Bindings recorded in documentation tables: which class listens on which queue.

When deployment descriptors are not in the repository, the binding between a
listener class, its JNDI name and the IBM MQ queue behind it often lives in a
Markdown table or a CSV file. Each row that names two or more such things
becomes linked facts: every cell in the row shares a row key, and each cell
carries the key that ties it to code (class:, cls:, ejb:, jndi:, mq:).

A cell's role comes from its shape first (jms/... is a JNDI name, a dotted
name ending in a capitalised word is a class) and from its column header
otherwise. Findings are (type, value, detail, offset, ref) as in jee.py.
"""

import csv
import io
import re

_HEADER_ROLES = [
    ("jndi", re.compile(r"jndi", re.I)),
    ("ejb", re.compile(r"\bejb", re.I)),
    ("queue", re.compile(r"queue|destination|topic|\bmq\b|队列|主题", re.I)),
    ("class", re.compile(r"class|mdb|bean|listener|consumer|handler|receiver|component|类|监听", re.I)),
]
# A class column that names listeners makes its classes entry points; any other is a component.
_LISTENER_HEADER = re.compile(r"mdb|listener|consumer|receiver|subscriber|监听|接收", re.I)
_JNDI = re.compile(r"^(?:java:comp/env/)?jms/\S+$")
_FQN = re.compile(r"^(?:[a-z_][\w]*\.)+[A-Z][\w$]*$")
_SIMPLE_CLASS = re.compile(r"^[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+$")
_MQ_NAME = re.compile(r"^[A-Za-z0-9_]+(?:[._][A-Za-z0-9_]+)+$")


def _clean(cell):
    return re.sub(r"[`*]|<[^>]+>", "", cell).strip()


def _header_role(header):
    for role, pattern in _HEADER_ROLES:
        if pattern.search(header):
            return role
    return None


def _cell_role(value, header_role):
    if not value or " " in value:
        return None
    if _JNDI.match(value):
        return "jndi"
    if header_role == "class" and (_FQN.match(value) or _SIMPLE_CLASS.match(value)):
        return "class"
    if _FQN.match(value) and header_role in (None, "class", "ejb"):
        return "class"
    if header_role == "queue" and _MQ_NAME.match(value):
        return "queue"
    if header_role == "ejb":
        return "ejb"
    if header_role == "jndi":
        return "jndi"
    return None


def _row_facts(headers, cells, offsets, row_key, source):
    roles = []
    for header, value, offset in zip(headers, cells, offsets):
        role = _cell_role(value, _header_role(header))
        if role:
            roles.append((role, header, value, offset))
    if len(roles) < 2:
        return []
    out = []
    for role, header, value, offset in roles:
        column = header.strip() or "?"
        if role == "class":
            simple = value.split(".")[-1]
            keys = "%s cls:%s" % (row_key, simple)
            if "." in value:
                keys += " class:" + value
            if _LISTENER_HEADER.search(header):
                out.append(("entry_point", value, "mdb documented in %s (column %s)" % (source, column), offset, keys))
            else:
                out.append(("component", value, "documented in %s (column %s)" % (source, column), offset, keys))
        elif role == "ejb":
            out.append(("entry_point", value, "mdb ejb-name documented in %s (column %s)" % (source, column), offset,
                        "%s ejb:%s" % (row_key, value)))
        elif role == "jndi":
            out.append(("queue", value, "JNDI name documented in %s (column %s)" % (source, column), offset,
                        "%s jndi:%s" % (row_key, value)))
        else:
            out.append(("queue", value, "queue documented in %s (column %s)" % (source, column), offset,
                        "%s mq:%s jndi:%s" % (row_key, value, value)))
    return out


def _split_pipe_row(line):
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return body.split("|")


def markdown(text, path=""):
    """Facts from Markdown pipe tables in TEXT."""
    out = []
    lines = text.split("\n")
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line) + 1)
    index = 0
    while index < len(lines) - 1:
        header, separator = lines[index], lines[index + 1]
        if "|" in header and re.match(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$", separator):
            headers = [_clean(h) for h in _split_pipe_row(header)]
            row = index + 2
            while row < len(lines) and "|" in lines[row] and lines[row].strip():
                raw = _split_pipe_row(lines[row])
                cells = [_clean(c) for c in raw]
                line_text = lines[row]
                offsets = []
                cursor = 0
                for cell in raw:
                    at = line_text.find(cell, cursor) if cell else cursor
                    offsets.append(starts[row] + max(at, 0))
                    cursor = max(at, 0) + len(cell)
                out.extend(_row_facts(headers, cells, offsets, "row:%s:%d" % (path, row + 1), "table"))
                row += 1
            index = row
        else:
            index += 1
    return out


def delimited(text, path="", delimiter=None):
    """Facts from a CSV or TSV file. Assumes one record per line."""
    lines = text.split("\n")
    if not lines or not lines[0].strip():
        return []
    if delimiter is None:
        delimiter = "\t" if lines[0].count("\t") > lines[0].count(",") else ","
    out = []
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line) + 1)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    headers = None
    for number, record in enumerate(reader):
        if number >= len(lines):
            break
        if headers is None:
            headers = [_clean(h) for h in record]
            continue
        cells = [_clean(c) for c in record]
        offsets = []
        cursor = 0
        for cell in record:
            at = lines[number].find(cell, cursor) if cell else cursor
            offsets.append(starts[number] + max(at, 0))
            cursor = max(at, 0) + len(cell)
        out.extend(_row_facts(headers, cells, offsets, "row:%s:%d" % (path, number + 1), "csv"))
    return out
