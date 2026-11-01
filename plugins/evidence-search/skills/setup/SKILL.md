---
name: setup
description: Build or rebuild the evidence-search index for this repository — BM25 search over code, requirements, design documents and configuration, a repo map, and a fact table of SQL tables, URLs, includes, queues, config keys and requirement ids — and install tree-sitter for method-level chunking of Java and JavaScript. Use when setting up evidence-search in a project, when `evs` reports "no index", when the user asks to index, re-index or exclude part of the repository or to index requirement ids, or when the index looks wrong after a large change.
---

# Set up the evidence-search index

The index is optional: without it, the `evidence-search` skill falls back to
ripgrep. With it, search returns `path:line` pointers instead of grep output,
and enumeration questions start from a fact table. It covers code, Markdown,
AsciiDoc and text documents, and configuration files in the repository.

All commands go through one wrapper. It runs from any directory and finds the
repository root with git:

```sh
"${CLAUDE_PLUGIN_ROOT}/scripts/evs" <command>
```

If it exits 2 with "no Python 3.10 or later found", tell the user to install
Python 3.10 or later, or to set `EVIDENCE_SEARCH_PYTHON` to its path.

## Steps

1. **Check what is there.** Run `evs deps --check` and `evs status`. `status`
   exits 3 when there is no index yet; that is expected on first setup.
2. **Install tree-sitter.** If `deps --check` reports it missing, run
   `evs deps`. It creates a private virtual environment under
   `~/.cache/evidence-search/venv` (override with `EVIDENCE_SEARCH_HOME`)
   and installs the Java and JavaScript grammars there; nothing goes into the
   user's own Python. If pip cannot reach a package index, say so and carry
   on: indexing still works, with line chunks for Java and JavaScript.
3. **Agree the exclusions.** Defaults cover build output, `node_modules`,
   vendored directories and minified files; git-ignored files are skipped too.
   Look at the top-level layout and ask the user about directories that hold
   generated code, copied third-party libraries or archives. Add each with
   `evs index --exclude 'path/**'`; exclusions are remembered. If the
   requirements or design documents live outside this repository, ask where,
   index that folder too with `evs index --root <folder>`, and tell the user
   that queries on it take the same `--root`.
4. **Ask for the project's id formats.** Ask whether requirements, use cases,
   user stories or tickets carry ids the documents and code cite, and what
   they look like. Turn each answer into a regular expression and confirm it
   with the user before adding it, for example
   `evs index --id-pattern 'REQ-\d{3,5}' --id-pattern 'UC-[A-Z]{2,4}-\d+'`.
   Keep each pattern specific: a loose one such as `[A-Z]+-\d+` also matches
   `UTF-8` and `SHA-1`. Patterns are remembered, and adding one re-extracts
   facts for every file. Skip this step if the user has no such ids.
5. **Ask where queue bindings live.** If the WebLogic descriptors
   (`ejb-jar.xml`, `weblogic-ejb-jar.xml`, JMS modules) are not in the
   repository, ask where the binding between listeners, JNDI names and MQ
   queues is recorded. Markdown tables and CSV files are read automatically
   when their header names a listener column (MDB, listener, receiver,
   consumer) and a JNDI or queue column; if the record lives outside the
   repository, index its folder with `--root` as for other documents. A
   binding written as prose is not extracted; say so.
6. **Build the index.** Run `evs index`. The first build reads every file;
   expect roughly a minute per ten thousand files. Report the summary it
   prints: files by chunker, chunks, symbols and facts.
7. **Check it answers.** Run one search the user would recognise, such as a
   class name from the repo map (`evs map --types-only -k 20`), and one
   `evs facts --summary -k 20`, and `evs facts --type entry_point --match mdb`
   to confirm that listeners show their queues under `->`. If facts look
   sparse for a project that
   clearly has SQL or URL mappings, say so: the extraction rules are regular
   expressions and may need a project-specific pattern.
8. **Tell the user how it stays fresh.** Every query re-reads only files whose
   size or modification time changed, so there is no daemon and no hook.
   `evs index --full` rebuilds from scratch. The index lives in
   `.evidence-search/` at the repository root and is listed in
   `.git/info/exclude`, so it is never committed and the shared `.gitignore`
   is untouched.

## Encoding

Files are read as UTF-8. Legacy code in another encoding falls back to
Latin-1, which keeps ASCII identifiers intact but garbles other characters in
comments. For a GBK or Shift-JIS repository, set `EVIDENCE_SEARCH_ENCODING`
(for example `gbk`) and run `evs index --full`.
