# Verify task {{TASK_ID}} — {{TASK_TITLE}}

Project: {{PROJECT}}
Session: {{SESSION_NAME}}
Time zone: {{TIMEZONE}}

## GOAL

Judge whether the output of task {{TASK_ID}} meets every ACCEPTANCE line.
Check the real artifact, not the worker's report. Do not fix anything.

## SCOPE

Read only. You run in your own worktree. If the output under review is a
commit SHA, run `git checkout --detach <that SHA>` first. If it is a list of
checksums, the output is outside git: compare the files against the
checksums and do not check anything out. Then change nothing. Do not edit,
commit, or delete anything.

## CONTEXT

- Task: `{{TASKGRAPH_COMMAND}} show {{TASK_ID}}` (read only)
- Output under review: {{VERDICT_REF}}

### Worker report

{{WORKER_REPORT}}

## ACCEPTANCE

{{ACCEPTANCE}}

## VERIFY

{{VERIFY}}

Then exercise the real output: run it, open it, or read the values it
produced. Report every failure you can prove, not only the first.

## TIMEBOX

{{TIMEBOX}}

## FORBIDDEN

{{FORBIDDEN}}

## STANDING ORDERS

{{STANDING_ORDERS}}

## REPORT

Your last action is this one command, run once. Replace `<STATUS>` with
`PASS`, `ISSUES`, or `BLOCKED`, and replace `<your report>` with your report
in the format in your agent instructions, with a `Verdict:` line. Keep the
quoted heredoc as it is. Do not pipe the report in, and do not write it to a
file.

```sh
{{RESULT_COMMAND}}
```
