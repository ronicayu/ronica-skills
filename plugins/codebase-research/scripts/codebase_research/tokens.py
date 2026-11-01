"""Turn code and prose into BM25 terms.

FTS5's unicode61 tokenizer splits on anything that is not a letter or digit
and does not split camelCase, so terms are prepared here and stored as a
space-separated string. Queries go through the same function, so a search for
"user by id" meets getUserById, get_user_by_id and USER_BY_ID alike.
"""

import re

# A word in code: letters, digits, `_` and `$`.
_WORD = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*|[0-9]+")
# Boundaries inside an identifier: fooBar, HTTPServer, user2Name.
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[A-Za-z])(?=[0-9])|(?<=[0-9])(?=[A-Za-z])")
# CJK runs. unicode61 would keep a whole run as one term, so runs become bigrams.
_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿぀-ヿ가-힯]+")


def _identifier_terms(word):
    """Terms for one identifier: its parts, then the whole word joined."""
    parts = []
    for piece in re.split(r"[_$]+", word):
        if piece:
            parts.extend(p for p in _CAMEL.split(piece) if p)
    parts = [p.lower() for p in parts]
    joined = "".join(parts)
    terms = [p for p in parts if len(p) > 1 or p.isdigit()]
    if len(parts) > 1 and joined:
        terms.append(joined)
    return terms


def _cjk_terms(run):
    if len(run) == 1:
        return [run]
    return [run[i:i + 2] for i in range(len(run) - 1)]


def terms(text):
    """Every BM25 term in TEXT, in order, duplicates kept (they carry term frequency)."""
    out = []
    for match in _CJK.finditer(text):
        out.extend(_cjk_terms(match.group()))
    for match in _WORD.finditer(_CJK.sub(" ", text)):
        out.extend(_identifier_terms(match.group()))
    return out


def as_document(text):
    """TEXT as the space-separated term string stored in the index."""
    return " ".join(terms(text))


def as_query(text):
    """An FTS5 MATCH expression that ORs the distinct terms of TEXT.

    Returns "" when TEXT has no searchable terms.
    """
    seen = []
    for term in terms(text):
        if term not in seen:
            seen.append(term)
    return " OR ".join('"%s"' % t for t in seen)
