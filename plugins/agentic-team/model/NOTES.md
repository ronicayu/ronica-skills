# The lifecycle model

The method comes from poteto's statechart skill in the pstack plugin (https://github.com/cursor/plugins/tree/main/pstack/skills/statechart): a TLA+ model of a system that moves between states, checked with TLC, drawn as a Mermaid statechart, with the shortest path to each state that breaks a rule.

`Lifecycle.tla` models the task-attempt lifecycle of `scripts/run.py` as it is in this version of the plugin: 0.12.1. It reads the code, not the docs: what `record` prints as `next:`, what each command refuses, what each command writes. Its purpose is to find dead ends (a state where the hinted command is refused or useless and nothing else moves) and lost transitions before an operator does. Line numbers in the model and in this file are of `scripts/run.py` at this version; keep them current when the code moves.

The model found the six issues that 0.12.0 fixes (#56, #57, #58, #59, #61, #62). Their old paths live on as sensitivity checks (`REGRESS_*`), below. 0.12.1 adds the ghost row (#65), see "Ghost rows".

## How to read the model

- The Manager's only moves are the command that `record` names in its `next:` hint, and `record` itself. `Hint` is a derived operator: what `record` would print from the current state. `Record` is an action only when `record` writes something (a row, a meta, a `claude stop`); while it would, `Hint = "record"` and no other command is enabled.
- A refused command (exit 2) is not enabled. A command that would change nothing is not enabled either. `Done` is the only self-loop, for the end states (merged, or abandoned). So TLC's deadlock check is the rule "no dead end".
- Hints that name no run.py command (`tg add ... --type decision`, "record later", "merge it on the host", "reopen it") are `"none"`: the Manager waits for the world to move. The `unknown` hint (`claude logs <sid>; if it has stopped working, run.py stop ...`) is read as `stop`: the Manager looks, finds the session has stopped working, and stops it.
- At the last attempt the retry hints say `run.py abandon <id> <mode> (the cap is 3 attempts), or run.py launch <id> --attempt <n+1> to override`. The Manager never overrides, so the hint is `abandon`. The at-cap `unknown` hint offers `run.py stop ..., then ... launch --attempt` as its second alternative; the model reads abandon there too, so in 0.12.0 a recovery stop at the cap happens only when the Manager chooses that override (`regress-59.cfg` reads that branch on purpose). A pause at the cap under a recorded verify-failed verdict gets an abandon hint from `unclosed_next` (the pause is exempt, the verdict is not): a quirk, not a break.
- Two hints are read, not copied: `unclosed_next` for check-only ("verify --again for a stronger verdict, or accept it") maps to `verify --again`; verify-blocked is left out (it acts like check-only in every modelled decision).
- Sessions keep their state until something acts on them. An idle verifier may wake up or go quiet (30 minutes, `VERIFIER_QUIET_MINUTES`); an idle worker, and every quiet, blocked, prompted, failed or finished session, changes only when a command stops it. A worker files one result per attempt, as its last step (worker.md), and its row may stay live for a while after that.
- A stop is `run.py stop`. Under a STOP first line in the standing orders (`Orders.stop`, 378-385) it is a pause (`Reason: pause`) and does not use an attempt; without one it recovers a session that went quiet or broke (`Reason: recover`) and counts toward the cap, as DIED does (3358-3360, #59). `close` stops the worker with `Reason: close` (3140-3159). `commit_stopped` copies the reason into the row it files (1910-1911). The Manager runs `stop` where the `unknown` hint says so (#58); the operator runs it as a pause.
- A ghost row (#65, `Session.ghost`, 465): a live row with no status and no pid, no process now. Young, it is `unknown` for `record` (the hint names `run.py stop`), and the CLI may start it again. `claude stop` keeps a row's state and removes its status and pid (a probe on CLI 2.1.318, 2026-11-06): a busy row becomes "stopped", a done/idle row "done" with no status, both finished; an idle/working row (one that said it will check back) becomes working with no status and no pid, a young ghost. The field saw exactly that: `close --verdict verify-failed` stopped an idle worker, and the next `launch` refused on the row "None/working" (2026-11-06). Since part 3 of #65 every stop that run.py runs goes through `stop_session` (481-494), which notes the id in the run directory's `stopped-sessions` file (`STOPPED_FILE`, 139), and `Run.sessions` (365-375) counts a noted live row with no status as finished at once. So in the model a run.py stop always ends the row (`AfterStop`), whatever it was; the field's case (an idle/working worker with its result filed, stopped by launch's stopped-idle) no longer blocks the launch. Before part 3 (`REGRESS_65B`) a stopped idle/working row stayed a young ghost until its 30 quiet minutes: the model's `ghostStopped`, which does not come back (the probe saw a stopped busy row stay stopped and never saw a stopped row revive; only a kill-induced ghost came back). A stop the operator runs by hand is not modelled. After `VERIFIER_QUIET_MINUTES` (30) with no transcript write and no start (`quiet_for`, 1846-1855, above `verifier_over`), `Run.sessions` (365-375) marks it finished (`finished`, `turn_over` set; `live`, `stuck`, `unknown` cleared): launch no longer waits for it, record salvages its report or files DIED, a verifier goes to `lost_verifier`, and cleanup removes it. The model has two values: `ghost` (young: live, unknown) and `ghostGone` (quiet: finished). The `ghost` flag is line 456.
- The operator's free moves (write a STOP order, lift it, order a pause) are behind `OPERATOR_PAUSES`. With them on, every state has a step out (order, pause, lift, launch), so TLC's deadlock check would find nothing: the check configs keep them off, so that "no dead end" means "following record's hints leads out". `pause.cfg` turns them on to check the pause flow itself. A STOP order also refuses launches (1258-1259, exit 3) and holds merges (3305-3308, 3050-3051).

## Actions and the code they model (scripts/run.py, 0.12.0)

| TLA+ action | run.py | Lines |
|---|---|---|
| `Launch` | `cmd_launch` without `--attempt`, `--base`, `--model`; `idle_and_filed` and `work_filed` (a live row that is idle, or a worker that waits after its filed result, is stopped: `stopped-idle`, #61); `refuse_past_cap` (only a STOPPED row with `Reason: pause` is exempt, #59) | 1256-1448, 1246-1253, 590-595, 1312-1326, 1451-1458 |
| `LaunchStopsIdleThenRefuses` | the same launch when a later check refuses: the idle rows are stopped (1314-1323), then line 1330 (a pause not committed) or 1451 (the cap) refuses | 1314-1330, 1451 |
| `VerifyPlain`, `VerifyAgain` | `cmd_verify` in session mode; `refuse_unless_running`, `worker_for`, `verifier_over`; a verifier whose turn is over is stopped before a new one starts | 1553-1634, 1528-1550, 1856-1869, 1577-1580 |
| `CloseAuto`, `CloseManual` | `cmd_close`, `choose_verdict`, `resume_close`, `stop_live` (stops the worker with `Reason: close` and the verifier, #57), `publish` with catch-up, `host_catch_up`, `pr_status` (clean: merge, unless a STOP order), `merge_branch` | 3233-3300, 3206-3230, 3180-3203, 3140-3159, 2814-2868, 2896-2940, 3013-3063, 3303-3330 |
| `Stop` | `cmd_stop`: `Reason: pause` under a STOP order, else `Reason: recover` | 3349-3370 |
| `Abandon` | `cmd_abandon`: stops the task's live worker (an ABANDONED row) and its live verifier (no row, #57) | 3373-3399 |
| `Merged` | `cmd_merged`; never fires: the hints that name it (`pr-changed`, `push-refused`) need a request head that moved or a push someone else won, both out of scope | 3335-3346 |
| `Record` | `cmd_record` -> `record_in_progress`, `record_done`: `commit_stopped` first (#54), a verifier that waits after its filed verdict is stopped and the verdict stands (#62), `file_stuck`, `lost_verifier`, `verifier_filed`, `salvage_verifier`, `salvage`, `record_arrived`, `emit_verified`, `unclosed_next`, `retry_next`, `stopped_next`, `ready_events`, `merged_into` | 2134-2150, 1965-2091, 2093-2113, 1977-1981, 1987-1993, 1734-1745, 1872-1877, 1832-1843, 1891-1904, 1803-1823, 1747-1782, 1694-1703, 616-627, 565-573, 583-587, 2116-2120, 2104 |
| `Done` | the end states: merged, or abandoned | - |
| `Worker*`, `Verifier*` | the rows of `claude agents --json --all` as `Session.__init__` reads them: `finished`, `live`, `stuck`, `unknown`, `turn_over` | 427-471 |
| `WorkerFiles*`, `VerifierFiles` | the one `result add` command of a session's brief (`result_command`), as `is_worker_result`, `latest_worker`, `verifier_rows`, `verdict_of` read the rows | 742-747, 539-563 |
| `VerifierLeavesReport` | a report file or transcript that `salvage` and `parse_report` find for a verifier that filed nothing | 1784-1823 |
| `WorkerDirties` | uncommitted files in the task worktree, as `cmd_launch` and `commit_stopped` see them | 1398-1409, 1940-1952 |
| `HostDecides`, `TargetMoves`, `CheckFails`, `CheckPasses`, `SomeoneMerges`, `SomeoneCloses`, `SomeoneReopens` | the request states that `pr_status` and `publish` read from the host | 3013-3063 |
| `OperatorMerges` | local mode: a merge by hand that `record_done` finds with `merged_into` | 2102-2107 |
| `WorkerGhosts`, `WorkerGhostReturns`, `WorkerGhostStays`, `VerifierGhosts`, `VerifierGhostReturns`, `VerifierGhostStays` | a process that dies and leaves a live row with no status and no pid (`Session.ghost`); the CLI starting it again; or 30 quiet minutes, after which `Run.sessions` counts the row as ended (`quiet_for`) | 465, 365-375, 1846-1855 |
| `OperatorOrdersStop`, `OperatorLiftsStop` | a STOP first line written to or removed from the standing orders (`Orders.stop`); while it stands, `cmd_launch` exits 3 and `merge_branch`/`pr_status` say ready-to-merge instead of merging | 378-385, 1258-1259, 3305-3308, 3050-3051 |

## What the model leaves out

- `wait` and `notify-to`: `wait` polls and writes nothing; the notify line only wakes the Manager, which then runs `record`. Neither changes the state the model reads.
- Other tasks, decisions (`waits_for`, `gated`, `answered`), dependencies, slots and `check_cap`, `adopt`, `status`, `cleanup` (it never stops a live session: "never forces", line 2669 keeps a folder with a live row). Of the standing orders only the STOP first line is in (`stopOrder`); a MERGE: line is always present.
- `verify_mode = ci:*`, `verify_kind` other than code, `test-verified` (acts like artifact-verified for a code task), `verify-blocked` (acts like check-only), `--override-verifier`, a `--verdict` that differs from the verifier's, `--ref`, `--attempt` (the override the at-cap hint offers), `--base`, `--model`, `--dry-run`.
- Git details: a branch at another head (`branch_at`, `same_change`, `pr-changed`, `take_host_head`, `caught_up_from`), a missing or plain worktree folder, a wrong branch in it, a dirty or detached main checkout, `kept` (a `claude stop` that fails), `push-refused` and a gone remote branch. A failed first push (`push-failed`, line 2828) is in: the task is done and unpublished until a later close pushes.
- Tokens, report text, report file paths, transcripts: a verifier's unfiled report is one flag (`vreport`) with a passing verdict. A worker's unfiled report is left out: a salvaged PASS or ISSUES leads to the same hint as a filed one.
- Unrecorded session rows and `record_row`: every session is recorded by the command that started it.
- A verify row without a `Verdict:` line (`verified: no Verdict line`): verifier rows always carry a level. A STOPPED row without a `Reason:` line: every modelled stop writes one.
- A second verifier session's folder name and rank: one verifier row at a time; `verify --again` replaces it.
- `host-error`, `merge-failed`, `pr-draft`, `pr-unpinned`; `pr_status`'s UNKNOWN state is folded into "pending".

## Simplifications

1. Rows are summarised: the newest task row (`lastTask`: PASS, ISSUES, BLOCKED, BLOCKEDmgr for `file_stuck`, DIED, STOPPED without a Head line, STOPPEDhead, ABANDONED) with the `Reason:` of the newest STOPPED row (`stopReason`), `latest_worker` (`workerResult`), the newest verifier-authored verify row (`vv`), the newest Manager verify row (`vManager`: BLOCKED, or manual for `close --verdict`), their order (`vNewer`: the verifier's row is newer than the Manager's newest row *with a verdict*, which is what lines 2031-2033 read since #62), and `vfiled` (`verifier_filed`: a row covers the newest verifier session).
2. One worker and one verifier session at a time. `claude stop` is immediate except after `run.py stop`, where the row stays busy ("stopping") until the process exits, so that `commit_stopped`'s "has not exited yet" branch exists.
3. The host's answer after a push is a free choice among the open states (pending, clean, behind, blocked, dirty). Requests move: pending -> any decided state; clean or blocked -> behind; clean <-> blocked; any open -> merged or closed by someone; closed -> pending by a reopen. "behind" moves only by the host's rebase (close) or by a merge or close by hand.
4. A local merge either succeeds or conflicts (a free choice); a conflict is a decision for the operator, who can then merge by hand.
5. `HIGH_RISK = TRUE`: a PASS goes to a verifier session. With FALSE, `record_arrived` tells the Manager to rerun VERIFY itself and close with `--verdict L` (`CloseManual`), where the model lets the Manager pick any level.
6. `MAX_ATTEMPTS = 2` (the code has 3): two attempts show the retry and the cap. `AttemptBound` explores up to 3; TLC checks the rules in the states one step past it, so `TypeOK` allows 4.
7. The thirty quiet minutes are one environment step (`VerifierQuiet`). The worker has no quiet state: the code treats an idle worker the same at any age.
8. After `verify --again` the model tracks the new verifier only. In the code the old verifier's row stays; a young ghost among them refuses `launch` ("has a live session") until it comes back or goes quiet. The worker ghost shows that path; the verifier one is not drawn twice.
9. The STOP order is one boolean the operator sets and lifts (`OperatorOrdersStop`, `OperatorLiftsStop`). `cmd_stop` reads it when it runs: a stop of an idle worker while a STOP line stands is a pause, not a recovery (the owner's rule as stated, #59).

## Rules

- `VerdictNotLost`: once the verifier's session ended or its turn ended, a verify row covers it, or record is about to write one, or record says no-verdict, or a pause is pending (a STOPPED row without a Head line: record finishes it first by design, 1980, and the record after the commit finds the lost verifier). An invariant, not a liveness property: the model has no fairness (a PROPERTY would need weak fairness on `Record` and on the paused worker's exit), and a state is easier to read than a lasso.
- `NoMergeWithoutPassingVerdict`: done or merged implies the verdict meta is passing and a verify row of the attempt carries it.
- `AttemptCap` (a PROPERTY): the attempt passes MAX_ATTEMPTS only by a launch after a pause the operator ordered (the newest row is STOPPED with `Reason: pause`). The owner's rule (#59): a stop that recovers a quiet or broken session, a stop by close, and DIED all count as an attempt. As an action property it names the step that passes the cap. `refuse_past_cap` (1451-1458) is where the code keeps it.
- `PausedWipCommitted`, from "Phase 2 of a pause: commit the WIP of a stopped worker that has exited" (commit_stopped, 1908).
- `PauseFinishedFirst`, from "finish the pause first: launch needs its Head line" (record_in_progress, 1980).
- `LaunchCommitsLeftovers`, from "A dirty worktree never reaches a worker silently" (cmd_launch, 1398).
- `OneRequestPerTask`, from "Never unset pr, pr_branch, pushed or target: one request per task across attempts" (cmd_launch, 1434).
- `StoppedIdleNeverRefuses` (a PROPERTY), from "launch stops such a session itself instead of refusing" (idle_and_filed, 1246-1253): a launch that stops the idle rows and passes every other check starts the next attempt. The step must be the launch itself: the first form of the rule counted the operator's STOP order written in such a state (launch then exits 3 before it stops anything, pause.md), which broke pause.cfg, pause-pr.cfg and regress-54.cfg (an artifact of the rule, not of the code). Before part 3 of #65 the stopped idle/working row was a young ghost and the launch's second read of the live rows (1324) refused on it.
- `NoSessionLeftAtEnd`, from "Remove the sessions and worktrees of a merged task" (cleanup, 2640) and `stop_live`/`cmd_abandon` (#57): an end state leaves no live session of the task. A young ghost row at the end is not a break: `claude stop` cannot end it, it ends by itself after 30 quiet minutes, and since 0.12.1 cleanup removes it with `claude rm` once the task is done (2669, 2683, 2715). With `REGRESS_65` it counts as left, as it was before.
- No dead end: TLC's deadlock check, with `Done` for the end states.

## Ghost rows (#65)

What 0.12.1 changes, and what the model does with it:

- The session cap (`live_count`, 503-504, no longer counts ghosts) is out of the model's scope: the cap is a count across every task on the machine, and the model checks one task. `check_cap` is left out (above).
- `cleanup` (2639-2737) is out of the model's scope too, as before. The ghost part of cleanup (a ghost is removable and does not keep its folder) is reflected in one rule: `NoSessionLeftAtEnd` lets a ghost row stand at the end, because cleanup removes it then; `REGRESS_65` makes it count as left, and `regress-65.cfg` must break.
- `merged_into` accepting a rebased commit (`git cherry`, 2355-2367) changes no modelled decision: `mainHas` already stands for "the main checkout holds the change".
- What the model does check: a ghost worker or verifier of a task in progress. Part 1 alone left a dead end, which the model found: a ghost row that holds a result or a stop blocked `launch` for ever (`idle_and_filed` needs a status, a ghost has none; `claude stop` does not change the row; no hint names `claude rm`). Part 2 ends the row after 30 quiet minutes (`quiet_for`, `Run.sessions`), so the young ghost either comes back or ends, and every path goes on: launch does not refuse on an ended row, record salvages or files DIED, a verifier goes to `no-verdict`. `REGRESS_65` restores a ghost that never ends (and cleanup that skips it): `regress-65.cfg` must break NoDeadlock on that path and NoSessionLeftAtEnd on a ghost left at the end.
- The 2026-11-05 probe showed that a session does not come back after `claude stop` ran on its ghost; the 2026-11-06 probe showed what the stop leaves (state kept, status and pid removed). With part 3 a run.py stop ends the row at once, whatever it was. No dead end remains in the model.
- A stopped `blocked` row (an idleBlocked session stopped before part 3) would read as live and stuck, not as a ghost; the model does not draw that pre-part-3 variant, since part 3 ends it like every other noted row.

## Fixed issues

0.12.0 fixed the six breaks the model found in 0.11.2 and 0.11.3. Each had an `ALLOW_*` switch that gave the Manager or the operator the real way out; the switches are gone, and `check.cfg` is expected to hold every rule. What the code does now, and where:

| Issue | Was | Now |
|---|---|---|
| #56 | at the last attempt the stuck, BLOCKED, unclosed and unknown hints said `launch`, which `refuse_past_cap` refused | every retry hint comes from `retry_next` (565-573): `abandon` at the cap |
| #57 | `stop_live` and `cmd_abandon` stopped worker sessions only | both stop the live verifier too, with `record_row` and no row (3140-3159, 3386-3389) |
| #58 | an idle worker with no result got `claude logs <sid>`, no run.py step | the `unknown` hint adds `run.py stop <id>, then run.py record and run.py launch <id>` (2060-2062) |
| #59 | `refuse_past_cap` exempted every STOPPED row, a recovery stop too | only `Reason: pause` is exempt (1451-1458); `cmd_stop` writes the reason (3358-3360); `stopped_next` retries after any other stop (583-587) |
| #61 | `launch` refused a worker that waited on a prompt after its result | `idle_and_filed` accepts a stuck worker whose work is filed (1246-1253) |
| #62 | `record` filed a Manager BLOCKED row for a verifier that waited after its verdict; the row hid the verdict and the hint said plain `verify`, refused | `record` stops that verifier, files no row, and goes on to `verified` (1987-1993); a Manager row without a verdict hides nothing (2029-2033) |

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

| `regress-65.cfg` | a ghost row never ends, and cleanup skips it (before 0.12.1, #65) | `NoDeadlock` (4 steps: ISSUES, the worker's process dies, 30 quiet minutes pass; the hint says launch, launch refuses on the live row, stop does not clear it) and `NoSessionLeftAtEnd` (6 steps: the verifier's process dies after its verdict; close merges; the ghost row is left) | #65 |
| `regress-65b.cfg` | run.py does not note the sessions it stops (before part 3 of #65): a stopped idle/working row is a young ghost (`ghostStopped`) | `StoppedIdleNeverRefuses` (4 steps: ISSUES, the worker goes idle, launch stops it and refuses on its ghost row). Not `NoDeadlock`: the ghost ends after 30 quiet minutes; the cost is the wait, which the rule names. The first run of this config also broke NoDeadlock, NoMergeWithoutPassingVerdict and NoSessionLeftAtEnd: those came from the model letting a stop-induced ghost come back as idle (a stopped verifier filed check-only after the close; a stopped worker came back and blocked the launch for good), which the probe does not support; `ghostStopped` does not come back | #65, the field's fix-round refusal |

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
| 12a | `regress-65.cfg` | `view.mjs` | REGRESS_65 | must break NoDeadlock and NoSessionLeftAtEnd |
| 12b | `regress-65b.cfg` | `view.mjs` | REGRESS_65B | must break StoppedIdleNeverRefuses |
| 13 | `overview.cfg` | `overview-view.mjs` | local, OPERATOR_PAUSES = FALSE, FULL_ENV = FALSE | every rule holds; 106 states, under the 500-state budget, so a full chart: the README diagram. The operator's pause is left out to stay under the budget; `pause.cfg` checks it |
| 14 | `overview-pr.cfg` | `overview-view.mjs` | as 13, pr mode | as 13, with the request states |

A TLC run reports one dead end per config (the shortest). The statechart command removes a broken invariant itself and runs again. The constants `MAX_ATTEMPTS`, `MERGE_MODE`, `HIGH_RISK`, `FULL_ENV`, `OPERATOR_PAUSES` and the `REGRESS_*` flags are set in each config.

`FULL_ENV = FALSE` keeps only the main flow of the environment: a worker reports and ends, a stopped worker exits, a verifier files and ends, the operator merges, the host moves the request. No idle, blocked, prompted, failed or ghost sessions, no dirty worktree, no unfiled report. It is for the overview chart, not for the check.

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
