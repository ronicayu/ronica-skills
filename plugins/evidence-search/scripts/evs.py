#!/usr/bin/env python3
"""evs: build and query a evidence-search index.

Every query returns pointers (path:line and a symbol), never chunk bodies:
read the lines you need afterwards. Queries refresh the index first, re-reading
only files whose size or modification time changed.

Commands
  deps      install tree-sitter into a private virtual environment
  index     build or refresh the index
  status    what is indexed, and what is out of date
  search    BM25 search; prints path:start-end, language and symbol
  facts     entry points, queues, SQL tables, URLs, includes, config keys and ids
  map       the repo map: classes, methods, functions and headings
  similar   chunks sharing distinctive terms with a file range (more like this)
  excludes  the index's exclusions as ripgrep -g flags

Exit codes: 0 ok, 2 usage or environment problem, 3 no index yet.
"""

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from evidence_search import chunk, discover, store, tokens  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def home_dir():
    if os.environ.get("EVIDENCE_SEARCH_HOME"):
        return os.environ["EVIDENCE_SEARCH_HOME"]
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(cache, "evidence-search")


def venv_python():
    return os.path.join(home_dir(), "venv", "bin", "python")


def note(message):
    print("# " + message)


def open_index(args, create=False):
    root = discover.find_root(args.root)
    try:
        return store.Index(root, create=create)
    except store.IndexError_ as exc:
        code = 3 if "no index" in str(exc) else 2
        print("evs: %s" % exc, file=sys.stderr)
        sys.exit(code)


def maybe_refresh(index, args):
    if getattr(args, "no_refresh", False):
        return
    stats = index.refresh()
    changed = stats["added"] + stats["updated"] + stats["removed"]
    if changed:
        note("refreshed %d file(s) first: %d added, %d updated, %d removed"
             % (changed, stats["added"], stats["updated"], stats["removed"]))


def more(shown, total, hint):
    if total > shown:
        note("%d more not shown; %s" % (total - shown, hint))


# ---------------------------------------------------------------- commands


def cmd_deps(args):
    python = venv_python()
    if args.check:
        available, reason = chunk.treesitter_status()
        print("interpreter: %s" % sys.executable)
        print("tree-sitter: %s" % ("available" if available else reason))
        print("private venv: %s" % (python if os.path.exists(python) else "not created"))
        return 0
    if not os.path.exists(python):
        note("creating %s" % os.path.dirname(os.path.dirname(python)))
        subprocess.run([sys.executable, "-m", "venv", os.path.dirname(os.path.dirname(python))], check=True)
    note("installing tree-sitter grammars for Java and JavaScript")
    result = subprocess.run([python, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                             "-r", os.path.join(HERE, "requirements.txt")])
    if result.returncode != 0:
        print("evs: pip install failed; indexing still works, with line chunks for Java and JavaScript",
              file=sys.stderr)
        return 2
    check = subprocess.run([python, "-c", "import tree_sitter, tree_sitter_java, tree_sitter_javascript"])
    if check.returncode != 0:
        print("evs: installed, but tree-sitter does not import", file=sys.stderr)
        return 2
    print("tree-sitter ready in %s; evs uses this interpreter from now on" % python)
    return 0


def cmd_index(args):
    index = open_index(args, create=True)
    if args.exclude:
        index.set_excludes(index.excludes() + args.exclude)
    full = args.full
    if args.id_pattern:
        try:
            if index.set_id_patterns(index.id_patterns() + args.id_pattern):
                full = True  # every file needs its ref_id facts extracted again
        except re.error as exc:
            print("evs: invalid --id-pattern: %s" % exc, file=sys.stderr)
            return 2
    available, reason = chunk.treesitter_status()
    if not available and not args.quiet:
        note("tree-sitter %s; Java and JavaScript get line chunks" % reason)

    def progress(done, total):
        if not args.quiet:
            note("%d/%d files" % (done, total))

    stats = index.refresh(full=full, progress=progress)
    counts = index.counts()
    print("index: %s" % index.path)
    print("files: %d (%s)" % (counts["files"], ", ".join("%s %d" % kv for kv in sorted(counts["chunkers"].items()))))
    print("chunks: %d  symbols: %d  facts: %d" % (counts["chunks"], counts["symbols"], counts["facts"]))
    print("this run: %d added, %d updated, %d removed, %d unchanged in %ss"
          % (stats["added"], stats["updated"], stats["removed"], stats["unchanged"], stats["seconds"]))
    return 0


def cmd_status(args):
    index = open_index(args)
    counts = index.counts()
    changed, removed = index.pending()
    available, reason = chunk.treesitter_status()
    if index.upgraded:
        note("the index format changed in this version; the next query or `evs index` rebuilds it")
    print("root: %s" % index.root)
    print("index: %s" % index.path)
    print("refreshed: %s at commit %s" % (index.meta("refreshed_at"), index.meta("head") or "-"))
    print("files: %d (%s)" % (counts["files"], ", ".join("%s %d" % kv for kv in sorted(counts["chunkers"].items()))))
    print("chunks: %d  symbols: %d  facts: %d" % (counts["chunks"], counts["symbols"], counts["facts"]))
    print("out of date: %d changed or new, %d removed (queries refresh these first)" % (len(changed), len(removed)))
    print("tree-sitter: %s" % ("available" if available else reason))
    if index.excludes():
        print("extra excludes: %s" % ", ".join(index.excludes()))
    if index.id_patterns():
        print("id patterns: %s" % ", ".join(index.id_patterns()))
    return 0


def cmd_search(args):
    index = open_index(args)
    maybe_refresh(index, args)
    query = " ".join(args.query)
    try:
        rows, total = index.search(query, limit=args.k, kind=args.kind, lang=args.lang,
                                   path_glob=args.path, files_only=args.files)
    except store.IndexError_ as exc:
        print("evs: %s" % exc, file=sys.stderr)
        return 2
    if args.json:
        keys = ("path", "best_score", "chunks") if args.files else ("path", "start", "end", "lang", "symbol", "score")
        print(json.dumps([dict(zip(keys, (r[0], -r[1], r[2]) if args.files else r[:5] + (-r[5],))) for r in rows],
                         ensure_ascii=False))
        return 0
    if args.files:
        note("%d matching file(s); best %d" % (total, len(rows)))
        for path, score, hits in rows:
            print("%s  %d chunk(s)  %.2f" % (path, hits, -score))
        more(len(rows), total, "raise -k, or narrow with --path, --kind or --lang")
        return 0
    note("%d hit(s); best %d" % (total, len(rows)))
    for path, start, end, lang, symbol, score in rows:
        print("%s:%d-%d  %s  %s  %.2f" % (path, start, end, lang, symbol or "-", -score))
    more(len(rows), total, "raise -k, or narrow with --path, --kind or --lang")
    return 0


def parse_source(text):
    """PATH, PATH:LINE or PATH:START-END."""
    match = re.match(r"^(.*?):(\d+)(?:-(\d+))?$", text)
    if match:
        start = int(match.group(2))
        return match.group(1), start, int(match.group(3) or start)
    return text, None, None


def cmd_similar(args):
    index = open_index(args)
    maybe_refresh(index, args)
    path, start, end = parse_source(args.source)
    path = path[2:] if path.startswith("./") else path
    try:
        start, end, label, kind = index.section(path, start, end, args.heading)
        text = index.read_lines(path, start, end)
    except (store.IndexError_, OSError) as exc:
        print("evs: %s" % exc, file=sys.stderr)
        return 2
    targets = args.to or (["code", "config"] if kind == "docs" else ["docs"])
    picked = index.distinctive_terms(text, limit=args.terms, kinds=targets, exclude_path=path)
    also = " ".join(args.also)
    query = " ".join(term for term, _ in picked) + " " + also
    if not query.strip():
        print("evs: no distinctive terms in %s:%d-%d; pass likely code terms with --also" % (path, start, end),
              file=sys.stderr)
        return 2
    rows, total = index.search(query, limit=args.k, kind=targets, path_glob=args.path, exclude_path=path)
    wanted = set(tokens.terms(query))
    results = []
    for hit_path, hit_start, hit_end, lang, symbol, score in rows:
        try:
            found = set(tokens.terms(index.read_lines(hit_path, hit_start, hit_end)))
        except OSError:
            found = set()
        matched = [t for t in tokens.terms(query) if t in found and t in wanted]
        results.append((hit_path, hit_start, hit_end, lang, symbol, -score, list(dict.fromkeys(matched))))
    if args.json:
        print(json.dumps({
            "source": {"path": path, "start": start, "end": end, "label": label, "kind": kind},
            "terms": [{"term": t, "idf": round(i, 2)} for t, i in picked], "also": args.also,
            "targets": targets,
            "candidates": [dict(zip(("path", "start", "end", "lang", "symbol", "score", "matched"), r))
                           for r in results]}, ensure_ascii=False))
        return 0
    note("source: %s:%d-%d%s (%s)" % (path, start, end, "  " + label if label else "", kind))
    note("terms: %s%s" % (", ".join(t for t, _ in picked) or "-", ("  also: " + also) if also else ""))
    note("%d chunk(s) in %s share terms with it; best %d. Shared terms show relatedness, not that one "
         "implements the other" % (total, "/".join(targets), len(results)))
    for hit_path, hit_start, hit_end, lang, symbol, score, matched in results:
        print("%s:%d-%d  %s  %s  %.2f  matched: %s" % (hit_path, hit_start, hit_end, lang, symbol or "-",
                                                      score, ", ".join(matched[:8]) or "-"))
    more(len(results), total, "raise -k, narrow with --path, or sharpen the terms with --also")
    return 0


def cmd_facts(args):
    index = open_index(args)
    maybe_refresh(index, args)
    rows, total = index.facts(args.type, args.match, args.path, args.k, args.summary)
    if args.summary:
        if args.json:
            keys = ("type", "value", "detail", "count", "files")
            print(json.dumps([dict(zip(keys, r)) for r in rows], ensure_ascii=False))
            return 0
        for fact_type, value, detail, count, files in rows:
            print("%s  %s  %s  x%d in %d file(s)" % (fact_type, value, detail or "-", count, files))
    else:
        shown = {tuple(r[:4]) for r in rows}
        records = []
        for row in rows:
            links = [] if args.no_links or not row[5] else index.linked(row[5], exclude=shown, limit=args.links)
            records.append((row, links))
        if args.json:
            keys = ("path", "line", "type", "value", "detail")
            print(json.dumps([dict(zip(keys, row[:5]), linked=[dict(zip(keys, link[:5])) for link in links])
                              for row, links in records], ensure_ascii=False))
            return 0
        for row, links in records:
            path, line, fact_type, value, detail = row[:5]
            print("%s:%d  %s  %s  %s" % (path, line, fact_type, value, detail or "-"))
            for link in links:
                print("    -> %s:%d  %s  %s  %s" % (link[0], link[1], link[2], link[3], link[4] or "-"))
    if not rows:
        note("no facts match; facts are best effort, so confirm with grep")
    more(len(rows), total, "raise -k, or narrow with --type, --match or --path")
    return 0


def cmd_map(args):
    index = open_index(args)
    maybe_refresh(index, args)
    kinds = ["class", "interface", "enum", "record", "annotation_type", "heading"] if args.types_only else None
    rows, total = index.symbols(args.path, kinds, args.match, args.k)
    if args.json:
        print(json.dumps([dict(zip(("path", "line", "kind", "name", "signature"), r)) for r in rows],
                         ensure_ascii=False))
        return 0
    current = None
    for path, line, kind, name, signature in rows:
        if path != current:
            print(path)
            current = path
        print("  L%d %s %s" % (line, kind, signature or name))
    more(len(rows), total, "raise -k, or narrow with --path, --match or --types-only")
    return 0


def cmd_excludes(args):
    root = discover.find_root(args.root)
    extra = []
    if os.path.exists(store.index_path(root)):
        extra = store.Index(root).excludes()
    print(discover.rg_flags(extra))
    return 0


# -------------------------------------------------------------------- main


def build_parser():
    parser = argparse.ArgumentParser(prog="evs", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, func, help_text):
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.set_defaults(func=func)
        p.add_argument("--root", default=".", help="repository root (default: git top level of the cwd)")
        return p

    p = add("deps", cmd_deps, "install tree-sitter into a private virtual environment")
    p.add_argument("--check", action="store_true", help="report what is installed; change nothing")

    p = add("index", cmd_index, "build the index, or refresh it incrementally")
    p.add_argument("--full", action="store_true", help="re-index every file")
    p.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                   help="add an exclusion, kept for later runs (repeatable), e.g. 'legacy/lib/**'")
    p.add_argument("--id-pattern", action="append", default=[], metavar="REGEX",
                   help="extract matches as ref_id facts, kept for later runs (repeatable), "
                        r"e.g. 'REQ-\d+'; a capture group, if present, is the value")
    p.add_argument("--quiet", action="store_true")

    add("status", cmd_status, "what is indexed and what is out of date")

    p = add("search", cmd_search, "BM25 search; prints pointers, not code")
    p.add_argument("query", nargs="+")
    p.add_argument("-k", type=int, default=20, help="results to show (default 20)")
    p.add_argument("--kind", choices=("code", "docs", "config"))
    p.add_argument("--lang", help="java, javascript, jsp, markdown, xml ...")
    p.add_argument("--path", help="path glob, e.g. 'src/main/**' (* also matches /)")
    p.add_argument("--files", action="store_true", help="one line per file: the candidate file set")
    p.add_argument("--no-refresh", action="store_true")
    p.add_argument("--json", action="store_true")

    p = add("facts", cmd_facts, "static facts for enumeration questions")
    p.add_argument("--type", choices=("entry_point", "queue", "component", "sql_table", "url_handler", "url_ref", "include",
                                      "jsp_import", "taglib", "config_key", "ref_id"))
    p.add_argument("--match", help="case-insensitive substring of the value, detail or link keys, "
                                   "e.g. a class, a queue, 'mdb' or 'scheduled'")
    p.add_argument("--no-links", action="store_true",
                   help="do not list the facts linked to each row (same EJB, class, JNDI name or MQ queue)")
    p.add_argument("--links", type=int, default=6, help="linked facts to list per row (default 6)")
    p.add_argument("--path", help="path glob")
    p.add_argument("--summary", action="store_true", help="one line per distinct value, with counts")
    p.add_argument("-k", type=int, default=100, help="rows to show (default 100)")
    p.add_argument("--no-refresh", action="store_true")
    p.add_argument("--json", action="store_true")

    p = add("map", cmd_map, "repo map: classes, methods, functions and headings")
    p.add_argument("--path", help="path glob, e.g. 'src/main/java/com/acme/billing/*'")
    p.add_argument("--match", help="case-insensitive substring of the name or signature")
    p.add_argument("--types-only", action="store_true", help="classes, interfaces, enums and headings only")
    p.add_argument("-k", type=int, default=300, help="symbols to show (default 300)")
    p.add_argument("--no-refresh", action="store_true")
    p.add_argument("--json", action="store_true")

    p = add("similar", cmd_similar,
            "chunks that share distinctive terms with a file range (more like this): related code for a "
            "document section, or related documents for code")
    p.add_argument("source", help="PATH, PATH:LINE or PATH:START-END")
    p.add_argument("--heading", help="for a document: the section whose heading path contains this text")
    p.add_argument("--also", action="append", default=[], metavar="TERMS",
                   help="extra terms to search with: likely identifiers, synonyms, or translations when "
                        "the documents and the code use different languages (repeatable)")
    p.add_argument("--to", action="append", choices=("code", "docs", "config"),
                   help="kinds to search (default: code and config from docs, docs from anything else)")
    p.add_argument("--terms", type=int, default=12, help="distinctive terms to take from the source (default 12)")
    p.add_argument("--path", help="path glob for candidates")
    p.add_argument("-k", type=int, default=15, help="candidates to show (default 15)")
    p.add_argument("--no-refresh", action="store_true")
    p.add_argument("--json", action="store_true")

    add("excludes", cmd_excludes, "print the exclusions as ripgrep -g flags")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
