---
name: codebase-research
description: Answer questions about a codebase and its documentation with cited evidence at low token cost — tiered search (repo map, index pointers, line-range reads, bounded grep), mandatory grep cross-checks for enumeration and absence questions, and an evidence ledger of path:line citations. Use when asked how something works or where it is implemented, what calls, reads, writes or depends on X, what a change would affect, whether the system does Y at all, or to gather evidence for a design review, migration plan or system design. Especially useful in large or legacy codebases, including code that does not compile. Not for writing or changing code.
---

# Codebase Research

Find evidence a reviewer can check, spending as few tokens as the question allows. Two rules carry
the skill: search cheap first and escalate only when that is not enough, and let the question type —
not the search results — decide whether a grep cross-check is mandatory.

Grep itself is free: it runs locally. What costs tokens is its output entering the context, whole
files being read, and search loops run on an expensive model. Control those, not the use of grep.

## 1. Classify the question yourself

| Type | Example | Grep's role |
| --- | --- | --- |
| Lookup | How is this validation implemented? | Fallback when confidence is low |
| Enumeration | Which pages submit to this controller? What would changing this table affect? | Mandatory cross-check |
| Absence | Does the system retry or deduplicate anywhere? | Mandatory exhaustive search |

Misclassification costs are lopsided. Calling a lookup an enumeration costs one extra `rg -l`.
Calling an enumeration a lookup skips the check and silently drops items. So:

1. **Keyword pre-check.** "which, all, list, every, impact, affect, callers, depends, uses" leans
   enumeration; "is there, does it, whether, any … at all" leans absence. Apply the same reading to
   the question in any language.
2. **Your judgement.** Read for intent and catch hidden enumerations: impact analysis, migration
   scope, dependency mapping.
3. **Take the stricter of the two.** Absence > enumeration > lookup. A type the user states wins.
4. **Delegated work can only escalate.** When you hand the search to a subagent, state the type and
   why. The subagent may raise lookup to enumeration (for example, hits spread across many files) and
   must say why; it may never lower the type.

Do not hand classification to a cheaper model: it saves almost nothing and risks the costly
direction of error.

## 2. Search in tiers; escalate only when a tier is not enough

1. **Repo map.** If the project has one (a file, class and method index), read it to narrow scope.
2. **Index pointers.** If the project provides BM25, vector or fact-table search, use it and take
   pointers only — `path:line`, signature, score — never whole chunks. Without such tools, use
   `rg -l` and `rg -c` as the pointer source.
3. **Line-range reads.** Read only the ranges you need to verify. Never read a whole large file to
   find one function.
4. **Bounded grep.** See section 3.

Escalate from tier 3 to tier 4 when an exact identifier gets no hits, when different search methods
disagree, when the best hit is weak or nothing stands out, or when the question type makes it
mandatory. When the question contains an exact string — an identifier, error code or quoted
literal — start with a grep count straight away.

## 3. Bounded grep

Count first, then narrow, then look at lines.

```bash
# 1) Count per file, busiest first
rg -c -S -g '!target/**' -g '!build/**' -g '!dist/**' -g '!node_modules/**' -g '!*.min.js' 'pattern' \
  | sort -t: -k2,2nr | head -20

# 2) File list only — the enumeration cross-check uses this
rg -l -S -g '!target/**' -g '!build/**' -g '!dist/**' -g '!node_modules/**' -g '!*.min.js' 'pattern'

# 3) Lines, only after narrowing scope: cap hits per file, truncate long lines
rg -n -S --max-count 5 --max-columns 200 --max-columns-preview \
  -g '!target/**' -g '!build/**' -g '!dist/**' -g '!node_modules/**' -g '!*.min.js' 'pattern' path/to/scope
```

- Use the same exclusions in every call, and the same set the project's indexes use, so the two
  file sets are comparable. Adjust them to the ecosystem: vendored libraries, generated code, build
  output, lock files.
- `-F` for literals, `-w` for whole words.
- A large count means narrow the pattern or the scope. Do not dump the lines.

## 4. Mandatory checks for enumeration and absence

**Enumeration.** List candidates from the index, fact table or tier-2 search. Run `rg -l` with the
same patterns. Files grep finds that the candidates miss are a recall gap: read their lines, then
add them to the evidence. Report the gap if the project maintains indexes, because it points at a
tokenizer rule or an unindexed file.

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
side by side with the document's version or date. Do not silently pick one.

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

- `references/language-notes.md` — read when the codebase includes Java, JSP or JavaScript, or when
  you need identifier-aware search patterns, chunking hints or the facts worth extracting from a
  legacy web application.
