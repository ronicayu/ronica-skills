# Verify task {{TASK_ID}} — {{TASK_TITLE}}

Project: {{PROJECT}}
Manager session: {{SESSION_NAME}}
Time zone: {{TIMEZONE}}

## GOAL

Judge whether the output of task {{TASK_ID}} meets every ACCEPTANCE line.
Check the real artifact, not the worker's report. Do not fix anything.

## SCOPE

Read only. Do not change, commit, or delete anything in the repository.

## CONTEXT

- Task: `{{TASKGRAPH_COMMAND}} show {{TASK_ID}}` (read only)
- Worker report: {{REPORT_FILE}}
- Output under review: {{VERDICT_REF}}

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
