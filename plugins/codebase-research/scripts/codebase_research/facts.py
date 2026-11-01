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
  queue        queue, topic or JMS JNDI name
  config_key   configuration key; detail is defined or used
"""

import re
from dataclasses import dataclass


@dataclass
class Fact:
    type: str
    value: str
    detail: str
    line: int


_LITERAL = re.compile(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'')

_SQL = re.compile(
    r"(?<![<\w/.])(INSERT\s+INTO|DELETE\s+FROM|MERGE\s+INTO|TRUNCATE\s+TABLE|ALTER\s+TABLE|CREATE\s+TABLE|"
    r"DROP\s+TABLE|UPDATE|FROM|JOIN|INTO)\s+([A-Za-z_#][\w.$#]*)", re.IGNORECASE)
_SQL_WORDS = re.compile(r"\b(select|insert|update|delete|from|where|set|values|join|into|merge|order\s+by|group\s+by)\b",
                        re.IGNORECASE)
_SQL_NOT_TABLES = {"select", "where", "set", "values", "the", "a", "an", "table", "if", "exists", "only",
                   "lateral", "unnest", "this", "that", "to", "and", "or", "in", "on", "with"}

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


def _sql_facts(text, number, out):
    for keyword, table in _SQL.findall(text):
        name = table.strip("\"`[]")
        if name.lower() in _SQL_NOT_TABLES or name.isdigit():
            continue
        verb = re.sub(r"\s+", " ", keyword.upper())
        if verb in ("FROM", "JOIN"):
            detail = "read"
        elif verb in ("ALTER TABLE", "CREATE TABLE", "DROP TABLE", "TRUNCATE TABLE"):
            detail = "ddl"
        else:
            detail = "write"
        out.append(Fact("sql_table", name, "%s (%s)" % (detail, verb), number))


def _looks_like_sql(text):
    return len(_SQL_WORDS.findall(text)) >= 2


def extract(lang, text):
    """Facts found in one file's TEXT."""
    out = []
    lines = text.split("\n")
    for number, line in enumerate(lines, 1):
        if lang in ("java", "javascript", "typescript", "jsp", "groovy", "kotlin", "scala"):
            literal_text = " ".join(_strings(line))
            if literal_text and _looks_like_sql(literal_text):
                _sql_facts(literal_text, number, out)
        elif lang in ("sql", "xml"):
            if _looks_like_sql(line) or lang == "sql":
                _sql_facts(line, number, out)

        if lang in ("java", "groovy", "kotlin"):
            for verb, args in _MAPPING.findall(line):
                for value in _strings(args):
                    out.append(Fact("url_handler", value, "@%sMapping" % verb, number))
            for args in _WEBSERVLET.findall(line):
                for value in _strings(args):
                    if value.startswith("/") or "*" in value:
                        out.append(Fact("url_handler", value, "@WebServlet", number))
            for value in _JAXRS.findall(line):
                out.append(Fact("url_handler", value, "@Path", number))

        if lang == "xml":
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
    return out
