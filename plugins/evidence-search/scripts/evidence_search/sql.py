"""Find the tables a piece of SQL names, with their offsets.

Works on a whole statement, not a line, because real SQL spreads one FROM
list over several lines. String literals and comments are blanked first
(keeping offsets), so data such as 'fish from Australia' is never read as a
table. Callers map offsets back to line numbers.
"""

import re

_TABLE = r'[A-Za-z_#"`\[][\w.$#"`\]]*'
_QUOTED = re.compile(r"'(?:[^']|'')*'")
_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_WRITE = re.compile(r"\b(INSERT\s+INTO|DELETE\s+FROM|MERGE\s+INTO|REPLACE\s+INTO|UPDATE)\s+(" + _TABLE + ")", re.I)
_DDL = re.compile(r"\b(CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE|TRUNCATE\s+TABLE)\s+"
                  r"(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(" + _TABLE + ")", re.I)
_JOIN = re.compile(r"\bJOIN\s+(" + _TABLE + ")", re.I)
_FROM = re.compile(r"\bFROM\s+", re.I)
_FROM_END = re.compile(r"\b(WHERE|GROUP|ORDER|HAVING|UNION|INTERSECT|EXCEPT|MINUS|JOIN|INNER|LEFT|RIGHT|FULL|"
                       r"CROSS|NATURAL|ON|USING|LIMIT|OFFSET|FETCH|FOR|WITH|SET|VALUES|START|CONNECT|WINDOW|"
                       r"SELECT|INSERT|UPDATE|DELETE)\b|[();]", re.I)
_WORDS = re.compile(r"\b(select|insert|update|delete|from|where|set|values|join|into|merge|order\s+by|group\s+by)\b",
                    re.I)
CLAUSE_START = re.compile(r"^\s*(FROM|WHERE|JOIN|INNER|LEFT|RIGHT|OUTER|SET|VALUES|AND|OR|ORDER|GROUP|HAVING|"
                          r"INTO|UPDATE|SELECT|INSERT|DELETE|UNION)\b", re.I)
_NOT_TABLES = {"select", "where", "set", "values", "the", "a", "an", "table", "if", "exists", "only", "lateral",
               "unnest", "this", "that", "to", "and", "or", "in", "on", "with", "dual", "nowait", "of", "skip"}


def looks_like_sql(text):
    """Two or more SQL keywords: enough to treat a string as SQL."""
    return len(_WORDS.findall(text)) >= 2


def _blank(match):
    return " " * len(match.group(0))


def _blank_literal(match):
    text = match.group(0)
    return "'" + " " * (len(text) - 2) + "'"


def _name(raw):
    name = raw.strip('"`[]')
    if not name or name.lower() in _NOT_TABLES or name.isdigit() or not re.search(r"[A-Za-z]", name):
        return None
    return name


def _verb(text):
    return re.sub(r"\s+", " ", text.upper())


def tables(text):
    """[(offset, table, detail)] for every table TEXT names, in order.

    detail is "read (FROM)", "read (JOIN)", "write (UPDATE)", "ddl (CREATE TABLE)" and so on.
    """
    clean = _COMMENT.sub(_blank, text)
    clean = _QUOTED.sub(_blank_literal, clean)
    found = []

    for match in _WRITE.finditer(clean):
        verb = _verb(match.group(1))
        before = clean[:match.start()].rstrip().upper()
        if verb == "UPDATE" and before.endswith(("KEY", "FOR")):
            continue  # ON DUPLICATE KEY UPDATE, SELECT ... FOR UPDATE
        name = _name(match.group(2))
        if name:
            found.append((match.start(2), name, "write (%s)" % verb))

    for match in _DDL.finditer(clean):
        name = _name(match.group(2))
        if name:
            found.append((match.start(2), name, "ddl (%s)" % _verb(match.group(1))))

    for match in _JOIN.finditer(clean):
        name = _name(match.group(1))
        if name:
            found.append((match.start(1), name, "read (JOIN)"))

    for match in _FROM.finditer(clean):
        before = clean[:match.start()].rstrip().upper()
        if before.endswith(("DELETE", "DISTINCT")):
            continue  # DELETE FROM is a write; IS DISTINCT FROM is not a table list
        start = match.end()
        end_match = _FROM_END.search(clean, start)
        segment = clean[start:end_match.start() if end_match else len(clean)]
        position = start
        for part in segment.split(","):
            stripped = part.lstrip()
            token = re.match(_TABLE, stripped)
            if token:
                name = _name(token.group(0))
                if name:
                    found.append((position + len(part) - len(stripped), name, "read (FROM)"))
            position += len(part) + 1
    found.sort()
    return found
