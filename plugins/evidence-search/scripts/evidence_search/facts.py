"""Extract static facts for enumeration questions, one row per occurrence.

Rules are regular expressions, so they need neither compilation nor
tree-sitter. They are best effort: SQL built from string concatenation,
class names constructed at runtime and configuration resolved at runtime
escape them. Callers should cross-check enumerations with grep.

Fact types
  sql_table    table named in SQL; detail is read, write or ddl
  url_handler  URL a handler serves (annotations, web.xml, Struts)
  url_ref      URL a page or script calls (forms, links, AJAX)
  include      page composed into another (JSP include, forward, import)
  jsp_import   Java class a JSP imports
  taglib       tag library a JSP uses
  queue        queue, topic, JMS JNDI name or IBM MQ queue; detail says which
               listener, descriptor, API call or config key names it
  entry_point  where work enters the system; detail starts with mdb, http,
               scheduled, startup, webservice or ejb (see jee.py)
  component    a class a documentation table binds to a queue without
               calling it a listener, such as a sender (see tables.py)
  config_key   configuration key; detail is defined or used
  ref_id       an identifier matching a project pattern, such as a
               requirement or use-case id, in code, docs or config; detail is
               the file kind. Patterns are set with `evs index --id-pattern`.
"""

import bisect
import re
from dataclasses import dataclass

from . import jee, sql, tables


@dataclass
class Fact:
    type: str
    value: str
    detail: str
    line: int
    ref: str = ""  # space-separated link keys; see jee.py


_LITERAL = re.compile(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'')

_CODE_LANGS = ("java", "javascript", "typescript", "jsp", "groovy", "kotlin", "scala")
_XML_STATEMENT = re.compile(
    r"<(select|insert|update|delete|sql|statement|procedure|sql-query|named-native-query|query)\b[^>]*>(.*?)</\1\s*>",
    re.S | re.I)
_CDATA = re.compile(r"<!\[CDATA\[|\]\]>")
_TAG = re.compile(r"<[^>]*>")
_TABLE_ATTR = re.compile(
    r"<(?:class|joined-subclass|union-subclass|subclass|join|set|bag|list|map|idbag)\b[^>]*?\btable\s*=\s*\"([^\"]+)\"")
_JPA_TABLE = re.compile(r"@Table\s*\(\s*(?:name\s*=\s*)?\"([^\"]+)\"")
_CLASS_LINE = re.compile(r"^\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:public|protected|private|abstract|final|static)\s+)*"
                         r"(?:class|interface|enum|record)\s+\w+")
# A line that adds to a string being built: sb.append("…"), sql += "…", or a leading +.
_BUILDS_STRING = re.compile(r"\.append\s*\(|\+=|^\s*\+")
_TRAILING_COMMENT = re.compile(r"\s*//[^\"']*$")

_MAPPING = re.compile(r"@(Request|Get|Post|Put|Delete|Patch)Mapping\s*\(([^)]*)\)")
_WEBSERVLET = re.compile(r"@WebServlet\s*\(([^)]*)\)")
_JAXRS = re.compile(r"@Path\s*\(\s*\"([^\"]*)\"")
_URL_PATTERN = re.compile(r"<url-pattern>\s*([^<]+?)\s*</url-pattern>")
_ACTION = re.compile(r"<action\s[^>]*?\b(path|name)\s*=\s*\"([^\"]+)\"[^>]*")
_ACTION_TYPE = re.compile(r"\b(?:type|class)\s*=\s*\"([^\"]+)\"")

_URL_REFS = [
    re.compile(r"\b(?:action|href)\s*=\s*[\"']([^\"'#][^\"']*)[\"']", re.IGNORECASE),
    re.compile(r"\burl\s*:\s*[\"']([^\"']+)[\"']"),
    re.compile(r"\$\.(?:get|post|getJSON|ajax|load)\s*\(\s*[\"']([^\"']+)[\"']"),
    re.compile(r"\bfetch\s*\(\s*[\"']([^\"']+)[\"']"),
    re.compile(r"\blocation(?:\.href)?\s*=\s*[\"']([^\"']+)[\"']"),
    re.compile(r"\.open\s*\(\s*[\"'](?:GET|POST|PUT|DELETE|PATCH)[\"']\s*,\s*[\"']([^\"']+)[\"']", re.IGNORECASE),
]
_INCLUDES = [
    re.compile(r"<%@\s*include\s+file\s*=\s*\"([^\"]+)\""),
    re.compile(r"<jsp:(?:include|forward)\s+page\s*=\s*\"([^\"]+)\""),
    re.compile(r"<c:import\s+url\s*=\s*\"([^\"]+)\""),
]
_JSP_IMPORT = re.compile(r"<%@\s*page\b[^%]*?\bimport\s*=\s*\"([^\"]+)\"")
_TAGLIB = re.compile(r"<%@\s*taglib\b([^%]*)%>")
_QUEUES = [
    re.compile(r"@JmsListener\s*\([^)]*?destination\s*=\s*\"([^\"]+)\""),
    re.compile(r"\bcreate(?:Queue|Topic)\s*\(\s*\"([^\"]+)\""),
    re.compile(r"@KafkaListener\s*\([^)]*?topics?\s*=\s*\{?\s*\"([^\"]+)\""),
    re.compile(r"@RabbitListener\s*\([^)]*?queues?\s*=\s*\{?\s*\"([^\"]+)\""),
    re.compile(r"[\"']((?:java:comp/env/)?jms/[^\"']+)[\"']"),
]
_PROPERTY = re.compile(r"^\s*([A-Za-z0-9_][A-Za-z0-9_.\-]*)\s*[=:]")
_CONFIG_USES = [
    re.compile(r"@Value\s*\(\s*\"\$\{([^}:\"]+)"),
    re.compile(r"\bgetProperty\s*\(\s*\"([^\"]+)\""),
]


def _strings(line):
    return [a if a is not None else b for a, b in _LITERAL.findall(line)]


def _clean_url(value):
    value = re.sub(r"<%=.*?%>|\$\{[^}]*\}", "", value).strip()
    return value.split("?")[0].split("#")[0]


def _is_app_url(value):
    lowered = value.lower()
    if not value or lowered.startswith(("http://", "https://", "mailto:", "javascript:", "tel:", "data:", "//")):
        return False
    return "/" in value or "." in value


def _line_starts(text):
    starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            starts.append(index + 1)
    return starts


def _line_of(starts, offset):
    """1-based line holding OFFSET."""
    return bisect.bisect_right(starts, offset)


def _blank(match):
    return " " * len(match.group(0))


def _sql_in_code(text, starts, out):
    """Tables in SQL held in string literals, across lines of one statement.

    Literals on consecutive lines join while the statement goes on (no ';'),
    so "SELECT a " + "FROM T" is read as one query. A literal that starts
    with a clause keyword shortly after a SQL literal, as in a run of
    StringBuilder.append calls or += concatenation, is read too.
    """
    groups = []
    current = []
    previous_ended = True
    for number, line in enumerate(text.split("\n"), 1):
        base = starts[number - 1]
        literals = []
        for match in _LITERAL.finditer(line):
            group = 1 if match.group(1) is not None else 2
            literals.append((base + match.start(group), match.group(group)))
        if not literals:
            if current:
                groups.append(current)
                current = []
            previous_ended = True
            continue
        if current and not previous_ended:
            current.extend(literals)
        else:
            if current:
                groups.append(current)
            current = list(literals)
        previous_ended = _TRAILING_COMMENT.sub("", line).rstrip().endswith((";", "{", "}"))
    if current:
        groups.append(current)

    lines = text.split("\n")
    context_until = 0
    for group in groups:
        pieces = []
        mapping = []  # (offset in joined text, offset in file)
        position = 0
        for offset, literal in group:
            mapping.append((position, offset))
            pieces.append(literal)
            position += len(literal) + 1
        joined = " ".join(pieces)
        first_line = _line_of(starts, group[0][0])
        builds_sql = _BUILDS_STRING.search(lines[first_line - 1])
        continues = first_line <= context_until and builds_sql and sql.CLAUSE_START.match(joined)
        if not (sql.looks_like_sql(joined) or continues):
            continue
        keys = [m[0] for m in mapping]
        for offset, name, detail in sql.tables(joined):
            index = bisect.bisect_right(keys, offset) - 1
            file_offset = mapping[index][1] + offset - mapping[index][0]
            out.append(Fact("sql_table", name, detail, _line_of(starts, file_offset)))
        context_until = _line_of(starts, group[-1][0]) + 5


def _sql_in_xml(text, starts, out):
    """Tables in mapper statements (MyBatis, iBATIS, Hibernate named queries).

    Without statement elements, a line that reads as SQL is used instead.
    """
    statements = list(_XML_STATEMENT.finditer(text))
    if statements:
        for match in statements:
            inner = _TAG.sub(_blank, _CDATA.sub(_blank, match.group(2)))
            for offset, name, detail in sql.tables(inner):
                out.append(Fact("sql_table", name, detail, _line_of(starts, match.start(2) + offset)))
        return
    for number, line in enumerate(text.split("\n"), 1):
        if sql.looks_like_sql(line):
            for offset, name, detail in sql.tables(_TAG.sub(_blank, line)):
                out.append(Fact("sql_table", name, detail, number))


def _join_path(prefix, path):
    if path in ("", "/"):
        return prefix or path
    if not prefix:
        return path
    return prefix.rstrip("/") + "/" + path.lstrip("/")


def _mapping_paths(args):
    """Path strings in a mapping annotation's arguments; [""] when it names none."""
    values = [v for v in _strings(args) if "=" not in v and " " not in v]
    return values or [""]


def compile_id_patterns(patterns):
    """Compiled ID patterns; raises re.error on an invalid one."""
    return [re.compile(p) for p in patterns]


def extract(lang, text, id_patterns=(), kind="", path=""):
    """Facts found in one file's TEXT. ID_PATTERNS are compiled regexes; PATH names row keys."""
    out = []
    lines = text.split("\n")
    starts = _line_starts(text)
    if lang in _CODE_LANGS:
        _sql_in_code(text, starts, out)
    elif lang == "sql":
        for offset, name, detail in sql.tables(text):
            out.append(Fact("sql_table", name, detail, _line_of(starts, offset)))
    elif lang == "xml":
        _sql_in_xml(text, starts, out)
    class_seen = False
    prefixes = []
    for number, line in enumerate(lines, 1):
        for pattern in id_patterns:
            for match in pattern.finditer(line):
                value = match.group(1) if pattern.groups else match.group(0)
                out.append(Fact("ref_id", value, kind, number))

        if lang in ("java", "groovy", "kotlin"):
            for name in _JPA_TABLE.findall(line):
                out.append(Fact("sql_table", name, "mapping (@Table)", number))
            # A mapping before the class declaration prefixes every method mapping.
            for verb, args in _MAPPING.findall(line):
                paths = _mapping_paths(args)
                if not class_seen:
                    prefixes = [p for p in paths if p]
                    for path in prefixes:
                        out.append(Fact("url_handler", path, "@%sMapping (class)" % verb, number))
                    continue
                for path in paths:
                    for prefix in prefixes or [""]:
                        full = _join_path(prefix, path)
                        if full:
                            detail = "@%sMapping" % verb
                            if prefix:
                                detail += " (method %s)" % (path or '""')
                            out.append(Fact("url_handler", full, detail, number))
            if not class_seen and _CLASS_LINE.match(line):
                class_seen = True
            for args in _WEBSERVLET.findall(line):
                for value in _strings(args):
                    if value.startswith("/") or "*" in value:
                        out.append(Fact("url_handler", value, "@WebServlet", number))
            for value in _JAXRS.findall(line):
                out.append(Fact("url_handler", value, "@Path", number))

        if lang == "xml":
            for name in _TABLE_ATTR.findall(line):
                out.append(Fact("sql_table", name, "mapping (hbm)", number))
            for value in _URL_PATTERN.findall(line):
                out.append(Fact("url_handler", value, "url-pattern", number))
            for match in _ACTION.finditer(line):
                handler = _ACTION_TYPE.search(match.group(0))
                detail = "action %s" % match.group(1)
                if handler:
                    detail += " -> %s" % handler.group(1)
                out.append(Fact("url_handler", match.group(2), detail, number))

        if lang in ("jsp", "html", "javascript", "typescript"):
            for pattern in _URL_REFS:
                for raw in pattern.findall(line):
                    value = _clean_url(raw)
                    if _is_app_url(value):
                        out.append(Fact("url_ref", value, lang, number))

        if lang == "jsp":
            for pattern in _INCLUDES:
                for value in pattern.findall(line):
                    out.append(Fact("include", value, "jsp", number))
            for value in _JSP_IMPORT.findall(line):
                for name in value.split(","):
                    if name.strip():
                        out.append(Fact("jsp_import", name.strip(), "", number))
            for attrs in _TAGLIB.findall(line):
                uri = re.search(r"\b(?:uri|tagdir)\s*=\s*\"([^\"]+)\"", attrs)
                prefix = re.search(r"\bprefix\s*=\s*\"([^\"]+)\"", attrs)
                if uri:
                    out.append(Fact("taglib", uri.group(1), "prefix %s" % prefix.group(1) if prefix else "", number))

        if lang in ("java", "groovy", "kotlin", "xml", "properties", "jsp"):
            for pattern in _QUEUES:
                for value in pattern.findall(line):
                    out.append(Fact("queue", value, "", number))

        if lang == "properties":
            stripped = line.lstrip()
            if stripped and not stripped.startswith(("#", "!")):
                match = _PROPERTY.match(line)
                if match:
                    out.append(Fact("config_key", match.group(1), "defined", number))
        elif lang in ("java", "groovy", "kotlin", "jsp"):
            for pattern in _CONFIG_USES:
                for value in pattern.findall(line):
                    out.append(Fact("config_key", value, "used", number))
    found = []
    if lang in ("java", "groovy", "kotlin"):
        found = jee.java(text)
    elif lang == "xml":
        found = jee.xml(text)
    elif lang == "properties":
        found = jee.properties(text)
    elif lang in ("markdown", "text"):
        found = tables.markdown(text, path)
    elif lang == "csv":
        found = tables.delimited(text, path)
    for fact_type, value, detail, offset, ref in found:
        out.append(Fact(fact_type, value, detail, _line_of(starts, offset), _with_simple_names(ref)))
    return _dedupe(out)


def _with_simple_names(ref):
    """Add cls:<SimpleName> beside every class:<FQN>, so a table naming PermitMDB links to com.x.PermitMDB."""
    keys = ref.split()
    for key in list(keys):
        if key.startswith("class:"):
            simple = "cls:" + key[6:].split(".")[-1]
            if simple not in keys:
                keys.append(simple)
    return " ".join(keys)


def _dedupe(facts_found):
    """Drop exact repeats, and a detail-less fact where a detailed one says the same."""
    detailed = {(f.type, f.value, f.line) for f in facts_found if f.detail}
    seen = set()
    kept = []
    for fact in facts_found:
        key = (fact.type, fact.value, fact.detail, fact.line)
        if key in seen or (not fact.detail and (fact.type, fact.value, fact.line) in detailed):
            continue
        seen.add(key)
        kept.append(fact)
    return kept
