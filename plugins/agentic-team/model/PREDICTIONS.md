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
