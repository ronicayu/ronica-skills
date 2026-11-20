# Predictions for the lifecycle model (0.11.2)

Written from the model, before any run. A run's `report.md` gives the shortest path of each rule that breaks; the paths below are my shortest, TLC may find another of the same length. "Dead end" is TLC's deadlock: a reachable state that is not an end state and has no step out. Constants: MAX_ATTEMPTS = 2, HIGH_RISK = TRUE.

## check.cfg (local mode, every switch FALSE)

- Dead end, 2 steps: launch, the worker goes idle for good. `record` prints `unknown ... next: claude logs` (1964): no run.py step (#58).
- NoSessionLeftAtEnd, 6 steps: launch, the worker reports PASS, you start a verifier, the verifier files passes, the verifier goes idle, you close (the branch merges). The verifier row is still live after the task is merged; `stop_live` (3040) and `cleanup` (2567) leave it (#57).
- AttemptCap, 10 model steps (the view hides the two STOP-order steps, so the report draws 8 arrows): launch, the worker ends, record files DIED, launch (attempt 2), the operator writes a STOP order, the operator orders a pause, the stopped worker exits, record commits the WIP, the operator lifts the STOP order, launch (attempt 3). `refuse_past_cap` (1386) exempts the STOPPED row. This one is an ordered pause, which the owner's rule allows; the rule as written cannot tell it from #59.
- Hold: TypeOK, VerdictNotLost, NoMergeWithoutPassingVerdict, PausedWipCommitted, PauseFinishedFirst, LaunchCommitsLeftovers, OneRequestPerTask.

## peel-1.cfg (+ ALLOW_IDLE_WORKER)

- Dead end, 3 steps: launch, the worker reports ISSUES (or BLOCKED), the worker hits a permission prompt. `record_arrived` says launch (1708, 1711); `cmd_launch` refuses on the live row (1261), and `idle_and_filed` (1185) excludes a row with `waitingFor`. Not filed as an issue: the brief ends with the result command, so the prompt would come from the notify line.
- AttemptCap, now 9 steps, by #59: launch, the worker ends, record files DIED, launch (attempt 2), the worker goes idle for good, you stop the worker (a recovery stop, no STOP order), the stopped worker exits, record commits the WIP, launch (attempt 3).
- NoSessionLeftAtEnd as in check.cfg.

## peel-2.cfg (+ ALLOW_PROMPT_AFTER_RESULT)

- Dead end, 6 steps (#56): launch, the worker ends, record files DIED, launch (attempt 2), the worker ends its turn with a question, record stops the stuck worker and files BLOCKED. The `stuck` hint says launch (1957, 1691) at the last attempt; `refuse_past_cap` refuses. Ties with: launch, the worker ends, record files DIED, launch, the worker reports BLOCKED, the worker ends (the BLOCKED hint, 1711, ignores the cap too).
- AttemptCap and NoSessionLeftAtEnd as before.

## peel-3.cfg (+ ALLOW_STUCK_AT_CAP)

- Dead end, 7 steps: launch, the worker reports PASS, you start a verifier, the verifier files a verdict, the verifier hits a permission prompt, record stops the stuck verifier and files BLOCKED, the worker ends. The Manager row outranks the verdict (1937), `record_arrived` says plain `verify` (1702), which 1498 refuses because verifier rows exist. Not filed as an issue yet.
- AttemptCap and NoSessionLeftAtEnd as before.

## peel-4.cfg (+ ALLOW_BLOCKED_ROW_HIDES_VERDICT)

- No dead end. The paths that were dead ends in 0.11.1 are gone: a pause while a verdict is recorded (record commits the WIP first, 1895-1899), a live verifier or idle worker with filed work that refused every launch (launch stops it, 1250-1258).
- AttemptCap and NoSessionLeftAtEnd break as before.

## peel-5.cfg (every switch TRUE)

- Nothing breaks. The state count is likely above the 500-state chart budget, so no chart; the report gives the count.

## check-pr.cfg and peel-pr-all.cfg (pr mode)

- check-pr: the same dead end, AttemptCap and NoSessionLeftAtEnd paths as check.cfg (the NoSessionLeftAtEnd path ends with the host saying clean and `close` merging the request).
- peel-pr-all: nothing breaks. The request states after close (pending, behind, blocked, dirty, closed, a failed first push) all have a host, operator or Manager step out.

## overview.cfg and overview-pr.cfg (FULL_ENV = FALSE, every switch TRUE)

- Nothing breaks, well under 500 states: a full chart. With `overview-view.mjs`, about thirteen states (Not started, Worker working, Worker gone no result, Died no result, Reported PASS, Reported ISSUES or BLOCKED, Paused, Verifier working, Verifier gone no verdict, Verdict filed, Verdict recorded not closed, Closed waiting for the merge, Merged, Abandoned) and about twenty arrows. Steps that stay in one label (the STOP order, the paused worker's exit, the operator's merge before record records it) are not drawn.

## Not predicted, to classify if it appears

Any other dead end is either a run.py behaviour to confirm at the line, or a model artifact to fix in `Lifecycle.tla` with a note here.

# Round 2 of the repo model (759222a + the pause gate, the regression constants, the relaxed VerdictNotLost)

Written before the run. Changes since the section above: the operator's free moves (STOP order, lift, ordered pause) sit behind `OPERATOR_PAUSES`, off in the check and peel configs; `VerdictNotLost` allows a pending pause; `REGRESS_54` and `REGRESS_42` restore two fixed bugs; the overview view labels every step. The first run (model-runs/) found no dead end anywhere because the operator could always write a STOP order, and a 6-step `VerdictNotLost` transient (a pause ordered while a lost verifier waits); both are addressed here.

| Config | Dead end (NoDeadlock) | Other breaks | Holds |
|---|---|---|---|
| check.cfg | #58, 2 steps: launch, the worker goes idle for good | NoSessionLeftAtEnd (#57), 6 steps: launch, PASS, verifier, files passes, verifier goes idle, close | AttemptCap (no pause can happen: no STOP order, no recovery stop without its switch), VerdictNotLost, the rest |
| peel-1.cfg | prompt after result, 3 steps: launch, reports ISSUES, hits a permission prompt | AttemptCap by #59, 9 steps: launch, the worker ends, record files DIED, launch (attempt 2), the worker goes idle, you stop the worker, the stopped worker exits, record commits the WIP, launch (attempt 3); NoSessionLeftAtEnd | the rest |
| peel-2.cfg | #56, 6 steps: launch, the worker ends, record files DIED, launch, the worker ends its turn with a question, record files BLOCKED (hint launch, the cap refuses); ties with the BLOCKED report at the cap | AttemptCap, NoSessionLeftAtEnd | the rest |
| peel-3.cfg | BLOCKED row hides the verdict, 7 steps: launch, PASS, verifier, files a verdict, hits a prompt, record files BLOCKED, the worker ends | AttemptCap, NoSessionLeftAtEnd | the rest |
| peel-4.cfg | none | AttemptCap, NoSessionLeftAtEnd | the rest |
| peel-5.cfg | none | none | all |
| check-pr.cfg | as check.cfg | as check.cfg (the #57 path ends with the host saying clean and close merging) | as check.cfg |
| peel-pr-all.cfg | none | none | all |
| pause.cfg | none (every state has an operator step out, by design of this config) | none; with ALLOW_PAUSE_PAST_CAP = FALSE: AttemptCap, 10 model steps (launch, the worker ends, record files DIED, launch, the operator writes a STOP order, orders a pause, the stopped worker exits, record commits the WIP, the operator lifts the order, launch) | all |
| pause-pr.cfg | none | none | all |
| regress-54.cfg | 9 steps: launch, PASS, verifier, files fails, the verifier ends, you close (verify-failed recorded), the worker goes idle, you stop the worker, the stopped worker exits; record says `unclosed ... launch`, launch refuses "WIP not committed yet" for ever (the 0.11.1 "A8") | PauseFinishedFirst, 6 steps: launch, PASS, verifier, the worker goes idle, you stop the worker, the stopped worker exits; record says `verifying`, the pause is not finished | the rest (VerdictNotLost holds: the pause row covers the transient) |
| regress-42.cfg | 2 steps: launch, the worker fails (live and unknown; `claude logs`; the #58 way out stops only an idle row) | VerdictNotLost, 4 steps: launch, PASS, verifier, the verifier fails (live, "verifying" for ever) | the rest |
| overview.cfg | none | none | all; I expect fewer than 500 states (FULL_ENV off: 4 worker states, 3 verifier states), so a full chart with about 14 states |
| overview-pr.cfg | none | none | all; a full chart with the request states |

If check.cfg again reports no dead end, the gate is wrong: look for a step out of "Worker idle" other than `Stop` with `ALLOW_IDLE_WORKER`.

# agentic-team 0.12.0 (the six fixes: #56, #57, #58, #59, #61, #62)

Written from the model before any run. The ALLOW_* switches are gone with the breaks they covered; `AttemptCap` is now an action property that states the owner's rule (the attempt passes the cap only by a launch after an ordered pause). MAX_ATTEMPTS = 2, HIGH_RISK = TRUE.

| Config | Expect |
|---|---|
| check.cfg | Every rule holds and there is no dead end. The idle worker gets `stop` from the `unknown` hint (#58), a recovery stop counts toward the cap (#59: `stopped_next` says launch below the cap, abandon at it), every retry hint says abandon at the cap (#56), a worker on a prompt after its result is stopped by launch (#61), a verifier on a prompt after its verdict is stopped by record and the verdict stands (#62), close and abandon stop the verifier (#57). More than 500 states, so no chart. |
| check-pr.cfg | as check.cfg, with the request states |
| pause.cfg | every rule holds. The ordered pause at the cap passes it (STOPPEDhead with Reason: pause), which AttemptCap allows; a stop of an idle worker under a STOP order is a pause too (the rule as stated). No dead end, by design of the operator's free moves. |
| pause-pr.cfg | as pause.cfg |
| overview.cfg, overview-pr.cfg | every rule holds; under 500 states, a full chart of about 14 states |
| regress-42.cfg | VerdictNotLost, 4 steps: launch, PASS, verifier, the verifier fails (live, record says `verifying`). NoDeadlock, 5 steps: the same, then the worker ends (verify refused "still running", no hint). The failed worker is no longer a dead end: the `unknown` hint names `stop`, which 0.10.2's live row accepts, and launch stops a failed-but-live worker whose result is filed (its status is idle). |
| regress-54.cfg (OPERATOR_PAUSES on) | PauseFinishedFirst, 6 steps: launch, PASS, verifier, the operator writes a STOP order, orders a pause, the stopped worker exits; record says `verifying` and the WIP waits. No dead end (the operator's moves), VerdictNotLost holds (a pending pause is allowed). |
| regress-56.cfg | NoDeadlock, 6 steps: launch, the worker ends, record files DIED, launch (attempt 2), the worker ends its turn with a question, record files BLOCKED; the hint says launch, `refuse_past_cap` refuses. Ties with the BLOCKED report at the cap (launch, ends, DIED, launch, reports BLOCKED, ends). |
| regress-57.cfg | NoSessionLeftAtEnd, 6 steps: launch, PASS, verifier, files passes, the verifier goes idle, close: merged with the verifier still live. |
| regress-58.cfg | NoDeadlock, 2 steps: launch, the worker goes idle for good; the hint is `claude logs` only. |
| regress-59.cfg | AttemptCap, 9 steps: launch, the worker ends, record files DIED, launch (attempt 2), the worker goes idle, you stop the idle worker (the at-cap hint's second alternative, which REGRESS_59 takes; Reason: recover), the stopped worker exits, record commits the WIP (hint launch, the old "after the pause"), launch (attempt 3): the step past the cap follows a recovery stop, not an ordered pause. |
| regress-61.cfg | NoDeadlock, 3 steps: launch, the worker reports ISSUES, the worker hits a permission prompt; the hint says launch, launch refuses the waiting row. |
| regress-62.cfg | NoDeadlock, 7 steps: launch, PASS, verifier, files a verdict, hits a prompt, record files BLOCKED (the row outranks the verdict), the worker ends; the hint is plain `verify`, refused. |

If check.cfg reports a dead end or a break, it is either a path the fixes missed (confirm it in run.py at the line) or a model artifact; either way it goes in NOTES.md before a switch is added.

# agentic-team 0.12.1 (ghost rows, #65, parts 1 and 2)

Written from the model before any run. New: the session values `ghost` (young: no process, live and `unknown`; the CLI may start it again; `claude stop` leaves it) and `ghostGone` (30 quiet minutes: `Run.sessions` counts it as ended, `finished` and `turn_over`); `REGRESS_65` (a ghost never ends and cleanup skips it). The part-1 dead end the model predicted is fixed by part 2, so check.cfg is expected to hold again.

| Config | Expect |
|---|---|
| check.cfg, check-pr.cfg | every rule holds, no dead end. A young ghost worker with no result: the `unknown` hint's stop ends the row (the probe) or leaves it (the field); record commits the WIP (STOPPEDhead, Reason: recover) and hints launch; an ended row lets the launch through at once, a left row refuses it until its 30 quiet minutes end it (no return after a stop). A young ghost with a filed result refuses the launch until it comes back (then launch stops it) or goes quiet (ended). A quiet ghost verifier is lost: `no-verdict`, `verify --again`. A young ghost at the end is allowed (cleanup removes it). |
| pause.cfg, pause-pr.cfg | every rule holds |
| regress-65.cfg | NoDeadlock, 4 steps: launch, the worker reports ISSUES, the worker's process dies (a ghost row), 30 quiet minutes pass (the row stays live under REGRESS_65): the hint says launch, `cmd_launch` refuses on the live row, `idle_and_filed` needs a status, `claude stop` does not change it, no hint names `claude rm`. NoSessionLeftAtEnd, 6 steps: launch, PASS, verifier, files passes, the verifier's process dies, close (merged with the ghost left; before 0.12.1 cleanup skipped it as live). |
| regress-42, -54, -56, -57, -58, -59, -61, -62 | as in the 0.12.0 section (a young ghost always has a step out, so the ghost steps add no shorter dead end) |
| overview.cfg, overview-pr.cfg | every rule holds; no ghost steps (FULL_ENV off), so the chart is the 0.12.0 one, 106 states |

If check.cfg reports a ghost dead end anyway, the path to look at first is a ghost the stop left (`ghostStuck`) that never goes quiet: in the model the quiet step is always available to it, so a dead end there means a hint or a guard reads the row wrongly (`idle_and_filed` is not consulted for a finished row; a `ghostStuck` row has no status, so it is never idle-and-filed).

## Results (run by the coordinator, 2026-11-06, code at 4798d50)

Every prediction matched. check.cfg (11,092 states), check-pr.cfg (12,820), pause.cfg (43,112), pause-pr.cfg (48,728), overview.cfg (106) and overview-pr.cfg (130) hold every rule with no dead end. All nine regress configs break as predicted; regress-65.cfg breaks NoDeadlock and NoSessionLeftAtEnd.

# agentic-team 0.12.1 part 3 (a session that run.py stopped counts as ended, #65)

Written from the model before any run. New: every run.py stop (`stop`, close's `stop_live`, `abandon`, launch's stopped-idle, record's stuck and salvage stops) leaves the row finished at once (`stop_session` notes the id; `Run.sessions` reads the note); the `ghostStuck` value is gone; `REGRESS_65B` restores the pre-part-3 stop (an idle/working row becomes a young ghost); the rule `StoppedIdleNeverRefuses` (an action property, from the idle_and_filed docstring) is checked in every config.

| Config | Expect |
|---|---|
| check.cfg, check-pr.cfg | every rule holds, no dead end. The field's path: launch, PASS, verifier, files verify-failed, the verifier ends, the worker goes idle, close (verdict recorded, not closed; hint launch), launch: it stops the idle worker (its result is filed), the row counts as ended, and the next attempt starts. |
| pause.cfg, pause-pr.cfg | every rule holds |
| regress-65b.cfg | StoppedIdleNeverRefuses, 4 steps: launch, the worker reports ISSUES, the worker goes idle for good, launch stops the idle worker; the row turns into a ghost and launch refuses on it (attempt stays 1). No dead end: the ghost ends after 30 quiet minutes (then launch starts attempt 2), or comes back idle and is stopped again. Every other rule holds. |
| regress-65.cfg | as before: NoDeadlock (4 steps) and NoSessionLeftAtEnd (6 steps) |
| regress-42, -54, -56, -57, -58, -59, -61, -62 | as in the 0.12.0 section |
| overview.cfg, overview-pr.cfg | every rule holds; 106 and 130 states, unchanged |

Line numbers at b7608bb: `STOPPED_FILE` 139, the `Run.sessions` loop 365-375, `stop_session` 481-494.

## Part 3, revised after the first run (model0121c-runs)

Two changes, written before the second run:
- `StoppedIdleNeverRefuses` now counts only the launch step itself (`Launch` or `LaunchStopsIdleThenRefuses`): the first form broke in pause.cfg, pause-pr.cfg and regress-54.cfg on the operator writing a STOP order in such a state (launch exits 3 before it stops anything). Expected now: pause.cfg, pause-pr.cfg hold every rule; regress-54.cfg breaks PauseFinishedFirst only.
- A stop-induced ghost under REGRESS_65B is `ghostStopped`: live, unknown, it does not come back, it goes quiet after 30 minutes. The extra breaks of the first regress-65b run (NoDeadlock, NoMergeWithoutPassingVerdict, NoSessionLeftAtEnd) came from the model letting that ghost come back as idle, which the probe does not support. Expected now: regress-65b.cfg breaks StoppedIdleNeverRefuses only (4 steps: launch, ISSUES, the worker goes idle for good, launch stops it and refuses on its ghost row); no dead end.
- check.cfg, check-pr.cfg, the overviews and the other regress configs: unchanged from the part-3 section.

## Results (part 3, rerun by the coordinator after the revision, code at b7608bb)

Every config matches the revised predictions: check.cfg, check-pr.cfg, pause.cfg, pause-pr.cfg, overview.cfg and overview-pr.cfg hold every rule; regress-42 breaks VerdictNotLost and NoDeadlock; regress-54 PauseFinishedFirst; regress-56, -58, -61, -62 and -65 NoDeadlock; regress-57 NoSessionLeftAtEnd; regress-59 AttemptCap; regress-65b StoppedIdleNeverRefuses.

# agentic-team 0.18.0 (PR #87: roles, the #89 rules, the scratch exclude), code at 74aed9a

Written from the model before any run. New in the model: `vIssues` (the Issues: lines of the verifier's row: blocking, unlabelled, none) and the rule `FixRoundNeedsBlocking`; `ALLOW_UNCHECKED_REPORT` (TRUE: a verifier may file an ISSUES report with no `blocking:` line, worker.md "Report" step 1 -> 2, the filing command checks nothing); `fault`/`faulted` and `FAULTS` (once per run the role file breaks or info/exclude turns read-only; launch and verify refuse; the operator repairs); `VerifyStopsThenRefuses` and the exclude branch of `LaunchStopsIdleThenRefuses`; `NoChangeClose` (0.12.3, #72). Baseline before the edit, this machine: check.cfg 10,766 states (NOTES.md's 11,092 came from an earlier revision of the model).

| Config | Expect |
|---|---|
| check.cfg, check-pr.cfg (ALLOW_UNCHECKED_REPORT on) | `FixRoundNeedsBlocking` breaks, 5 steps: launch, the worker reports PASS, you start a verifier, the verifier files ISSUES/verify-failed with no `blocking:` line, you close (verify-failed recorded): the hint says `fix round: launch`. Every other rule holds, no dead end. More states than before (`vIssues`, the no-change close): about 13,000 and 15,000. |
| peel-1.cfg (ALLOW_UNCHECKED_REPORT off) | every rule holds, no dead end. |
| pause.cfg, pause-pr.cfg | `FixRoundNeedsBlocking` breaks by the same 5-step path; the rest holds. |
| faults.cfg, faults-pr.cfg (FAULTS on, ALLOW off) | every rule holds. The deadlock check is blind inside a broken state (the repair is enabled in every one, by construction); it is meaningful only for the repaired copies, which have the steps their originals had. What the configs check is the invariants and action properties across the refusals' side effects. `StoppedIdleNeverRefuses` holds because its antecedent excludes the exclude refusal (a late check, like the cap). `VerdictNotLost` holds across `VerifyStopsThenRefuses`: the stopped verifier had no verdict, record says no-verdict or salvages. About 3 to 4 times the states of peel-1. |
| regress-42 .. regress-65b | as in the 0.12.1 part-3 section: the same rules break by paths of the same length (the new steps only add longer paths). |
| overview.cfg, overview-pr.cfg | every rule holds; a few states more than 106 and 130 (the no-change close adds a merged state with no merge), still under the chart budget. |
| mailbox/check.cfg | unchanged: the mailbox model did not change; the `ignore_scratch` refusal in `resume_with` settles pending before the try counts, a branch the model has (a pending settle that is not a try). |

If check.cfg holds `FixRoundNeedsBlocking`, the unchecked filing step is not reachable: look at `VerifierFilesUnchecked`'s guard. If faults.cfg reports a dead end, look first at a state where the hint is launch or verify and `OperatorRepairs` is not enabled (the fault variable is "none" there: the refusal must come from something else).

## Results (2026-11-11, code at 74aed9a, model as committed with this section)

Every prediction held, with two notes. Lifecycle (distinct states): check.cfg 13,998 and check-pr.cfg 15,150 break `FixRoundNeedsBlocking` only, by the predicted path (6 steps as TLC counts them: launch, PASS, verifier, the verifier files ISSUES with no `blocking:` line, the verifier ends, close; the hint is then `fix round: launch`); pause.cfg 54,772 and pause-pr.cfg 58,660 the same; peel-1.cfg 10,958, faults.cfg 43,832, faults-pr.cfg 48,440, overview.cfg 110 and overview-pr.cfg 134 hold every rule with no dead end. regress-42 (VerdictNotLost 4, NoDeadlock 5), -54 (PauseFinishedFirst 6), -56 (NoDeadlock 6), -57 (NoSessionLeftAtEnd 6), -58 (NoDeadlock 2), -59 (AttemptCap), -61 (NoDeadlock 3), -62 (NoDeadlock 7), -65 (NoDeadlock 4), -65b (StoppedIdleNeverRefuses) break as before.

Note 1: regress-65.cfg breaks NoDeadlock only. NOTES.md's sensitivity table also named NoSessionLeftAtEnd; the pre-edit model (HEAD before this change) gives the same result (10,420 states), so the table was stale since part 3 of #65, where a close's stop ends a ghost row. The part-3 results above already said so. Corrected in NOTES.md.

Note 2: mailbox/check.cfg (the ADR as written, every FIX_* off) breaks the seven rules its round-1 table lists (NoDoorbellAfterAttemptEnds, AskerNeverFiledDead, SteersSettledOnceAttemptOver, AnswersSettledOnceAttemptOver, ClosedTaskHasNoUnreadSteer, InboxShowsEveryUnreadMessage, DoorbellOnlyToOwnAttempt) and stops at the 100,000-state bound on the reruns, as it did on 2026-11-09. The mailbox model was not changed: 0.18.0's one messaging change (`resume_with` catching the `ignore_scratch` refusal, a pending settle before the try counts) maps onto a branch the model has.

# agentic-team 0.18.0, round 2 (8006a3c and ff2c8b0: the two fixes)

Written from the model before any run. 8006a3c: `unlabelled_failure` makes `record` hint `verify --again` for a verifier's verify-failed row with no `blocking:` line, and `close` refuse it; the old reading is `REGRESS_89`. ff2c8b0: the exclude check runs before launch, verify and a resume stop or commit anything; the exclude side effects (`VerifyStopsThenRefuses`, the exclude branch of `LaunchStopsIdleThenRefuses`) are gone from the model, and `StoppedIdleNeverRefuses` has no exemption for it.

| Config | Expect |
|---|---|
| check.cfg, check-pr.cfg, pause.cfg, pause-pr.cfg (ALLOW_UNCHECKED_REPORT on) | every rule holds, no dead end. The unlabelled row's path: launch, PASS, verifier, files ISSUES with no `blocking:` line, the verifier ends, record says verified with `verify --again`, a new verifier files (labelled or not); close is refused on the unlabelled row and never hinted for it. States a little above round 1 (the --again loop adds a few). |
| peel-1.cfg, faults.cfg, faults-pr.cfg | every rule holds; faults* a little below round 1 (no side-effect steps). |
| regress-89.cfg | `FixRoundNeedsBlocking` breaks by the round-1 path (6 steps). Nothing else. |
| regress-42 .. regress-65b | as in round 1. |
| overview.cfg, overview-pr.cfg | 110 and 134, unchanged. |
| mailbox/impl-r3.cfg | 181,886, holds, unchanged (the mailbox model did not change). |

Revised before the second run: the first run of check.cfg broke `FixRoundNeedsBlocking` in 9 steps (an unlabelled row, `verify --again`, the new verifier hits a prompt, record files BLOCKED, close). A model artifact: `VerifyAgain` reset `vIssues` while `vv` still held the unlabelled row, so the model hinted close where the code keeps the old row as the newest with a verdict (`with_verdict`, 3462) and `choose_verdict` refuses it. `vIssues` now changes only with `vv`. Expected: check.cfg holds.

## Results (round 2, 2026-11-11, code at ff2c8b0)

Every prediction of the revised round held. check.cfg 15,566, check-pr.cfg 16,718, pause.cfg 60,892, pause-pr.cfg 64,780 (ALLOW_UNCHECKED_REPORT on), peel-1.cfg 10,958, faults.cfg 43,832 and faults-pr.cfg 48,440 (the same counts as round 1: the removed side-effect steps led to states the repair path reached anyway), overview.cfg 110 and overview-pr.cfg 134 hold every rule with no dead end. regress-89.cfg breaks FixRoundNeedsBlocking in 6 steps (13,998 states, the round-1 check.cfg path); regress-42 .. regress-65b break as in round 1. mailbox/impl-r3.cfg holds, 181,886.

# agentic-team 0.19.0 (PR-1 of #97: a closed task is done only once its change is merged)

Written from the model before any run. New in the model: `Closed` (a passing verdict: only a passing close writes one, with `phase=awaiting_merge`), `Awaiting` (closed, not merged, not abandoned), `StatusAfter` (a close or record leaves the task done only with the merge), the rule `DoneOnlyWhenMerged` (status done exactly when merged), and `REGRESS_97` (the old close: `tg done` at once). The closed states keep their other variables and only change `status` from done to in_progress, and `Stop`, `Launch`, the verify and the normal close were already disabled there by the done status, so the state counts should not move.

| Config | Expect |
|---|---|
| check.cfg, check-pr.cfg, pause.cfg, pause-pr.cfg | every rule holds, `DoneOnlyWhenMerged` included, no dead end. 15,566, 16,718, 60,892 and 64,780 states, as round 2. |
| peel-1.cfg, faults.cfg, faults-pr.cfg | every rule holds; 10,958, 43,832 and 48,440 states. |
| regress-97.cfg | `DoneOnlyWhenMerged` breaks in 5 steps: launch, the worker reports PASS, you start a verifier, the verifier files a passing verdict, you close and the local merge waits: the task is done and not merged. Nothing else breaks. 15,566 states (the round-2 check.cfg model). |
| regress-42 .. regress-89 | as in round 2; `DoneOnlyWhenMerged` holds in each. |
| overview.cfg, overview-pr.cfg | 110 and 134, every rule holds. The views now read a closed task from its verdict, so the chart keeps "Closed, waiting for the merge". |
| mailbox/impl-r3.cfg | unchanged (the mailbox model did not change). |

If `DoneOnlyWhenMerged` breaks in check.cfg, look for a step that sets `merged` without `status` (a `Record` path that `StatusAfter` does not cover) or a close that sets `status` from a stale `merged'`. If `PauseFinishedFirst` breaks, look for a closed task that `RecOut` sends to `RecInProgress`.

## Results (0.19.0)

Run on 2026-11-13 with tla2tools 1.7.4. Every prediction held.

| Config | States | Result |
|---|---|---|
| check.cfg, check-pr.cfg | 15,566, 16,718 | every rule holds, `DoneOnlyWhenMerged` included, no dead end |
| pause.cfg, pause-pr.cfg | 60,892, 64,780 | every rule holds |
| peel-1.cfg, faults.cfg, faults-pr.cfg | 10,958, 43,832, 48,440 | every rule holds |
| regress-97.cfg | 15,566 | only `DoneOnlyWhenMerged` breaks, in 6 steps, not 5: the verifier also ends (step 5) before the close |
| regress-42 | 10,388 | VerdictNotLost and NoDeadlock break |
| regress-54 | 41,332 | PauseFinishedFirst breaks |
| regress-56, -58, -61, -62, -65 | 10,852, 10,953, 10,958, 13,070, 10,516 | NoDeadlock breaks |
| regress-57 | 11,534 | NoSessionLeftAtEnd breaks |
| regress-59 | 16,498 | AttemptCap breaks |
| regress-65b | 11,798 | StoppedIdleNeverRefuses breaks |
| regress-89 | 13,998 | FixRoundNeedsBlocking breaks |
| overview.cfg, overview-pr.cfg | 110, 134 | every rule holds; `assets/diagrams/attempt-statechart.mmd` is the new overview chart |

`DoneOnlyWhenMerged` holds in every regress config except regress-97.

# agentic-team 0.19.0, step B of #99 (the phase edges)

Written from the model before any run; this session could not run TLC. New in the model: the operator `Phase` (the phase meta as `derive_phase` reads it), which no action, rule or config reads. Only comments changed besides it: the line numbers moved with run.py's transition table. New beside the model: `phase-view.mjs`, `phase-edges.mjs`, `phase-edges.json` (written by hand from the actions) and `phase-edges-exclusions.json`.

| Config | Expect |
|---|---|
| every config | the same states and the same result as in "Results (0.19.0)": check.cfg 15,566, check-pr.cfg 16,718, pause.cfg 60,892, pause-pr.cfg 64,780, peel-1.cfg 10,958, faults.cfg 43,832, faults-pr.cfg 48,440, overview.cfg 110, overview-pr.cfg 134; each regress config breaks its rule as there and nothing else. SANY parses `Phase` (it uses `Closed` and `WorkerStatuses`, both defined above it). |
| check.cfg and check-pr.cfg through `phase-edges.mjs` (NOTES.md, "Phase edges") | the 18 edges of `phase-edges.json`, so `git diff --exit-code phase-edges.json` is empty. Each config alone gives all 18: in local mode a close waits on a conflict, merges at once by a merge or a no-change close, and record finds the operator's merge; in pr mode a close waits on the request, merges at once on a clean request or a no-change close, and record finds the request merged. I expect no `seen_*` edge but `running -> reported` (no other environment step moves a phase), no edge into `abandoned` from `verifying` or `awaiting_merge` (no hint names abandon there), no edge out of `merged` or `abandoned`, and no `record` label. |
| overview.cfg with `phase-view.mjs` (optional, a chart) | 16 of the 18 edges, in a chart: without FULL_ENV no worker goes idle or gets stuck, so there is no `running -> stopped` (neither the hinted stop nor record's stop of a stuck worker) and no `running -> abandoned` (the unknown hint at the cap). |

If the regenerated file differs: an extra edge with a `record` label means a `Record` path moves the phase in a way the view does not name (read it in the dump, then fix the view or the model). An extra `seen_*` edge means an environment step moves a phase (`WorkerFiles*` aside), which the model did not do before. A missing edge means my reading of a hint was wrong; the test then names the table row that lost its model edge, and the row needs an exclusion with a reason, or the model a fix.

# agentic-team 0.23.0 (#119, rounds)

Written from the model before any run; this session could not run TLC or SANY. New in the model: the constants
`ROUND_CAP`, `ROUND_VERIFY` and `REGRESS_119`; the variables `inRound`, `roundSame`, `rounds`, `mainConflicts`,
`roundPushed` and `unverifiedMerge`; the actions `StartRound`, `RoundCancel`, `RoundMerged`; the environment steps
`TargetConflicts`, `ConflictClears`, `RoundHeadPushed`, `MainConflicts`, `MainConflictClears`; the rules
`RoundIsInFlight` and `NoHintAbandonsWaitingWork`; and changed `NoMergeWithoutPassingVerdict` and `AttemptCap`. Every
config sets `ROUND_CAP = 2` (the overviews `1`), `ROUND_VERIFY = "always"` and `REGRESS_119 = FALSE`, except
`regress-119.cfg` (`REGRESS_119 = TRUE`).

| Config | Expect |
|---|---|
| check.cfg, check-pr.cfg | Every rule holds, no dead end. More states than 15,566 and 16,718 (six variables; a closed task can now start up to two rounds, each a full attempt), I guess three to six times as many. |
| pause.cfg, pause-pr.cfg, peel-1.cfg, faults.cfg, faults-pr.cfg | Every rule holds; more states. |
| overview.cfg, overview-pr.cfg | Every rule holds. More states than 110 and 134: `overview.cfg` reaches a round through a local merge conflict (`LocalMergeStep` may set `mainConflicts`), `overview-pr.cfg` through a request the host marks dirty. If a count passes the statechart command's 516-state budget, the lifecycle chart in docs/lifecycle.md (`assets/diagrams/attempt-statechart.mmd`) cannot be regenerated as a full chart; then note it and keep the old chart, or draw it with `ROUND_CAP = 0` in a copy of the config. |
| each regress config of 0.22.3 | It breaks its own rule as in "Results (0.19.0)", and no other rule (the new rules hold there: no hint abandons a waiting task, and a round is never closed). |
| regress-119.cfg | Breaks `NoHintAbandonsWaitingWork` in 7 steps: you launch, the task session reports PASS, you start a verifier, the verifier files artifact-verified, the verifier session ends, you close and the request opens dirty, you abandon. Nothing else breaks. |
| check.cfg and check-pr.cfg through `phase-edges.mjs` | The 31 edges of `phase-edges.json` (28 table rows once each `close_waits, merged` is split), so `git diff --exit-code phase-edges.json` is empty. New: `awaiting_merge, round, running`; `<p>, round_cancel, awaiting_merge` for running, stopped, reported, verifying and verdict_failed (both configs: a failed round's hint, or the round-not-needed line after `ConflictClears` or `MainConflictClears`); `<p>, merged, merged` for the same five (check-pr.cfg only: `SomeoneMerges` during a round, then `RoundMerged`); `reported, close_waits, awaiting_merge` (the carry: a round's PASS with the same change goes to close with no verifier); `reported, close_waits, merged, merged` (check.cfg only: the carry, and the local merge succeeds). |

If a rule breaks: `NoMergeWithoutPassingVerdict` points at a merge path that writes neither a carried row nor
`unverifiedMerge`; `RoundIsInFlight` at a path that closes or finishes a round without clearing `inRound`;
`AttemptCap` at a round whose `rounds` did not grow; a dead end in a round state means a round hint whose action is
refused (check `RoundCancel`'s guard first). A missing `round_cancel` or `merged` edge for one of the five phases means
my reading of the reachable round states was wrong: find out why before adding an exclusion.

# agentic-team 0.24.0 (#127, revisions)

Written from the model before any run; this session could not run TLC or SANY. New in the model: the constants
`REVISION_CAP`, `SEAT`, `REGRESS_127C`, `REGRESS_127H`, `REGRESS_127W`, `REGRESS_127A`; the variables `revision`,
`workerKept`, `verifierKept`, `findingsOpen`, `verifierAt`, `vvRev`; the actions `Revise`, `WorkerAcksFindings`,
`VerifyResume`, `WorkerKeepEnds`, `VerifierKeepEnds`; the rules `RevisionCap`, `ClosingVerdictOnFinalHead`,
`NoConcurrentWriters`, `FindingsAckedBeforeReport`; and changed `UnclosedNext`, `ArrivedNext`, `VerifyAccepted`,
`VerifyPlain`, `VerifyAgain`, `Record`, `Launch`, `LaunchStopsIdleThenRefuses`, `StopLive`, `Stop`, `Abandon`, `Merged`,
`StartRound`, `WorkerFiles*`, `VerifierFiles*`, `FixRoundNeedsBlocking` and `NoSessionLeftAtEnd`. Every config of 0.23.0
sets `REVISION_CAP = 0`, `SEAT = "own"` and the four `REGRESS_127*` FALSE, adds `RevisionBound` to CONSTRAINT and the
four new rules.

Why the 0.23.0 configs cannot change: with `REVISION_CAP = 0` every new action is disabled (`Revise` needs `RevisionOK`,
which needs `REVISION_CAP > 0`; `VerifyResume` needs `revision > 0`; `WorkerAcksFindings` needs `findingsOpen`, set only by
`Revise`; the keep-time steps need a `*Kept` flag, set TRUE only as `REVISION_CAP > 0`). Every changed action writes the new
variables to their `Init` values there (`workerKept' = (REVISION_CAP > 0)` is FALSE, `verifierAt' = revision` is 0,
`vvRev' = verifierAt` is 0), and the new guards are TRUE (`ReportAllowed`, the seat rule with `SEAT = "own"`,
`~(revision > 0 /\ verifierKept)`), and `RevisionOK` is FALSE, so `UnclosedNext` is `RetryNextOld` as before and
`ArrivedNext` reads `revision > 0` as FALSE. So each state of 0.23.0 maps to exactly one state with the new variables at
`Init`, with the same successors: the same distinct and generated counts, and for a regress config the same first break.
The 0.23.0 counts are from the main session's TLC run of `bf3cab5` (scratchpad `tlc119`).

| Config | Expect |
|---|---|
| check.cfg | Every rule holds, no dead end; 294,921 states generated, 63,272 distinct (as 0.23.0). |
| check-pr.cfg | Every rule holds, no dead end; 2,459,470 generated, 333,260 distinct (as 0.23.0). |
| pause.cfg, pause-pr.cfg, peel-1.cfg, faults.cfg, faults-pr.cfg | Every rule holds; distinct states as 0.23.0: 185,356, 894,808, 44,552, 178,208, 922,640. |
| overview.cfg, overview-pr.cfg | Every rule holds; 286 and 1,054 distinct (as 0.23.0). |
| each regress config of 0.23.0 | The same first break with the same state count: regress-42 VerdictNotLost (57 distinct), regress-54 PauseFinishedFirst (813), regress-56 deadlock (571), regress-57 NoSessionLeftAtEnd (540), regress-58 deadlock (14), regress-59 AttemptCap (1,149), regress-61 deadlock (72), regress-62 deadlock (1,311), regress-65 deadlock (208), regress-65b StoppedIdleNeverRefuses (76), regress-89 FixRoundNeedsBlocking (640), regress-97 DoneOnlyWhenMerged (604), regress-119 NoHintAbandonsWaitingWork (1,345). |
| check-revise.cfg (local, cap 2, seat task) | Every rule holds, the four of #127 included; no dead end. More states than check.cfg: each attempt can now take up to two revisions, each a worker turn and a verifier turn, and the keep flags double some states; I guess 3 to 8 times 63,272. |
| check-revise-pr.cfg | As check-revise.cfg; more states than check-pr.cfg by a similar factor. |
| check-revise-own.cfg (seat own) | As check-revise.cfg; somewhat more states than it, because without the seat rule the verifier may start while the worker's turn still runs. |
| overview-revise.cfg (FULL_ENV = FALSE, cap 1) | Every rule holds; more than 286 states. With `phase-view.mjs` the chart shows `verdict_failed -> running` labelled revise. If it passes the 516-state budget, the statechart command draws no chart; then note it, the edge is still in the check-revise dump. |
| regress-127c.cfg | Breaks `RevisionCap` in 24 steps (two full revisions, then a third `revise` at revision 2). Nothing else breaks first. |
| regress-127h.cfg (seat own) | Breaks `ClosingVerdictOnFinalHead` in 14 steps: the resumed verifier files artifact-verified about revision 0, and close passes at revision 1. |
| regress-127w.cfg | Breaks `NoConcurrentWriters` in 3 steps: launch, PASS (the worker's turn still runs), verify. |
| regress-127a.cfg | Breaks `FindingsAckedBeforeReport` in 9 steps: the first revision's worker files PASS before its acks. |
| regress-89-revise.cfg | Breaks `FixRoundNeedsBlocking` in 7 steps (not 6 as regress-89: with seat task the worker's turn must end before verify). The last hint is `revise` (the worker ended: both sessions kept) or `launch` (it went idle: not finished, so no revision); both are 7 steps, and TLC shows the one it reaches first. |
| check.cfg, check-pr.cfg and check-revise.cfg through `phase-edges.mjs` | The 32 edges of `phase-edges.json`: the 31 of 0.23.0 from check and check-pr, and `verdict_failed, revise, running` from check-revise (written by hand into the fixture). check-revise alone should give all 32: it has every path of check.cfg (a revision is only an extra choice where `RevisionOK` holds, and when the keep time ends first the old path follows). `VerifyResume` gives `reported, verify, verifying`, an edge already there. No other new edge: `WorkerAcksFindings` and the keep-time steps keep the phase. |

If a rule breaks in a revise config: `NoConcurrentWriters` points at a path where the worker becomes busy while a
verifier runs (check `Revise`'s `verifier = "finished"` and the `VerifyAccepted` seat rule); `ClosingVerdictOnFinalHead`
at a verifier row that no `verifierAt` update covers (a salvaged row: `Record` sets `vvRev` from `verifierAt`);
`NoSessionLeftAtEnd` at an end step that leaves a `*Kept` flag; a dead end with hint `revise` means `Revise`'s guard
differs from `RevisionOK`. A count change in a 0.23.0 config means a new variable moved from `Init` there: find the action
that writes it without `REVISION_CAP > 0`.

# Workflow templates W5 (Workflow.tla, and the W4 escalation in Lifecycle.tla)

Written with the model, on the workflow-templates branch after W3 (2d61d1e). The first runs were made while the model was
written, so this section records what each config must show and then the results; the changes that the first runs led to
are named. TLC 2.19 (tla2tools 1.7.4), `-workers 8`, on the Mac Studio; times are wall clock of a run that shared the
machine with one other TLC run.

## Expect

| Config | Expect |
|---|---|
| wf-check.cfg, wf-feature.cfg | Every rule holds, no dead end. |
| wf-hold.cfg | As wf-check; fewer states (a held approval has no due time and no default). |
| wf-overview.cfg | Every rule holds, under the chart budget of 500 states. |
| wf-code-fixed.cfg | Every rule holds; far fewer states (no W4). |
| regress-wf-sink-orphan.cfg | A dead end: the last stage (test, auto) is abandoned and no `stage-orphaned` hint is printed. |
| regress-wf-rechoose-rules.cfg | RuleStagesKept in 2 steps: split (a late rule on ux), rechoose without ux. |
| regress-wf-split-approval.cfg | SplitApprovalAfterAllParts: part 1 of impl merges while part 2 has not. |
| regress-wf-skip-rule.cfg | RuleStagesKept in 1 step: downgrade spec. |
| regress-wf-escalate-loop.cfg | AdjBound in 3 steps: downgrade, escalate, downgrade the escalated stage. |
| regress-wf-no-contract.cfg | NoGhostDeps in the initial state (ux left out, spec still after it). |
| regress-wf-downgrade-done-only.cfg | NoBypass in 2 steps: downgrade ux before prd has run, launch spec. |
| regress-wf-insert-running.cfg | NoBypass (or NoInsertIntoBusy): escalate before impl while it runs. |
| regress-wf-no-default.cfg | Liveness: the human approval of spec is open and past due, and the owner never answers. |
| every Lifecycle config of 0.24.0, with `ESCALATIONS = FALSE` | The same distinct states and the same first break as before the change: `Escalate` is disabled, the new `RecInProgress` branch needs `stopReason = "escalated"`, which nothing else writes. |
| escalate.cfg, escalate-revise.cfg | Every rule holds, `EscalationKeepsAttempt` included; no dead end. |
| regress-esc-cap.cfg | NoDeadlock: an escalation at the cap, then launch refused. |

## Results (2026-11-20)

The first model had no approval on check's impl, so `regress-wf-split-approval.cfg` held (a split stage without an
approval cannot show the bug); check's impl now has `approval: manager`. The first `escalate.cfg` run broke
`PausedWipCommitted` (9 states deep: the escalated STOPPED row over a dirty worktree), and `escalate-revise.cfg` and
`regress-esc-cap.cfg` broke `VerdictNotLost` (an idle verifier with no row stopped by the escalation). `Escalate` now
commits the WIP and needs `vfiled`; both are W4 requirements (NOTES.md). `Cancel` now abandons stages that still run
(`NoSessionAfterEnd`, added with it).

| Config | Result | Distinct states | Depth | Time |
|---|---|---|---|---|
| wf-check.cfg | every rule holds | 2,739,280 (5,434,903 generated) | 60 | 54 s alone, 115 s shared |
| wf-feature.cfg | every rule holds | 934,448 | 57 | 24 s |
| wf-hold.cfg | every rule holds | 925,912 | 59 | 23 s |
| wf-overview.cfg | every rule holds | 298 (the chart: 27 states, 44 arrows) | 24 | 1 s |
| wf-code-fixed.cfg | every rule holds | 8,894 | 34 | 1 s |
| regress-wf-sink-orphan.cfg (was wf-code-orphan.cfg) | **dead end**, 15 steps (prd, spec, impl merged and approved; test launched and abandoned) | 1,333 at the stop | 19 | 1 s |
| regress-wf-rechoose-rules.cfg (was wf-code-rechoose.cfg) | **RuleStagesKept**, 2 steps (Split, Rechoose) | 53 | 7 | 1 s |
| regress-wf-split-approval.cfg | breaks SplitApprovalAfterAllParts, 14 steps (prd, spec approved; split impl; part 1 merges; the approval opens) | 3,397 | 15 | 1 s |
| regress-wf-skip-rule.cfg | breaks RuleStagesKept, 1 step | 26 | 4 | 0 s |
| regress-wf-escalate-loop.cfg | breaks AdjBound, 3 steps | 137 | 7 | 0 s |
| regress-wf-no-contract.cfg | breaks NoGhostDeps in the initial state | 2 | 1 | 0 s |
| regress-wf-downgrade-done-only.cfg | breaks NoBypass, 2 steps | 64 | 5 | 0 s |
| regress-wf-insert-running.cfg | breaks NoBypass, 11 steps (escalate while impl runs); with NoBypass left out, NoInsertIntoBusy at the same step | 1,936 | 13 | 0 s |
| regress-wf-no-default.cfg | breaks Liveness (the spec approval open and past due; stutter) | 176,601 at the stop | - | 3 s |
| (scratch) wf-check with `REGRESS_SINK_ORPHAN = TRUE` | dead end, 15 steps, as regress-wf-sink-orphan: W4 does not help while the hint is missing | 7,263 | 17 | 1 s |

Lifecycle, every config of 0.24.0 with `ESCALATIONS = FALSE`, compared with the same configs run on the committed model
(HEAD 2d61d1e) the same day: every config that holds has the same distinct states (check 63,272; check-pr 333,260; pause
185,356; pause-pr 894,808; peel-1 44,552; faults 178,208; faults-pr 922,640; overview 286; overview-pr 1,054;
overview-revise 928; check-revise 549,352; check-revise-pr 2,979,244; check-revise-own 623,656), and each regress config
breaks the same rule as before (42 VerdictNotLost, 54 PauseFinishedFirst, 56/58/61/62/65 deadlock, 57 NoSessionLeftAtEnd,
59 AttemptCap, 65b StoppedIdleNeverRefuses, 89 and 89-revise FixRoundNeedsBlocking, 97 DoneOnlyWhenMerged, 119
NoHintAbandonsWaitingWork, 127a/127c/127h/127w their #127 rules; the state counts at the stop differ run to run with 8
workers). The phase-edges test passes (`TransitionTest.test_the_table_has_the_edges_of_the_model`).

| Config | Result | Distinct states | Depth | Time |
|---|---|---|---|---|
| escalate.cfg | every rule holds, EscalationKeepsAttempt included | 72,227 | 30 | 2 s |
| escalate-revise.cfg | every rule holds | 620,963 | 48 | 11 s |
| regress-esc-cap.cfg | breaks NoDeadlock, 7 steps (launch, the worker fails, record files DIED, launch attempt 2, PASS, the worker fails, escalate; launch refused at the cap) | 1,198 at the stop | 9 | 1 s |

# Workflow templates W4 (the escalation lands in run.py)

| Prediction | Result |
|---|---|
| `phase-edges.json` regenerated from `check.cfg`, `check-pr.cfg`, `overview-revise.cfg` and `escalate.cfg` differs from the W5 fixture by exactly two edges, `reported, escalated, stopped` and `verifying, escalated, stopped`; a failed verdict keeps `verdict_failed`, so it adds no edge. | Confirmed: the three old configs alone reproduce the old file byte for byte (TLC 2.x, Java 27), and `escalate.cfg` adds those two edges (72,227 distinct states, 2 s). The test `test_the_table_has_the_edges_of_the_model` passes with the two `TRANSITIONS` rows. No exclusion entry was needed. |
