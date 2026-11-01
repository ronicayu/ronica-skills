# codebase-research

Answers questions about a codebase and its documentation with cited
`path:line` evidence, spending as few tokens as the question allows.

Two skills:

- `codebase-research` classifies each question (lookup, enumeration or
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
"${CLAUDE_PLUGIN_ROOT}/scripts/cr" deps     # optional: tree-sitter in a private venv
"${CLAUDE_PLUGIN_ROOT}/scripts/cr" index    # build, or refresh
"${CLAUDE_PLUGIN_ROOT}/scripts/cr" search reject declaration -k 10
"${CLAUDE_PLUGIN_ROOT}/scripts/cr" facts --type sql_table --match customer
"${CLAUDE_PLUGIN_ROOT}/scripts/cr" map --types-only --path 'src/main/java/*'
"${CLAUDE_PLUGIN_ROOT}/scripts/cr" excludes # the same exclusions as ripgrep flags
```

| Part | Choice |
| --- | --- |
| Storage | One SQLite file at `.codebase-research/index.db`, listed in `.git/info/exclude` |
| Ranking | SQLite FTS5 `bm25()`, with path, symbol and body weighted 2, 3 and 1 |
| Terms | Identifiers split by case and underscore and also kept whole; CJK text as bigrams; no stop words |
| Chunks | tree-sitter: one per Java method or JavaScript function, doc comment included, code between them in its own chunks. Without tree-sitter, and for other languages: 60-line windows overlapping by 10. Markdown and AsciiDoc: by heading |
| Facts | SQL tables (read, write or DDL), URL handlers and references, JSP includes, imports and taglibs, queues, config keys |
| Freshness | Each query stats every file and re-indexes only those whose size or modification time changed and whose content hash differs |

tree-sitter is error tolerant, so code that does not compile still splits by
method. Without it, Java and JavaScript fall back to line windows labelled by
regex-found symbols; everything else works the same.

### Requirements

- Python 3.10 or later whose SQLite has FTS5 (most builds do). Set
  `CODEBASE_RESEARCH_PYTHON` to pick an interpreter.
- Optional: network access to a Python package index for `cr deps`. The venv
  lives under `~/.cache/codebase-research`; set `CODEBASE_RESEARCH_HOME` to
  move it.
- SQLite 3.43 or later stores no copy of the indexed terms, which keeps the
  index at roughly a third of the size it has on older versions.

### Environment variables

| Variable | Effect |
| --- | --- |
| `CODEBASE_RESEARCH_PYTHON` | Interpreter to run `cr` with |
| `CODEBASE_RESEARCH_HOME` | Where `cr deps` puts its virtual environment |
| `CODEBASE_RESEARCH_ENCODING` | Fallback encoding for files that are not UTF-8 (default `latin-1`), e.g. `gbk` |
| `CODEBASE_RESEARCH_NO_TREESITTER` | `1` turns tree-sitter off |

## Tests

```sh
python3 -m unittest discover -s plugins/codebase-research/tests
```

The tree-sitter tests run only when tree-sitter is importable; run them with
the venv's interpreter after `cr deps`.
