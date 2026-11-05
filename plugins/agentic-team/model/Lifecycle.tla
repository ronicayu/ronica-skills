---- MODULE Lifecycle ----
\* The task-attempt lifecycle of scripts/run.py (agentic-team 0.11.2): one task, its attempts, one worker
\* session and one verifier session at a time, the result rows of the current attempt, the meta that
\* decides the next step, and the request in pr mode. Line numbers are of scripts/run.py at that version.
\*
\* The Manager's only moves are the command that `record` names in its `next:` hint, and `record` itself.
\* A refused command (exit 2) is not enabled. A command that would change nothing is not enabled either.
\* `Done` is the only self-loop: the task is merged or abandoned. So a state with no step out is a dead
\* end for the Manager: the hinted command is refused or useless, and nothing in the world moves.
\*
\* Each ALLOW_* constant takes one known break out of the check: TRUE gives the Manager or the operator
\* the real way out of it, so that TLC reports the next one. NOTES.md names the issue behind each.

EXTENDS Naturals

CONSTANTS MAX_ATTEMPTS,  \* line 89: MAX_ATTEMPTS = 3; the configs use 2
          MERGE_MODE,    \* "local" or "pr": merge.mode of .agentic-team.toml
          HIGH_RISK,     \* TRUE: risk meta "high", so a PASS goes to a verifier session (line 1702)
          FULL_ENV,      \* FALSE: only the main environment steps (overview.cfg), see NOTES.md
          OPERATOR_PAUSES, \* TRUE: the operator may write or lift a STOP order and order a pause at any time
          \* Sensitivity checks: TRUE restores a fixed bug, so the check must break again (NOTES.md):
          REGRESS_54,    \* record no longer finishes a pause first (before 0.11.2, #54)
          REGRESS_42,    \* a failed row counts as live (before 0.10.3, #42)
          \* Known breaks. TRUE takes the path out of the check:
          ALLOW_PAUSE_PAST_CAP,          \* refuse_past_cap (1386) lets a launch pass MAX_ATTEMPTS after an ordered pause (intended)
          ALLOW_STUCK_AT_CAP,            \* #56: launch hints at the last attempt ignore the cap: read them as abandon
          ALLOW_VERIFIER_LEFT_AT_END,    \* #57: close and abandon leave a live verifier: stop it by hand
          ALLOW_IDLE_WORKER,             \* #58: an idle worker with no result gets `claude logs`: run.py stop
          ALLOW_PROMPT_AFTER_RESULT,     \* a worker on a permission prompt after its result: run.py stop
          ALLOW_BLOCKED_ROW_HIDES_VERDICT, \* a Manager BLOCKED row outranks the verdict, plain verify refused: --again
          ALLOW_RECOVERY_STOP_PAST_CAP   \* #59: a stop that recovers a session is exempt from the cap like a pause: abandon

ASSUME MERGE_MODE \in {"local", "pr"}

VARIABLES
  status,        \* Taskgraph status: "open", "in_progress", "done"
  attempt,       \* the attempt meta (0 before the first launch)
  abandoned,     \* the abandoned meta is set
  verdict,       \* the verdict meta: "none" or a level
  merged,        \* the merged_at meta is set
  pr,            \* pr mode: the request and what the host says about it
  mainHas,       \* local mode: the main checkout already contains the verdict commit
  lastTask,      \* the newest result row of kind task for this attempt
  workerResult,  \* latest_worker(rows, attempt): the newest row that counts as a worker report
  vv,            \* the newest verify row by a verifier (its Verdict), or "none"
  vManager,      \* the newest verify row by the Manager: "none", "BLOCKED", or "manual" (close --verdict)
  vNewer,        \* the verifier's row is newer than the Manager's (row id order, line 1937)
  vfiled,        \* verifier_filed (1764): a verify row covers the newest verifier session
  worker,        \* the worker session row of this attempt
  verifier,      \* the newest verifier session row of this attempt
  vreport,       \* the verifier wrote a passing report file it did not file (salvage, 1735)
  wtDirty,       \* the task worktree has uncommitted changes
  stopOrder,     \* the standing orders start with a STOP line (Orders.stop, lines 365-372)
  recoveryStop   \* the attempt's STOPPED row came from a stop without a STOP order (#59: a recovery stop)

vars == <<status, attempt, abandoned, verdict, merged, pr, mainHas,
          lastTask, workerResult, vv, vManager, vNewer, vfiled,
          worker, verifier, vreport, wtDirty, stopOrder, recoveryStop>>
OrderVars == <<stopOrder, recoveryStop>>

\* ---------------------------------------------------------------- values

\* VERDICTS (line 91) without test-verified (acts like artifact-verified for a code task) and without
\* verify-blocked (acts like check-only in every modelled decision).
Levels == {"artifact-verified", "check-only", "verify-failed"}
Passing == {"artifact-verified"}                      \* PASSING["code"], line 94
WorkerStatuses == {"PASS", "ISSUES", "BLOCKED"}
\* Task rows: a worker's report, or a Manager row: BLOCKEDmgr (file_stuck), DIED, STOPPED without a Head
\* line (cmd_stop, stop_live), STOPPEDhead (commit_stopped), ABANDONED.
RowKinds == {"none", "BLOCKEDmgr", "DIED", "STOPPED", "STOPPEDhead", "ABANDONED"} \cup WorkerStatuses
ManagerVerify == {"none", "BLOCKED", "manual"}
\* One row of `claude agents --json --all`, as the Session class reads it (lines 424-455):
\*   busy        status busy, state working
\*   idle        status idle, state working ("it will check back")
\*   idleQuiet   (verifier) idle, and 30 minutes passed with no activity (VERIFIER_QUIET_MINUTES, 136)
\*   idleBlocked state blocked, status idle, no waitingFor: its turn ended with a question
\*   prompt      waitingFor set: a permission prompt
\*   stopping    (worker) `claude stop` was sent, the process has not exited (status still busy)
\*   finished    state done or stopped, status idle or none
\*   failed      state failed, status idle (finished, line 448)
WorkerStates == {"none", "busy", "idle", "idleBlocked", "prompt", "stopping", "finished", "failed"}
VerifierStates == {"none", "busy", "idle", "idleQuiet", "idleBlocked", "prompt", "finished", "failed"}
OpenPr == {"pending", "clean", "behind", "blocked", "dirty"}
PrStates == {"none", "merged", "closed"} \cup OpenPr
Hints == {"launch", "verify", "verifyAgain", "close", "closeManual", "abandon", "merged", "record", "none"}

PrMode == MERGE_MODE = "pr"

\* Session class, lines 448-455. With REGRESS_42 a failed row is live and unknown, as before 0.10.3.
Finished(s) == s = "finished" \/ (s = "failed" /\ ~REGRESS_42)
Live(s) == s \in {"busy", "idle", "idleQuiet", "idleBlocked", "prompt", "stopping"} \/ (s = "failed" /\ REGRESS_42)
Stuck(s) == s \in {"idleBlocked", "prompt"}
Unknown(s) == s \in {"idle", "idleQuiet"} \/ (s = "failed" /\ REGRESS_42)
TurnOver(s) == Finished(s) \/ s = "idleBlocked"
\* verifier_over, lines 1778-1791: a turn that is over, or an unknown row quiet for 30 minutes.
VerifierOver(s) == TurnOver(s) \/ s = "idleQuiet"
\* The rule's words: the session ended, or its turn ended. Independent of the code's predicates.
Over(s) == s \in {"finished", "failed", "idleBlocked"}
\* idle_and_filed, lines 1181-1189: status idle, no waitingFor, and the attempt's work is filed.
IdleStatus(s) == s \in {"idle", "idleQuiet", "idleBlocked"}
WorkerFiled == workerResult # "none" \/ lastTask \in {"BLOCKEDmgr", "DIED"}   \* a task row that is not STOPPED
VerifierFiled == vv # "none" \/ vManager # "none"                             \* any verify row
WorkerIdleFiled == Live(worker) /\ IdleStatus(worker) /\ WorkerFiled
VerifierIdleFiled == Live(verifier) /\ IdleStatus(verifier) /\ VerifierFiled

End == (status = "done" /\ merged) \/ abandoned

\* #57 with ALLOW_VERIFIER_LEFT_AT_END: the operator stops the verifier by hand when the task ends.
VerifierAtEnd == IF ALLOW_VERIFIER_LEFT_AT_END /\ Live(verifier) THEN "finished" ELSE verifier

\* ---------------------------------------------------------------- record

RetryNext == IF attempt < MAX_ATTEMPTS THEN "launch" ELSE "abandon"     \* lines 1708-1709, 1981-1982
ArrivedNext(st) ==                                                      \* record_arrived, lines 1700-1713
  IF st = "PASS" THEN (IF HIGH_RISK THEN "verify" ELSE "closeManual")
  ELSE IF st = "ISSUES" THEN RetryNext
  ELSE "launch"                                                         \* line 1711: BLOCKED, whatever the attempt
UnclosedNext(v) ==                                                      \* unclosed_next, lines 551-561
  IF v = "verify-failed" THEN "launch"
  ELSE IF v = "check-only" THEN "verifyAgain"                           \* "verify --again ..., or accept it"
  ELSE "close"

\* What one `record` would write and print: the new values plus the event and its hint.
Same == [lastTask |-> lastTask, workerResult |-> workerResult, vv |-> vv, vManager |-> vManager,
         vNewer |-> vNewer, vfiled |-> vfiled, worker |-> worker, verifier |-> verifier,
         vreport |-> vreport, wtDirty |-> wtDirty, merged |-> merged, pr |-> pr,
         ev |-> "none", nx |-> "none"]

\* commit_stopped, lines 1829-1873: a STOPPED row without a Head line gets its WIP committed once the stopped
\* worker has exited. record_in_progress runs it first, lines 1895-1899 (the #54 fix); before 0.11.2 it ran
\* only after the verifier and verdict checks (REGRESS_54).
PauseOutOf(b) ==
  IF worker = "stopping" THEN [b EXCEPT !.ev = "stopping", !.nx = "none"]           \* 1832-1834
  ELSE [b EXCEPT !.lastTask = "STOPPEDhead", !.wtDirty = FALSE, !.ev = "stopped", !.nx = "launch"]  \* 1858-1868
PauseOut == PauseOutOf(Same)

\* record_in_progress from line 1948 on: the task rows of the attempt.
TaskRowsOut(b) ==
  IF lastTask = "none" THEN
     IF Stuck(worker) THEN                                              \* file_stuck, lines 1953-1959
        [b EXCEPT !.worker = "finished", !.lastTask = "BLOCKEDmgr", !.ev = "stuck", !.nx = "launch"]
     ELSE IF worker \in {"busy", "stopping"} THEN [b EXCEPT !.ev = "running", !.nx = "none"]
     ELSE IF Unknown(worker) THEN [b EXCEPT !.ev = "unknown", !.nx = "none"]   \* 1964: next: claude logs
     ELSE [b EXCEPT !.lastTask = "DIED", !.ev = "died", !.nx = RetryNext]       \* lines 1980-1983
  ELSE IF lastTask = "STOPPEDhead" THEN [b EXCEPT !.ev = "stopped", !.nx = "launch"]   \* lines 1986-1989
  ELSE IF lastTask = "STOPPED" THEN PauseOutOf(b)                     \* 1990-1991: only reached with REGRESS_54
  ELSE IF lastTask = "DIED" THEN [b EXCEPT !.ev = "died", !.nx = RetryNext]            \* lines 1992-1995
  ELSE IF lastTask = "BLOCKEDmgr" THEN [b EXCEPT !.ev = "stuck", !.nx = "launch"]      \* 1685-1692
  ELSE [b EXCEPT !.ev = "arrived", !.nx = ArrivedNext(lastTask)]

\* record_in_progress lines 1935-1947: the verdict rows of the attempt.
Verdicts(b) ==
  IF b.vv # "none" /\ b.vNewer /\ (verdict = "none" \/ b.vv # verdict)
  THEN [b EXCEPT !.ev = "verified", !.nx = "close"]                     \* emit_verified, line 1627
  ELSE IF verdict # "none" THEN [b EXCEPT !.ev = "unclosed", !.nx = UnclosedNext(verdict)]
  ELSE TaskRowsOut(b)

\* record_in_progress lines 1883-1998.
RecInProgress ==
  LET vRunning == Live(verifier) /\ ~VerifierOver(verifier)             \* line 1901
      lost == verifier # "none" /\ ~vfiled                               \* lost_verifier, lines 1794-1799
      salvaged == [Same EXCEPT !.vv = "artifact-verified", !.vNewer = TRUE, !.vfiled = TRUE,
                   !.vreport = FALSE,
                   !.verifier = IF Live(verifier) THEN "finished" ELSE verifier]   \* salvage_verifier, 1813-1826
  IN IF lastTask = "STOPPED" /\ ~REGRESS_54 THEN PauseOut
     ELSE IF vRunning THEN
        IF Stuck(verifier)                                              \* lines 1904-1909
        THEN [Same EXCEPT !.verifier = "finished", !.vManager = "BLOCKED", !.vNewer = FALSE,
                          !.vfiled = TRUE, !.ev = "stuck", !.nx = "verifyAgain"]
        ELSE [Same EXCEPT !.ev = "verifying", !.nx = "none"]
     ELSE IF lost /\ ~vreport THEN [Same EXCEPT !.ev = "no-verdict", !.nx = "verifyAgain"]  \* 1916-1922
     ELSE Verdicts(IF lost THEN salvaged ELSE Same)

\* pr_status, lines 2911-2961. The standing orders hold a MERGE: line, so a clean request is merged here.
PrStatus(b) ==
  IF pr = "merged" THEN [b EXCEPT !.merged = TRUE, !.verifier = VerifierAtEnd, !.ev = "merged", !.nx = "none"]
  ELSE IF pr = "closed" THEN [b EXCEPT !.ev = "pr-closed", !.nx = "none"]      \* reopen it, or a decision
  ELSE IF pr = "pending" THEN [b EXCEPT !.ev = "pr-pending", !.nx = "none"]    \* record later
  ELSE IF pr = "dirty" THEN [b EXCEPT !.ev = "conflict", !.nx = "none"]        \* a decision
  ELSE IF pr = "behind" THEN [b EXCEPT !.ev = "pr-behind", !.nx = "close"]
  ELSE IF pr = "blocked" THEN [b EXCEPT !.ev = "pr-blocked", !.nx = "none"]    \* record later
  ELSE IF stopOrder THEN [b EXCEPT !.ev = "ready-to-merge", !.nx = "none"]   \* 2948-2949: not merged during a pause
  ELSE [b EXCEPT !.pr = "merged", !.merged = TRUE, !.verifier = VerifierAtEnd, !.ev = "merged", !.nx = "none"]

\* record_done, lines 2000-2020.
RecDone ==
  IF merged THEN [Same EXCEPT !.ev = "nothing", !.nx = "none"]
  ELSE IF PrMode THEN
     IF pr = "none" THEN [Same EXCEPT !.ev = "unpublished", !.nx = "close"]   \* line 2006
     ELSE PrStatus(Same)
  ELSE IF mainHas THEN [Same EXCEPT !.merged = TRUE, !.verifier = VerifierAtEnd, !.ev = "merged", !.nx = "none"]
  ELSE [Same EXCEPT !.ev = "unmerged", !.nx = "none"]                   \* line 2017: no next

RecOut ==
  IF abandoned THEN [Same EXCEPT !.ev = "nothing", !.nx = "none"]
  ELSE IF status = "open" THEN [Same EXCEPT !.ev = "ready", !.nx = "launch"]  \* ready_events, line 2023
  ELSE IF status = "in_progress" THEN RecInProgress
  ELSE RecDone

RecordHasEffect ==
  LET o == RecOut IN
  \/ o.lastTask # lastTask \/ o.workerResult # workerResult \/ o.vv # vv \/ o.vManager # vManager
  \/ o.vNewer # vNewer \/ o.vfiled # vfiled \/ o.worker # worker \/ o.verifier # verifier
  \/ o.vreport # vreport \/ o.wtDirty # wtDirty \/ o.merged # merged \/ o.pr # pr

\* The step that record names. While record still has something to write, the Manager runs record.
RawHint == IF RecordHasEffect THEN "record" ELSE RecOut.nx
\* ALLOW_STUCK_AT_CAP (#56): a launch hint at the last attempt is read as abandon, as the ISSUES and died hints
\* already say. After a pause (STOPPEDhead), which refuse_past_cap exempts: ALLOW_RECOVERY_STOP_PAST_CAP (#59)
\* reads the hint as abandon when the stop recovered a session; ALLOW_PAUSE_PAST_CAP when the operator ordered it.
Hint ==
  IF /\ RawHint = "launch" /\ attempt >= MAX_ATTEMPTS /\ status # "open"
     /\ \/ (ALLOW_STUCK_AT_CAP /\ lastTask # "STOPPEDhead")
        \/ (ALLOW_RECOVERY_STOP_PAST_CAP /\ lastTask = "STOPPEDhead" /\ recoveryStop)
        \/ (ALLOW_PAUSE_PAST_CAP /\ lastTask = "STOPPEDhead" /\ ~recoveryStop)
  THEN "abandon"
  ELSE RawHint
Event == RecOut.ev

Record ==
  /\ RecordHasEffect
  /\ LET o == RecOut IN
       /\ lastTask' = o.lastTask /\ workerResult' = o.workerResult /\ vv' = o.vv /\ vManager' = o.vManager
       /\ vNewer' = o.vNewer /\ vfiled' = o.vfiled /\ worker' = o.worker /\ verifier' = o.verifier
       /\ vreport' = o.vreport /\ wtDirty' = o.wtDirty /\ merged' = o.merged /\ pr' = o.pr
  /\ UNCHANGED <<status, attempt, abandoned, verdict, mainHas>> /\ UNCHANGED OrderVars

\* ---------------------------------------------------------------- launch

\* cmd_launch, lines 1192-1383, without --attempt, --base, --model. Lines 1248-1261: a live row refuses the
\* launch, unless every live row is idle with its work filed; then launch stops them (stopped-idle, 1250-1258)
\* and goes on. The checks after that can still refuse (1265: a pause not committed; 1386: the cap).
\* The checks before the live-row scan (1248): a STOP order (1194-1195, exit 3), a done task (1204), abandoned (1214).
EarlyChecks == ~stopOrder /\ status # "done" /\ ~abandoned
\* The checks after it: a pause not committed (1265), the cap (refuse_past_cap, 1386-1389).
LateChecks == lastTask # "STOPPED" /\ ((attempt + 1 <= MAX_ATTEMPTS) \/ (lastTask = "STOPPEDhead"))
LiveRowsAllowLaunch ==
  /\ ~(Live(worker) /\ ~WorkerIdleFiled)
  /\ ~(Live(verifier) /\ ~VerifierIdleFiled)
LaunchStopsIdle == (Live(worker) \/ Live(verifier)) /\ LiveRowsAllowLaunch /\ attempt >= 1

Launch ==
  /\ Hint = "launch"
  /\ EarlyChecks
  /\ LiveRowsAllowLaunch
  /\ LateChecks
  /\ status' = "in_progress" /\ attempt' = attempt + 1 /\ verdict' = "none"   \* lines 1367-1376
  /\ lastTask' = "none" /\ workerResult' = "none"
  /\ vv' = "none" /\ vManager' = "none" /\ vNewer' = FALSE /\ vfiled' = TRUE
  /\ worker' = "busy" /\ verifier' = "none" /\ vreport' = FALSE
  /\ wtDirty' = FALSE                                                   \* lines 1332-1344: WIP is committed
  /\ recoveryStop' = FALSE
  /\ UNCHANGED <<abandoned, merged, pr, mainHas, stopOrder>>

\* The launch stopped the idle sessions (1250-1258) and then refused (1265 or 1386): the rows ended, nothing else.
LaunchStopsIdleThenRefuses ==
  /\ Hint = "launch"
  /\ EarlyChecks
  /\ LaunchStopsIdle
  /\ ~LateChecks
  /\ worker' = IF Live(worker) THEN "finished" ELSE worker
  /\ verifier' = IF Live(verifier) THEN "finished" ELSE verifier
  /\ UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, workerResult,
                 vv, vManager, vNewer, vfiled, vreport, wtDirty>> /\ UNCHANGED OrderVars

\* ---------------------------------------------------------------- verify

\* cmd_verify in session mode, lines 1484-1565. Shared checks of both forms.
VerifyAccepted ==
  /\ status = "in_progress" /\ ~abandoned                               \* refuse_unless_running, 1459-1466
  /\ workerResult = "PASS"                                              \* worker_for, lines 1469-1481
  /\ ~(Live(verifier) /\ ~VerifierOver(verifier))                       \* lines 1503-1506
VerifyUnchanged ==
  UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, workerResult,
              vv, vManager, vNewer, worker, wtDirty, stopOrder, recoveryStop>>

VerifyPlain ==
  /\ Hint = "verify"
  /\ VerifyAccepted
  /\ vv = "none"                                                        \* lines 1497-1502: else --again
  /\ verifier' = "busy" /\ vfiled' = FALSE /\ vreport' = FALSE          \* 1508-1511 stop the old one; 1553 start
  /\ VerifyUnchanged

\* With ALLOW_BLOCKED_ROW_HIDES_VERDICT the Manager also passes --again where the hint says plain verify
\* and verifier rows exist (the earlier `stuck` line said --again).
VerifyAgain ==
  /\ Hint = "verifyAgain" \/ (ALLOW_BLOCKED_ROW_HIDES_VERDICT /\ Hint = "verify" /\ vv # "none")
  /\ VerifyAccepted
  /\ verifier' = "busy" /\ vfiled' = FALSE /\ vreport' = FALSE
  /\ VerifyUnchanged

\* ---------------------------------------------------------------- close

\* stop_live, lines 3038-3051: stop the live worker and file a STOPPED row without a Head line.
StopLive ==
  /\ worker' = IF Live(worker) THEN "finished" ELSE worker
  /\ lastTask' = IF Live(worker) THEN "STOPPED" ELSE lastTask

\* publish with catch_up (lines 2712-2766) once the host shows the request in state s:
\* clean is merged (pr_status), behind goes to the host's rebase (host_catch_up, 2794-2838), which ends
\* rebased (the host recomputes the state), in a conflict (a decision), or not at all.
PublishAfter(s) ==
  \/ s = "clean" /\ ~stopOrder /\ pr' = "merged" /\ merged' = TRUE
  \/ s = "clean" /\ stopOrder /\ pr' = s /\ merged' = merged            \* ready-to-merge: not merged during a pause
  \/ s = "behind" /\ merged' = merged /\ pr' \in {"pending", "dirty", "behind"}
  \/ s \in {"pending", "blocked", "dirty", "closed"} /\ pr' = s /\ merged' = merged
  \/ s = "merged" /\ pr' = s /\ merged' = TRUE

\* A first push creates the request and the host picks its state; or the push fails (line 2726: Refused,
\* exit 1, after `tg done`), and record says unpublished until a later close pushes again.
PublishStep ==
  IF pr = "none" THEN (\E s \in OpenPr : PublishAfter(s)) \/ (pr' = "none" /\ merged' = merged)
  ELSE PublishAfter(pr)

\* merge_branch, lines 3195-3222: a merge, or a conflict that becomes a decision.
LocalMergeStep ==
  \/ (~stopOrder /\ merged' = TRUE /\ mainHas' = TRUE)
  \/ (merged' = FALSE /\ mainHas' = mainHas)                              \* a conflict, or a pause (3198-3200)

Finish ==
  IF PrMode THEN mainHas' = mainHas /\ PublishStep ELSE pr' = pr /\ LocalMergeStep

\* resume_close, lines 3072-3095: a close that stopped after `tg done`.
ResumeClose ==
  /\ status = "done" /\ ~merged /\ ~abandoned                           \* cmd_close, lines 3129-3131
  /\ StopLive
  /\ Finish
  /\ verifier' = IF merged' THEN VerifierAtEnd ELSE verifier
  /\ UNCHANGED <<status, attempt, abandoned, verdict, workerResult, vv, vManager, vNewer, vfiled,
                 vreport, wtDirty>> /\ UNCHANGED OrderVars

\* cmd_close lines 3181-3191: `tg done`, stop the worker, publish or merge.
CloseAsPassing ==
  /\ status' = "done" /\ StopLive /\ Finish
  /\ verifier' = IF merged' THEN VerifierAtEnd ELSE verifier

\* cmd_close lines 3177-3180: the verdict is recorded, the task is not closed.
CloseNotPassing ==
  /\ status' = status
  /\ UNCHANGED <<worker, verifier, lastTask, merged, pr, mainHas>>

\* cmd_close, lines 3125-3192, with choose_verdict, lines 3098-3122. L is --verdict, or "auto" for none.
NormalClose(L) ==
  /\ status = "in_progress" /\ ~abandoned                               \* refuse_unless_running
  /\ workerResult = "PASS"                                              \* worker_for
  /\ (vv = "none") => (L # "auto")                                      \* line 3107: no verdict at all
  /\ (vv # "none") => (L = "auto" \/ L = vv)                            \* lines 3111-3115: no --override-verifier
  /\ LET level == IF vv = "none" THEN L ELSE vv
         manual == vv = "none"
     IN /\ verdict' = level                                             \* line 3159
        /\ vManager' = IF manual THEN "manual" ELSE vManager            \* lines 3147-3155
        /\ vNewer' = IF manual THEN FALSE ELSE vNewer
        /\ vfiled' = vfiled \/ manual
        /\ IF level \in Passing THEN CloseAsPassing ELSE CloseNotPassing
  /\ UNCHANGED <<attempt, abandoned, workerResult, vv, vreport, wtDirty>> /\ UNCHANGED OrderVars

CloseAuto ==
  /\ Hint = "close"
  /\ ResumeClose \/ NormalClose("auto")
  /\ vars' # vars

CloseManual ==
  /\ Hint = "closeManual"
  /\ \E L \in Levels : ResumeClose \/ NormalClose(L)
  /\ vars' # vars

\* ---------------------------------------------------------------- stop, abandon, merged

\* cmd_stop, lines 3241-3256: accepted for any live worker row of the attempt (line 3246, `s.live`).
\* The model runs it on the operator's pause order (a STOP line in the standing orders, a working session)
\* and, with a switch, as the Manager's way out of an idle worker (#58) or a worker on a prompt after its
\* result, which no `next:` hint names. A stop without a STOP order is a recovery stop (#59).
Stop ==
  /\ status = "in_progress" /\ Live(worker)
  /\ \/ (OPERATOR_PAUSES /\ stopOrder /\ worker = "busy")
     \/ (ALLOW_IDLE_WORKER /\ worker = "idle")
     \/ (ALLOW_PROMPT_AFTER_RESULT /\ worker = "prompt" /\ WorkerFiled)
  /\ worker' = "stopping"
  /\ lastTask' = "STOPPED"                                              \* lines 3254-3255: no Head line
  /\ recoveryStop' = ~stopOrder
  /\ UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, workerResult,
                 vv, vManager, vNewer, vfiled, verifier, vreport, wtDirty, stopOrder>>

\* cmd_abandon, lines 3259-3281: stops the task's live worker sessions (3267-3271), not a verifier.
Abandon ==
  /\ Hint = "abandon"
  /\ status = "in_progress" /\ ~abandoned
  /\ abandoned' = TRUE
  /\ worker' = IF Live(worker) THEN "finished" ELSE worker
  /\ lastTask' = IF Live(worker) THEN "ABANDONED" ELSE lastTask
  /\ verifier' = VerifierAtEnd
  /\ UNCHANGED <<status, attempt, verdict, merged, pr, mainHas, workerResult,
                 vv, vManager, vNewer, vfiled, vreport, wtDirty>> /\ UNCHANGED OrderVars

\* cmd_merged, lines 3227-3238. No modelled event names it, so it never fires (NOTES.md).
Merged ==
  /\ Hint = "merged"
  /\ status = "done" /\ ~merged
  /\ merged' = TRUE
  /\ UNCHANGED <<status, attempt, abandoned, verdict, pr, mainHas, lastTask, workerResult,
                 vv, vManager, vNewer, vfiled, worker, verifier, vreport, wtDirty>> /\ UNCHANGED OrderVars

Done == End /\ UNCHANGED vars

\* ---------------------------------------------------------------- environment

\* Sessions keep their state until something acts on them: an idle verifier may wake up or go quiet; an idle
\* worker, and every quiet, blocked, prompted, failed or finished session, changes only when stopped.
\* With FULL_ENV = FALSE only the steps of the main flow exist: a worker reports and ends, a verifier files
\* and ends, a stopped worker exits, the operator merges, the host moves the request.
NotSessions == <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, workerResult,
                 vv, vManager, vNewer, vfiled, vreport, wtDirty, stopOrder, recoveryStop>>

WorkerEnds == ~End /\ worker = "busy" /\ worker' = "finished" /\ UNCHANGED verifier /\ UNCHANGED NotSessions
WorkerExits == ~End /\ worker = "stopping" /\ worker' = "finished" /\ UNCHANGED verifier /\ UNCHANGED NotSessions
WorkerFails == ~End /\ FULL_ENV /\ worker = "busy" /\ worker' = "failed" /\ UNCHANGED verifier /\ UNCHANGED NotSessions
WorkerIdles == ~End /\ FULL_ENV /\ worker = "busy" /\ worker' = "idle" /\ UNCHANGED verifier /\ UNCHANGED NotSessions
WorkerAsks == ~End /\ FULL_ENV /\ worker = "busy" /\ worker' = "idleBlocked" /\ UNCHANGED verifier /\ UNCHANGED NotSessions
WorkerPrompted == ~End /\ FULL_ENV /\ worker = "busy" /\ worker' = "prompt" /\ UNCHANGED verifier /\ UNCHANGED NotSessions

\* A worker files one result per attempt, as its last step (worker.md: "Run the one `result add` command in
\* REPORT ... then end"). Its process may still show as live for a while after that.
WorkerFilesUnchanged ==
  UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas,
              vv, vManager, vNewer, vfiled, worker, verifier, vreport, wtDirty, stopOrder, recoveryStop>>
WorkerFilesPass ==
  ~End /\ worker = "busy" /\ workerResult = "none" /\ lastTask' = "PASS" /\ workerResult' = "PASS" /\ WorkerFilesUnchanged
WorkerFilesIssues ==
  ~End /\ worker = "busy" /\ workerResult = "none" /\ lastTask' = "ISSUES" /\ workerResult' = "ISSUES" /\ WorkerFilesUnchanged
WorkerFilesBlocked ==
  ~End /\ worker = "busy" /\ workerResult = "none" /\ lastTask' = "BLOCKED" /\ workerResult' = "BLOCKED" /\ WorkerFilesUnchanged

WorkerDirties ==
  /\ ~End /\ FULL_ENV /\ worker = "busy" /\ ~wtDirty /\ wtDirty' = TRUE
  /\ UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, workerResult,
                 vv, vManager, vNewer, vfiled, worker, verifier, vreport>> /\ UNCHANGED OrderVars

VerifierEnds == ~End /\ verifier = "busy" /\ verifier' = "finished" /\ UNCHANGED worker /\ UNCHANGED NotSessions
VerifierFails == ~End /\ FULL_ENV /\ verifier = "busy" /\ verifier' = "failed" /\ UNCHANGED worker /\ UNCHANGED NotSessions
VerifierIdles == ~End /\ FULL_ENV /\ verifier = "busy" /\ verifier' = "idle" /\ UNCHANGED worker /\ UNCHANGED NotSessions
VerifierWakes == ~End /\ FULL_ENV /\ verifier = "idle" /\ verifier' = "busy" /\ UNCHANGED worker /\ UNCHANGED NotSessions
VerifierQuiet == ~End /\ FULL_ENV /\ verifier = "idle" /\ verifier' = "idleQuiet" /\ UNCHANGED worker /\ UNCHANGED NotSessions
VerifierAsks == ~End /\ FULL_ENV /\ verifier = "busy" /\ verifier' = "idleBlocked" /\ UNCHANGED worker /\ UNCHANGED NotSessions
VerifierPrompted == ~End /\ FULL_ENV /\ verifier = "busy" /\ verifier' = "prompt" /\ UNCHANGED worker /\ UNCHANGED NotSessions

VerifierFiles ==
  /\ ~End /\ verifier = "busy"
  /\ vv' \in Levels /\ vNewer' = TRUE /\ vfiled' = TRUE
  /\ UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, workerResult,
                 vManager, worker, verifier, vreport, wtDirty>> /\ UNCHANGED OrderVars

VerifierLeavesReport ==
  /\ ~End /\ FULL_ENV /\ verifier = "busy" /\ ~vreport /\ vreport' = TRUE
  /\ UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, workerResult,
                 vv, vManager, vNewer, vfiled, worker, verifier, wtDirty>> /\ UNCHANGED OrderVars

\* The code host, in pr mode.
HostUnchanged ==
  UNCHANGED <<status, attempt, abandoned, verdict, merged, mainHas, lastTask, workerResult,
              vv, vManager, vNewer, vfiled, worker, verifier, vreport, wtDirty, stopOrder, recoveryStop>>
HostDecides == ~End /\ PrMode /\ pr = "pending" /\ pr' \in {"clean", "behind", "blocked", "dirty"} /\ HostUnchanged
TargetMoves == ~End /\ PrMode /\ pr \in {"clean", "blocked"} /\ pr' = "behind" /\ HostUnchanged
CheckFails == ~End /\ PrMode /\ pr = "clean" /\ pr' = "blocked" /\ HostUnchanged
CheckPasses == ~End /\ PrMode /\ pr = "blocked" /\ pr' = "clean" /\ HostUnchanged
SomeoneMerges == ~End /\ PrMode /\ pr \in OpenPr /\ pr' = "merged" /\ HostUnchanged
SomeoneCloses == ~End /\ PrMode /\ pr \in OpenPr /\ pr' = "closed" /\ HostUnchanged
SomeoneReopens == ~End /\ PrMode /\ pr = "closed" /\ pr' = "pending" /\ HostUnchanged

\* Local mode: the operator merges the branch by hand; record then finds it in HEAD (merged_into, 2011).
OperatorMerges ==
  /\ ~End /\ ~PrMode /\ status = "done" /\ ~mainHas /\ mainHas' = TRUE
  /\ UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, lastTask, workerResult,
                 vv, vManager, vNewer, vfiled, worker, verifier, vreport, wtDirty>> /\ UNCHANGED OrderVars

\* The operator's standing orders: a STOP first line pauses launches and merges (Orders.stop); the operator
\* lifts it later. A pause is `run.py stop` under that line.
OperatorOrdersStop ==
  /\ ~End /\ OPERATOR_PAUSES /\ ~stopOrder /\ stopOrder' = TRUE
  /\ UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, workerResult,
                 vv, vManager, vNewer, vfiled, worker, verifier, vreport, wtDirty, recoveryStop>>
OperatorLiftsStop ==
  /\ ~End /\ OPERATOR_PAUSES /\ stopOrder /\ stopOrder' = FALSE
  /\ UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, workerResult,
                 vv, vManager, vNewer, vfiled, worker, verifier, vreport, wtDirty, recoveryStop>>

\* ---------------------------------------------------------------- spec

Init ==
  /\ status = "open" /\ attempt = 0 /\ abandoned = FALSE /\ verdict = "none"
  /\ merged = FALSE /\ pr = "none" /\ mainHas = FALSE
  /\ lastTask = "none" /\ workerResult = "none"
  /\ vv = "none" /\ vManager = "none" /\ vNewer = FALSE /\ vfiled = TRUE
  /\ worker = "none" /\ verifier = "none" /\ vreport = FALSE /\ wtDirty = FALSE
  /\ stopOrder = FALSE /\ recoveryStop = FALSE

Next ==
  \/ Launch \/ LaunchStopsIdleThenRefuses \/ VerifyPlain \/ VerifyAgain \/ CloseAuto \/ CloseManual
  \/ Stop \/ Abandon \/ Merged \/ Record \/ Done
  \/ WorkerEnds \/ WorkerExits \/ WorkerFails \/ WorkerIdles \/ WorkerAsks \/ WorkerPrompted
  \/ WorkerFilesPass \/ WorkerFilesIssues \/ WorkerFilesBlocked \/ WorkerDirties
  \/ VerifierEnds \/ VerifierFails \/ VerifierIdles \/ VerifierWakes \/ VerifierQuiet \/ VerifierAsks
  \/ VerifierPrompted \/ VerifierFiles \/ VerifierLeavesReport
  \/ HostDecides \/ TargetMoves \/ CheckFails \/ CheckPasses \/ SomeoneMerges \/ SomeoneCloses \/ SomeoneReopens
  \/ OperatorMerges \/ OperatorOrdersStop \/ OperatorLiftsStop

Spec == Init /\ [][Next]_vars

\* States past this bound are checked but not explored.
AttemptBound == attempt <= MAX_ATTEMPTS + 1

\* ---------------------------------------------------------------- rules

TypeOK ==
  /\ status \in {"open", "in_progress", "done"}
  /\ attempt \in 0..(MAX_ATTEMPTS + 2)       \* one past the constraint: such states are checked, not explored
  /\ abandoned \in BOOLEAN /\ merged \in BOOLEAN /\ mainHas \in BOOLEAN
  /\ verdict \in {"none"} \cup Levels
  /\ pr \in PrStates
  /\ lastTask \in RowKinds
  /\ workerResult \in {"none"} \cup WorkerStatuses
  /\ vv \in {"none"} \cup Levels /\ vManager \in ManagerVerify /\ vNewer \in BOOLEAN /\ vfiled \in BOOLEAN
  /\ worker \in WorkerStates /\ verifier \in VerifierStates
  /\ vreport \in BOOLEAN /\ wtDirty \in BOOLEAN /\ stopOrder \in BOOLEAN /\ recoveryStop \in BOOLEAN
  /\ Hint \in Hints

\* Once the verifier's session ended or its turn ended, the attempt has a verify row that covers it, or
\* record is about to write one, or record says that the verdict is missing (no-verdict). A pending pause
\* (a STOPPED row without a Head line) is allowed: record finishes it first by design (1898), and the lost
\* verifier is found by the record that follows the commit. An invariant, not a liveness property: the model
\* has no fairness, and a state is easier to read than a lasso.
VerdictNotLost ==
  (verifier # "none" /\ Over(verifier) /\ ~vfiled)
    => (RecordHasEffect \/ Event = "no-verdict" \/ lastTask = "STOPPED")

\* A done or merged task has a passing verdict, and a verify row of the attempt carries it.
NoMergeWithoutPassingVerdict ==
  (status = "done" \/ merged) => (verdict \in Passing /\ (vv = verdict \/ vManager = "manual"))

\* The attempt number never passes MAX_ATTEMPTS. refuse_past_cap (1386) exempts any STOPPED row. The owner's
\* rule (#59): only a pause the operator ordered (a STOP line when `run.py stop` ran) is exempt; a stop that
\* recovers a quiet or broken session counts as an attempt. The rule here cannot tell the two apart, so it
\* breaks on both; ALLOW_PAUSE_PAST_CAP takes the intended one out, ALLOW_RECOVERY_STOP_PAST_CAP the bug.
AttemptCap == attempt <= MAX_ATTEMPTS

\* cmd_launch line 1333: "A dirty worktree never reaches a worker silently: commit what the last attempt left."
LaunchCommitsLeftovers == [][Launch => wtDirty' = FALSE]_vars

\* commit_stopped line 1830: "Phase 2 of a pause: commit the WIP of a stopped worker that has exited."
PausedWipCommitted == (lastTask = "STOPPEDhead") => ~wtDirty

\* record_in_progress line 1898: "finish the pause first: launch needs its Head line". Once the paused worker
\* has exited, the next step is record, which commits the WIP.
PauseFinishedFirst ==
  (status = "in_progress" /\ ~abandoned /\ lastTask = "STOPPED" /\ worker # "stopping") => Hint = "record"

\* cleanup line 2538: "Remove the sessions and worktrees of a merged task." cmd_abandon stops the task's
\* worker sessions. So an end state leaves no live session of the task (#57).
NoSessionLeftAtEnd == End => (~Live(worker) /\ ~Live(verifier))

\* cmd_launch line 1369: "Never unset pr, pr_branch, pushed or target: one request per task across attempts."
OneRequestPerTask == [][pr # "none" => pr' # "none"]_vars

====
