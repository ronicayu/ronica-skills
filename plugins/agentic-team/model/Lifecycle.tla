---- MODULE Lifecycle ----
\* The task-attempt lifecycle of scripts/run.py (agentic-team 0.18.0, commit ff2c8b0): one task, its attempts,
\* one worker session and one verifier session at a time, the result rows of the current attempt, the meta that
\* decides the next step, and the request in pr mode. Line numbers are of scripts/run.py at that commit.
\*
\* The Manager's only moves are the command that `record` names in its `next:` hint, and `record` itself.
\* A refused command (exit 2) is not enabled. A command that would change nothing is not enabled either.
\* `Done` is the only self-loop: the task is merged or abandoned. So a state with no step out is a dead
\* end for the Manager: the hinted command is refused or useless, and nothing in the world moves.
\*
\* Each REGRESS_* constant, when TRUE, restores a bug the code has fixed, so that the matching regress config
\* must break again (NOTES.md, "Sensitivity checks"). ALLOW_* constants, when TRUE, let the model take a path
\* the code or the briefs allow today (NOTES.md, "Open breaks").

EXTENDS Naturals

CONSTANTS MAX_ATTEMPTS,  \* line 122: MAX_ATTEMPTS = 3; the configs use 2
          MERGE_MODE,    \* "local" or "pr": merge.mode of .agentic-team.toml
          HIGH_RISK,     \* TRUE: risk meta "high", so a PASS goes to a verifier session (line 3169)
          FULL_ENV,      \* FALSE: only the main environment steps (overview.cfg), see NOTES.md
          OPERATOR_PAUSES, \* TRUE: the operator may write or lift a STOP order and order a pause at any time
          FAULTS,        \* TRUE: once per run, the role file breaks or info/exclude turns read-only (0.18.0 refusals)
          ALLOW_UNCHECKED_REPORT, \* TRUE: a verifier files an ISSUES report with no `blocking:` line (worker.md step 1 -> 2)
          \* Sensitivity checks: TRUE restores a fixed bug, so the check must break again (NOTES.md):
          REGRESS_42,    \* a failed row counts as live (before 0.10.3, #42)
          REGRESS_54,    \* record no longer finishes a pause first (before 0.11.2, #54)
          REGRESS_56,    \* the retry hints at the last attempt say launch, which the cap refuses (before 0.12.0, #56)
          REGRESS_57,    \* close and abandon stop worker sessions only, a verifier stays live (before 0.12.0, #57)
          REGRESS_58,    \* an idle worker with no result gets `claude logs` and no run.py step (before 0.12.0, #58)
          REGRESS_59,    \* every STOPPED row is exempt from the cap, a recovery stop too (before 0.12.0, #59)
          REGRESS_61,    \* launch refuses a worker that waits on a prompt after its result (before 0.12.0, #61)
          REGRESS_62,    \* record files BLOCKED for a verifier that waits after its verdict; the row hides it (before 0.12.0, #62)
          REGRESS_65,    \* a ghost row never ends and cleanup skips it (before 0.12.1, #65)
          REGRESS_65B,   \* a row that run.py stopped is not noted: a stopped idle/working row is a young ghost (before part 3 of #65)
          REGRESS_89     \* record and close read only the Verdict: line: an unlabelled ISSUES report opens a fix round (before 8006a3c)

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
  stopReason,    \* the Reason: line of the newest STOPPED row (stop_reason, 717-721): "none", "pause", "recover", "close"
  workerResult,  \* latest_worker(rows, attempt): the newest row that counts as a worker report
  vv,            \* the newest verify row by a verifier (its Verdict), or "none"
  vIssues,       \* the Issues: lines of that row: "none", "blocking" (every line labelled), "unlabelled" (0.18.0)
  vManager,      \* the newest verify row by the Manager: "none", "BLOCKED", or "manual" (close --verdict)
  vNewer,        \* the verifier's row is newer than the Manager's newest row with a verdict (lines 3457-3461)
  vfiled,        \* verifier_filed (3230): a verify row covers the newest verifier session
  worker,        \* the worker session row of this attempt
  verifier,      \* the newest verifier session row of this attempt
  vreport,       \* the verifier wrote a passing report file it did not file (salvage, 3201)
  wtDirty,       \* the task worktree has uncommitted changes
  stopOrder,     \* the standing orders start with a STOP line (Orders.stop, lines 518-525)
  fault,         \* 0.18.0: "none"; "role" (the attempt's role file is missing or broken); "exclude" (info/exclude is read-only)
  faulted        \* the one fault of this run has happened (FAULTS)

vars == <<status, attempt, abandoned, verdict, merged, pr, mainHas,
          lastTask, stopReason, workerResult, vv, vIssues, vManager, vNewer, vfiled,
          worker, verifier, vreport, wtDirty, stopOrder, fault, faulted>>

\* ---------------------------------------------------------------- values

\* VERDICTS (line 124) without test-verified (acts like artifact-verified for a code task) and without
\* verify-blocked (acts like check-only in every modelled decision).
Levels == {"artifact-verified", "check-only", "verify-failed"}
Passing == {"artifact-verified"}                      \* PASSING["code"], line 127
WorkerStatuses == {"PASS", "ISSUES", "BLOCKED"}
\* Task rows: a worker's report, or a Manager row: BLOCKEDmgr (file_stuck), DIED, STOPPED without a Head
\* line (cmd_stop, stop_live), STOPPEDhead (commit_stopped), ABANDONED.
RowKinds == {"none", "BLOCKEDmgr", "DIED", "STOPPED", "STOPPEDhead", "ABANDONED"} \cup WorkerStatuses
StopReasons == {"none", "pause", "recover", "close"}
ManagerVerify == {"none", "BLOCKED", "manual"}
IssueKinds == {"none", "blocking", "unlabelled"}
Faults == {"none", "role", "exclude"}
\* One row of `claude agents --json --all`, as the Session class reads it (lines 527-572):
\*   busy        status busy, state working
\*   idle        status idle, state working ("it will check back")
\*   idleQuiet   (verifier) idle, and 30 minutes passed with no activity (VERIFIER_QUIET_MINUTES, 194)
\*   idleBlocked state blocked, status idle, no waitingFor: its turn ended with a question
\*   prompt      waitingFor set: a permission prompt
\*   stopping    (worker) `claude stop` was sent, the process has not exited (status still busy)
\*   finished    state done or stopped, status idle or none
\*   failed      state failed, status idle (finished, line 553)
\*   ghost       state working, no status, no pid: no process now; the CLI may start it again (Session.ghost, 557)
\*   ghostStopped (REGRESS_65B only) an idle/working row that a run.py stop left as a young ghost before part 3;
\*               it does not come back (a stopped row was not seen to revive), and goes quiet like a ghost
\*   ghostGone   a ghost quiet for 30 minutes (no transcript write, no start: quiet_for): it counts as ended
\*               (Run.sessions, lines 467-476, sets finished and turn_over; quiet_for, lines 3244-3252; stop_session, 600-613)
WorkerStates == {"none", "busy", "idle", "idleBlocked", "prompt", "stopping", "finished", "failed", "ghost", "ghostStopped", "ghostGone"}
VerifierStates == {"none", "busy", "idle", "idleQuiet", "idleBlocked", "prompt", "finished", "failed", "ghost", "ghostStopped", "ghostGone"}
OpenPr == {"pending", "clean", "behind", "blocked", "dirty"}
PrStates == {"none", "merged", "closed"} \cup OpenPr
Hints == {"launch", "verify", "verifyAgain", "close", "closeManual", "abandon", "stop", "merged", "record", "none"}

PrMode == MERGE_MODE = "pr"

\* Session class, lines 527-572. With REGRESS_42 a failed row is live and unknown, as before 0.10.3.
\* A young ghost row (#65, line 557) is live and unknown. A ghost quiet for VERIFIER_QUIET_MINUTES is gone:
\* Run.sessions makes it finished (quiet_for; part 2 of #65). Before that (REGRESS_65) a ghost never ended.
\* `claude stop` keeps a row's state and removes its status and pid (a probe on CLI 2.1.318): a busy row becomes
\* "stopped", a done/idle row "done" with no status, both finished; an idle/working row becomes working with no
\* status and no pid, a young ghost. Since part 3 of #65 every stop that run.py runs goes through stop_session,
\* which notes the id, and Run.sessions counts a noted row with no status as finished at once. So a run.py stop
\* always ends the row (AfterStop). Before part 3 (REGRESS_65B) a stopped idle/working row stayed a young ghost.
Ghost(s) == s \in {"ghost", "ghostStopped", "ghostGone"}
AfterStop(s) == IF REGRESS_65B /\ s \in {"idle", "idleQuiet"} THEN "ghostStopped" ELSE "finished"
Finished(s) == s = "finished" \/ (s = "failed" /\ ~REGRESS_42) \/ (s = "ghostGone" /\ ~REGRESS_65)
Live(s) == s \in {"busy", "idle", "idleQuiet", "idleBlocked", "prompt", "stopping", "ghost", "ghostStopped"} \/ (s = "ghostGone" /\ REGRESS_65) \/ (s = "failed" /\ REGRESS_42)
Stuck(s) == s \in {"idleBlocked", "prompt"}
Unknown(s) == s \in {"idle", "idleQuiet", "ghost", "ghostStopped"} \/ (s = "ghostGone" /\ REGRESS_65) \/ (s = "failed" /\ REGRESS_42)
TurnOver(s) == Finished(s) \/ s = "idleBlocked"
\* verifier_over, lines 3254-3268: a turn that is over, or an unknown row quiet for 30 minutes.
VerifierOver(s) == TurnOver(s) \/ s \in {"idleQuiet", "ghostGone"}
\* The rule's words: the session ended, or its turn ended. Independent of the code's predicates. A gone ghost
\* counts as ended (the owner's rule for #65).
Over(s) == s \in {"finished", "failed", "idleBlocked", "ghostGone"}
\* work_filed (731-738): a task row that is not STOPPED for a worker; verifier_filed for a verifier.
WorkerFiled == workerResult # "none" \/ lastTask \in {"BLOCKEDmgr", "DIED"}
\* idle_and_filed (1966-1974): a worker that is idle or stuck with its work filed (#61; before: idle and not
\* waiting); a verifier that is idle, waits on nothing, and the attempt has a verify row.
IdleStatus(s) == s \in {"idle", "idleQuiet", "idleBlocked"} \/ (s = "failed" /\ REGRESS_42)   \* a failed row has status idle
WorkerIdleFiled ==
  Live(worker) /\ WorkerFiled /\ (IF REGRESS_61 THEN IdleStatus(worker) ELSE IdleStatus(worker) \/ Stuck(worker))
VerifierIdleFiled == Live(verifier) /\ IdleStatus(verifier) /\ (vv # "none" \/ vManager # "none")

End == (status = "done" /\ merged) \/ abandoned

\* ---------------------------------------------------------------- record

\* retry_next, lines 706-715: below the cap `run.py launch`; from MAX_ATTEMPTS on `run.py abandon <id> <mode>
\* (the cap is 3 attempts), or run.py launch --attempt <n+1> to override`. The Manager never overrides (0.18.0
\* rule 13: at the cap it abandons and re-plans; the override is for a bounded fix the operator names), so the
\* hint is abandon. Before 0.12.0 (REGRESS_56) the stuck, BLOCKED, unclosed and unknown hints said launch at
\* the cap; only ISSUES and died checked it.
RetryNext == IF attempt < MAX_ATTEMPTS THEN "launch" ELSE "abandon"
RetryNextOld == IF REGRESS_56 THEN "launch" ELSE RetryNext
\* stopped_next, lines 724-729: after a pause the launch, at any attempt; after any other stop retry_next.
\* Before 0.12.0 (REGRESS_59) every STOPPED row read as a pause.
StoppedNext == IF stopReason = "pause" \/ REGRESS_59 THEN "launch" ELSE RetryNext
ArrivedNext(st) ==                                                      \* record_arrived, lines 3167-3179
  IF st = "PASS" THEN (IF HIGH_RISK THEN "verify" ELSE "closeManual")   \* 3168-3172: ci, risk high, or a kind that is not code
  ELSE IF st = "ISSUES" THEN RetryNext                                  \* line 3174
  ELSE RetryNextOld                                                     \* line 3176: "answer it and ..."
UnclosedNext(v) ==                                                      \* unclosed_next, lines 757-768
  IF v = "verify-failed" THEN RetryNextOld                              \* "fix round: ..."
  ELSE IF v = "check-only" THEN "verifyAgain"                           \* "verify --again ..., or accept it"
  ELSE "close"
\* The unknown hint, lines 3490-3494 (#58): `claude logs <sid>; if it has stopped working, run.py stop <id>,
\* then run.py record and run.py launch <id>`; at the cap `run.py abandon <id> unknown (...), or run.py stop <id>,
\* then run.py record and run.py launch <id> --attempt <n+1> to override`, read as abandon. Before 0.12.0
\* (REGRESS_58): `claude logs` only. REGRESS_59 takes the second alternative at the cap (the recovery stop),
\* which is the stop the old exemption bug needed.
UnknownNext ==
  IF REGRESS_58 THEN "none"
  ELSE IF attempt < MAX_ATTEMPTS \/ REGRESS_59 THEN "stop"
  ELSE "abandon"

\* What one `record` would write and print: the new values plus the event and its hint. A record never changes
\* vIssues (it reads the Verdict: line only, verdict_of 685-687), fault or faulted.
Same == [lastTask |-> lastTask, stopReason |-> stopReason, workerResult |-> workerResult, vv |-> vv,
         vManager |-> vManager, vNewer |-> vNewer, vfiled |-> vfiled, worker |-> worker, verifier |-> verifier,
         vreport |-> vreport, wtDirty |-> wtDirty, merged |-> merged, pr |-> pr,
         ev |-> "none", nx |-> "none"]

\* commit_stopped, lines 3305-3348: a STOPPED row without a Head line gets its WIP committed once the stopped
\* worker has exited; the new row copies the Reason: line (3307-3309). record_in_progress runs it first, lines
\* 3376-3378 (the #54 fix); before 0.11.2 it ran only after the verifier and verdict checks (REGRESS_54).
PauseOutOf(b) ==
  IF worker = "stopping" THEN [b EXCEPT !.ev = "stopping", !.nx = "none"]           \* 3311-3313
  ELSE [b EXCEPT !.lastTask = "STOPPEDhead", !.wtDirty = FALSE, !.ev = "stopped", !.nx = StoppedNext]  \* 3338-3348
PauseOut == PauseOutOf(Same)

\* record_in_progress from line 3476 on: the task rows of the attempt.
TaskRowsOut(b) ==
  IF lastTask = "none" THEN
     IF Stuck(worker) THEN                                              \* file_stuck, lines 3480-3487
        [b EXCEPT !.worker = "finished", !.lastTask = "BLOCKEDmgr", !.ev = "stuck", !.nx = RetryNextOld]
     ELSE IF worker \in {"busy", "stopping"} THEN [b EXCEPT !.ev = "running", !.nx = "none"]   \* 3488-3489
     ELSE IF Unknown(worker) THEN [b EXCEPT !.ev = "unknown", !.nx = UnknownNext]   \* 3490-3494
     ELSE [b EXCEPT !.lastTask = "DIED", !.ev = "died", !.nx = RetryNext]           \* lines 3513-3519
  ELSE IF lastTask = "STOPPEDhead" THEN [b EXCEPT !.ev = "stopped", !.nx = StoppedNext]  \* lines 3522-3525
  ELSE IF lastTask = "STOPPED" THEN PauseOutOf(b)                      \* 3526-3527: only reached with REGRESS_54
  ELSE IF lastTask = "DIED" THEN [b EXCEPT !.ev = "died", !.nx = RetryNext]        \* lines 3528-3529
  ELSE IF lastTask = "BLOCKEDmgr" THEN [b EXCEPT !.ev = "stuck", !.nx = RetryNextOld]   \* 3152-3160
  ELSE [b EXCEPT !.ev = "arrived", !.nx = ArrivedNext(lastTask)]

\* record_in_progress lines 3455-3472: the verdict rows of the attempt. A Manager row with no verdict (the
\* BLOCKED row of a stuck verifier) no longer hides an older verdict (3457-3461, #62). Since 8006a3c a verifier's
\* verify-failed row whose Issues: lines fail verifier_problems (unlabelled_failure, 690-699) gets the hint
\* `run.py verify <id> --again (the verifier's report has no blocking: line: ...)` (unlabelled_next, 702-703;
\* emit_verified 2455-2467), at any attempt; close refuses it (choose_verdict 4768-4771). Before (REGRESS_89)
\* only the Verdict: line was read, and the hint was close.
Verdicts(b) ==
  IF b.vv # "none" /\ b.vNewer /\ (verdict = "none" \/ b.vv # verdict)
  THEN [b EXCEPT !.ev = "verified",
                 !.nx = IF vIssues = "unlabelled" /\ ~REGRESS_89 THEN "verifyAgain" ELSE "close"]
  ELSE IF verdict # "none" THEN [b EXCEPT !.ev = "unclosed", !.nx = UnclosedNext(verdict)]   \* 3470-3472
  ELSE TaskRowsOut(b)

\* record_in_progress lines 3363-3532.
RecInProgress ==
  LET vRunning == Live(verifier) /\ ~VerifierOver(verifier)             \* line 3413
      lost == verifier # "none" /\ ~vfiled                               \* lost_verifier, lines 3270-3275
      salvaged == [Same EXCEPT !.vv = "artifact-verified", !.vNewer = TRUE, !.vfiled = TRUE,
                   !.vreport = FALSE,
                   !.verifier = IF Live(verifier) /\ ~Ghost(verifier) THEN "finished" ELSE verifier]   \* salvage_verifier, 3289-3302
      \* #62, lines 3416-3422: a verifier that waits after its filed verdict is stopped, no row, record goes on.
      stoppedIdle == [Same EXCEPT !.verifier = "finished"]
      \* file_stuck, lines 3423-3429: BLOCKED by the Manager; before 0.12.0 that row outranked the verdict.
      stuckOut == [Same EXCEPT !.verifier = "finished", !.vManager = "BLOCKED",
                   !.vNewer = IF REGRESS_62 THEN FALSE ELSE vNewer,
                   !.vfiled = TRUE, !.ev = "stuck", !.nx = "verifyAgain"]
  IN IF lastTask = "STOPPED" /\ ~REGRESS_54 THEN PauseOut
     ELSE IF vRunning /\ Stuck(verifier) /\ vfiled /\ ~REGRESS_62 THEN Verdicts(stoppedIdle)
     ELSE IF vRunning /\ Stuck(verifier) THEN stuckOut
     ELSE IF vRunning THEN [Same EXCEPT !.ev = "verifying", !.nx = "none"]          \* 3430-3432
     ELSE IF lost /\ ~vreport THEN [Same EXCEPT !.ev = "no-verdict", !.nx = "verifyAgain"]  \* 3435-3444
     ELSE Verdicts(IF lost THEN salvaged ELSE Same)

\* pr_status, lines 4557-4610. The standing orders hold a MERGE: line, so a clean request is merged here,
\* except during a pause (4595).
PrStatus(b) ==
  IF pr = "merged" THEN [b EXCEPT !.merged = TRUE, !.ev = "merged", !.nx = "none"]
  ELSE IF pr = "closed" THEN [b EXCEPT !.ev = "pr-closed", !.nx = "none"]      \* reopen it, or a decision
  ELSE IF pr = "pending" THEN [b EXCEPT !.ev = "pr-pending", !.nx = "none"]    \* record later
  ELSE IF pr = "dirty" THEN [b EXCEPT !.ev = "conflict", !.nx = "none"]        \* a decision
  ELSE IF pr = "behind" THEN [b EXCEPT !.ev = "pr-behind", !.nx = "close"]
  ELSE IF pr = "blocked" THEN [b EXCEPT !.ev = "pr-blocked", !.nx = "none"]    \* record later
  ELSE IF stopOrder THEN [b EXCEPT !.ev = "ready-to-merge", !.nx = "none"]
  ELSE [b EXCEPT !.pr = "merged", !.merged = TRUE, !.ev = "merged", !.nx = "none"]

\* record_done, lines 3534-3554.
RecDone ==
  IF merged THEN [Same EXCEPT !.ev = "nothing", !.nx = "none"]
  ELSE IF PrMode THEN
     IF pr = "none" THEN [Same EXCEPT !.ev = "unpublished", !.nx = "close"]   \* line 3540
     ELSE PrStatus(Same)                                                 \* line 3542
  ELSE IF mainHas THEN [Same EXCEPT !.merged = TRUE, !.ev = "merged", !.nx = "none"]   \* merged_into, 3545
  ELSE [Same EXCEPT !.ev = "unmerged", !.nx = "none"]                   \* line 3551: no next

RecOut ==
  IF abandoned THEN [Same EXCEPT !.ev = "nothing", !.nx = "none"]
  ELSE IF status = "open" THEN [Same EXCEPT !.ev = "ready", !.nx = "launch"]  \* ready_events, line 3557
  ELSE IF status = "in_progress" THEN RecInProgress
  ELSE RecDone

RecordHasEffect ==
  LET o == RecOut IN
  \/ o.lastTask # lastTask \/ o.workerResult # workerResult \/ o.vv # vv \/ o.vManager # vManager
  \/ o.vNewer # vNewer \/ o.vfiled # vfiled \/ o.worker # worker \/ o.verifier # verifier
  \/ o.vreport # vreport \/ o.wtDirty # wtDirty \/ o.merged # merged \/ o.pr # pr

\* The step that record names. While record still has something to write, the Manager runs record.
Hint == IF RecordHasEffect THEN "record" ELSE RecOut.nx
Event == RecOut.ev

Record ==
  /\ RecordHasEffect
  /\ LET o == RecOut IN
       /\ lastTask' = o.lastTask /\ workerResult' = o.workerResult /\ vv' = o.vv /\ vManager' = o.vManager
       /\ vNewer' = o.vNewer /\ vfiled' = o.vfiled /\ worker' = o.worker /\ verifier' = o.verifier
       /\ vreport' = o.vreport /\ wtDirty' = o.wtDirty /\ merged' = o.merged /\ pr' = o.pr
       /\ vIssues' = IF o.vv = vv THEN vIssues ELSE "none"             \* a salvaged report is a passing one
  /\ UNCHANGED <<status, attempt, abandoned, verdict, mainHas, stopReason, stopOrder, fault, faulted>>

\* ---------------------------------------------------------------- launch

\* cmd_launch, lines 1976-2201, without --attempt, --base, --model. Lines 2024-2049: a live row refuses the
\* launch, unless every live row is idle_and_filed; then launch stops them (stopped-idle, 2037-2046) and goes
\* on. The checks after that can still refuse (2063: a pause not committed; 2064: the cap).
\* The checks before the live-row scan: a STOP order (1978-1980, exit 3), info/exclude (ignore_reports and
\* ignore_scratch, 1981-1983, since ff2c8b0: a read-only file refuses before anything is stopped or committed),
\* a done task (1992), the role (choose, 1995: a role file that is missing or broken refuses, 0.18.0),
\* abandoned (2001).
EarlyChecks == ~stopOrder /\ fault = "none" /\ status # "done" /\ ~abandoned
\* The checks after it: a pause not committed (2063); refuse_past_cap (2204-2212): past MAX_ATTEMPTS only a
\* STOPPED row with Reason: pause is exempt (#59; before 0.12.0, REGRESS_59, any STOPPED row).
Exempt == lastTask = "STOPPEDhead" /\ (stopReason = "pause" \/ REGRESS_59)
LateChecks == lastTask # "STOPPED" /\ ((attempt + 1 <= MAX_ATTEMPTS) \/ Exempt)
LiveRowsAllowLaunch ==
  /\ ~(Live(worker) /\ ~WorkerIdleFiled)
  /\ ~(Live(verifier) /\ ~VerifierIdleFiled)
LaunchStopsIdle == (Live(worker) \/ Live(verifier)) /\ LiveRowsAllowLaunch /\ attempt >= 1

\* Before part 3 of #65 (REGRESS_65B), the stop of an idle/working row left a young ghost, and the launch's second
\* read of the live rows (2048) refused on it: the field's "None/working" refusal.
StoppedIdleGhosts == REGRESS_65B /\ ((Live(worker) /\ worker = "idle") \/ (Live(verifier) /\ verifier \in {"idle", "idleQuiet"}))

Launch ==
  /\ Hint = "launch"
  /\ EarlyChecks
  /\ LiveRowsAllowLaunch
  /\ LateChecks
  /\ ~StoppedIdleGhosts
  /\ status' = "in_progress" /\ attempt' = attempt + 1 /\ verdict' = "none"   \* lines 2180-2193
  /\ lastTask' = "none" /\ stopReason' = "none" /\ workerResult' = "none"
  /\ vv' = "none" /\ vIssues' = "none" /\ vManager' = "none" /\ vNewer' = FALSE /\ vfiled' = TRUE
  /\ worker' = "busy" /\ verifier' = "none" /\ vreport' = FALSE
  /\ wtDirty' = FALSE                                                   \* lines 2140-2150: WIP is committed
  /\ UNCHANGED <<abandoned, merged, pr, mainHas, stopOrder, fault, faulted>>

\* The launch stopped the idle sessions (2037-2046) and then refused (2063 or 2064): the rows ended, nothing else.
LaunchStopsIdleThenRefuses ==
  /\ Hint = "launch"
  /\ EarlyChecks
  /\ LaunchStopsIdle
  /\ (~LateChecks \/ StoppedIdleGhosts)
  /\ worker' = IF Live(worker) THEN AfterStop(worker) ELSE worker
  /\ verifier' = IF Live(verifier) THEN AfterStop(verifier) ELSE verifier
  /\ UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, stopReason, workerResult,
                 vv, vIssues, vManager, vNewer, vfiled, vreport, wtDirty, stopOrder, fault, faulted>>

\* ---------------------------------------------------------------- verify

\* cmd_verify in session mode, lines 2307-2395. Shared checks of both forms. The role of the attempt is read
\* from its file again (verify_role, 1049-1056, at 2316): a missing or broken file refuses, and so does a
\* read-only info/exclude (2328-2330, since ff2c8b0), both before anything is stopped.
VerifyAccepted ==
  /\ status = "in_progress" /\ ~abandoned                               \* refuse_unless_running, 2282-2289
  /\ fault = "none"
  /\ workerResult = "PASS"                                              \* worker_for, lines 2292-2304
  /\ ~(Live(verifier) /\ ~VerifierOver(verifier))                       \* lines 2332-2335
VerifyUnchanged ==
  UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, stopReason, workerResult,
              vv, vManager, vNewer, worker, wtDirty, stopOrder, fault, faulted>>

VerifyPlain ==
  /\ Hint = "verify"
  /\ VerifyAccepted
  /\ vv = "none"                                                        \* lines 2322-2327: else --again
  /\ verifier' = "busy" /\ vfiled' = FALSE /\ vreport' = FALSE          \* 2336-2340 stop the old one; 2383 start
  /\ UNCHANGED vIssues /\ VerifyUnchanged

\* --again also after an unlabelled verify-failed row (its hint since 8006a3c): the row stays, with its Issues:
\* lines (vIssues describes the vv row, so it changes only with vv), until the new verifier's row replaces it.
VerifyAgain ==
  /\ Hint = "verifyAgain"
  /\ VerifyAccepted
  /\ verifier' = "busy" /\ vfiled' = FALSE /\ vreport' = FALSE
  /\ UNCHANGED vIssues /\ VerifyUnchanged

\* ---------------------------------------------------------------- close

\* stop_live, lines 4685-4705: stop the live worker (a STOPPED row with Reason: close, no Head line) and, since
\* 0.12.0 (#57), the live verifier (no row). Before (REGRESS_57) a verifier stayed live.
StopLive ==
  /\ worker' = IF Live(worker) THEN AfterStop(worker) ELSE worker
  /\ lastTask' = IF Live(worker) THEN "STOPPED" ELSE lastTask
  /\ stopReason' = IF Live(worker) THEN "close" ELSE stopReason
  /\ verifier' = IF Live(verifier) /\ ~REGRESS_57 THEN AfterStop(verifier) ELSE verifier

\* publish with catch_up (lines 4357-4413) once the host shows the request in state s:
\* clean is merged (pr_status), unless a STOP order holds it; behind goes to the host's rebase (host_catch_up,
\* 4440-4485), which ends rebased (the host recomputes the state), in a conflict (a decision), or not at all.
PublishAfter(s) ==
  \/ s = "clean" /\ ~stopOrder /\ pr' = "merged" /\ merged' = TRUE
  \/ s = "clean" /\ stopOrder /\ pr' = s /\ merged' = merged            \* ready-to-merge: not merged during a pause
  \/ s = "behind" /\ merged' = merged /\ pr' \in {"pending", "dirty", "behind"}
  \/ s \in {"pending", "blocked", "dirty", "closed"} /\ pr' = s /\ merged' = merged
  \/ s = "merged" /\ pr' = s /\ merged' = TRUE

\* A first push creates the request and the host picks its state; or the push fails (push-failed, 4428: exit 1,
\* after `tg done`), and record says unpublished until a later close pushes again.
PublishStep ==
  IF pr = "none" THEN (\E s \in OpenPr : PublishAfter(s)) \/ (pr' = "none" /\ merged' = merged)
  ELSE PublishAfter(pr)

\* merge_branch, lines 4887-4916: a merge, or a conflict that becomes a decision, or a pause (4889-4892).
LocalMergeStep ==
  \/ (~stopOrder /\ merged' = TRUE /\ mainHas' = TRUE)
  \/ (merged' = FALSE /\ mainHas' = mainHas)

\* 0.12.3 (#72): a verified head with no commit beyond its base is recorded merged at once, with no merge,
\* push or request (no_change 4785-4797, close_no_change 4800-4809; at 4874-4878 and 4741-4743). A free
\* choice: the model does not track the commits of the branch. Only before any request exists.
NoChangeClose == pr = "none" /\ merged' = TRUE /\ UNCHANGED <<pr, mainHas>>

Finish ==
  \/ NoChangeClose
  \/ (IF PrMode THEN mainHas' = mainHas /\ PublishStep ELSE pr' = pr /\ LocalMergeStep)

\* resume_close, lines 4726-4752: a close that stopped after `tg done`.
ResumeClose ==
  /\ status = "done" /\ ~merged /\ ~abandoned                           \* cmd_close, lines 4816-4818
  /\ StopLive
  /\ Finish
  /\ UNCHANGED <<status, attempt, abandoned, verdict, workerResult, vv, vIssues, vManager, vNewer, vfiled,
                 vreport, wtDirty, stopOrder, fault, faulted>>

\* cmd_close lines 4870-4883: `tg done`, stop the sessions, publish or merge.
CloseAsPassing == status' = "done" /\ StopLive /\ Finish

\* cmd_close lines 4866-4869: the verdict is recorded, the task is not closed.
CloseNotPassing ==
  /\ status' = status
  /\ UNCHANGED <<worker, verifier, lastTask, stopReason, merged, pr, mainHas>>

\* cmd_close, lines 4812-4884, with choose_verdict, lines 4755-4782. L is --verdict, or "auto" for none.
\* close never refuses on a role: verify_kind (1804-1819) reads the kind stored at launch (0.18.0).
NormalClose(L) ==
  /\ status = "in_progress" /\ ~abandoned                               \* refuse_unless_running
  /\ workerResult = "PASS"                                              \* worker_for
  /\ (vv = "none") => (L # "auto")                                      \* line 4764: no verdict at all
  /\ (vv # "none") => (L = "auto" \/ L = vv)                            \* lines 4766-4779: no --override-verifier
  /\ ~(vv # "none" /\ vIssues = "unlabelled" /\ ~REGRESS_89)            \* 4768-4771: refused, `verify --again` (8006a3c)
  /\ LET level == IF vv = "none" THEN L ELSE vv
         manual == vv = "none"
     IN /\ verdict' = level                                             \* line 4844
        /\ vManager' = IF manual THEN "manual" ELSE vManager            \* lines 4831-4841
        /\ vNewer' = IF manual THEN FALSE ELSE vNewer
        /\ vfiled' = vfiled \/ manual
        /\ IF level \in Passing THEN CloseAsPassing ELSE CloseNotPassing
  /\ UNCHANGED <<attempt, abandoned, workerResult, vv, vIssues, vreport, wtDirty, stopOrder, fault, faulted>>

CloseAuto ==
  /\ Hint = "close"
  /\ ResumeClose \/ NormalClose("auto")
  /\ vars' # vars

CloseManual ==
  /\ Hint = "closeManual"
  /\ \E L \in Levels : ResumeClose \/ NormalClose(L)
  /\ vars' # vars

\* ---------------------------------------------------------------- stop, abandon, merged

\* cmd_stop, lines 4933-4965: accepted for any live worker row of the attempt (4941, `s.live`). The row's
\* Reason: is pause under a STOP order, else recover (4953). The Manager runs it where the `unknown` hint
\* says so (#58); the operator runs it as a pause under a STOP order (OPERATOR_PAUSES).
Stop ==
  /\ status = "in_progress" /\ Live(worker)
  /\ \/ Hint = "stop"
     \/ (OPERATOR_PAUSES /\ stopOrder /\ worker = "busy")
  /\ worker' = IF worker = "busy" THEN "stopping" ELSE AfterStop(worker)   \* stop_session: the row counts as ended
  /\ lastTask' = "STOPPED"                                              \* lines 4959-4961: no Head line
  /\ stopReason' = IF stopOrder THEN "pause" ELSE "recover"
  /\ UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, workerResult,
                 vv, vIssues, vManager, vNewer, vfiled, verifier, vreport, wtDirty, stopOrder, fault, faulted>>

\* cmd_abandon, lines 4968-5004: stops the task's live worker sessions (4975-4979) and, since 0.12.0 (#57),
\* its live verifier (4980-4983). At the cap the Manager abandons and re-plans (0.18.0 rule 13): the new task
\* is another instance of this model, so the model ends here.
Abandon ==
  /\ Hint = "abandon"
  /\ status = "in_progress" /\ ~abandoned
  /\ abandoned' = TRUE
  /\ worker' = IF Live(worker) THEN AfterStop(worker) ELSE worker
  /\ lastTask' = IF Live(worker) THEN "ABANDONED" ELSE lastTask
  /\ verifier' = IF Live(verifier) /\ ~REGRESS_57 THEN AfterStop(verifier) ELSE verifier
  /\ UNCHANGED <<status, attempt, verdict, merged, pr, mainHas, stopReason, workerResult,
                 vv, vIssues, vManager, vNewer, vfiled, vreport, wtDirty, stopOrder, fault, faulted>>

\* cmd_merged, lines 4919-4930. No modelled event names it, so it never fires (NOTES.md).
Merged ==
  /\ Hint = "merged"
  /\ status = "done" /\ ~merged
  /\ merged' = TRUE
  /\ UNCHANGED <<status, attempt, abandoned, verdict, pr, mainHas, lastTask, stopReason, workerResult,
                 vv, vIssues, vManager, vNewer, vfiled, worker, verifier, vreport, wtDirty, stopOrder, fault, faulted>>

Done == End /\ UNCHANGED vars

\* ---------------------------------------------------------------- environment

\* Sessions keep their state until something acts on them: an idle verifier may wake up or go quiet; an idle
\* worker, and every quiet, blocked, prompted, failed or finished session, changes only when stopped.
\* With FULL_ENV = FALSE only the steps of the main flow exist: a worker reports and ends, a verifier files
\* and ends, a stopped worker exits, the operator merges, the host moves the request.
NotSessions == <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, stopReason, workerResult,
                 vv, vIssues, vManager, vNewer, vfiled, vreport, wtDirty, stopOrder, fault, faulted>>

WorkerEnds == ~End /\ worker = "busy" /\ worker' = "finished" /\ UNCHANGED verifier /\ UNCHANGED NotSessions
WorkerExits == ~End /\ worker = "stopping" /\ worker' = "finished" /\ UNCHANGED verifier /\ UNCHANGED NotSessions
WorkerFails == ~End /\ FULL_ENV /\ worker = "busy" /\ worker' = "failed" /\ UNCHANGED verifier /\ UNCHANGED NotSessions
WorkerIdles == ~End /\ FULL_ENV /\ worker = "busy" /\ worker' = "idle" /\ UNCHANGED verifier /\ UNCHANGED NotSessions
WorkerAsks == ~End /\ FULL_ENV /\ worker = "busy" /\ worker' = "idleBlocked" /\ UNCHANGED verifier /\ UNCHANGED NotSessions
WorkerPrompted == ~End /\ FULL_ENV /\ worker = "busy" /\ worker' = "prompt" /\ UNCHANGED verifier /\ UNCHANGED NotSessions
\* #65: the process dies (kill -9, a crash): the row stays live with no status and no pid. The CLI may start it
\* again (status idle, a new pid), or the row stays; after 30 quiet minutes it counts as ended (ghostGone).
WorkerGhosts == ~End /\ FULL_ENV /\ worker = "busy" /\ worker' = "ghost" /\ UNCHANGED verifier /\ UNCHANGED NotSessions
WorkerGhostReturns == ~End /\ FULL_ENV /\ worker = "ghost" /\ worker' = "idle" /\ UNCHANGED verifier /\ UNCHANGED NotSessions
WorkerGhostStays == ~End /\ FULL_ENV /\ worker \in {"ghost", "ghostStopped"} /\ worker' = "ghostGone" /\ UNCHANGED verifier /\ UNCHANGED NotSessions


\* A worker files one result per attempt, as its last step (worker.md "Report": run check-report, fix what it
\* names, then the one report command). A report that check-report refuses (too few Evidence: lines, a path
\* that does not exist) is rewritten, or filed as it is when the worker cannot fix it (step 1 -> 2): either
\* way the row that lands is one of these three, so the refusal is no state of its own. Its process may still
\* show as live for a while after that.
WorkerFilesUnchanged ==
  UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, stopReason,
              vv, vIssues, vManager, vNewer, vfiled, worker, verifier, vreport, wtDirty, stopOrder, fault, faulted>>
WorkerFilesPass ==
  ~End /\ worker = "busy" /\ workerResult = "none" /\ lastTask' = "PASS" /\ workerResult' = "PASS" /\ WorkerFilesUnchanged
WorkerFilesIssues ==
  ~End /\ worker = "busy" /\ workerResult = "none" /\ lastTask' = "ISSUES" /\ workerResult' = "ISSUES" /\ WorkerFilesUnchanged
WorkerFilesBlocked ==
  ~End /\ worker = "busy" /\ workerResult = "none" /\ lastTask' = "BLOCKED" /\ workerResult' = "BLOCKED" /\ WorkerFilesUnchanged

WorkerDirties ==
  /\ ~End /\ FULL_ENV /\ worker = "busy" /\ ~wtDirty /\ wtDirty' = TRUE
  /\ UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, stopReason, workerResult,
                 vv, vIssues, vManager, vNewer, vfiled, worker, verifier, vreport, stopOrder, fault, faulted>>

VerifierEnds == ~End /\ verifier = "busy" /\ verifier' = "finished" /\ UNCHANGED worker /\ UNCHANGED NotSessions
VerifierFails == ~End /\ FULL_ENV /\ verifier = "busy" /\ verifier' = "failed" /\ UNCHANGED worker /\ UNCHANGED NotSessions
VerifierIdles == ~End /\ FULL_ENV /\ verifier = "busy" /\ verifier' = "idle" /\ UNCHANGED worker /\ UNCHANGED NotSessions
VerifierWakes == ~End /\ FULL_ENV /\ verifier = "idle" /\ verifier' = "busy" /\ UNCHANGED worker /\ UNCHANGED NotSessions
VerifierQuiet == ~End /\ FULL_ENV /\ verifier = "idle" /\ verifier' = "idleQuiet" /\ UNCHANGED worker /\ UNCHANGED NotSessions
VerifierAsks == ~End /\ FULL_ENV /\ verifier = "busy" /\ verifier' = "idleBlocked" /\ UNCHANGED worker /\ UNCHANGED NotSessions
VerifierPrompted == ~End /\ FULL_ENV /\ verifier = "busy" /\ verifier' = "prompt" /\ UNCHANGED worker /\ UNCHANGED NotSessions
VerifierGhosts == ~End /\ FULL_ENV /\ verifier = "busy" /\ verifier' = "ghost" /\ UNCHANGED worker /\ UNCHANGED NotSessions
VerifierGhostReturns == ~End /\ FULL_ENV /\ verifier = "ghost" /\ verifier' = "idle" /\ UNCHANGED worker /\ UNCHANGED NotSessions
VerifierGhostStays == ~End /\ FULL_ENV /\ verifier \in {"ghost", "ghostStopped"} /\ verifier' = "ghostGone" /\ UNCHANGED worker /\ UNCHANGED NotSessions

\* The verifier files its one verify row (result_command, 1395-1400: a plain `tg result add`). Its brief runs
\* `check-report --verifier` first (1436, 1450-1455; verifier_problems 5051-5067): an ISSUES report needs a
\* `blocking:` line under Issues:, and findings that do not block go under Follow-ups: in a PASS report. A
\* report that passes the check: verify-failed with blocking findings, or another level with none under Issues:.
VerifierFilesUnchanged ==
  UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, stopReason, workerResult,
              vManager, worker, verifier, vreport, wtDirty, stopOrder, fault, faulted>>
VerifierFiles ==
  /\ ~End /\ verifier = "busy"
  /\ vv' \in Levels /\ vNewer' = TRUE /\ vfiled' = TRUE
  /\ vIssues' = IF vv' = "verify-failed" THEN "blocking" ELSE "none"
  /\ VerifierFilesUnchanged

\* The check is advisory: worker.md "Report" step 1 says that a problem the session cannot fix, or a refused
\* command, goes on to step 2, the filing, and the filing command checks nothing (ALLOW_UNCHECKED_REPORT). So
\* an ISSUES report with no `blocking:` line can land; since 8006a3c record and close judge it (Verdicts).
VerifierFilesUnchecked ==
  /\ ALLOW_UNCHECKED_REPORT
  /\ ~End /\ verifier = "busy"
  /\ vv' = "verify-failed" /\ vNewer' = TRUE /\ vfiled' = TRUE /\ vIssues' = "unlabelled"
  /\ VerifierFilesUnchanged

VerifierLeavesReport ==
  /\ ~End /\ FULL_ENV /\ verifier = "busy" /\ ~vreport /\ vreport' = TRUE
  /\ UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, stopReason, workerResult,
                 vv, vIssues, vManager, vNewer, vfiled, worker, verifier, wtDirty, stopOrder, fault, faulted>>

\* The code host, in pr mode.
HostUnchanged ==
  UNCHANGED <<status, attempt, abandoned, verdict, merged, mainHas, lastTask, stopReason, workerResult,
              vv, vIssues, vManager, vNewer, vfiled, worker, verifier, vreport, wtDirty, stopOrder, fault, faulted>>
HostDecides == ~End /\ PrMode /\ pr = "pending" /\ pr' \in {"clean", "behind", "blocked", "dirty"} /\ HostUnchanged
TargetMoves == ~End /\ PrMode /\ pr \in {"clean", "blocked"} /\ pr' = "behind" /\ HostUnchanged
CheckFails == ~End /\ PrMode /\ pr = "clean" /\ pr' = "blocked" /\ HostUnchanged
CheckPasses == ~End /\ PrMode /\ pr = "blocked" /\ pr' = "clean" /\ HostUnchanged
SomeoneMerges == ~End /\ PrMode /\ pr \in OpenPr /\ pr' = "merged" /\ HostUnchanged
SomeoneCloses == ~End /\ PrMode /\ pr \in OpenPr /\ pr' = "closed" /\ HostUnchanged
SomeoneReopens == ~End /\ PrMode /\ pr = "closed" /\ pr' = "pending" /\ HostUnchanged

\* Local mode: the operator merges the branch by hand; record then finds it in HEAD (merged_into, 3545).
OperatorMerges ==
  /\ ~End /\ ~PrMode /\ status = "done" /\ ~mainHas /\ mainHas' = TRUE
  /\ UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, lastTask, stopReason, workerResult,
                 vv, vIssues, vManager, vNewer, vfiled, worker, verifier, vreport, wtDirty, stopOrder, fault, faulted>>

\* The operator's standing orders: a STOP first line pauses launches and merges (Orders.stop); the operator
\* lifts it later. A pause is `run.py stop` under that line. Both are behind OPERATOR_PAUSES.
OrdersUnchanged ==
  UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, stopReason, workerResult,
              vv, vIssues, vManager, vNewer, vfiled, worker, verifier, vreport, wtDirty, fault, faulted>>
OperatorOrdersStop == ~End /\ OPERATOR_PAUSES /\ ~stopOrder /\ stopOrder' = TRUE /\ OrdersUnchanged
OperatorLiftsStop == ~End /\ OPERATOR_PAUSES /\ stopOrder /\ stopOrder' = FALSE /\ OrdersUnchanged

\* 0.18.0 faults (FAULTS), once per run so that a broken-then-fixed copy of a dead end is still a dead end:
\* the role file of the task (or of [roles] default) goes missing or breaks, which launch (choose, 1995) and
\* verify (verify_role, 2316) refuse while close and record read the values stored at launch; or info/exclude
\* turns read-only, which launch (1981-1983) and verify (2328-2330) refuse before they stop or commit anything
\* (ff2c8b0). The operator's repair is the only way out of a broken state (each refusal says so), and it is
\* enabled only there.
FaultUnchanged ==
  UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, stopReason, workerResult,
              vv, vIssues, vManager, vNewer, vfiled, worker, verifier, vreport, wtDirty, stopOrder>>
RoleBreaks == ~End /\ FAULTS /\ ~faulted /\ fault' = "role" /\ faulted' = TRUE /\ FaultUnchanged
ExcludeBreaks == ~End /\ FAULTS /\ ~faulted /\ fault' = "exclude" /\ faulted' = TRUE /\ FaultUnchanged
OperatorRepairs == ~End /\ fault # "none" /\ fault' = "none" /\ UNCHANGED faulted /\ FaultUnchanged

\* ---------------------------------------------------------------- spec

Init ==
  /\ status = "open" /\ attempt = 0 /\ abandoned = FALSE /\ verdict = "none"
  /\ merged = FALSE /\ pr = "none" /\ mainHas = FALSE
  /\ lastTask = "none" /\ stopReason = "none" /\ workerResult = "none"
  /\ vv = "none" /\ vIssues = "none" /\ vManager = "none" /\ vNewer = FALSE /\ vfiled = TRUE
  /\ worker = "none" /\ verifier = "none" /\ vreport = FALSE /\ wtDirty = FALSE
  /\ stopOrder = FALSE /\ fault = "none" /\ faulted = FALSE

Next ==
  \/ Launch \/ LaunchStopsIdleThenRefuses \/ VerifyPlain \/ VerifyAgain \/ CloseAuto \/ CloseManual
  \/ Stop \/ Abandon \/ Merged \/ Record \/ Done
  \/ WorkerEnds \/ WorkerExits \/ WorkerFails \/ WorkerIdles \/ WorkerAsks \/ WorkerPrompted
  \/ WorkerGhosts \/ WorkerGhostReturns \/ WorkerGhostStays
  \/ VerifierGhosts \/ VerifierGhostReturns \/ VerifierGhostStays
  \/ WorkerFilesPass \/ WorkerFilesIssues \/ WorkerFilesBlocked \/ WorkerDirties
  \/ VerifierEnds \/ VerifierFails \/ VerifierIdles \/ VerifierWakes \/ VerifierQuiet \/ VerifierAsks
  \/ VerifierPrompted \/ VerifierFiles \/ VerifierFilesUnchecked \/ VerifierLeavesReport
  \/ HostDecides \/ TargetMoves \/ CheckFails \/ CheckPasses \/ SomeoneMerges \/ SomeoneCloses \/ SomeoneReopens
  \/ OperatorMerges \/ OperatorOrdersStop \/ OperatorLiftsStop
  \/ RoleBreaks \/ ExcludeBreaks \/ OperatorRepairs

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
  /\ lastTask \in RowKinds /\ stopReason \in StopReasons
  /\ workerResult \in {"none"} \cup WorkerStatuses
  /\ vv \in {"none"} \cup Levels /\ vIssues \in IssueKinds
  /\ vManager \in ManagerVerify /\ vNewer \in BOOLEAN /\ vfiled \in BOOLEAN
  /\ worker \in WorkerStates /\ verifier \in VerifierStates
  /\ vreport \in BOOLEAN /\ wtDirty \in BOOLEAN /\ stopOrder \in BOOLEAN
  /\ fault \in Faults /\ faulted \in BOOLEAN
  /\ Hint \in Hints

\* Once the verifier's session ended or its turn ended, the attempt has a verify row that covers it, or
\* record is about to write one, or record says that the verdict is missing (no-verdict). A pending pause
\* (a STOPPED row without a Head line) is allowed: record finishes it first by design (3376-3378), and the lost
\* verifier is found by the record that follows the commit. An invariant, not a liveness property: the model
\* has no fairness, and a state is easier to read than a lasso.
VerdictNotLost ==
  (verifier # "none" /\ Over(verifier) /\ ~vfiled)
    => (RecordHasEffect \/ Event = "no-verdict" \/ lastTask = "STOPPED")

\* A done or merged task has a passing verdict, and a verify row of the attempt carries it.
NoMergeWithoutPassingVerdict ==
  (status = "done" \/ merged) => (verdict \in Passing /\ (vv = verdict \/ vManager = "manual"))

\* The owner's rule (#59): the attempt passes MAX_ATTEMPTS only by a launch after a pause the operator ordered
\* (the newest row is STOPPED with Reason: pause); a stop that recovers a quiet or broken session, a stop by
\* close, and DIED all count as an attempt. An action property: it names the step that passes the cap.
AttemptCap ==
  [][(attempt' > MAX_ATTEMPTS /\ attempt' # attempt) => (lastTask = "STOPPEDhead" /\ stopReason = "pause")]_vars

\* cmd_launch line 2140: "A dirty worktree never reaches a worker silently: commit what the last attempt left."
LaunchCommitsLeftovers == [][Launch => wtDirty' = FALSE]_vars

\* commit_stopped line 3305: "Phase 2 of a pause: commit the WIP of a stopped worker that has exited."
PausedWipCommitted == (lastTask = "STOPPEDhead") => ~wtDirty

\* record_in_progress line 3378: "finish the pause first: launch needs its Head line". Once the stopped worker
\* has exited, the next step is record, which commits the WIP.
PauseFinishedFirst ==
  (status = "in_progress" /\ ~abandoned /\ lastTask = "STOPPED" /\ worker # "stopping") => Hint = "record"

\* cleanup line 4103: "Remove the sessions and worktrees of a merged task." stop_live and cmd_abandon stop the
\* task's live sessions (#57). So an end state leaves no live session of the task. A young ghost row is not one:
\* `claude stop` cannot end it, it ends by itself after 30 quiet minutes, and cleanup removes it with `claude rm`
\* once the task is done (#65). Before 0.12.1 (REGRESS_65) cleanup skipped it as live, so it was left.
LeftAtEnd(s) == Live(s) /\ (~Ghost(s) \/ REGRESS_65)
NoSessionLeftAtEnd == End => (~LeftAtEnd(worker) /\ ~LeftAtEnd(verifier))

\* idle_and_filed (1966-1974): "launch stops such a session itself instead of refusing." A launch that stops the
\* idle rows and passes every other check starts the next attempt; it does not refuse on the row it stopped.
\* The step must be the launch itself (a STOP order written in that state exits launch before it stops anything,
\* as pause.md says, and the environment's own steps do not start attempts). Since ff2c8b0 the exclude check is
\* an early one (1981-1983, in EarlyChecks), so no refusal follows the stops but the pause and the cap.
StoppedIdleNeverRefuses ==
  [][(Hint = "launch" /\ EarlyChecks /\ LaunchStopsIdle /\ LateChecks /\ (Launch \/ LaunchStopsIdleThenRefuses))
       => attempt' = attempt + 1]_vars

\* cmd_launch line 2181: "Never unset pr, pr_branch, pushed or target: one request per task across attempts."
OneRequestPerTask == [][pr # "none" => pr' # "none"]_vars

\* 0.18.0 (#89 rule 1, README "Blocking and non-blocking findings", manager.md "No follow-up dropped"): a fix
\* round is opened only for a blocking finding; non-blocking findings never open one. In the model's words: when
\* a verifier's verify-failed verdict drives the next step (a fix round, or abandon at the cap), its report has
\* a `blocking:` line. A Manager's own verify-failed (close --verdict) is not a verifier's finding. Since
\* 8006a3c such a verdict is never recorded: record hints `verify --again`, close refuses (REGRESS_89 undoes both).
FixRoundNeedsBlocking ==
  (verdict = "verify-failed" /\ vv = verdict /\ vManager # "manual" /\ Hint \in {"launch", "abandon"})
    => vIssues = "blocking"

====
