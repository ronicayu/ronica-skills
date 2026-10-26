# Task {{TASK_ID}} — {{TASK_TITLE}}

Project: {{PROJECT}}
Session: {{SESSION_NAME}}
Time zone: {{TIMEZONE}}

## GOAL

{{GOAL}}

## SCOPE

{{SCOPE}}

## CONTEXT

- Task: `{{TASKGRAPH_COMMAND}} show {{TASK_ID}}` (read only)
- Supplemental plan: {{PLAN_FILE}}
- Base commit: {{BASE}}. Your worktree starts from the default branch.
  Before anything else, run `git reset --keep {{BASE}}` in your worktree.
- Last checkpoint: {{CHECKPOINT}}
- Consultants: {{CONSULTANTS}}

{{UPSTREAM}}

## ACCEPTANCE

{{ACCEPTANCE}}

## VERIFY

{{VERIFY}}

## TIMEBOX

{{TIMEBOX}}

## FORBIDDEN

{{FORBIDDEN}}

## AUTONOMY

{{AUTONOMY}}

## STANDING ORDERS

{{STANDING_ORDERS}}

## REPORT

Your last action is this one command, run once. Replace `<STATUS>` with
`PASS`, `ISSUES`, or `BLOCKED`, and replace `<your report>` with your report
in the format in your agent instructions. Keep the quoted heredoc as it is.
Do not pipe the report in, and do not write it to a file.

```sh
{{RESULT_COMMAND}}
```
