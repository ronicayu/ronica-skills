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

Not run yet: TLC needed an approval that the session that wrote this change did not have. Run the configs above and record the counts here.
