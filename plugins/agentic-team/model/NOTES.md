# The lifecycle model

The method comes from poteto's statechart skill in the pstack plugin (https://github.com/cursor/plugins/tree/main/pstack/skills/statechart): a TLA+ model of a system that moves between states, checked with TLC, drawn as a Mermaid statechart, with the shortest path to each state that breaks a rule.

`Lifecycle.tla` models the task-attempt lifecycle of `scripts/run.py` as it is in this version of the plugin: 0.12.0. It reads the code, not the docs: what `record` prints as `next:`, what each command refuses, what each command writes. Its purpose is to find dead ends (a state where the hinted command is refused or useless and nothing else moves) and lost transitions before an operator does. Line numbers in the model and in this file are of `scripts/run.py` at this version; keep them current when the code moves.

The model found the six issues that 0.12.0 fixes (#56, #57, #58, #59, #61, #62). Their old paths live on as sensitivity checks (`REGRESS_*`), below.

## How to read the model

- The Manager's only moves are the command that `record` names in its `next:` hint, and `record` itself. `Hint` is a derived operator: what `record` would print from the current state. `Record` is an action only when `record` writes something (a row, a meta, a `claude stop`); while it would, `Hint = "record"` and no other command is enabled.
- A refused command (exit 2) is not enabled. A command that would change nothing is not enabled either. `Done` is the only self-loop, for the end states (merged, or abandoned). So TLC's deadlock check is the rule "no dead end".
- Hints that name no run.py command (`tg add ... --type decision`, "record later", "merge it on the host", "reopen it") are `"none"`: the Manager waits for the world to move. The `unknown` hint (`claude logs <sid>; if it has stopped working, run.py stop ...`) is read as `stop`: the Manager looks, finds the session has stopped working, and stops it.
- At the last attempt the retry hints say `run.py abandon <id> <mode> (the cap is 3 attempts), or run.py launch <id> --attempt <n+1> to override`. The Manager never overrides, so the hint is `abandon`. The at-cap `unknown` hint offers `run.py stop ..., then ... launch --attempt` as its second alternative; the model reads abandon there too, so in 0.12.0 a recovery stop at the cap happens only when the Manager chooses that override (`regress-59.cfg` reads that branch on purpose). A pause at the cap under a recorded verify-failed verdict gets an abandon hint from `unclosed_next` (the pause is exempt, the verdict is not): a quirk, not a break.
- Two hints are read, not copied: `unclosed_next` for check-only ("verify --again for a stronger verdict, or accept it") maps to `verify --again`; verify-blocked is left out (it acts like check-only in every modelled decision).
- Sessions keep their state until something acts on them. An idle verifier may wake up or go quiet (30 minutes, `VERIFIER_QUIET_MINUTES`); an idle worker, and every quiet, blocked, prompted, failed or finished session, changes only when a command stops it. A worker files one result per attempt, as its last step (worker.md), and its row may stay live for a while after that.
- A stop is `run.py stop`. Under a STOP first line in the standing orders (`Orders.stop`, 366-373) it is a pause (`Reason: pause`) and does not use an attempt; without one it recovers a session that went quiet or broke (`Reason: recover`) and counts toward the cap, as DIED does (3309-3311, #59). `close` stops the worker with `Reason: close` (3091-3110). `commit_stopped` copies the reason into the row it files (1870-1871). The Manager runs `stop` where the `unknown` hint says so (#58); the operator runs it as a pause.
- The operator's free moves (write a STOP order, lift it, order a pause) are behind `OPERATOR_PAUSES`. With them on, every state has a step out (order, pause, lift, launch), so TLC's deadlock check would find nothing: the check configs keep them off, so that "no dead end" means "following record's hints leads out". `pause.cfg` turns them on to check the pause flow itself. A STOP order also refuses launches (1228-1229, exit 3) and holds merges (3256-3259, 3001-3002).

## Actions and the code they model (scripts/run.py, 0.12.0)

| TLA+ action | run.py | Lines |
|---|---|---|
| `Launch` | `cmd_launch` without `--attempt`, `--base`, `--model`; `idle_and_filed` and `work_filed` (a live row that is idle, or a worker that waits after its filed result, is stopped: `stopped-idle`, #61); `refuse_past_cap` (only a STOPPED row with `Reason: pause` is exempt, #59) | 1226-1418, 1216-1223, 560-565, 1282-1296, 1421-1428 |
| `LaunchStopsIdleThenRefuses` | the same launch when a later check refuses: the idle rows are stopped (1284-1293), then line 1300 (a pause not committed) or 1421 (the cap) refuses | 1284-1300, 1421 |
| `VerifyPlain`, `VerifyAgain` | `cmd_verify` in session mode; `refuse_unless_running`, `worker_for`, `verifier_over`; a verifier whose turn is over is stopped before a new one starts | 1523-1604, 1498-1520, 1816-1829, 1547-1550 |
| `CloseAuto`, `CloseManual` | `cmd_close`, `choose_verdict`, `resume_close`, `stop_live` (stops the worker with `Reason: close` and the verifier, #57), `publish` with catch-up, `host_catch_up`, `pr_status` (clean: merge, unless a STOP order), `merge_branch` | 3184-3251, 3157-3181, 3131-3154, 3091-3110, 2765-2819, 2847-2891, 2964-3014, 3254-3281 |
| `Stop` | `cmd_stop`: `Reason: pause` under a STOP order, else `Reason: recover` | 3300-3321 |
| `Abandon` | `cmd_abandon`: stops the task's live worker (an ABANDONED row) and its live verifier (no row, #57) | 3324-3350 |
| `Merged` | `cmd_merged`; never fires: the hints that name it (`pr-changed`, `push-refused`) need a request head that moved or a push someone else won, both out of scope | 3286-3297 |
| `Record` | `cmd_record` -> `record_in_progress`, `record_done`: `commit_stopped` first (#54), a verifier that waits after its filed verdict is stopped and the verdict stands (#62), `file_stuck`, `lost_verifier`, `verifier_filed`, `salvage_verifier`, `salvage`, `record_arrived`, `emit_verified`, `unclosed_next`, `retry_next`, `stopped_next`, `ready_events`, `merged_into` | 2094-2110, 1925-2051, 2053-2073, 1937-1941, 1947-1953, 1704-1715, 1832-1837, 1802-1813, 1851-1864, 1773-1793, 1717-1752, 1664-1673, 586-597, 535-543, 553-557, 2076-2080, 2064 |
| `Done` | the end states: merged, or abandoned | - |
| `Worker*`, `Verifier*` | the rows of `claude agents --json --all` as `Session.__init__` reads them: `finished`, `live`, `stuck`, `unknown`, `turn_over` | 415-456 |
| `WorkerFiles*`, `VerifierFiles` | the one `result add` command of a session's brief (`result_command`), as `is_worker_result`, `latest_worker`, `verifier_rows`, `verdict_of` read the rows | 712-717, 509-533 |
| `VerifierLeavesReport` | a report file or transcript that `salvage` and `parse_report` find for a verifier that filed nothing | 1754-1793 |
| `WorkerDirties` | uncommitted files in the task worktree, as `cmd_launch` and `commit_stopped` see them | 1368-1379, 1900-1912 |
| `HostDecides`, `TargetMoves`, `CheckFails`, `CheckPasses`, `SomeoneMerges`, `SomeoneCloses`, `SomeoneReopens` | the request states that `pr_status` and `publish` read from the host | 2964-3014 |
| `OperatorMerges` | local mode: a merge by hand that `record_done` finds with `merged_into` | 2062-2067 |
| `OperatorOrdersStop`, `OperatorLiftsStop` | a STOP first line written to or removed from the standing orders (`Orders.stop`); while it stands, `cmd_launch` exits 3 and `merge_branch`/`pr_status` say ready-to-merge instead of merging | 366-373, 1228-1229, 3256-3259, 3001-3002 |

## What the model leaves out

- `wait` and `notify-to`: `wait` polls and writes nothing; the notify line only wakes the Manager, which then runs `record`. Neither changes the state the model reads.
- Other tasks, decisions (`waits_for`, `gated`, `answered`), dependencies, slots and `check_cap`, `adopt`, `status`, `cleanup` (it never stops a live session: "never forces", line 2620 keeps a folder with a live row). Of the standing orders only the STOP first line is in (`stopOrder`); a MERGE: line is always present.
- `verify_mode = ci:*`, `verify_kind` other than code, `test-verified` (acts like artifact-verified for a code task), `verify-blocked` (acts like check-only), `--override-verifier`, a `--verdict` that differs from the verifier's, `--ref`, `--attempt` (the override the at-cap hint offers), `--base`, `--model`, `--dry-run`.
- Git details: a branch at another head (`branch_at`, `same_change`, `pr-changed`, `take_host_head`, `caught_up_from`), a missing or plain worktree folder, a wrong branch in it, a dirty or detached main checkout, `kept` (a `claude stop` that fails), `push-refused` and a gone remote branch. A failed first push (`push-failed`, line 2779) is in: the task is done and unpublished until a later close pushes.
- Tokens, report text, report file paths, transcripts: a verifier's unfiled report is one flag (`vreport`) with a passing verdict. A worker's unfiled report is left out: a salvaged PASS or ISSUES leads to the same hint as a filed one.
- Unrecorded session rows and `record_row`: every session is recorded by the command that started it.
- A verify row without a `Verdict:` line (`verified: no Verdict line`): verifier rows always carry a level. A STOPPED row without a `Reason:` line: every modelled stop writes one.
- A second verifier session's folder name and rank: one verifier row at a time; `verify --again` replaces it.
- `host-error`, `merge-failed`, `pr-draft`, `pr-unpinned`; `pr_status`'s UNKNOWN state is folded into "pending".

## Simplifications

1. Rows are summarised: the newest task row (`lastTask`: PASS, ISSUES, BLOCKED, BLOCKEDmgr for `file_stuck`, DIED, STOPPED without a Head line, STOPPEDhead, ABANDONED) with the `Reason:` of the newest STOPPED row (`stopReason`), `latest_worker` (`workerResult`), the newest verifier-authored verify row (`vv`), the newest Manager verify row (`vManager`: BLOCKED, or manual for `close --verdict`), their order (`vNewer`: the verifier's row is newer than the Manager's newest row *with a verdict*, which is what lines 1991-1993 read since #62), and `vfiled` (`verifier_filed`: a row covers the newest verifier session).
2. One worker and one verifier session at a time. `claude stop` is immediate except after `run.py stop`, where the row stays busy ("stopping") until the process exits, so that `commit_stopped`'s "has not exited yet" branch exists.
3. The host's answer after a push is a free choice among the open states (pending, clean, behind, blocked, dirty). Requests move: pending -> any decided state; clean or blocked -> behind; clean <-> blocked; any open -> merged or closed by someone; closed -> pending by a reopen. "behind" moves only by the host's rebase (close) or by a merge or close by hand.
4. A local merge either succeeds or conflicts (a free choice); a conflict is a decision for the operator, who can then merge by hand.
5. `HIGH_RISK = TRUE`: a PASS goes to a verifier session. With FALSE, `record_arrived` tells the Manager to rerun VERIFY itself and close with `--verdict L` (`CloseManual`), where the model lets the Manager pick any level.
6. `MAX_ATTEMPTS = 2` (the code has 3): two attempts show the retry and the cap. `AttemptBound` explores up to 3; TLC checks the rules in the states one step past it, so `TypeOK` allows 4.
7. The thirty quiet minutes are one environment step (`VerifierQuiet`). The worker has no quiet state: the code treats an idle worker the same at any age.
8. The STOP order is one boolean the operator sets and lifts (`OperatorOrdersStop`, `OperatorLiftsStop`). `cmd_stop` reads it when it runs: a stop of an idle worker while a STOP line stands is a pause, not a recovery (the owner's rule as stated, #59).

## Rules

- `VerdictNotLost`: once the verifier's session ended or its turn ended, a verify row covers it, or record is about to write one, or record says no-verdict, or a pause is pending (a STOPPED row without a Head line: record finishes it first by design, 1940, and the record after the commit finds the lost verifier). An invariant, not a liveness property: the model has no fairness (a PROPERTY would need weak fairness on `Record` and on the paused worker's exit), and a state is easier to read than a lasso.
- `NoMergeWithoutPassingVerdict`: done or merged implies the verdict meta is passing and a verify row of the attempt carries it.
- `AttemptCap` (a PROPERTY): the attempt passes MAX_ATTEMPTS only by a launch after a pause the operator ordered (the newest row is STOPPED with `Reason: pause`). The owner's rule (#59): a stop that recovers a quiet or broken session, a stop by close, and DIED all count as an attempt. As an action property it names the step that passes the cap. `refuse_past_cap` (1421-1428) is where the code keeps it.
- `PausedWipCommitted`, from "Phase 2 of a pause: commit the WIP of a stopped worker that has exited" (commit_stopped, 1868).
- `PauseFinishedFirst`, from "finish the pause first: launch needs its Head line" (record_in_progress, 1940).
- `LaunchCommitsLeftovers`, from "A dirty worktree never reaches a worker silently" (cmd_launch, 1368).
- `OneRequestPerTask`, from "Never unset pr, pr_branch, pushed or target: one request per task across attempts" (cmd_launch, 1404).
- `NoSessionLeftAtEnd`, from "Remove the sessions and worktrees of a merged task" (cleanup, 2591) and `stop_live`/`cmd_abandon` (#57): an end state leaves no live session of the task.
- No dead end: TLC's deadlock check, with `Done` for the end states.

## Fixed issues

0.12.0 fixed the six breaks the model found in 0.11.2 and 0.11.3. Each had an `ALLOW_*` switch that gave the Manager or the operator the real way out; the switches are gone, and `check.cfg` is expected to hold every rule. What the code does now, and where:

| Issue | Was | Now |
|---|---|---|
| #56 | at the last attempt the stuck, BLOCKED, unclosed and unknown hints said `launch`, which `refuse_past_cap` refused | every retry hint comes from `retry_next` (535-543): `abandon` at the cap |
| #57 | `stop_live` and `cmd_abandon` stopped worker sessions only | both stop the live verifier too, with `record_row` and no row (3091-3110, 3337-3340) |
| #58 | an idle worker with no result got `claude logs <sid>`, no run.py step | the `unknown` hint adds `run.py stop <id>, then run.py record and run.py launch <id>` (2020-2022) |
| #59 | `refuse_past_cap` exempted every STOPPED row, a recovery stop too | only `Reason: pause` is exempt (1421-1428); `cmd_stop` writes the reason (3309-3311); `stopped_next` retries after any other stop (553-557) |
| #61 | `launch` refused a worker that waited on a prompt after its result | `idle_and_filed` accepts a stuck worker whose work is filed (1216-1223) |
| #62 | `record` filed a Manager BLOCKED row for a verifier that waited after its verdict; the row hid the verdict and the hint said plain `verify`, refused | `record` stops that verifier, files no row, and goes on to `verified` (1947-1953); a Manager row without a verdict hides nothing (1989-1993) |

## Sensitivity checks

Run these when you change the model: if they stop breaking, the model has gone blind. Each `REGRESS_*` constant, when TRUE, restores a bug the code has fixed, so the check must find the old path again.

| Config | Restores | Must break | The old path |
|---|---|---|---|
| `regress-42.cfg` | a failed row counts as live (before 0.10.3, #42) | `VerdictNotLost` (4 steps: the verifier fails; `record` says `verifying` for ever), `NoDeadlock` (5 steps: the same, then the worker ends; `verify` refused "still running") | the 0.10.2 study: "B2". The failed worker is no longer a dead end there: the `unknown` hint names `stop`, which that live row accepts |
| `regress-54.cfg` (`OPERATOR_PAUSES` on) | `record` no longer finishes a pause first (before 0.11.2, #54): the STOPPED row is handled only after the verifier and verdict checks | `PauseFinishedFirst` (6 steps: an ordered pause while a verifier runs; record says `verifying`, the WIP waits) | the 0.11.1 study: "A8" (the full dead end needs a stop under a recorded verdict, which only the operator's pause can make now, and the operator's free moves keep it out of the deadlock check) |
| `regress-56.cfg` | the retry hints at the last attempt say `launch` | `NoDeadlock` (6 steps: a stuck worker at the cap; `record` files BLOCKED, the hint says launch, `refuse_past_cap` refuses) | #56 |
| `regress-57.cfg` | close and abandon stop worker sessions only | `NoSessionLeftAtEnd` (6 steps: the verifier goes idle after its verdict, close merges) | #57 |
| `regress-58.cfg` | the `unknown` hint names no run.py step | `NoDeadlock` (2 steps: the worker goes idle with no result) | #58 |
| `regress-59.cfg` | every STOPPED row is exempt from the cap, and `stopped` says "after the pause"; the Manager also takes the at-cap `unknown` hint's second alternative (`run.py stop ..., then ... launch --attempt`), the recovery stop the old bug needed | `AttemptCap` (9 steps: a recovery stop of an idle worker at the cap, record commits, launch past the cap) | #59 |
| `regress-61.cfg` | `launch` refuses a worker that waits on a prompt after its result | `NoDeadlock` (3 steps: ISSUES, then a permission prompt; the hint says launch) | #61 |
| `regress-62.cfg` | `record` files BLOCKED for a verifier that waits after its verdict, and the row hides the verdict | `NoDeadlock` (7 steps: a verdict, then a prompt; record files BLOCKED, the hint says plain `verify`, refused) | #62 |

Add one when an issue is fixed: keep its path as a `REGRESS_*` constant that undoes the fix, and a config that must break.

## Configs, in run order

| # | Config | View | Constants | Expect |
|---|---|---|---|---|
| 1 | `check.cfg` | `view.mjs` | local, OPERATOR_PAUSES = FALSE | every rule holds, no dead end |
| 2 | `check-pr.cfg` | `view.mjs` | pr mode | as 1 |
| 3 | `pause.cfg` | `view.mjs` | local, OPERATOR_PAUSES = TRUE | every rule holds (an ordered pause at the cap is exempt) |
| 4 | `pause-pr.cfg` | `view.mjs` | pr mode, OPERATOR_PAUSES = TRUE | as 3 |
| 5 | `regress-42.cfg` | `view.mjs` | REGRESS_42 | must break VerdictNotLost and NoDeadlock |
| 6 | `regress-54.cfg` | `view.mjs` | REGRESS_54, OPERATOR_PAUSES = TRUE | must break PauseFinishedFirst |
| 7 | `regress-56.cfg` | `view.mjs` | REGRESS_56 | must break NoDeadlock |
| 8 | `regress-57.cfg` | `view.mjs` | REGRESS_57 | must break NoSessionLeftAtEnd |
| 9 | `regress-58.cfg` | `view.mjs` | REGRESS_58 | must break NoDeadlock |
| 10 | `regress-59.cfg` | `view.mjs` | REGRESS_59 | must break AttemptCap |
| 11 | `regress-61.cfg` | `view.mjs` | REGRESS_61 | must break NoDeadlock |
| 12 | `regress-62.cfg` | `view.mjs` | REGRESS_62 | must break NoDeadlock |
| 13 | `overview.cfg` | `overview-view.mjs` | local, OPERATOR_PAUSES = FALSE, FULL_ENV = FALSE | every rule holds; 106 states, under the 500-state budget, so a full chart: the README diagram. The operator's pause is left out to stay under the budget; `pause.cfg` checks it |
| 14 | `overview-pr.cfg` | `overview-view.mjs` | as 13, pr mode | as 13, with the request states |

A TLC run reports one dead end per config (the shortest). The statechart command removes a broken invariant itself and runs again. The constants `MAX_ATTEMPTS`, `MERGE_MODE`, `HIGH_RISK`, `FULL_ENV`, `OPERATOR_PAUSES` and the `REGRESS_*` flags are set in each config.

`FULL_ENV = FALSE` keeps only the main flow of the environment: a worker reports and ends, a stopped worker exits, a verifier files and ends, the operator merges, the host moves the request. No idle, blocked, prompted or failed sessions, no dirty worktree, no unfiled report. It is for the overview chart, not for the check.

## How to run

The statechart skill of this repository runs TLC and draws the chart:

```
plugins/statechart/skills/statechart/scripts/statechart plugins/agentic-team/model/Lifecycle.tla \
  --config plugins/agentic-team/model/check.cfg --view plugins/agentic-team/model/view.mjs --out <new folder>
```

Its `setup.sh` installs TLC and Java and prints the `TLA2TOOLS` and `JAVA` values to export; without them the command installs both with mise on the first run. Use a new `--out` folder per run, outside the repository. Each run takes about fifteen seconds. Read `report.md` (the shortest path of each rule that breaks, numbered) and `chart.mmd`.

For the README, run `overview.cfg` with `overview-view.mjs`, copy `chart.mmd` to `assets/diagrams/attempt-statechart.mmd` below the `%% Generated by the statechart skill` comment lines, and render it with `plugins/statechart/skills/statechart/scripts/render.mjs`.

## Keeping the model current

When `run.py` changes a hint, a refusal, or what a command writes, change the matching action and its line numbers, run `check.cfg`, the regress configs and `pause.cfg`, and update PREDICTIONS.md. When the check finds a new break, confirm it in the code at the line, file it, and give it an `ALLOW_*` switch (TRUE: the real way out) until the fix lands; then turn the switch into a `REGRESS_*` constant and a regress config.
