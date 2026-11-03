Then exercise the real output: run the scripts, apply the DDL, read the
values. Report every failure you can prove, not only the first.

### Method: schema

1. Recompute every number the artifact states (columns, fields added, merged
   or dropped, row counts) from the source tables or inventories. Do not copy
   a number from the document. Write each recomputed number next to the
   stated one under `Ran:`.
2. Coverage: every source field is in exactly one class (added, merged,
   dropped or unchanged). Report a field that is missing or counted twice.
3. Execution: the DDL parses. Each migration applies and rolls back on a
   temporary database. Keys, foreign keys and non-null constraints hold on
   sample data. Use a container started with `--rm`, or a file database under
   `mktemp -d`; remove it before you report. A leftover goes under
   `Follow-ups:` as `leftover container: <name>` or `leftover file: <path>`.
4. Consistency: names and numbers agree across every artifact of the task
   (the ADR text, the DDL, the review page). Each disagreement is an issue.
5. Compare with the base commit named in CONTEXT: `git diff --stat <base>
   <head>` lists what changed. Flag every file, field or decision that
   changed outside SCOPE under `Issues:`.

Verdict levels for this kind:
- `artifact-verified`: scripts recomputed the numbers and the coverage, the
  DDL ran, and every ACCEPTANCE line holds. This is the only level that
  closes a schema task.
- `test-verified`: VERIFY passes, but you did not recompute the numbers or
  run the DDL. It does not close the task.
- `check-only`: a read-through only.
- `verify-blocked`: a check could not run; name the cause.
- `verify-failed`: an ACCEPTANCE line does not hold, or a recomputed number
  differs from the stated one.
