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
