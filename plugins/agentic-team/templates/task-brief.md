# Task {{TASK_ID}} — {{TASK_TITLE}}

Project: {{PROJECT}}
Time zone: {{TIMEZONE}}

## GOAL

{{GOAL}}

## SCOPE

{{SCOPE}}

## CONTEXT

- Task: `{{TASKGRAPH_COMMAND}} show {{TASK_ID}}` (read only)
- {{SETUP}}
- Last checkpoint: {{CHECKPOINT}}

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

Write your report with the Write tool to this file, in the format in your
agent instructions. {{REPORT_NOTE}}

`{{REPORT_FILE}}`

Then run this one command, once. Replace `<STATUS>` with `PASS`, `ISSUES`, or
`BLOCKED`. Keep the rest as it is.

```sh
{{RESULT_COMMAND}}
```

Do not put report text in a shell command: a guard can refuse the command for
a word in it. If the Write tool or the command is refused, follow the Report
section of your agent instructions.{{NOTIFY}}
