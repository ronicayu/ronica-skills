---
name: setup
description: Build or rebuild the codebase-research index for this repository — BM25 search, a repo map and a fact table of SQL tables, URLs, includes, queues and config keys — and install tree-sitter for method-level chunking of Java and JavaScript. Use when setting up codebase-research in a project, when `cr` reports "no index", when the user asks to index, re-index or exclude part of the codebase, or when the index looks wrong after a large change.
---

# Set up the codebase-research index

The index is optional: without it, the `codebase-research` skill falls back to
ripgrep. With it, search returns `path:line` pointers instead of grep output,
and enumeration questions start from a fact table.

All commands go through one wrapper. It runs from any directory and finds the
repository root with git:

```sh
"${CLAUDE_PLUGIN_ROOT}/scripts/cr" <command>
```

If it exits 2 with "no Python 3.10 or later found", tell the user to install
Python 3.10 or later, or to set `CODEBASE_RESEARCH_PYTHON` to its path.

## Steps

1. **Check what is there.** Run `cr deps --check` and `cr status`. `status`
   exits 3 when there is no index yet; that is expected on first setup.
2. **Install tree-sitter.** If `deps --check` reports it missing, run
   `cr deps`. It creates a private virtual environment under
   `~/.cache/codebase-research/venv` (override with `CODEBASE_RESEARCH_HOME`)
   and installs the Java and JavaScript grammars there; nothing goes into the
   user's own Python. If pip cannot reach a package index, say so and carry
   on: indexing still works, with line chunks for Java and JavaScript.
3. **Agree the exclusions.** Defaults cover build output, `node_modules`,
   vendored directories and minified files; git-ignored files are skipped too.
   Look at the top-level layout and ask the user about directories that hold
   generated code, copied third-party libraries or archives. Add each with
   `cr index --exclude 'path/**'`; exclusions are remembered.
4. **Build the index.** Run `cr index`. The first build reads every file;
   expect roughly a minute per ten thousand files. Report the summary it
   prints: files by chunker, chunks, symbols and facts.
5. **Check it answers.** Run one search the user would recognise, such as a
   class name from the repo map (`cr map --types-only -k 20`), and one
   `cr facts --summary -k 20`. If facts look sparse for a codebase that
   clearly has SQL or URL mappings, say so: the extraction rules are regular
   expressions and may need a project-specific pattern.
6. **Tell the user how it stays fresh.** Every query re-reads only files whose
   size or modification time changed, so there is no daemon and no hook.
   `cr index --full` rebuilds from scratch. The index lives in
   `.codebase-research/` at the repository root and is listed in
   `.git/info/exclude`, so it is never committed and the shared `.gitignore`
   is untouched.

## Encoding

Files are read as UTF-8. Legacy code in another encoding falls back to
Latin-1, which keeps ASCII identifiers intact but garbles other characters in
comments. For a GBK or Shift-JIS codebase, set `CODEBASE_RESEARCH_ENCODING`
(for example `gbk`) and run `cr index --full`.
