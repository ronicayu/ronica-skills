# evidence-search

Finds and cites evidence in a project's code, requirements, design documents
and configuration, spending as few tokens as the question allows: what a
requirement says, where something is implemented or mentioned, how something
works, what a change would touch, and where documents and code disagree.

It stops at evidence. Judging whether code satisfies a requirement needs the
code's business logic understood first; that is analysis, for the caller or an
analysis skill that uses this plugin to fetch and cite evidence.

Two skills:

- `evidence-search` classifies each question (lookup, enumeration or
  absence), searches in tiers, cross-checks enumerations with grep, and
  records an evidence ledger.
- `setup` builds the optional index that makes the cheap tiers cheaper.

## How it saves tokens

Grep runs locally and costs nothing; its output entering the context does.
The skill searches in tiers and escalates only when a tier is not enough:

1. Repo map: classes, methods and headings.
2. Index pointers: BM25 search and a fact table that return `path:line`, never
   code.
3. Line-range reads of what the pointers name.
4. Bounded grep: counts first, then file lists, then capped lines.

Enumeration and absence questions always get a grep cross-check, because an
index that confidently returns an incomplete list is the failure that hurts a
design review most.

## The index

```sh
"${CLAUDE_PLUGIN_ROOT}/scripts/evs" deps     # optional: tree-sitter in a private venv
"${CLAUDE_PLUGIN_ROOT}/scripts/evs" index    # build, or refresh
"${CLAUDE_PLUGIN_ROOT}/scripts/evs" search reject declaration -k 10
"${CLAUDE_PLUGIN_ROOT}/scripts/evs" facts --type sql_table --match customer
"${CLAUDE_PLUGIN_ROOT}/scripts/evs" similar docs/design.md --heading 'rejection flow'   # related code
"${CLAUDE_PLUGIN_ROOT}/scripts/evs" index --id-pattern 'REQ-\d{3,5}'   # index requirement ids
"${CLAUDE_PLUGIN_ROOT}/scripts/evs" facts --type ref_id --match REQ-112
"${CLAUDE_PLUGIN_ROOT}/scripts/evs" map --types-only --path 'src/main/java/*'
"${CLAUDE_PLUGIN_ROOT}/scripts/evs" excludes # the same exclusions as ripgrep flags
```

| Part | Choice |
| --- | --- |
| Storage | One SQLite file at `.evidence-search/index.db`, listed in `.git/info/exclude` |
| Ranking | SQLite FTS5 `bm25()`, with path, symbol and body weighted 2, 3 and 1 |
| Terms | Identifiers split by case and underscore and also kept whole; English plurals and -ed/-ing endings also stemmed; CJK text as bigrams; no stop words |
| Related chunks | `similar` takes the source range's rarest terms that also occur on the other side (code for a document, documents for code) and ranks chunks by them, listing the shared terms per hit |
| Chunks | tree-sitter: one per Java method or JavaScript function, doc comment included, code between them in its own chunks. Without tree-sitter, and for other languages: 60-line windows overlapping by 10 |
| Facts | SQL tables (read, write or DDL), URL handlers and references, JSP includes, imports and taglibs, queues, config keys, and ids matching the project's own patterns (`ref_id`) |
| Documents | Markdown and AsciiDoc split by heading, each chunk labelled with its heading path; plain text in line windows. Word and PDF are not indexed |
| Freshness | Each query stats every file and re-indexes only those whose size or modification time changed and whose content hash differs |

tree-sitter is error tolerant, so code that does not compile still splits by
method. Without it, Java and JavaScript fall back to line windows labelled by
regex-found symbols; everything else works the same.

### Requirements

- Python 3.10 or later whose SQLite has FTS5 (most builds do). Set
  `EVIDENCE_SEARCH_PYTHON` to pick an interpreter.
- Optional: network access to a Python package index for `evs deps`. The venv
  lives under `~/.cache/evidence-search`; set `EVIDENCE_SEARCH_HOME` to
  move it.
- SQLite 3.43 or later stores no copy of the indexed terms, which keeps the
  index at roughly a third of the size it has on older versions.

### Environment variables

| Variable | Effect |
| --- | --- |
| `EVIDENCE_SEARCH_PYTHON` | Interpreter to run `evs` with |
| `EVIDENCE_SEARCH_HOME` | Where `evs deps` puts its virtual environment |
| `EVIDENCE_SEARCH_ENCODING` | Fallback encoding for files that are not UTF-8 (default `latin-1`), e.g. `gbk` |
| `EVIDENCE_SEARCH_NO_TREESITTER` | `1` turns tree-sitter off |

## Tests

```sh
python3 -m unittest discover -s plugins/evidence-search/tests
```

The tree-sitter tests run only when tree-sitter is importable; run them with
the venv's interpreter after `evs deps`.
