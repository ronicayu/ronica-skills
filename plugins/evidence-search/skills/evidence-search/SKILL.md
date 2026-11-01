---
name: evidence-search
description: Answer questions from a project's code, requirements, design documents and configuration with cited path:line evidence at low token cost — tiered search (repo map, index pointers, line-range reads, bounded grep), mandatory grep cross-checks for enumeration and absence questions, and an evidence ledger. Use when asked what a requirement or design document says, whether and where the code implements it, how something works, what calls, reads, writes or depends on X, what a change would affect, whether the system does Y at all, or where documents and code disagree; and to gather evidence for a design review, migration plan or system design. Works on large or legacy codebases, including code that does not compile. Not for writing or changing code or documents.
---

# Evidence Search

Find evidence a reviewer can check — in code, requirements, design documents and configuration —
spending as few tokens as the question allows. Two rules carry
the skill: search cheap first and escalate only when that is not enough, and let the question type —
not the search results — decide whether a grep cross-check is mandatory.

Grep itself is free: it runs locally. What costs tokens is its output entering the context, whole
files being read, and search loops run on an expensive model. Control those, not the use of grep.

## 1. Classify the question yourself

| Type | Example | Grep's role |
| --- | --- | --- |
| Lookup | How is this validation implemented? What does the design say about retries? | Fallback when confidence is low |
| Enumeration | Which pages submit to this controller? Which code implements REQ-112? What would changing this table affect? | Mandatory cross-check |
| Absence | Does the system retry anywhere? Is REQ-207 implemented at all? | Mandatory exhaustive search |

Misclassification costs are lopsided. Calling a lookup an enumeration costs one extra `rg -l`.
Calling an enumeration a lookup skips the check and silently drops items. So:

1. **Keyword pre-check.** "which, all, list, every, impact, affect, callers, depends, uses" leans
   enumeration; "is there, does it, whether, any … at all" leans absence. Apply the same reading to
   the question in any language.
2. **Your judgement.** Read for intent and catch hidden enumerations: impact analysis, migration
   scope, dependency mapping, requirement-to-code tracing.
3. **Take the stricter of the two.** Absence > enumeration > lookup. A type the user states wins.
4. **Delegated work can only escalate.** When you hand the search to a subagent, state the type and
   why. The subagent may raise lookup to enumeration (for example, hits spread across many files) and
   must say why; it may never lower the type.

Do not hand classification to a cheaper model: it saves almost nothing and risks the costly
direction of error.

## 2. Search in tiers; escalate only when a tier is not enough

The plugin ships an index tool, `evs`, used through
`"${CLAUDE_PLUGIN_ROOT}/scripts/evs"`. Every `evs` query returns pointers —
`path:start-end`, language, symbol — never code, and re-reads changed files
first, so its answers match the working tree. If `evs status` exits 3 there is
no index: carry on with `rg` and mention once that the `setup` skill builds one.
Documents kept in another folder or repository have their own index; query it
with `--root <folder>`.

1. **Repo map.** `evs map --types-only --path 'src/main/java/com/acme/billing/*'`
   lists classes; drop `--types-only` for methods and signatures. Use it to
   narrow scope before searching.
2. **Index pointers.** `evs search <words> -k 10` ranks chunks by BM25 across
   code, docs and config; narrow with `--kind code|docs|config`, `--lang`,
   `--path`. Identifiers match by part, so `user by id` finds `getUserById`.
   For documents, `--kind docs` returns sections labelled by their heading
   path. `evs facts` answers "which tables, URLs, includes, queues, config
   keys, requirement ids" directly; see section 4. Without an index, use
   `rg -l` and `rg -c` here.
3. **Line-range reads.** Read only the ranges the pointers name, widening a
   little when the context demands it. Never read a whole large file to find
   one function.
4. **Bounded grep.** See section 3.

Escalate from tier 3 to tier 4 when an exact identifier gets no hits, when
search methods disagree, when the best hit is weak or nothing stands out, or
when the question type makes it mandatory. When the question contains an exact
string — an identifier, error code or quoted literal — start with a grep count
straight away.

## 3. Bounded grep

Count first, then narrow, then look at lines. `evs excludes` prints the index's
exclusions as ripgrep flags; use exactly those, so grep and the index search
the same files. Without an index, use the defaults below and adjust them to
the ecosystem: vendored libraries, generated code, build output.

```bash
# 1) Count per file, busiest first
rg -c -S -g '!**/target/**' -g '!**/build/**' -g '!**/dist/**' -g '!**/node_modules/**' -g '!*.min.js' 'pattern' \
  | sort -t: -k2,2nr | head -20

# 2) File list only — the enumeration cross-check uses this
rg -l -S -g '!**/target/**' -g '!**/build/**' -g '!**/dist/**' -g '!**/node_modules/**' -g '!*.min.js' 'pattern'

# 3) Lines, only after narrowing scope: cap hits per file, truncate long lines
rg -n -S --max-count 5 --max-columns 200 --max-columns-preview \
  -g '!**/target/**' -g '!**/build/**' -g '!**/dist/**' -g '!**/node_modules/**' -g '!*.min.js' 'pattern' path/to/scope
```

- `-F` for literals, `-w` for whole words.
- A large count means narrow the pattern or the scope. Do not dump the lines.

## 4. Mandatory checks for enumeration and absence

**Enumeration.** List candidates from the fact table (`evs facts --type sql_table --match customer`,
`--summary` for one line per value) or from `evs search <words> --files`. Then run `rg -l` with the
patterns that define the set. Files grep finds that the candidates miss are a recall gap: read
their lines, then add them to the evidence. Name the gap in the answer, because it points at a
fact rule or tokenizer rule the index lacks, or at an excluded file.

Fact types: `sql_table` (detail read, write or ddl), `url_handler`, `url_ref`, `include`,
`jsp_import`, `taglib`, `queue`, `config_key` (defined or used), and `ref_id` — identifiers that
match the project's own patterns, such as requirement or use-case ids, wherever they appear (detail
docs, code or config). They come from regular expressions, so string-built SQL and runtime
configuration escape them.

**Tracing requirements to code.** `evs facts --type ref_id --match REQ-112` lists every document
section and code line that names the id. Code that implements a requirement without citing its id
is the usual gap: search the requirement's key terms with `evs search` too, and grep for the
identifiers it names (fields, screens, error codes). Report which links rest on a cited id and
which on matching terms; the second kind is inferred, not observed.

**Absence.** Search several spellings: class and method names, annotations, configuration keys,
SQL keywords, XML or YAML configuration. Write the conclusion as "not found in the searched scope",
followed by the patterns and paths searched — never "does not exist".

Static search misses behaviour that is wired at runtime: reflection, dependency injection configured
in XML or YAML, string-built SQL or class names, dynamic includes and dispatch. Search configuration
files separately, and list these mechanisms as possible blind spots in the answer.

## 5. Evidence ledger

Record each piece of evidence as:

| Field | Content |
| --- | --- |
| claim | The point it supports |
| location | `path:start-end` |
| snippet | The few lines that matter |
| source | code, docs or config |
| found_by | Tool plus the query or pattern |
| kind | observed (checkable at that location) or inferred (a judgement built on observations) |
| verified | Whether the cited range was re-read |

Re-read every cited range before you rely on it and confirm it supports the claim. Search snippets
get truncated and lose context.

Code shows current behaviour; documentation shows intent or history. When they conflict, show both
side by side with the document's version or date. Do not silently pick one. Cite a document by
`path:start-end` plus its heading path, so the reader can find the section in a rendered view.

## 6. Save tokens

- If you can start a subagent, run the search loop there, on a cheaper model where available. Ask it
  to return the evidence ledger only, not file contents. Its brief states the question type, the
  reason, and that it may escalate the type but never lower it.
- Reuse evidence already verified in the session instead of searching again.

## 7. Answer format

1. Conclusion, in one or two sentences.
2. Question type and why; if escalated, what triggered it.
3. Evidence table: `claim | path:line | code or docs | observed or inferred`.
4. Search scope: queries and grep patterns used, directories excluded.
5. Gaps and uncertainty: where reflection, configuration or dynamic behaviour could hide something.

## References

- `${CLAUDE_PLUGIN_ROOT}/scripts/evs --help` — every `evs` command and flag.
- `references/language-notes.md` — read when the project includes Java, JSP or JavaScript, or when
  you need identifier-aware search patterns, chunking hints or the facts extracted from a legacy web
  application.
