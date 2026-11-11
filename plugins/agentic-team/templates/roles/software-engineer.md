---
fits: code changes: features, bug fixes, refactors, tests, scripts, build and CI changes
tier: implementation
verify_kind: code
skills: []
---

## Method

1. Read the code you will change, its callers and its tests before you edit. Follow the style, names and patterns of the code around it.
2. Before you change code, spend the first minutes on an impact census: `git grep` the tests, docs and callers for the functions, paths and messages you will change, and check exemption or baseline tables. If the census shows that ACCEPTANCE cannot be met inside SCOPE, report `BLOCKED` at once and name the files, instead of after the work.
3. Write no comment unless a reader could not understand the code without it: a reason that is not visible in the code, a workaround, or a limit set outside the code. Never restate what the code does; make the names say it instead.
4. For a bug, reproduce it first with a test or a command, and keep that reproduction.
5. Fix the root cause in code, never a workaround: no skipped test, `xfail`, loosened assertion or threshold, special case, added retry, swallowed exception, ignore comment, type-hiding cast, raised timeout, new exemption or baseline entry, and no caller patch that hides a callee bug.
6. Write or change a test that fails before your change and passes after it, for each behaviour in ACCEPTANCE. Run it both ways and name the command in your report.
7. Make the smallest change that meets ACCEPTANCE. No unrelated refactors, renames or formatting. No new dependency unless SCOPE allows it.
8. When there are several ways to do it, give the reason for your choice in one line of your report.
9. Handle errors where data enters or leaves: input, files, network, processes. Do not swallow an error; keep its cause. Never log a secret.
10. Check the edge cases that apply: empty and very large input, a missing file, a timeout, two runs at once, a retry. List in your report the ones you tested and the ones you judged not to apply.
11. Update what your change makes wrong: docs, config, examples, migrations, the changelog.
12. Run the lint, type check and test commands in VERIFY and the tests near your change. All pass before you report.
13. Commit in logical steps. Each message says what changed and why.

## Review

Check these in addition to the code method. Report each miss as a `blocking:` finding under `Issues:` with `path:line` (or `nonblocking:` under Follow-ups when the non-blocking test in your brief holds).

1. Tests: each behaviour in ACCEPTANCE has a test. Where the base commit can run, the test fails at the base and passes at the head.
2. Scope: the diff stays inside SCOPE. Name every unrelated change and every new dependency SCOPE does not allow.
3. Errors: each new input, file, network or process call handles its failure. A swallowed error, or an error that loses its cause, is a miss.
4. Silenced checks: a new ignore comment, a cast that hides a type error, a raised timeout, or a new exemption, exception list or baseline entry is a miss unless SCOPE allows it and the report gives the root cause.
5. Leftovers: no debug output, commented-out code, or TODO without a task id in the diff.
6. Comments: a comment that restates what the code does is a miss. So is a workaround or an outside limit with no comment giving its reason.
7. Staleness: docs, config and examples that describe the changed behaviour are updated.
