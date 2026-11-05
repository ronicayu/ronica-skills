# The lifecycle model

The method comes from poteto's statechart skill in the pstack plugin (https://github.com/cursor/plugins/tree/main/pstack/skills/statechart): a TLA+ model of a system that moves between states, checked with TLC, drawn as a Mermaid statechart, with the shortest path to each state that breaks a rule.

`Lifecycle.tla` models the task-attempt lifecycle of `scripts/run.py` as it is in this version of the plugin (0.11.2). It reads the code, not the docs: what `record` prints as `next:`, what each command refuses, what each command writes. Its purpose is to find dead ends (a state where the hinted command is refused or useless and nothing else moves) and lost transitions before an operator does. Line numbers in the model and in this file are of `scripts/run.py` at this version; keep them current when the code moves.

## How to read the model

- The Manager's only moves are the command that `record` names in its `next:` hint, and `record` itself. `Hint` is a derived operator: what `record` would print from the current state. `Record` is an action only when `record` writes something (a row, a meta, a `claude stop`); while it would, `Hint = "record"` and no other command is enabled.
- A refused command (exit 2) is not enabled. A command that would change nothing is not enabled either. `Done` is the only self-loop, for the end states (merged, or abandoned). So TLC's deadlock check is the rule "no dead end".
- Hints that name no run.py command (`claude logs <sid>`, `tg add ... --type decision`, "record later", "merge it on the host", "reopen it") are `"none"`: the Manager waits for the world to move.
- Two hints are read, not copied: `unclosed_next` for check-only ("verify --again for a stronger verdict, or accept it") maps to `verify --again`; verify-blocked is left out (it acts like check-only in every modelled decision).
- Sessions keep their state until something acts on them. An idle verifier may wake up or go quiet (30 minutes, `VERIFIER_QUIET_MINUTES`); an idle worker, and every quiet, blocked, prompted, failed or finished session, changes only when a command stops it. A worker files one result per attempt, as its last step (worker.md), and its row may stay live for a while after that.
- The pause (`run.py stop`) is the operator's order: a STOP first line in the standing orders (`Orders.stop`, 365-372), which also refuses launches (1194-1195, exit 3) and holds merges (3198-3200, 2948-2949). The code accepts `stop` for any live worker row (3246); the model fires it from a working session under a STOP order, and with a switch as the Manager's way out of an idle worker or a worker on a prompt after its result, which no `next:` hint names. A stop without a STOP order is a recovery stop (#59): the model remembers it (`recoveryStop`) because the owner's rule says it counts as an attempt.
- The operator's free moves (write a STOP order, lift it, order a pause) are behind `OPERATOR_PAUSES`. With them on, every state has a step out (order, pause, lift, launch), so TLC's deadlock check would find nothing: the check configs keep them off, so that "no dead end" means "following record's hints leads out". `pause.cfg` turns them on to check the pause flow itself. The recovery stop stays a Manager move (a switch's way out) in every config.

## Actions and the code they model (scripts/run.py, 0.11.2)

| TLA+ action | run.py | Lines |
|---|---|---|
| `Launch` | `cmd_launch` without `--attempt`, `--base`, `--model`; `idle_and_filed` (a live row that is idle with its work filed is stopped, `stopped-idle`); `refuse_past_cap` | 1192-1383, 1181-1189, 1248-1261, 1386-1389 |
| `LaunchStopsIdleThenRefuses` | the same launch when a later check refuses: the idle rows are stopped (1250-1258), then line 1265 (a pause not committed) or 1386 (the cap) refuses | 1250-1265, 1386 |
| `VerifyPlain`, `VerifyAgain` | `cmd_verify` in session mode; `refuse_unless_running`, `worker_for`, `verifier_over`; a verifier whose turn is over is stopped before a new one starts | 1484-1565, 1459-1481, 1778-1791, 1508-1511 |
| `CloseAuto`, `CloseManual` | `cmd_close`, `choose_verdict`, `resume_close`, `stop_live`, `publish` with catch-up, `host_catch_up`, `pr_status` (clean: merge), `merge_branch` | 3125-3192, 3098-3122, 3072-3095, 3038-3051, 2712-2766, 2794-2838, 2911-2961, 3195-3222 |
| `Stop` | `cmd_stop` | 3241-3256 |
| `Abandon` | `cmd_abandon` (stops the task's worker sessions, not a verifier) | 3259-3281 |
| `Merged` | `cmd_merged`; never fires: the hints that name it (`pr-changed`, `push-refused`) need a request head that moved or a push someone else won, both out of scope | 3227-3238 |
| `Record` | `cmd_record` -> `record_in_progress`, `record_done`: `commit_stopped` first (the #54 fix), `file_stuck`, `lost_verifier`, `verifier_filed`, `salvage_verifier`, `salvage`, `record_arrived`, `emit_verified`, `unclosed_next`, `ready_events`, `merged_into` | 2041-2057, 1883-1998, 2000-2020, 1895-1899, 1829-1873, 1665-1676, 1794-1799, 1764-1775, 1813-1826, 1735-1755, 1678-1713, 1625-1634, 551-561, 2023-2027, 2011 |
| `Done` | the end states: merged, or abandoned | - |
| `Worker*`, `Verifier*` | the rows of `claude agents --json --all` as `Session.__init__` reads them: `finished`, `live`, `stuck`, `unknown`, `turn_over` | 424-455 |
| `WorkerFiles*`, `VerifierFiles` | the one `result add` command of a session's brief (`result_command`), as `is_worker_result`, `latest_worker`, `verifier_rows`, `verdict_of` read the rows | 677-682, 508-531 |
| `VerifierLeavesReport` | a report file or transcript that `salvage` and `parse_report` find for a verifier that filed nothing | 1716-1755 |
| `WorkerDirties` | uncommitted files in the task worktree, as `cmd_launch` and `commit_stopped` see them | 1333-1344, 1858-1868 |
| `HostDecides`, `TargetMoves`, `CheckFails`, `CheckPasses`, `SomeoneMerges`, `SomeoneCloses`, `SomeoneReopens` | the request states that `pr_status` and `publish` read from the host | 2911-2961 |
| `OperatorMerges` | local mode: a merge by hand that `record_done` finds with `merged_into` | 2009-2014 |
| `OperatorOrdersStop`, `OperatorLiftsStop` | a STOP first line written to or removed from the standing orders (`Orders.stop`); while it stands, `cmd_launch` exits 3 and `merge_branch`/`pr_status` say ready-to-merge instead of merging | 365-372, 1194-1195, 3198-3200, 2948-2949 |

## What the model leaves out

- `wait` and `notify-to`: `wait` polls and writes nothing; the notify line only wakes the Manager, which then runs `record`. Neither changes the state the model reads.
- Other tasks, decisions (`waits_for`, `gated`, `answered`), dependencies, slots and `check_cap`, `adopt`, `status`, `cleanup` (it never stops a live session: "never forces", line 2567 keeps a folder with a live row). Of the standing orders only the STOP first line is in (`stopOrder`); a MERGE: line is always present.
- `verify_mode = ci:*`, `verify_kind` other than code, `test-verified` (acts like artifact-verified for a code task), `verify-blocked` (acts like check-only), `--override-verifier`, a `--verdict` that differs from the verifier's, `--ref`, `--attempt`, `--base`, `--model`, `--dry-run`.
- Git details: a branch at another head (`branch_at`, `same_change`, `pr-changed`, `take_host_head`, `caught_up_from`), a missing or plain worktree folder, a wrong branch in it, a dirty or detached main checkout, `kept` (a `claude stop` that fails), `push-refused` and a gone remote branch. A failed first push (`push-failed`, line 2726) is in: the task is done and unpublished until a later close pushes.
- Tokens, report text, report file paths, transcripts: a verifier's unfiled report is one flag (`vreport`) with a passing verdict. A worker's unfiled report is left out: a salvaged PASS or ISSUES leads to the same hint as a filed one.
- Unrecorded session rows and `record_row`: every session is recorded by the command that started it.
- A verify row without a `Verdict:` line (`verified: no Verdict line`): verifier rows always carry a level.
- A second verifier session's folder name and rank: one verifier row at a time; `verify --again` replaces it.
- `host-error`, `merge-failed`, `pr-draft`, `pr-unpinned`; `pr_status`'s UNKNOWN state is folded into "pending".

## Simplifications

1. Rows are summarised: the newest task row (`lastTask`: PASS, ISSUES, BLOCKED, BLOCKEDmgr for `file_stuck`, DIED, STOPPED without a Head line, STOPPEDhead, ABANDONED), `latest_worker` (`workerResult`), the newest verifier-authored verify row (`vv`), the newest Manager verify row (`vManager`: BLOCKED, or manual for `close --verdict`), their order (`vNewer`, what `r["id"] > newest_manager` reads), and `vfiled` (`verifier_filed`: a row covers the newest verifier session).
2. One worker and one verifier session at a time. `claude stop` is immediate except after `run.py stop`, where the row stays busy ("stopping") until the process exits, so that `commit_stopped`'s "has not exited yet" branch exists.
3. The host's answer after a push is a free choice among the open states (pending, clean, behind, blocked, dirty). Requests move: pending -> any decided state; clean or blocked -> behind; clean <-> blocked; any open -> merged or closed by someone; closed -> pending by a reopen. "behind" moves only by the host's rebase (close) or by a merge or close by hand.
4. A local merge either succeeds or conflicts (a free choice); a conflict is a decision for the operator, who can then merge by hand.
5. `HIGH_RISK = TRUE`: a PASS goes to a verifier session. With FALSE, `record_arrived` tells the Manager to rerun VERIFY itself and close with `--verdict L` (`CloseManual`), where the model lets the Manager pick any level.
6. `MAX_ATTEMPTS = 2` (the code has 3): two attempts show the retry and the cap. `AttemptBound` explores up to 3; TLC checks the rules in the states one step past it, so `TypeOK` allows 4.
7. The thirty quiet minutes are one environment step (`VerifierQuiet`). The worker has no quiet state: the code treats an idle worker the same at any age.
8. The STOP order is one boolean the operator sets and lifts (`OperatorOrdersStop`, `OperatorLiftsStop`). `recoveryStop` marks the attempt's STOPPED row as a stop made without the order; the code does not record that difference, the owner's rule (#59) needs it. The rule is read as stated: a stop of an idle worker while a STOP line stands counts as an ordered pause, not as a recovery.

## Rules

- `VerdictNotLost`: once the verifier's session ended or its turn ended, a verify row covers it, or record is about to write one, or record says no-verdict, or a pause is pending (a STOPPED row without a Head line: record finishes it first by design, 1898, and the record after the commit finds the lost verifier). An invariant, not a liveness property: the model has no fairness (a PROPERTY would need weak fairness on `Record` and on the paused worker's exit), and a state is easier to read than a lasso. The pause-first transient was the only false break the invariant gave.
- `NoMergeWithoutPassingVerdict`: done or merged implies the verdict meta is passing and a verify row of the attempt carries it.
- `AttemptCap`: the attempt never passes MAX_ATTEMPTS. `refuse_past_cap` (1386) exempts any STOPPED row, so a stop at the last attempt lets the next launch pass the cap. The owner's rule (#59): only a pause the operator ordered (a STOP line when `run.py stop` ran) is exempt; a stop that recovers a quiet or broken session counts as an attempt. The rule as written cannot tell the two apart and breaks on both: `ALLOW_PAUSE_PAST_CAP` takes the intended one out (an ordered pause at the cap ends in abandon in the model), `ALLOW_RECOVERY_STOP_PAST_CAP` the bug.
- `PausedWipCommitted`, from "Phase 2 of a pause: commit the WIP of a stopped worker that has exited" (commit_stopped, 1830).
- `PauseFinishedFirst`, from "finish the pause first: launch needs its Head line" (record_in_progress, 1898).
- `LaunchCommitsLeftovers`, from "A dirty worktree never reaches a worker silently" (cmd_launch, 1333).
- `OneRequestPerTask`, from "Never unset pr, pr_branch, pushed or target: one request per task across attempts" (cmd_launch, 1369).
- `NoSessionLeftAtEnd`, from "Remove the sessions and worktrees of a merged task" (cleanup, 2538) and `cmd_abandon`: an end state leaves no live session of the task.
- No dead end: TLC's deadlock check, with `Done` for the end states.

## Known breaks and their switches

Each `ALLOW_*` constant, when TRUE, takes one known break out of the check by giving the Manager or the operator the real way out, so that TLC reports the next one. The method: run `check.cfg`, read the shortest path of each break, then the peel configs in order, each adding one switch.

| Constant | Break | Way out when TRUE |
|---|---|---|
| `ALLOW_IDLE_WORKER` | #58: an idle worker with no result; `record` says `unknown ... next: claude logs <sid>` (1964), no run.py step | `Stop` on the idle worker (cmd_stop accepts it) |
| `ALLOW_PROMPT_AFTER_RESULT` | a worker filed its result and sits on a permission prompt; `record_arrived` says launch (1708, 1711), `cmd_launch` refuses on the live row (1261; `idle_and_filed` excludes a row with `waitingFor`) | `Stop` on that worker. Not filed as an issue yet: the worker's brief ends with the result command, so the prompt would come from the notify line |
| `ALLOW_STUCK_AT_CAP` | #56: at the last attempt the stuck (1957, 1691) and BLOCKED (1711) hints say launch; `refuse_past_cap` (1386) refuses; only the ISSUES (1708) and died (1981, 1993) hints check the cap | every launch hint at the last attempt is read as abandon (the `Hint` wrapper), except after a pause |
| `ALLOW_BLOCKED_ROW_HIDES_VERDICT` | a verifier files its verdict, then hits a permission prompt; `record` stops it and files a Manager BLOCKED row (1904-1909); the row outranks the verdict (1937), `record_arrived` says plain `verify` (1702), which 1498 refuses because verifier rows exist. Not filed as an issue yet | `VerifyAgain` fires where the hint says plain `verify` and verifier rows exist |
| `ALLOW_VERIFIER_LEFT_AT_END` | #57: `stop_live` (3040) and `cmd_abandon` (3267) stop task-kind sessions only; a live verifier stays after the task is merged or abandoned | the operator stops it by hand when the task ends (`VerifierAtEnd`) |
| `ALLOW_RECOVERY_STOP_PAST_CAP` | #59: a stop that recovers a quiet or broken session at the last attempt (no STOP order), then a launch past the cap: 1386 exempts every STOPPED row | the launch hint after a recovery stop at the cap is read as abandon (the stop counts as an attempt) |
| `ALLOW_PAUSE_PAST_CAP` | AttemptCap on an ordered pause at the last attempt, then a launch past the cap. Intended by the owner's rule; the rule as written cannot tell it from #59 | the launch hint after an ordered pause at the cap is read as abandon, so the rest can be checked |

Fixed in 0.11.2 and no longer reported (the model shows them gone): a pause while a verdict is recorded left the WIP uncommitted for ever (#54: `record` finishes the pause first, 1895-1899); a live verifier that filed and ended its turn refused every launch (#55: `idle_and_filed`, launch stops it, 1250-1258); the same for an idle worker with its result filed.

## Configs, in run order

| # | Config | View | Switches | Expect |
|---|---|---|---|---|
| 1 | `check.cfg` | `view.mjs` | all FALSE, OPERATOR_PAUSES = FALSE | the #58 dead end (2 steps); NoSessionLeftAtEnd (#57, 6 steps) breaks |
| 2 | `peel-1.cfg` | `view.mjs` | + ALLOW_IDLE_WORKER | the prompt-after-result dead end (3 steps); AttemptCap breaks by #59 (a recovery stop of an idle worker at the cap, 9 steps) |
| 3 | `peel-2.cfg` | `view.mjs` | + ALLOW_PROMPT_AFTER_RESULT | the #56 dead end (6 steps) |
| 4 | `peel-3.cfg` | `view.mjs` | + ALLOW_STUCK_AT_CAP | the BLOCKED-row dead end (7 steps) |
| 5 | `peel-4.cfg` | `view.mjs` | + ALLOW_BLOCKED_ROW_HIDES_VERDICT | no dead end; AttemptCap (#59) and NoSessionLeftAtEnd still break |
| 6 | `peel-5.cfg` | `view.mjs` | + ALLOW_VERIFIER_LEFT_AT_END, ALLOW_RECOVERY_STOP_PAST_CAP, ALLOW_PAUSE_PAST_CAP (all TRUE) | nothing breaks |
| 7 | `check-pr.cfg` | `view.mjs` | all FALSE, pr mode | as 1 |
| 8 | `peel-pr-all.cfg` | `view.mjs` | all TRUE, pr mode | nothing breaks |
| 9 | `pause.cfg` | `view.mjs` | all TRUE, OPERATOR_PAUSES = TRUE | nothing breaks. With ALLOW_PAUSE_PAST_CAP = FALSE it shows the ordered pause at the cap (AttemptCap, 10 model steps), which the owner's rule allows |
| 10 | `pause-pr.cfg` | `view.mjs` | as 9, pr mode | nothing breaks |
| 11 | `regress-54.cfg` | `view.mjs` | peel-5 + REGRESS_54 | must break: PauseFinishedFirst and NoDeadlock (see below) |
| 12 | `regress-42.cfg` | `view.mjs` | peel-5 + REGRESS_42 | must break: NoDeadlock and VerdictNotLost (see below) |
| 13 | `overview.cfg` | `overview-view.mjs` | all TRUE, OPERATOR_PAUSES = TRUE, FULL_ENV = FALSE | nothing breaks; under the 500-state budget, so a full chart: the README diagram |
| 14 | `overview-pr.cfg` | `overview-view.mjs` | as 13, pr mode | as 13, with the request states |

A TLC run reports one dead end per config (the shortest). The statechart command removes a broken invariant itself and runs again, so the other rules need no peeling. The constants `MAX_ATTEMPTS`, `MERGE_MODE`, `HIGH_RISK`, `FULL_ENV`, `OPERATOR_PAUSES`, `REGRESS_54` and `REGRESS_42` are set in each config.

`FULL_ENV = FALSE` keeps only the main flow of the environment: a worker reports and ends, a stopped worker exits, a verifier files and ends, the operator merges, the host moves the request. No idle, blocked, prompted or failed sessions, no dirty worktree, no unfiled report. It is for the overview chart, not for the check.

## Sensitivity checks

Run these when you change the model: if they stop breaking, the model has gone blind. Each `REGRESS_*` constant, when TRUE, restores a bug the code has fixed, so the check must find the old path again.

| Config | Restores | Must break | The old path |
|---|---|---|---|
| `regress-54.cfg` | `record` no longer finishes a pause first (before 0.11.2, #54): the STOPPED row is handled only after the verifier and verdict checks | `PauseFinishedFirst` (6 steps: a recovery stop while a verifier runs; record says `verifying`, the WIP waits), `NoDeadlock` (9 steps: a verify-failed verdict recorded, then a recovery stop; record says `unclosed ... launch`, launch refuses "WIP is not committed yet" for ever) | NOTES of the 0.11.1 study: "A8" |
| `regress-42.cfg` | a failed row counts as live (before 0.10.3, #42) | `NoDeadlock` (2 steps: the worker fails; `record` says `unknown`, no run.py step, and the #58 way out stops only an idle row), `VerdictNotLost` (4 steps: the verifier fails; `record` says `verifying` for ever) | the 0.10.2 study: "B1", "B2" |

Add one when a listed issue is fixed: keep its switch's path as a `REGRESS_*` constant that undoes the fix, and a config that must break.

## How to run

The statechart skill of this repository runs TLC and draws the chart:

```
plugins/statechart/skills/statechart/scripts/statechart plugins/agentic-team/model/Lifecycle.tla \
  --config plugins/agentic-team/model/check.cfg --view plugins/agentic-team/model/view.mjs --out <new folder>
```

Its `setup.sh` installs TLC and Java and prints the `TLA2TOOLS` and `JAVA` values to export; without them the command installs both with mise on the first run. Use a new `--out` folder per run, outside the repository. Each run takes about fifteen seconds. Read `report.md` (the shortest path of each rule that breaks, numbered) and `chart.mmd`.

For the README, run `overview.cfg` with `overview-view.mjs` and copy `chart.mmd` to `assets/diagrams/lifecycle.mmd`.

## Keeping the model current

When `run.py` changes a hint, a refusal, or what a command writes, change the matching action and its line numbers, run `check.cfg` and the peel configs, and update PREDICTIONS.md. When a listed issue is fixed, delete its switch and its row above; the check should then report the path no more.
