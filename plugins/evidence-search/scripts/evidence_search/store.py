"""The SQLite index: build, refresh incrementally, and query.

One file, <root>/.evidence-search/index.db, holds
  files     path, size, mtime, content hash, language, chunker
  chunks    path and line range per chunk, plus its symbol
  chunks_fts  FTS5 over the chunk's path, symbol and body terms (BM25)
  symbols   the repo map: classes, methods, functions, headings
  facts     rows from facts.extract
  meta      schema version, root, exclusions, last refresh

A refresh stats every file and re-reads only those whose size or mtime
changed, then re-indexes only those whose content hash changed.
"""

import hashlib
import json
import os
import sqlite3
import subprocess
import time

from . import chunk, discover, facts, tokens

SCHEMA_VERSION = "1"
INDEX_DIR = ".evidence-search"
# Column weights for bm25(): path terms, symbol terms, body terms.
WEIGHTS = (2.0, 3.0, 1.0)

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS files (
  path TEXT PRIMARY KEY, size INTEGER, mtime_ns INTEGER, sha1 TEXT,
  lang TEXT, kind TEXT, chunker TEXT);
CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY, path TEXT, start INTEGER, end INTEGER,
  symbol TEXT, lang TEXT, kind TEXT);
CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  path_terms, symbol_terms, body_terms, tokenize='unicode61 remove_diacritics 2'%(fts_options)s);
CREATE TABLE IF NOT EXISTS symbols (path TEXT, line INTEGER, kind TEXT, name TEXT, signature TEXT);
CREATE INDEX IF NOT EXISTS symbols_path ON symbols(path);
CREATE TABLE IF NOT EXISTS facts (path TEXT, line INTEGER, type TEXT, value TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS facts_path ON facts(path);
CREATE INDEX IF NOT EXISTS facts_type ON facts(type, value);
"""


# SQLite 3.43 and later can drop the stored copy of the terms and still delete
# rows, which shrinks the index by about two thirds. Older versions keep it.
FTS_OPTIONS = ", content='', contentless_delete=1" if sqlite3.sqlite_version_info >= (3, 43, 0) else ""
SCHEMA = SCHEMA % {"fts_options": FTS_OPTIONS}


class IndexError_(Exception):
    """A problem the user has to fix; the message says how."""


def index_path(root):
    return os.path.join(root, INDEX_DIR, "index.db")


def fts5_available():
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        conn.close()
        return True
    except sqlite3.OperationalError:
        return False


def _decode(data):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        fallback = os.environ.get("EVIDENCE_SEARCH_ENCODING", "latin-1")
        return data.decode(fallback, "replace")


def _git_exclude(root):
    """Keep the index out of git without touching the shared .gitignore."""
    try:
        out = subprocess.run(["git", "-C", root, "rev-parse", "--git-path", "info/exclude"],
                             capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return
    path = out.stdout.strip()
    if not os.path.isabs(path):
        path = os.path.join(root, path)
    entry = INDEX_DIR + "/"
    try:
        existing = open(path).read() if os.path.exists(path) else ""
    except OSError:
        return
    if entry in existing.split("\n"):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        handle.write(entry + "\n")


class Index:
    def __init__(self, root, create=False):
        self.root = root
        self.path = index_path(root)
        if not os.path.exists(self.path) and not create:
            raise IndexError_("no index at %s; run: evs index" % self.path)
        if not fts5_available():
            raise IndexError_("this Python's SQLite has no FTS5; use another Python 3.10+ "
                              "(set EVIDENCE_SEARCH_PYTHON) or rely on rg")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(SCHEMA)
        version = self.meta("schema_version")
        if version not in (None, SCHEMA_VERSION):
            self.conn.close()
            os.remove(self.path)
            self.conn = sqlite3.connect(self.path)
            self.conn.executescript(SCHEMA)
        if create:
            self.set_meta("schema_version", SCHEMA_VERSION)
            self.set_meta("root", root)
            self.conn.commit()
            _git_exclude(root)

    # -- meta ---------------------------------------------------------------

    def meta(self, key):
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key, value):
        self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))

    def id_patterns(self):
        return json.loads(self.meta("id_patterns") or "[]")

    def set_id_patterns(self, patterns):
        """Store ID patterns. Returns True when they changed, so facts need a full rebuild."""
        patterns = sorted(set(patterns))
        facts.compile_id_patterns(patterns)  # raises re.error before anything is stored
        changed = patterns != self.id_patterns()
        self.set_meta("id_patterns", json.dumps(patterns))
        self.conn.commit()
        self.__dict__.pop("_compiled_ids", None)
        return changed

    @property
    def _id_regexes(self):
        if not hasattr(self, "_compiled_ids"):
            self._compiled_ids = facts.compile_id_patterns(self.id_patterns())
        return self._compiled_ids

    def excludes(self):
        return json.loads(self.meta("extra_excludes") or "[]")

    def set_excludes(self, patterns):
        self.set_meta("extra_excludes", json.dumps(sorted(set(patterns))))
        self.conn.commit()

    # -- refresh ------------------------------------------------------------

    def _forget(self, path):
        ids = [r[0] for r in self.conn.execute("SELECT id FROM chunks WHERE path = ?", (path,))]
        for chunk_id in ids:
            self.conn.execute("DELETE FROM chunks_fts WHERE rowid = ?", (chunk_id,))
        self.conn.execute("DELETE FROM chunks WHERE path = ?", (path,))
        self.conn.execute("DELETE FROM symbols WHERE path = ?", (path,))
        self.conn.execute("DELETE FROM facts WHERE path = ?", (path,))
        self.conn.execute("DELETE FROM files WHERE path = ?", (path,))

    def _add(self, path, st, digest, text):
        lang = discover.lang_of(path)
        kind = discover.kind_of(lang)
        split = chunk.split(lang, text)
        lines = text.split("\n")
        path_terms = tokens.as_document(path)
        for piece in split.chunks:
            body = "\n".join(lines[piece.start - 1:piece.end])
            cur = self.conn.execute(
                "INSERT INTO chunks(path, start, end, symbol, lang, kind) VALUES (?, ?, ?, ?, ?, ?)",
                (path, piece.start, piece.end, piece.symbol, lang, kind))
            self.conn.execute(
                "INSERT INTO chunks_fts(rowid, path_terms, symbol_terms, body_terms) VALUES (?, ?, ?, ?)",
                (cur.lastrowid, path_terms, tokens.as_document(piece.symbol), tokens.as_document(body)))
        self.conn.executemany(
            "INSERT INTO symbols(path, line, kind, name, signature) VALUES (?, ?, ?, ?, ?)",
            [(path, s.line, s.kind, s.name, s.signature) for s in split.symbols])
        self.conn.executemany(
            "INSERT INTO facts(path, line, type, value, detail) VALUES (?, ?, ?, ?, ?)",
            [(path, f.line, f.type, f.value, f.detail)
             for f in facts.extract(lang, text, self._id_regexes, kind)])
        self.conn.execute(
            "INSERT OR REPLACE INTO files(path, size, mtime_ns, sha1, lang, kind, chunker) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (path, st.st_size, st.st_mtime_ns, digest, lang, kind, split.chunker))

    def pending(self):
        """(changed or new paths, removed paths) without indexing anything."""
        known = {row[0]: (row[1], row[2]) for row in
                 self.conn.execute("SELECT path, size, mtime_ns FROM files")}
        current = discover.list_files(self.root, self.excludes())
        changed = []
        for path in current:
            try:
                st = os.stat(os.path.join(self.root, path))
            except OSError:
                continue
            if known.get(path) != (st.st_size, st.st_mtime_ns):
                changed.append(path)
        removed = sorted(set(known) - set(current))
        return changed, removed

    def refresh(self, full=False, progress=None):
        """Bring the index up to date. Returns counts of what changed."""
        started = time.time()
        if full:
            for table in ("chunks", "symbols", "facts", "files"):
                self.conn.execute("DELETE FROM %s" % table)
            if FTS_OPTIONS:
                self.conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('delete-all')")
            else:
                self.conn.execute("DELETE FROM chunks_fts")
        known = {row[0]: (row[1], row[2], row[3]) for row in
                 self.conn.execute("SELECT path, size, mtime_ns, sha1 FROM files")}
        current = discover.list_files(self.root, self.excludes())
        stats = {"added": 0, "updated": 0, "removed": 0, "unchanged": 0}
        for count, path in enumerate(current, 1):
            full_path = os.path.join(self.root, path)
            try:
                st = os.stat(full_path)
            except OSError:
                continue
            old = known.get(path)
            if old and (old[0], old[1]) == (st.st_size, st.st_mtime_ns):
                stats["unchanged"] += 1
                continue
            if discover.is_binary(full_path):
                continue
            with open(full_path, "rb") as handle:
                data = handle.read()
            digest = hashlib.sha1(data).hexdigest()
            if old and old[2] == digest:
                self.conn.execute("UPDATE files SET size = ?, mtime_ns = ? WHERE path = ?",
                                  (st.st_size, st.st_mtime_ns, path))
                stats["unchanged"] += 1
                continue
            if old:
                self._forget(path)
            self._add(path, st, digest, _decode(data))
            stats["updated" if old else "added"] += 1
            if count % 500 == 0:
                self.conn.commit()
                if progress:
                    progress(count, len(current))
        for path in sorted(set(known) - set(current)):
            self._forget(path)
            stats["removed"] += 1
        self.set_meta("refreshed_at", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        self.set_meta("head", _git_head(self.root) or "")
        self.conn.commit()
        stats["seconds"] = round(time.time() - started, 2)
        return stats

    # -- queries ------------------------------------------------------------

    def search(self, text, limit=20, kind=None, lang=None, path_glob=None, files_only=False):
        """Best chunks for TEXT as (rows, total hits). Lower bm25 is better."""
        expression = tokens.as_query(text)
        if not expression:
            raise IndexError_("the query has no searchable terms")
        where = ["chunks_fts MATCH ?"]
        args = [expression]
        if kind:
            where.append("c.kind = ?")
            args.append(kind)
        if lang:
            where.append("c.lang = ?")
            args.append(lang)
        if path_glob:
            where.append("c.path GLOB ?")
            args.append(path_glob)
        clause = " AND ".join(where)
        score = "bm25(chunks_fts, %s, %s, %s)" % WEIGHTS
        base = "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid WHERE " + clause
        total = self.conn.execute("SELECT count(*) " + base, args).fetchone()[0]
        if files_only:
            # bm25() cannot feed an aggregate, even through a subquery that SQLite
            # flattens, so group by file here.
            best = {}
            for path, value in self.conn.execute("SELECT c.path, %s AS s %s ORDER BY s" % (score, base), args):
                if path in best:
                    best[path][1] += 1
                else:
                    best[path] = [value, 1]
            ranked = sorted(best.items(), key=lambda item: item[1][0])
            rows = [(path, value, hits) for path, (value, hits) in ranked[:limit]]
            total = len(best)
        else:
            rows = self.conn.execute(
                "SELECT c.path, c.start, c.end, c.lang, c.symbol, %s AS s %s ORDER BY s LIMIT ?" % (score, base),
                args + [limit]).fetchall()
        return rows, total

    def facts(self, fact_type=None, match=None, path_glob=None, limit=100, summary=False):
        where = []
        args = []
        if fact_type:
            where.append("type = ?")
            args.append(fact_type)
        if match:
            where.append("lower(value) LIKE ?")
            args.append("%" + match.lower() + "%")
        if path_glob:
            where.append("path GLOB ?")
            args.append(path_glob)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        if summary:
            total = self.conn.execute(
                "SELECT count(*) FROM (SELECT 1 FROM facts%s GROUP BY type, lower(value), detail)" % clause,
                args).fetchone()[0]
            rows = self.conn.execute(
                "SELECT type, min(value), detail, count(*), count(DISTINCT path) FROM facts%s "
                "GROUP BY type, lower(value), detail ORDER BY type, lower(value), detail LIMIT ?" % clause,
                args + [limit]).fetchall()
            return rows, total
        total = self.conn.execute("SELECT count(*) FROM facts" + clause, args).fetchone()[0]
        rows = self.conn.execute(
            "SELECT path, line, type, value, detail FROM facts%s ORDER BY type, lower(value), path, line LIMIT ?"
            % clause, args + [limit]).fetchall()
        return rows, total

    def symbols(self, path_glob=None, kinds=None, match=None, limit=300):
        where = []
        args = []
        if path_glob:
            where.append("path GLOB ?")
            args.append(path_glob)
        if kinds:
            where.append("kind IN (%s)" % ",".join("?" * len(kinds)))
            args.extend(kinds)
        if match:
            where.append("(lower(name) LIKE ? OR lower(signature) LIKE ?)")
            args.extend(["%" + match.lower() + "%"] * 2)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        total = self.conn.execute("SELECT count(*) FROM symbols" + clause, args).fetchone()[0]
        rows = self.conn.execute(
            "SELECT path, line, kind, name, signature FROM symbols%s ORDER BY path, line LIMIT ?" % clause,
            args + [limit]).fetchall()
        return rows, total

    def counts(self):
        out = {}
        for table in ("files", "chunks", "symbols", "facts"):
            out[table] = self.conn.execute("SELECT count(*) FROM %s" % table).fetchone()[0]
        out["chunkers"] = dict(self.conn.execute("SELECT chunker, count(*) FROM files GROUP BY chunker"))
        return out


def _git_head(root):
    try:
        out = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
