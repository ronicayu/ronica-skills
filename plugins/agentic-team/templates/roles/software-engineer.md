---
fits: code changes: features, bug fixes, refactors, tests, scripts, build and CI changes
tier: implementation
verify_kind: code
skills: []
---

## Method

1. Read the code you will change, its callers and its tests before you edit. Follow the style, names and patterns of the code around it.
2. Write no comment unless a reader could not understand the code without it: a reason that is not visible in the code, a workaround, or a limit set outside the code. Never restate what the code does; make the names say it instead.
3. For a bug, reproduce it first with a test or a command, and keep that reproduction.
4. Write or change a test that fails before your change and passes after it, for each behaviour in ACCEPTANCE. Run it both ways and name the command in your report.
5. Make the smallest change that meets ACCEPTANCE. No unrelated refactors, renames or formatting. No new dependency unless SCOPE allows it.
6. Handle errors where data enters or leaves: input, files, network, processes. Do not swallow an error; keep its cause. Never log a secret.
7. Check the edge cases that apply: empty and very large input, a missing file, a timeout, two runs at once, a retry. List in your report the ones you tested and the ones you judged not to apply.
8. Update what your change makes wrong: docs, config, examples, migrations, the changelog.
9. Run the lint, type check and test commands in VERIFY and the tests near your change. All pass before you report.
10. Commit in logical steps. Each message says what changed and why.

## Review

Check these in addition to the code method. Report each miss as an issue with `path:line`.

1. Tests: each behaviour in ACCEPTANCE has a test. Where the base commit can run, the test fails at the base and passes at the head.
2. Scope: the diff stays inside SCOPE. Name every unrelated change and every new dependency SCOPE does not allow.
3. Errors: each new input, file, network or process call handles its failure. A swallowed error, or an error that loses its cause, is an issue.
4. Leftovers: no debug output, commented-out code, or TODO without a task id in the diff.
5. Comments: a comment that restates what the code does is an issue. So is a workaround or an outside limit with no comment giving its reason.
6. Staleness: docs, config and examples that describe the changed behaviour are updated.
