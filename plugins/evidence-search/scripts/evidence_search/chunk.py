"""Split a file into retrieval chunks and list its symbols.

Java and JavaScript are split by tree-sitter into one chunk per method or
function, with the lines between them (fields, imports, class headers) in
their own chunks. tree-sitter is error tolerant, so code that does not compile
still splits; anything it cannot place falls into line chunks. Without
tree-sitter, the same files use overlapping line windows and regex symbols.
Markdown and AsciiDoc split by heading. Everything else uses line windows.
"""

import bisect
import os
import re
from dataclasses import dataclass, field

WINDOW = 60
OVERLAP = 10
MAX_FUNCTION_LINES = 150


@dataclass
class Chunk:
    start: int  # first line, 1-based
    end: int  # last line, inclusive
    symbol: str = ""


@dataclass
class Symbol:
    line: int
    kind: str  # class, interface, enum, method, function, heading ...
    name: str
    signature: str = ""


@dataclass
class Split:
    chunks: list = field(default_factory=list)
    symbols: list = field(default_factory=list)
    chunker: str = "lines"


# ------------------------------------------------------------------ helpers


def _windows(start, end, symbol=""):
    """Overlapping windows covering lines START..END."""
    out = []
    if end < start:
        return out
    step = WINDOW - OVERLAP
    first = start
    part = 1
    total = end - start + 1
    while True:
        last = min(first + WINDOW - 1, end)
        label = symbol
        if symbol and total > WINDOW:
            label = "%s (part %d)" % (symbol, part)
        out.append(Chunk(first, last, label))
        if last >= end:
            return out
        first += step
        part += 1


def _blank(lines, start, end):
    """True when lines START..END hold nothing but whitespace and braces."""
    for line in lines[start - 1:end]:
        if line.strip(" \t{}();,") != "":
            return False
    return True


def _collapse(text, limit=120):
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


# ------------------------------------------------------------- tree-sitter

_PARSERS = {}
_TS_STATE = {"checked": False, "ok": False, "error": ""}


def treesitter_status():
    """(available, reason). Set EVIDENCE_SEARCH_NO_TREESITTER=1 to turn it off."""
    if os.environ.get("EVIDENCE_SEARCH_NO_TREESITTER") == "1":
        return False, "disabled by EVIDENCE_SEARCH_NO_TREESITTER=1"
    if not _TS_STATE["checked"]:
        _TS_STATE["checked"] = True
        try:
            import tree_sitter  # noqa: F401
            import tree_sitter_java  # noqa: F401
            import tree_sitter_javascript  # noqa: F401
            _TS_STATE["ok"] = True
        except ImportError as exc:
            _TS_STATE["error"] = "not installed (%s); run: evs deps" % exc.name
    return _TS_STATE["ok"], _TS_STATE["error"]


def _parser(lang):
    if lang not in _PARSERS:
        import tree_sitter
        if lang == "java":
            import tree_sitter_java as grammar
        else:
            import tree_sitter_javascript as grammar
        _PARSERS[lang] = tree_sitter.Parser(tree_sitter.Language(grammar.language()))
    return _PARSERS[lang]


JAVA_FUNCS = {"method_declaration", "constructor_declaration", "compact_constructor_declaration"}
JAVA_CONTAINERS = {"class_declaration", "interface_declaration", "enum_declaration",
                   "record_declaration", "annotation_type_declaration"}
JS_FUNCS = {"function_declaration", "generator_function_declaration", "method_definition"}
JS_FUNCTION_VALUES = {"function_expression", "function", "arrow_function", "generator_function"}
JS_CONTAINERS = {"class_declaration", "class"}


def _text(node, source):
    return source[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _field_text(node, name, source):
    child = node.child_by_field_name(name)
    return _text(child, source) if child is not None else ""


def _start_with_comment(node):
    """First row of NODE, moved up over a doc comment directly above it."""
    row = node.start_point[0]
    prev = node.prev_named_sibling
    while prev is not None and "comment" in prev.type and prev.end_point[0] >= row - 1:
        row = prev.start_point[0]
        prev = prev.prev_named_sibling
    return row


def _js_function(node, source):
    """(name, params, range node) when NODE defines a named JavaScript function."""
    kind = node.type
    if kind in JS_FUNCS:
        return _field_text(node, "name", source), _field_text(node, "parameters", source), node
    if kind == "variable_declarator":
        value = node.child_by_field_name("value")
        if value is not None and value.type in JS_FUNCTION_VALUES:
            params = _field_text(value, "parameters", source) or _field_text(value, "parameter", source)
            outer = node.parent if node.parent is not None else node
            return _field_text(node, "name", source), params, outer
    if kind == "assignment_expression":
        value = node.child_by_field_name("right")
        if value is not None and value.type in JS_FUNCTION_VALUES:
            outer = node.parent if node.parent is not None and node.parent.type == "expression_statement" else node
            return _field_text(node, "left", source), _field_text(value, "parameters", source), outer
    if kind == "pair":
        value = node.child_by_field_name("value")
        if value is not None and value.type in JS_FUNCTION_VALUES:
            return _field_text(node, "key", source), _field_text(value, "parameters", source), node
    return None


def _split_treesitter(lang, text, lines):
    source = text.encode("utf-8", "surrogatepass")
    tree = _parser(lang).parse(source)
    funcs = []  # (start_row, end_row, symbol)
    containers = []  # (start_row, end_row, name)
    symbols = []

    def visit(node, stack):
        kind = node.type
        if lang == "java" and kind in JAVA_CONTAINERS:
            name = _field_text(node, "name", source)
            symbols.append(Symbol(node.start_point[0] + 1, kind.replace("_declaration", ""), ".".join(stack + [name])))
            containers.append((node.start_point[0], node.end_point[0], ".".join(stack + [name])))
            for child in node.children:
                visit(child, stack + [name])
            return
        if lang == "javascript" and kind in JS_CONTAINERS:
            name = _field_text(node, "name", source) or "<anonymous class>"
            symbols.append(Symbol(node.start_point[0] + 1, "class", ".".join(stack + [name])))
            containers.append((node.start_point[0], node.end_point[0], ".".join(stack + [name])))
            for child in node.children:
                visit(child, stack + [name])
            return
        if lang == "javascript" and kind == "variable_declarator":
            value = node.child_by_field_name("value")
            if value is not None and value.type == "object":
                name = _field_text(node, "name", source)
                for child in value.children:
                    visit(child, stack + [name] if name else stack)
                return
        found = None
        if lang == "java" and kind in JAVA_FUNCS:
            found = (_field_text(node, "name", source), _field_text(node, "parameters", source), node)
        elif lang == "javascript":
            found = _js_function(node, source)
        if found and found[0]:
            name, params, outer = found
            qualified = ".".join(stack + [_collapse(name, 60)])
            signature = _collapse(qualified + params)
            start = _start_with_comment(outer)
            funcs.append((start, outer.end_point[0], signature))
            symbols.append(Symbol(node.start_point[0] + 1,
                                  "method" if stack else "function", qualified, signature))
            return  # nested functions stay inside this chunk
        for child in node.children:
            visit(child, stack)

    visit(tree.root_node, [])

    def container_at(line):
        best = ""
        best_size = None
        for start, end, name in containers:
            if start + 1 <= line <= end + 1 and (best_size is None or end - start < best_size):
                best, best_size = name, end - start
        return best

    return _chunks_from_spans(lines, funcs, container_at), symbols


def _chunks_from_spans(lines, spans, label_at=lambda line: ""):
    """One chunk per span (0-based start and end rows, label), windows for the lines between.

    A span that overlaps one already taken is skipped; one longer than
    MAX_FUNCTION_LINES is split into windows that keep its label.
    """
    chunks = []
    covered = [False] * (len(lines) + 1)
    for start, end, label in sorted(spans):
        first, last = start + 1, end + 1
        while first <= last and covered[first]:
            first += 1  # a doc comment that reaches into the previous chunk
        if first > last or any(covered[first:last + 1]):
            continue
        for i in range(first, last + 1):
            covered[i] = True
        if last - first + 1 > MAX_FUNCTION_LINES:
            chunks.extend(_windows(first, last, label))
        else:
            chunks.append(Chunk(first, last, label))
    line = 1
    while line <= len(lines):
        if covered[line]:
            line += 1
            continue
        gap_start = line
        while line <= len(lines) and not covered[line]:
            line += 1
        gap_end = line - 1
        if not _blank(lines, gap_start, gap_end):
            chunks.extend(_windows(gap_start, gap_end, label_at(gap_start)))
    chunks.sort(key=lambda c: (c.start, c.end))
    return chunks


# ---------------------------------------------------------------------- xml

# Elements worth a chunk of their own: mapper statements, Struts actions, Spring beans.
_XML_ELEMENT = re.compile(
    r"<(select|insert|update|delete|sql|resultMap|statement|procedure|sql-query|named-query|named-native-query|"
    r"action|bean|servlet|filter)\b([^>]*)>", re.I)
_XML_NAME = re.compile(r"\b(id|name|path)\s*=\s*\"([^\"]+)\"")


def _split_xml(text, lines):
    """Chunks per named element, labelled like "select getAccountByUsername"."""
    starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            starts.append(index + 1)

    def row(offset):
        return bisect.bisect_right(starts, offset) - 1

    spans = []
    symbols = []
    for match in _XML_ELEMENT.finditer(text):
        tag = match.group(1)
        named = _XML_NAME.search(match.group(2))
        if not named:
            continue
        label = "%s %s" % (tag, named.group(2))
        first = row(match.start())
        if match.group(0).endswith("/>"):
            last = row(match.end() - 1)
        else:
            close = re.compile(r"</%s\s*>" % re.escape(tag), re.I).search(text, match.end())
            last = row(close.end() - 1) if close else first
        spans.append((first, last, label))
        symbols.append(Symbol(first + 1, tag, named.group(2)))
    return _chunks_from_spans(lines, spans), symbols


# --------------------------------------------------------------- fallbacks

_JAVA_TYPE = re.compile(
    r"^\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:public|protected|private|abstract|final|static|sealed|non-sealed|strictfp)\s+)*"
    r"(class|interface|enum|record|@interface)\s+(\w+)")
_JAVA_METHOD = re.compile(
    r"^\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:public|protected|private|static|final|abstract|synchronized|native|default|strictfp)\s+)*"
    r"(?:<[^>]+>\s+)?(?:[\w.$<>\[\],?]+(?:\s*<[^;{]*>)?(?:\[\])*\s+)?(\w+)\s*\(([^;{]*?)\)?\s*(?:throws\s+[\w.,\s]+)?\s*\{?\s*$")
_NOT_METHODS = {"if", "for", "while", "switch", "catch", "return", "new", "else", "do", "try",
                "synchronized", "throw", "assert", "super", "this"}
_JS_PATTERNS = [
    re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([\w$]+)\s*\(([^)]*)"),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([\w$]+)\s*=\s*(?:async\s+)?(?:function\b[^(]*\(([^)]*)|\(([^)]*)\)\s*=>|([\w$]+)\s*=>)"),
    re.compile(r"^\s*([\w$.]+)\s*=\s*(?:async\s+)?function\s*[\w$]*\s*\(([^)]*)"),
    re.compile(r"^\s*([\w$]+)\s*:\s*(?:async\s+)?function\s*[\w$]*\s*\(([^)]*)"),
]


def _regex_symbols(lang, lines):
    symbols = []
    for number, line in enumerate(lines, 1):
        if lang == "java":
            match = _JAVA_TYPE.match(line)
            if match:
                symbols.append(Symbol(number, match.group(1).lstrip("@"), match.group(2)))
                continue
            stripped = line.strip()
            if stripped.endswith(";") or stripped.startswith(("//", "*", "/*")):
                continue
            match = _JAVA_METHOD.match(line)
            if match and match.group(1) not in _NOT_METHODS and "(" in line:
                name = match.group(1)
                symbols.append(Symbol(number, "method", name, _collapse("%s(%s)" % (name, match.group(2) or ""))))
        else:
            for pattern in _JS_PATTERNS:
                match = pattern.match(line)
                if match:
                    params = next((g for g in match.groups()[1:] if g is not None), "")
                    name = match.group(1)
                    symbols.append(Symbol(number, "function", name, _collapse("%s(%s)" % (name, params))))
                    break
    return symbols


def _label_windows(chunks, symbols):
    """Name each line window after the symbols declared in it, or the one above it."""
    for chunk in chunks:
        inside = [s for s in symbols if chunk.start <= s.line <= chunk.end]
        if inside:
            chunk.symbol = _collapse(", ".join((s.signature or s.name) for s in inside[:3]))
        else:
            before = [s for s in symbols if s.line < chunk.start]
            chunk.symbol = (before[-1].signature or before[-1].name) if before else ""
    return chunks


_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_ADOC_HEADING = re.compile(r"^(={1,6})\s+(.+?)\s*$")


def _split_headings(lang, lines):
    pattern = _MD_HEADING if lang == "markdown" else _ADOC_HEADING
    heads = []  # (line, level, title)
    fenced = False
    for number, line in enumerate(lines, 1):
        if line.lstrip().startswith(("```", "~~~", "----")):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = pattern.match(line)
        if match:
            heads.append((number, len(match.group(1)), match.group(2).strip()))
    symbols = []
    chunks = []
    path = []
    bounds = [h[0] for h in heads] + [len(lines) + 1]
    if not heads or heads[0][0] > 1:
        first_end = (heads[0][0] - 1) if heads else len(lines)
        if not _blank(lines, 1, first_end):
            chunks.extend(_windows(1, first_end))
    for i, (number, level, title) in enumerate(heads):
        path = [p for p in path if p[0] < level] + [(level, title)]
        label = " > ".join(t for _, t in path)
        symbols.append(Symbol(number, "heading", label))
        chunks.extend(_windows(number, bounds[i + 1] - 1, label))
    return chunks, symbols


# -------------------------------------------------------------------- main


def split(lang, text):
    """Chunks and symbols for one file's TEXT."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines:
        return Split()
    if lang in ("java", "javascript"):
        available, _ = treesitter_status()
        if available:
            try:
                chunks, symbols = _split_treesitter(lang, text, lines)
                return Split(chunks, symbols, "tree-sitter")
            except Exception:  # a grammar failure must not stop indexing
                pass
        symbols = _regex_symbols(lang, lines)
        return Split(_label_windows(_windows(1, len(lines)), symbols), symbols, "lines")
    if lang in ("markdown", "asciidoc"):
        chunks, symbols = _split_headings(lang, lines)
        return Split(chunks, symbols, "headings")
    if lang == "xml":
        chunks, symbols = _split_xml(text, lines)
        return Split(chunks, symbols, "elements" if symbols else "lines")
    if lang in ("jsp", "html"):
        symbols = _regex_symbols("javascript", lines)
        return Split(_label_windows(_windows(1, len(lines)), symbols), symbols, "lines")
    return Split(_windows(1, len(lines)), [], "lines")
