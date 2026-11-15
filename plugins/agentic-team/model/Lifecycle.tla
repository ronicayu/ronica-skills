---- MODULE Lifecycle ----
\* The task-attempt lifecycle of scripts/run.py (agentic-team 0.24.0; the lifecycle of 0.19.0, PR-1 of #97, with the rounds of
\* #119 and the revisions of #127): one task, its attempts,
\* one worker session and one verifier session at a time, the result rows of the current attempt, the meta that
\* decides the next step, and the request in pr mode. Line numbers are of scripts/run.py at that version.
\*
\* The Manager's only moves are the command that `record` names in its `next:` hint, and `record` itself.
\* A refused command (exit 2) is not enabled. A command that would change nothing is not enabled either.
\* `Done` is the only self-loop: the task is merged (and done) or abandoned. So a state with no step out is a dead
\* end for the Manager: the hinted command is refused or useless, and nothing in the world moves.
\*
\* Each REGRESS_* constant, when TRUE, restores a bug the code has fixed, so that the matching regress config
\* must break again (NOTES.md, "Sensitivity checks"). ALLOW_* constants, when TRUE, let the model take a path
\* the code or the briefs allow today (NOTES.md, "Open breaks").

EXTENDS Naturals

CONSTANTS MAX_ATTEMPTS,  \* line 124: MAX_ATTEMPTS = 3; the configs use 2
          MERGE_MODE,    \* "local" or "pr": merge.mode of .agentic-team.toml
          HIGH_RISK,     \* TRUE: risk meta "high", so a PASS goes to a verifier session (line 3537)
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
          REGRESS_89,    \* record and close read only the Verdict: line: an unlabelled ISSUES report opens a fix round (before 8006a3c)
          REGRESS_97,    \* a passing close runs `tg done` at once, before the merge (before 0.19.0, #97)
          REGRESS_119,   \* a conflict's only way to new work is the redo hint: abandon, then launch (before 0.23.0, #119)
          ROUND_CAP,     \* [rounds] cap: the rounds without --attempt (the code's default is 3; the configs use 2, the overviews 1)
          ROUND_VERIFY,  \* [rounds] verify: "always" (a round's PASS goes to a verifier) or "by-risk" (the rule of a plain attempt)
          REVISION_CAP,  \* [verify] revisions_per_attempt (#127; the code's default is 2; 0 turns revisions off)
          SEAT,          \* [verify] seat: "task" (the verifier works in the task worktree) or "own" (a verify-<id>-<n> folder)
          REGRESS_127C,  \* revise ignores the cap
          REGRESS_127H,  \* the resumed verifier is not moved to the new head (its folder, or its brief, stays at the old one)
          REGRESS_127W,  \* verify starts the verifier while the worker is still busy in the same folder
          REGRESS_127A   \* the report check ignores an unacked finding steer

ASSUME MERGE_MODE \in {"local", "pr"}
ASSUME ROUND_VERIFY \in {"always", "by-risk"}
ASSUME SEAT \in {"task", "own"}

VARIABLES
  status,        \* Taskgraph status: "open", "in_progress", "done"
  attempt,       \* the attempt meta (0 before the first launch)
  abandoned,     \* the abandoned meta is set
  verdict,       \* the verdict meta: "none" or a level; a passing one is written only by a passing close (with phase)
  merged,        \* the merged_at meta is set (with phase merged, then `tg done`: mark_merged)
  pr,            \* pr mode: the request and what the host says about it
  mainHas,       \* local mode: the main checkout already contains the verdict commit
  lastTask,      \* the newest result row of kind task for this attempt
  stopReason,    \* the Reason: line of the newest STOPPED row (stop_reason, 741-745): "none", "pause", "recover", "close"
  workerResult,  \* latest_worker(rows, attempt): the newest row that counts as a worker report
  vv,            \* the newest verify row by a verifier (its Verdict), or "none"
  vIssues,       \* the Issues: lines of that row: "none", "blocking" (every line labelled), "unlabelled" (0.18.0)
  vManager,      \* the newest verify row by the Manager: "none", "BLOCKED", or "manual" (close --verdict)
  vNewer,        \* the verifier's row is newer than the Manager's newest row with a verdict (lines 3825-3829)
  vfiled,        \* verifier_filed (3598): a verify row covers the newest verifier session
  worker,        \* the worker session row of this attempt
  verifier,      \* the newest verifier session row of this attempt
  vreport,       \* the verifier wrote a passing report file it did not file (salvage, 3569)
  wtDirty,       \* the task worktree has uncommitted changes
  stopOrder,     \* the standing orders start with a STOP line (Orders.stop, lines 542-549)
  fault,         \* 0.18.0: "none"; "role" (the attempt's role file is missing or broken); "exclude" (info/exclude is read-only)
  faulted,       \* the one fault of this run has happened (FAULTS)
  \* #119, rounds (run.py round <id> rebase, and round --cancel):
  inRound,       \* a round is in flight: the round_from meta is set
  roundSame,     \* the round's PASS head carries the same change as round_from (same_change)
  rounds,        \* the rounds meta
  mainConflicts, \* local mode: the verified commit conflicts with the target (git merge-tree, or merge_branch's conflict)
  roundPushed,   \* the request's head is not round_from any more: a CI verify of the round pushed the round's head (CI
                 \* verify is out of the model otherwise, so one environment step stands for it)
  unverifiedMerge, \* record recorded the merge of a head that no verdict covers (a round's pushed head; merged_by=operator)
  \* #127, revisions (run.py revise <id>: the same worker and verifier sessions fix and judge again, in the same attempt):
  revision,      \* the revision meta: 0, or the revisions of this attempt so far
  workerKept,    \* the attempt's worker filed PASS and is kept for a revision (keep time not over, not stopped)
  verifierKept,  \* the attempt's verifier filed its row and is kept for a resume
  findingsOpen,  \* a finding steer of this revision has no ack
  verifierAt,    \* the revision whose head the verifier's seat shows
  vvRev          \* the revision whose head the newest verifier row judged

vars == <<status, attempt, abandoned, verdict, merged, pr, mainHas,
          lastTask, stopReason, workerResult, vv, vIssues, vManager, vNewer, vfiled,
          worker, verifier, vreport, wtDirty, stopOrder, fault, faulted,
          inRound, roundSame, rounds, mainConflicts, roundPushed, unverifiedMerge,
          revision, workerKept, verifierKept, findingsOpen, verifierAt, vvRev>>
RoundVars == <<inRound, roundSame, rounds, mainConflicts, roundPushed, unverifiedMerge>>
RevVars == <<revision, workerKept, verifierKept, findingsOpen, verifierAt, vvRev>>

\* ---------------------------------------------------------------- values

\* VERDICTS (line 126) without test-verified (acts like artifact-verified for a code task) and without
\* verify-blocked (acts like check-only in every modelled decision).
Levels == {"artifact-verified", "check-only", "verify-failed"}
Passing == {"artifact-verified"}                      \* PASSING["code"], line 129
WorkerStatuses == {"PASS", "ISSUES", "BLOCKED"}
\* Task rows: a worker's report, or a Manager row: BLOCKEDmgr (file_stuck), DIED, STOPPED without a Head
\* line (cmd_stop, stop_live), STOPPEDhead (commit_stopped), ABANDONED.
RowKinds == {"none", "BLOCKEDmgr", "DIED", "STOPPED", "STOPPEDhead", "ABANDONED"} \cup WorkerStatuses
StopReasons == {"none", "pause", "recover", "close"}
ManagerVerify == {"none", "BLOCKED", "manual", "carried"}   \* carried: a round's round_verdict filed again by the Manager (#119)
IssueKinds == {"none", "blocking", "unlabelled"}
Faults == {"none", "role", "exclude"}
\* One row of `claude agents --json --all`, as the Session class reads it (lines 551-596):
\*   busy        status busy, state working
\*   idle        status idle, state working ("it will check back")
\*   idleQuiet   (verifier) idle, and 30 minutes passed with no activity (VERIFIER_QUIET_MINUTES, 216)
\*   idleBlocked state blocked, status idle, no waitingFor: its turn ended with a question
\*   prompt      waitingFor set: a permission prompt
\*   stopping    (worker) `claude stop` was sent, the process has not exited (status still busy)
\*   finished    state done or stopped, status idle or none
\*   failed      state failed, status idle (finished, line 577)
\*   ghost       state working, no status, no pid: no process now; the CLI may start it again (Session.ghost, 581)
\*   ghostStopped (REGRESS_65B only) an idle/working row that a run.py stop left as a young ghost before part 3;
\*               it does not come back (a stopped row was not seen to revive), and goes quiet like a ghost
\*   ghostGone   a ghost quiet for 30 minutes (no transcript write, no start: quiet_for): it counts as ended
\*               (Run.sessions, lines 491-500, sets finished and turn_over; quiet_for, lines 3612-3620; stop_session, 624-637)
WorkerStates == {"none", "busy", "idle", "idleBlocked", "prompt", "stopping", "finished", "failed", "ghost", "ghostStopped", "ghostGone"}
VerifierStates == {"none", "busy", "idle", "idleQuiet", "idleBlocked", "prompt", "finished", "failed", "ghost", "ghostStopped", "ghostGone"}
OpenPr == {"pending", "clean", "behind", "blocked", "dirty"}
PrStates == {"none", "merged", "closed"} \cup OpenPr
Hints == {"launch", "verify", "verifyAgain", "close", "closeManual", "abandon", "stop", "merged", "record",
          "round", "roundCancel", "revise", "none"}

PrMode == MERGE_MODE = "pr"

\* Session class, lines 551-596. With REGRESS_42 a failed row is live and unknown, as before 0.10.3.
\* A young ghost row (#65, line 581) is live and unknown. A ghost quiet for VERIFIER_QUIET_MINUTES is gone:
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
\* verifier_over, lines 3622-3636: a turn that is over, or an unknown row quiet for 30 minutes.
VerifierOver(s) == TurnOver(s) \/ s \in {"idleQuiet", "ghostGone"}
\* The rule's words: the session ended, or its turn ended. Independent of the code's predicates. A gone ghost
\* counts as ended (the owner's rule for #65).
Over(s) == s \in {"finished", "failed", "idleBlocked", "ghostGone"}
\* work_filed (755-762): a task row that is not STOPPED for a worker; verifier_filed for a verifier.
WorkerFiled == workerResult # "none" \/ lastTask \in {"BLOCKEDmgr", "DIED"}
\* idle_and_filed (2323-2331): a worker that is idle or stuck with its work filed (#61; before: idle and not
\* waiting); a verifier that is idle, waits on nothing, and the attempt has a verify row.
IdleStatus(s) == s \in {"idle", "idleQuiet", "idleBlocked"} \/ (s = "failed" /\ REGRESS_42)   \* a failed row has status idle
WorkerIdleFiled ==
  Live(worker) /\ WorkerFiled /\ (IF REGRESS_61 THEN IdleStatus(worker) ELSE IdleStatus(worker) \/ Stuck(worker))
VerifierIdleFiled == Live(verifier) /\ IdleStatus(verifier) /\ (vv # "none" \/ vManager # "none")

End == (status = "done" /\ merged) \/ abandoned

\* The phase meta (0.19.0, #97). A passing close writes the verdict with phase awaiting_merge in one edit (cmd_close),
\* and nothing else writes a passing verdict, so Closed is the phase awaiting_merge or merged. Awaiting: closed and not
\* merged; the task stays in progress (`awaiting`, `unmerged`), and only a merge record marks it done (mark_merged,
\* finish_merged). With REGRESS_97 the close marks it done at once, as before 0.19.0.
Closed == verdict \in Passing
Awaiting == Closed /\ ~merged /\ ~abandoned
\* The status a close or record leaves: done once the change is merged (mark_merged), else unchanged.
StatusAfter(m) == IF m \/ REGRESS_97 THEN "done" ELSE status

\* The phase meta as derive_phase reads it from the other fields (#99): the model keeps no phase variable, and no action
\* or rule reads Phase. "none" is the code's None: a task not launched yet. The in-flight phases follow the newest task
\* row (is_worker_result: not DIED, STOPPED, ABANDONED or the Manager's BLOCKED) and the verifier of the attempt. Done
\* and not merged is a 0.18.0 close (only REGRESS_97 reaches it), which derive_phase reads as awaiting_merge.
\* phase-view.mjs draws the states by Phase, with run.py's event names on the steps; tests/test_run.py checks those
\* edges (phase-edges.json) against TRANSITIONS. Change phase-view.mjs's state() with this operator.
Phase ==
  IF abandoned THEN "abandoned"
  ELSE IF merged THEN "merged"
  ELSE IF status = "done" THEN "awaiting_merge"
  ELSE IF status = "open" THEN "none"
  ELSE IF verdict # "none" THEN (IF Closed THEN "awaiting_merge" ELSE "verdict_failed")
  ELSE IF lastTask = "none" THEN "running"
  ELSE IF lastTask \notin WorkerStatuses THEN "stopped"
  ELSE IF verifier # "none" \/ vv # "none" \/ vManager # "none" THEN "verifying"
  ELSE "reported"

\* ---------------------------------------------------------------- revisions (#127)

\* States past this bound are checked but not explored (only REGRESS_127C passes the cap).
RevisionBound == revision <= REVISION_CAP + 1

\* revision_possible: the verdict is a verifier's verify-failed with blocking lines (REGRESS_89 restores the unlabelled
\* case), below the cap, both sessions kept and finished (turn over, idle, resumable), no STOP order, no fault. With
\* REVISION_CAP = 0 it is FALSE, and no revision step is enabled: the lifecycle of 0.23.0.
RevisionOK ==
  /\ REVISION_CAP > 0
  /\ revision < REVISION_CAP \/ REGRESS_127C
  /\ verdict = "verify-failed" /\ vv = "verify-failed" /\ vManager # "manual"
  /\ vIssues = "blocking" \/ REGRESS_89
  /\ workerKept /\ verifierKept /\ worker = "finished" /\ verifier = "finished"
  /\ ~stopOrder /\ fault = "none"

\* ---------------------------------------------------------------- record

\* retry_next, lines 730-739: below the cap `run.py launch`; from MAX_ATTEMPTS on `run.py abandon <id> <mode>
\* (the cap is 3 attempts), or run.py launch --attempt <n+1> to override`. The Manager never overrides (0.18.0
\* rule 13: at the cap it abandons and re-plans; the override is for a bounded fix the operator names), so the
\* hint is abandon. Before 0.12.0 (REGRESS_56) the stuck, BLOCKED, unclosed and unknown hints said launch at
\* the cap; only ISSUES and died checked it.
\* #119: a round that fails is cancelled (round --cancel): the task waits again at its verified head. Launch refuses a
\* task in a round, so no hint of a round names launch or abandon.
RetryNext == IF inRound THEN "roundCancel" ELSE IF attempt < MAX_ATTEMPTS THEN "launch" ELSE "abandon"
RetryNextOld == IF inRound THEN "roundCancel" ELSE IF REGRESS_56 THEN "launch" ELSE RetryNext
\* stopped_next, lines 748-753: after a pause the launch, at any attempt; after any other stop retry_next.
\* Before 0.12.0 (REGRESS_59) every STOPPED row read as a pause.
StoppedNext == IF inRound THEN "roundCancel" ELSE IF stopReason = "pause" \/ REGRESS_59 THEN "launch" ELSE RetryNext
\* record_arrived: a round's PASS with the same change as round_from goes to close, which carries the verdict
\* (round_carry); any other PASS of a round goes to a verifier under [rounds] verify = "always".
ArrivedNext(st) ==                                                      \* record_arrived, lines 3535-3547
  IF st = "PASS" THEN
     IF inRound /\ roundSame THEN "close"
     ELSE IF HIGH_RISK \/ (inRound /\ ROUND_VERIFY = "always") \/ revision > 0 THEN "verify"   \* ci, risk high, a kind that is not code, a revision (#127)
     ELSE "closeManual"
  ELSE IF st = "ISSUES" THEN RetryNext                                  \* line 3542
  ELSE RetryNextOld                                                     \* line 3544: "answer it and ..."
UnclosedNext(v) ==                                                      \* unclosed_next, lines 923-934
  IF v = "verify-failed" THEN (IF RevisionOK THEN "revise" ELSE RetryNextOld)   \* #127 "revise: ...", else "fix round: ..."
  ELSE IF v = "check-only" THEN "verifyAgain"                           \* "verify --again ..., or accept it"
  ELSE "close"
\* The unknown hint, lines 3859-3863 (#58): `claude logs <sid>; if it has stopped working, run.py stop <id>,
\* then run.py record and run.py launch <id>`; at the cap `run.py abandon <id> unknown (...), or run.py stop <id>,
\* then run.py record and run.py launch <id> --attempt <n+1> to override`, read as abandon. Before 0.12.0
\* (REGRESS_58): `claude logs` only. REGRESS_59 takes the second alternative at the cap (the recovery stop),
\* which is the stop the old exemption bug needed.
UnknownNext ==
  IF REGRESS_58 THEN "none"
  ELSE IF inRound \/ attempt < MAX_ATTEMPTS \/ REGRESS_59 THEN "stop"
  ELSE "abandon"

\* What one `record` would write and print: the new values plus the event and its hint. A record never changes
\* vIssues (it reads the Verdict: line only, verdict_of 709-711), fault or faulted.
Same == [lastTask |-> lastTask, stopReason |-> stopReason, workerResult |-> workerResult, vv |-> vv,
         vManager |-> vManager, vNewer |-> vNewer, vfiled |-> vfiled, worker |-> worker, verifier |-> verifier,
         vreport |-> vreport, wtDirty |-> wtDirty, merged |-> merged, pr |-> pr,
         ev |-> "none", nx |-> "none"]

\* commit_stopped, lines 3673-3716: a STOPPED row without a Head line gets its WIP committed once the stopped
\* worker has exited; the new row copies the Reason: line (3675-3677). record_in_progress runs it first, lines
\* 3744-3746 (the #54 fix); before 0.11.2 it ran only after the verifier and verdict checks (REGRESS_54).
PauseOutOf(b) ==
  IF worker = "stopping" THEN [b EXCEPT !.ev = "stopping", !.nx = "none"]           \* 3679-3681
  ELSE [b EXCEPT !.lastTask = "STOPPEDhead", !.wtDirty = FALSE, !.ev = "stopped", !.nx = StoppedNext]  \* 3706-3716
PauseOut == PauseOutOf(Same)

\* record_in_progress from line 3844 on: the task rows of the attempt.
TaskRowsOut(b) ==
  IF lastTask = "none" THEN
     IF Stuck(worker) THEN                                              \* file_stuck, lines 3848-3856
        [b EXCEPT !.worker = "finished", !.lastTask = "BLOCKEDmgr", !.ev = "stuck", !.nx = RetryNextOld]
     ELSE IF worker \in {"busy", "stopping"} THEN [b EXCEPT !.ev = "running", !.nx = "none"]   \* 3857-3858
     ELSE IF Unknown(worker) THEN [b EXCEPT !.ev = "unknown", !.nx = UnknownNext]   \* 3859-3863
     ELSE [b EXCEPT !.lastTask = "DIED", !.ev = "died", !.nx = RetryNext]           \* lines 3883-3890
  ELSE IF lastTask = "STOPPEDhead" THEN [b EXCEPT !.ev = "stopped", !.nx = StoppedNext]  \* lines 3893-3896
  ELSE IF lastTask = "STOPPED" THEN PauseOutOf(b)                      \* 3897-3898: only reached with REGRESS_54
  ELSE IF lastTask = "DIED" THEN [b EXCEPT !.ev = "died", !.nx = RetryNext]        \* lines 3899-3900
  ELSE IF lastTask = "BLOCKEDmgr" THEN [b EXCEPT !.ev = "stuck", !.nx = RetryNextOld]   \* 3520-3528
  ELSE [b EXCEPT !.ev = "arrived", !.nx = ArrivedNext(lastTask)]

\* record_in_progress lines 3823-3840: the verdict rows of the attempt. A Manager row with no verdict (the
\* BLOCKED row of a stuck verifier) no longer hides an older verdict (3825-3829, #62). Since 8006a3c a verifier's
\* verify-failed row whose Issues: lines fail verifier_problems (unlabelled_failure, 714-723) gets the hint
\* `run.py verify <id> --again (the verifier's report has no blocking: line: ...)` (unlabelled_next, 726-727;
\* emit_verified 2823-2835), at any attempt; close refuses it (choose_verdict 5397-5400). Before (REGRESS_89)
\* only the Verdict: line was read, and the hint was close.
Verdicts(b) ==
  IF b.vv # "none" /\ b.vNewer /\ (verdict = "none" \/ b.vv # verdict)
  THEN [b EXCEPT !.ev = "verified",
                 !.nx = IF vIssues = "unlabelled" /\ ~REGRESS_89 THEN "verifyAgain" ELSE "close"]
  ELSE IF verdict # "none" THEN [b EXCEPT !.ev = "unclosed", !.nx = UnclosedNext(verdict)]   \* 3838-3840
  ELSE TaskRowsOut(b)

\* record_in_progress lines 3719-3891.
RecInProgress ==
  LET vRunning == Live(verifier) /\ ~VerifierOver(verifier)             \* line 3781
      lost == verifier # "none" /\ ~vfiled                               \* lost_verifier, lines 3638-3643
      salvaged == [Same EXCEPT !.vv = "artifact-verified", !.vNewer = TRUE, !.vfiled = TRUE,
                   !.vreport = FALSE,
                   !.verifier = IF Live(verifier) /\ ~Ghost(verifier) THEN "finished" ELSE verifier]   \* salvage_verifier, 3657-3670
      \* #62, lines 3784-3790: a verifier that waits after its filed verdict is stopped, no row, record goes on.
      stoppedIdle == [Same EXCEPT !.verifier = "finished"]
      \* file_stuck, lines 3791-3797: BLOCKED by the Manager; before 0.12.0 that row outranked the verdict.
      stuckOut == [Same EXCEPT !.verifier = "finished", !.vManager = "BLOCKED",
                   !.vNewer = IF REGRESS_62 THEN FALSE ELSE vNewer,
                   !.vfiled = TRUE, !.ev = "stuck", !.nx = "verifyAgain"]
  IN IF lastTask = "STOPPED" /\ ~REGRESS_54 THEN PauseOut
     ELSE IF vRunning /\ Stuck(verifier) /\ vfiled /\ ~REGRESS_62 THEN Verdicts(stoppedIdle)
     ELSE IF vRunning /\ Stuck(verifier) THEN stuckOut
     ELSE IF vRunning THEN [Same EXCEPT !.ev = "verifying", !.nx = "none"]          \* 3798-3800
     ELSE IF lost /\ ~vreport THEN [Same EXCEPT !.ev = "no-verdict", !.nx = "verifyAgain"]  \* 3803-3812
     ELSE Verdicts(IF lost THEN salvaged ELSE Same)

\* #119, conflict_next: below [rounds] cap the conflict hint is `run.py round <id> rebase`, at it the decision only.
\* REGRESS_119 restores the path the vmt Manager took before 0.23.0: the redo hint, abandon (then launch --attempt).
RoundNext == IF rounds < ROUND_CAP THEN "round" ELSE "none"
ConflictNext == IF REGRESS_119 THEN "abandon" ELSE RoundNext

\* pr_status, lines 5033-5086. The standing orders hold a MERGE: line, so a clean request is merged here,
\* except during a pause (5072).
PrStatus(b) ==
  IF pr = "merged" THEN [b EXCEPT !.merged = TRUE, !.ev = "merged", !.nx = "none"]
  ELSE IF pr = "closed" THEN [b EXCEPT !.ev = "pr-closed", !.nx = "none"]      \* reopen it, or a decision
  ELSE IF pr = "pending" THEN [b EXCEPT !.ev = "pr-pending", !.nx = "none"]    \* record later
  ELSE IF pr = "dirty" THEN [b EXCEPT !.ev = "conflict", !.nx = ConflictNext]  \* a round, or at the cap a decision (#119)
  ELSE IF pr = "behind" THEN [b EXCEPT !.ev = "pr-behind", !.nx = "close"]
  ELSE IF pr = "blocked" THEN [b EXCEPT !.ev = "pr-blocked", !.nx = "none"]    \* record later
  ELSE IF stopOrder THEN [b EXCEPT !.ev = "ready-to-merge", !.nx = "none"]
  ELSE [b EXCEPT !.pr = "merged", !.merged = TRUE, !.ev = "merged", !.nx = "none"]

\* record_closed, lines 3941-3978: a done task, or one in progress that waits for its merge.
RecDone ==
  IF merged THEN [Same EXCEPT !.ev = "nothing", !.nx = "none"]
  ELSE IF PrMode THEN
     IF pr = "none" THEN [Same EXCEPT !.ev = "unpublished", !.nx = "close"]   \* line 3956
     ELSE PrStatus(Same)                                                 \* line 3959
  ELSE IF mainHas THEN [Same EXCEPT !.merged = TRUE, !.ev = "merged", !.nx = "none"]   \* merged_into, 3967
  ELSE IF mainConflicts THEN [Same EXCEPT !.ev = "conflict", !.nx = ConflictNext]   \* git merge-tree (#119)
  ELSE [Same EXCEPT !.ev = "unmerged", !.nx = "none"]                   \* line 3975: no next

RecOut ==
  IF abandoned THEN [Same EXCEPT !.ev = "nothing", !.nx = "none"]
  ELSE IF status = "open" THEN [Same EXCEPT !.ev = "ready", !.nx = "launch"]  \* ready_events, line 3981
  ELSE IF status = "in_progress" /\ ~Closed THEN RecInProgress  \* Snapshot.in_progress: not a task that waits for its merge
  ELSE RecDone                                                     \* record_closed: done, or in progress and awaiting_merge

RecordHasEffect ==
  LET o == RecOut IN
  \/ o.lastTask # lastTask \/ o.workerResult # workerResult \/ o.vv # vv \/ o.vManager # vManager
  \/ o.vNewer # vNewer \/ o.vfiled # vfiled \/ o.worker # worker \/ o.verifier # verifier
  \/ o.vreport # vreport \/ o.wtDirty # wtDirty \/ o.merged # merged \/ o.pr # pr

\* record_round (#119): the request of a round merged. record_task runs it before record_in_progress.
RoundMergedPending == inRound /\ PrMode /\ pr = "merged" /\ status = "in_progress" /\ ~abandoned

\* The step that record names. While record still has something to write, the Manager runs record.
Hint == IF RecordHasEffect \/ RoundMergedPending THEN "record" ELSE RecOut.nx
Event == RecOut.ev

Record ==
  /\ ~RoundMergedPending
  /\ RecordHasEffect
  /\ LET o == RecOut IN
       /\ lastTask' = o.lastTask /\ workerResult' = o.workerResult /\ vv' = o.vv /\ vManager' = o.vManager
       /\ vNewer' = o.vNewer /\ vfiled' = o.vfiled /\ worker' = o.worker /\ verifier' = o.verifier
       /\ vreport' = o.vreport /\ wtDirty' = o.wtDirty /\ merged' = o.merged /\ pr' = o.pr
       /\ vIssues' = IF o.vv = vv THEN vIssues ELSE "none"             \* a salvaged report is a passing one
       /\ status' = IF o.merged # merged THEN "done" ELSE status         \* a merge record runs `tg done` (mark_merged)
       /\ vvRev' = IF o.vv # vv THEN verifierAt ELSE vvRev              \* a salvaged verifier row judged its seat's head
       /\ workerKept' = (workerKept /\ o.worker = worker)               \* a session that record stops is not kept
       /\ verifierKept' = (verifierKept /\ o.verifier = verifier)
  /\ UNCHANGED <<attempt, abandoned, verdict, mainHas, stopReason, stopOrder, fault, faulted>>
  /\ UNCHANGED RoundVars /\ UNCHANGED <<revision, findingsOpen, verifierAt>>

\* ---------------------------------------------------------------- launch

\* #127: a new attempt (launch, round) starts with no revision; launch stops both kept sessions as idle and filed.
RevReset ==
  /\ revision' = 0 /\ workerKept' = FALSE /\ verifierKept' = FALSE /\ findingsOpen' = FALSE
  /\ verifierAt' = 0 /\ vvRev' = 0

\* cmd_launch, lines 2333-2552, without --attempt, --base, --model. Lines 2373-2398: a live row refuses the
\* launch, unless every live row is idle_and_filed; then launch stops them (stopped-idle, 2386-2395) and goes
\* on. The checks after that can still refuse (2412: a pause not committed; 2413: the cap).
\* The checks before the live-row scan: a STOP order (2335-2337, exit 3), info/exclude (ignore_reports and
\* ignore_scratch, 2338-2340, since ff2c8b0: a read-only file refuses before anything is stopped or committed),
\* a done task (2349), the role (choose, 2353: a role file that is missing or broken refuses, 0.18.0),
\* abandoned (2359); a task that waits for its merge (refuse_closed, 0.19.0).
EarlyChecks == ~stopOrder /\ fault = "none" /\ status # "done" /\ ~Awaiting /\ ~abandoned /\ ~inRound   \* refuse_round (#119)
\* The checks after it: a pause not committed (2412); refuse_past_cap (2555-2563): past MAX_ATTEMPTS only a
\* STOPPED row with Reason: pause is exempt (#59; before 0.12.0, REGRESS_59, any STOPPED row).
Exempt == lastTask = "STOPPEDhead" /\ (stopReason = "pause" \/ REGRESS_59)
LateChecks == lastTask # "STOPPED" /\ ((attempt + 1 <= MAX_ATTEMPTS) \/ Exempt)
LiveRowsAllowLaunch ==
  /\ ~(Live(worker) /\ ~WorkerIdleFiled)
  /\ ~(Live(verifier) /\ ~VerifierIdleFiled)
LaunchStopsIdle == (Live(worker) \/ Live(verifier)) /\ LiveRowsAllowLaunch /\ attempt >= 1

\* Before part 3 of #65 (REGRESS_65B), the stop of an idle/working row left a young ghost, and the launch's second
\* read of the live rows (2397) refused on it: the field's "None/working" refusal.
StoppedIdleGhosts == REGRESS_65B /\ ((Live(worker) /\ worker = "idle") \/ (Live(verifier) /\ verifier \in {"idle", "idleQuiet"}))

Launch ==
  /\ Hint = "launch"
  /\ EarlyChecks
  /\ LiveRowsAllowLaunch
  /\ LateChecks
  /\ ~StoppedIdleGhosts
  /\ status' = "in_progress" /\ attempt' = attempt + 1 /\ verdict' = "none"   \* lines 2529-2544
  /\ lastTask' = "none" /\ stopReason' = "none" /\ workerResult' = "none"
  /\ vv' = "none" /\ vIssues' = "none" /\ vManager' = "none" /\ vNewer' = FALSE /\ vfiled' = TRUE
  /\ worker' = "busy" /\ verifier' = "none" /\ vreport' = FALSE
  /\ wtDirty' = FALSE                                                   \* lines 2489-2499: WIP is committed
  /\ UNCHANGED <<abandoned, merged, pr, mainHas, stopOrder, fault, faulted>>
  /\ UNCHANGED RoundVars
  /\ RevReset                                                           \* launch stops both kept sessions (#127)

\* The launch stopped the idle sessions (2386-2395) and then refused (2412 or 2413): the rows ended, nothing else.
LaunchStopsIdleThenRefuses ==
  /\ Hint = "launch"
  /\ EarlyChecks
  /\ LaunchStopsIdle
  /\ (~LateChecks \/ StoppedIdleGhosts)
  /\ worker' = IF Live(worker) THEN AfterStop(worker) ELSE worker
  /\ verifier' = IF Live(verifier) THEN AfterStop(verifier) ELSE verifier
  /\ UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, stopReason, workerResult,
                 vv, vIssues, vManager, vNewer, vfiled, vreport, wtDirty, stopOrder, fault, faulted>>
  /\ UNCHANGED RoundVars
  /\ workerKept' = FALSE /\ verifierKept' = FALSE                     \* the kept sessions are stopped too (#127)
  /\ UNCHANGED <<revision, findingsOpen, verifierAt, vvRev>>

\* ---------------------------------------------------------------- verify

\* cmd_verify in session mode, lines 2674-2761. Shared checks of both forms. The role of the attempt is read
\* from its file again (verify_role, 1218-1225, at 2684): a missing or broken file refuses, and so does a
\* read-only info/exclude (2696-2698, since ff2c8b0), both before anything is stopped.
VerifyAccepted ==
  /\ status = "in_progress" /\ ~abandoned /\ ~Closed                    \* refuse_unless_running, 2648-2656
  /\ fault = "none"
  /\ workerResult = "PASS"                                              \* worker_for, lines 2659-2671
  /\ ~(Live(verifier) /\ ~VerifierOver(verifier))                       \* lines 2700-2703
  \* #127: in the task worktree the verifier starts only once the worker's turn is over (REGRESS_127W drops the check).
  /\ (SEAT = "task" /\ ~REGRESS_127W) => worker # "busy"
VerifyUnchanged ==
  UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, stopReason, workerResult,
              vv, vManager, vNewer, worker, wtDirty, stopOrder, fault, faulted>>
  /\ UNCHANGED RoundVars

VerifyPlain ==
  /\ Hint = "verify"
  /\ VerifyAccepted
  /\ vv = "none"                                                        \* lines 2690-2695: else --again
  /\ ~(revision > 0 /\ verifierKept)                                    \* #127: a kept verifier is resumed (VerifyResume)
  /\ verifier' = "busy" /\ vfiled' = FALSE /\ vreport' = FALSE          \* 2704-2708 stop the old one; 2751 start
  /\ verifierAt' = revision /\ verifierKept' = FALSE
  /\ UNCHANGED vIssues /\ VerifyUnchanged /\ UNCHANGED <<revision, workerKept, findingsOpen, vvRev>>

\* --again also after an unlabelled verify-failed row (its hint since 8006a3c): the row stays, with its Issues:
\* lines (vIssues describes the vv row, so it changes only with vv), until the new verifier's row replaces it.
VerifyAgain ==
  /\ Hint = "verifyAgain"
  /\ VerifyAccepted
  /\ verifier' = "busy" /\ vfiled' = FALSE /\ vreport' = FALSE
  /\ verifierAt' = revision /\ verifierKept' = FALSE                   \* a new verifier; the kept one is stopped (#127)
  /\ UNCHANGED vIssues /\ VerifyUnchanged /\ UNCHANGED <<revision, workerKept, findingsOpen, vvRev>>

\* #127: cmd_verify resumes the kept verifier of a revision; with seat own it moves the folder to the new head first.
VerifyResume ==
  /\ Hint = "verify"
  /\ VerifyAccepted
  /\ revision > 0 /\ verifierKept /\ vv = "none"
  /\ verifier' = "busy" /\ vfiled' = FALSE /\ vreport' = FALSE
  /\ verifierAt' = IF REGRESS_127H THEN verifierAt ELSE revision
  /\ UNCHANGED <<vIssues, revision, workerKept, verifierKept, findingsOpen, vvRev>> /\ VerifyUnchanged

\* ---------------------------------------------------------------- close

\* #127: stop_live, abandon and the merge record also stop the kept idle sessions; the revision meta stays.
StopKept == workerKept' = FALSE /\ verifierKept' = FALSE /\ UNCHANGED <<revision, findingsOpen, verifierAt, vvRev>>

\* stop_live, lines 5313-5333: stop the live worker (a STOPPED row with Reason: close, no Head line) and, since
\* 0.12.0 (#57), the live verifier (no row). Before (REGRESS_57) a verifier stayed live.
StopLive ==
  /\ worker' = IF Live(worker) THEN AfterStop(worker) ELSE worker
  /\ lastTask' = IF Live(worker) THEN "STOPPED" ELSE lastTask
  /\ stopReason' = IF Live(worker) THEN "close" ELSE stopReason
  /\ verifier' = IF Live(verifier) /\ ~REGRESS_57 THEN AfterStop(verifier) ELSE verifier
  /\ StopKept

\* publish with catch_up (lines 4818-4879) once the host shows the request in state s:
\* clean is merged (pr_status), unless a STOP order holds it; behind goes to the host's rebase (host_catch_up,
\* 4906-4951), which ends rebased (the host recomputes the state), in a conflict (a decision), or not at all.
PublishAfter(s) ==
  \/ s = "clean" /\ ~stopOrder /\ pr' = "merged" /\ merged' = TRUE
  \/ s = "clean" /\ stopOrder /\ pr' = s /\ merged' = merged            \* ready-to-merge: not merged during a pause
  \/ s = "behind" /\ merged' = merged /\ pr' \in {"pending", "dirty", "behind"}
  \/ s \in {"pending", "blocked", "dirty", "closed"} /\ pr' = s /\ merged' = merged
  \/ s = "merged" /\ pr' = s /\ merged' = TRUE

\* A first push creates the request and the host picks its state; or the push fails (push-failed, 4894: exit 1,
\* the task in progress with phase awaiting_merge), and record says unpublished until a later close pushes again.
\* A round's close pushes a new head to the open request, and the host computes its state again (#119).
PublishStep ==
  IF pr = "none" THEN (\E s \in OpenPr : PublishAfter(s)) \/ (pr' = "none" /\ merged' = merged)
  ELSE IF inRound /\ pr \in OpenPr THEN pr' = "pending" /\ merged' = merged
  ELSE PublishAfter(pr)

\* merge_branch, lines 5624-5654: a merge, or a conflict that becomes a decision, or a pause (5626-5627, 5635-5638).
\* A conflict stays until the target changes (mainConflicts); a round's head resolved the conflict it had (#119). A
\* merge that fails for any other cause (a pause, a dirty checkout, no MERGE: line) leaves no conflict.
LocalMergeStep ==
  \/ (~stopOrder /\ (~mainConflicts \/ inRound) /\ merged' = TRUE /\ mainHas' = TRUE /\ mainConflicts' = FALSE)
  \/ (merged' = FALSE /\ mainHas' = mainHas /\ mainConflicts' \in (IF mainConflicts /\ ~inRound THEN {TRUE} ELSE BOOLEAN))

\* 0.12.3 (#72): a verified head with no commit beyond its base is recorded merged at once, with no merge,
\* push or request (no_change 5414-5426, close_no_change 5429-5436; at 5608-5613 and 5370-5372). A free
\* choice: the model does not track the commits of the branch. Only before any request exists.
NoChangeClose == pr = "none" /\ merged' = TRUE /\ UNCHANGED <<pr, mainHas>>

Finish ==
  \/ (NoChangeClose /\ UNCHANGED mainConflicts)
  \/ (IF PrMode THEN mainHas' = mainHas /\ mainConflicts' = mainConflicts /\ PublishStep
      ELSE pr' = pr /\ LocalMergeStep)

\* resume_close, lines 5354-5381: a closed task that waits for its merge (unmerged: phase awaiting_merge).
ResumeClose ==
  /\ Awaiting                                                          \* cmd_close, lines 5543-5544
  /\ StopLive
  /\ Finish
  /\ status' = StatusAfter(merged')
  /\ UNCHANGED <<attempt, abandoned, verdict, workerResult, vv, vIssues, vManager, vNewer, vfiled,
                 vreport, wtDirty, stopOrder, fault, faulted, inRound, roundSame, rounds, roundPushed, unverifiedMerge>>

\* cmd_close lines 5603-5620: stop the sessions, publish or merge; `tg done` only with the merge (mark_merged).
CloseAsPassing == StopLive /\ Finish /\ status' = StatusAfter(merged')

\* cmd_close lines 5599-5602: the verdict is recorded, the task is not closed.
CloseNotPassing ==
  /\ status' = status
  /\ UNCHANGED <<worker, verifier, lastTask, stopReason, merged, pr, mainHas, mainConflicts>>
  /\ UNCHANGED RevVars

\* cmd_close, lines 5535-5621, with choose_verdict, lines 5384-5411. L is --verdict, or "auto" for none.
\* close never refuses on a role: verify_kind (2161-2176) reads the kind stored at launch (0.18.0).
\* The carry (#119, round_carry): a round's PASS with the same change as round_from, no verifier verdict and no
\* --verdict keeps round_verdict, with a Manager row. A passing close ends the round.
NormalClose(L) ==
  /\ status = "in_progress" /\ ~abandoned /\ ~Closed                    \* refuse_unless_running; else resume_close
  /\ workerResult = "PASS"                                              \* worker_for
  /\ LET carry == inRound /\ roundSame /\ vv = "none" /\ L = "auto"
         level == IF carry THEN "artifact-verified" ELSE IF vv = "none" THEN L ELSE vv
         manual == vv = "none" /\ ~carry
     IN /\ (vv = "none" /\ ~carry) => (L # "auto")                      \* line 5393: no verdict at all
        /\ (vv # "none") => (L = "auto" \/ L = vv)                      \* lines 5395-5408: no --override-verifier
        /\ ~(vv # "none" /\ vIssues = "unlabelled" /\ ~REGRESS_89)      \* 5397-5400: refused, `verify --again` (8006a3c)
        /\ verdict' = level                                             \* line 5579
        /\ vManager' = IF carry THEN "carried" ELSE IF manual THEN "manual" ELSE vManager   \* lines 5562-5574
        /\ vNewer' = IF manual \/ carry THEN FALSE ELSE vNewer
        /\ vfiled' = (vfiled \/ manual \/ carry)
        /\ inRound' = (inRound /\ level \notin Passing)
        /\ roundSame' = (roundSame /\ level \notin Passing)
        /\ roundPushed' = (roundPushed /\ level \notin Passing)
        /\ IF level \in Passing THEN CloseAsPassing ELSE CloseNotPassing
  /\ UNCHANGED <<attempt, abandoned, workerResult, vv, vIssues, vreport, wtDirty, stopOrder, fault, faulted,
                 rounds, unverifiedMerge>>

CloseAuto ==
  /\ Hint = "close"
  /\ ResumeClose \/ NormalClose("auto")
  /\ vars' # vars

CloseManual ==
  /\ Hint = "closeManual"
  /\ \E L \in Levels : ResumeClose \/ NormalClose(L)
  /\ vars' # vars

\* ---------------------------------------------------------------- stop, abandon, merged

\* cmd_stop, lines 5674-5709: accepted for any live worker row of the attempt (5684, `s.live`). The row's
\* Reason: is pause under a STOP order, else recover (5696). The Manager runs it where the `unknown` hint
\* says so (#58); the operator runs it as a pause under a STOP order (OPERATOR_PAUSES).
Stop ==
  /\ status = "in_progress" /\ ~Closed /\ Live(worker)                  \* cmd_stop refuses a task that waits for its merge
  /\ \/ Hint = "stop"
     \/ (OPERATOR_PAUSES /\ stopOrder /\ worker = "busy")
  /\ worker' = IF worker = "busy" THEN "stopping" ELSE AfterStop(worker)   \* stop_session: the row counts as ended
  /\ lastTask' = "STOPPED"                                              \* lines 5702-5704: no Head line
  /\ stopReason' = IF stopOrder THEN "pause" ELSE "recover"
  /\ UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, workerResult,
                 vv, vIssues, vManager, vNewer, vfiled, verifier, vreport, wtDirty, stopOrder, fault, faulted>>
  /\ UNCHANGED RoundVars
  /\ workerKept' = FALSE /\ UNCHANGED <<revision, verifierKept, findingsOpen, verifierAt, vvRev>>

\* cmd_abandon, lines 5712-5762: stops the task's live worker sessions (5722-5727) and, since 0.12.0 (#57),
\* its live verifier (5728-5731). At the cap the Manager abandons and re-plans (0.18.0 rule 13): the new task
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
  /\ UNCHANGED RoundVars
  /\ StopKept

\* cmd_merged, lines 5657-5671, through mark_merged. No modelled event names it, so it never fires (NOTES.md).
Merged ==
  /\ Hint = "merged"
  /\ Awaiting
  /\ merged' = TRUE /\ status' = "done"
  /\ UNCHANGED <<attempt, abandoned, verdict, pr, mainHas, lastTask, stopReason, workerResult,
                 vv, vIssues, vManager, vNewer, vfiled, worker, verifier, vreport, wtDirty, stopOrder, fault, faulted>>
  /\ UNCHANGED RoundVars
  /\ StopKept

\* ---------------------------------------------------------------- round (#119)

\* cmd_round, start_round: a round on a task that waits for its merge and whose kind applies (rebase: the request is
\* DIRTY, or git merge-tree finds a conflict). Its checks: the STOP order (exit 3), the phase, the kind, the cap, no live
\* session, the role file of the kind (choose), info/exclude. The Manager never passes --attempt, so the cap holds.
StartRound ==
  /\ Hint = "round"
  /\ status = "in_progress" /\ Awaiting /\ ~inRound
  /\ ~stopOrder /\ fault = "none"
  /\ IF PrMode THEN pr = "dirty" ELSE mainConflicts
  /\ rounds < ROUND_CAP
  /\ ~Live(worker) /\ ~Live(verifier)
  /\ inRound' = TRUE /\ roundSame' = FALSE /\ roundPushed' = FALSE /\ rounds' = rounds + 1
  /\ attempt' = attempt + 1 /\ verdict' = "none"                          \* round_verdict keeps the old one
  /\ lastTask' = "none" /\ stopReason' = "none" /\ workerResult' = "none"
  /\ vv' = "none" /\ vIssues' = "none" /\ vManager' = "none" /\ vNewer' = FALSE /\ vfiled' = TRUE
  /\ worker' = "busy" /\ verifier' = "none" /\ vreport' = FALSE /\ wtDirty' = FALSE
  /\ UNCHANGED <<status, abandoned, merged, pr, mainHas, mainConflicts, stopOrder, fault, faulted, unverifiedMerge>>
  /\ RevReset

\* record_round's round-not-needed line: the verified head would merge as it is.
ConflictGone == inRound /\ IF PrMode THEN pr \in {"clean", "behind", "blocked"} ELSE ~mainConflicts

\* cmd_round --cancel, on a failed round's hint or on the round-not-needed line: stop the sessions (stop_live), commit
\* the WIP and keep the round's head in a ref, reset --keep to round_from, push round_from back when the round's head
\* was pushed, file the carried Manager row, and restore the verdict: the task waits for its merge again.
RoundCancel ==
  /\ inRound /\ status = "in_progress" /\ ~abandoned
  /\ Hint = "roundCancel" \/ (ConflictGone /\ Hint # "record")
  /\ StopLive
  /\ verdict' = "artifact-verified" /\ vManager' = "carried" /\ vNewer' = FALSE /\ vfiled' = TRUE
  /\ wtDirty' = FALSE
  /\ pr' = IF roundPushed /\ pr \in OpenPr THEN "pending" ELSE pr
  /\ inRound' = FALSE /\ roundSame' = FALSE /\ roundPushed' = FALSE
  /\ UNCHANGED <<status, attempt, abandoned, merged, mainHas, workerResult, vv, vIssues, vreport,
                 stopOrder, fault, faulted, rounds, mainConflicts, unverifiedMerge>>

\* record_round, round_merged (#119): stop the round's sessions and record the merge (`tg done`). The verdict of
\* round_from carries (a Manager row) only when the merged head is round_from, which no round step pushed over, or the
\* same change; else it is the operator's merge of a head no verdict covers (merged_by=operator, no verdict). The
\* round's verifier is moot: stop_live records its session with no row, so nothing waits for its verdict.
RoundMerged ==
  /\ RoundMergedPending
  /\ StopLive
  /\ LET carry == ~roundPushed \/ roundSame IN
       /\ verdict' = IF carry THEN "artifact-verified" ELSE verdict
       /\ vManager' = IF carry THEN "carried" ELSE vManager
       /\ vNewer' = IF carry THEN FALSE ELSE vNewer
       /\ unverifiedMerge' = ~carry
  /\ vfiled' = TRUE /\ merged' = TRUE /\ status' = "done"
  /\ inRound' = FALSE /\ roundSame' = FALSE /\ roundPushed' = FALSE
  /\ UNCHANGED <<attempt, abandoned, pr, mainHas, workerResult, vv, vIssues, vreport, wtDirty,
                 stopOrder, fault, faulted, rounds, mainConflicts>>

Done == End /\ UNCHANGED vars

\* ---------------------------------------------------------------- environment

\* Sessions keep their state until something acts on them: an idle verifier may wake up or go quiet; an idle
\* worker, and every quiet, blocked, prompted, failed or finished session, changes only when stopped.
\* With FULL_ENV = FALSE only the steps of the main flow exist: a worker reports and ends, a verifier files
\* and ends, a stopped worker exits, the operator merges, the host moves the request.
NotSessions == <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, stopReason, workerResult,
                 vv, vIssues, vManager, vNewer, vfiled, vreport, wtDirty, stopOrder, fault, faulted,
                 inRound, roundSame, rounds, mainConflicts, roundPushed, unverifiedMerge>>

WorkerEnds == ~End /\ worker = "busy" /\ worker' = "finished" /\ UNCHANGED verifier /\ UNCHANGED NotSessions /\ UNCHANGED RevVars
WorkerExits == ~End /\ worker = "stopping" /\ worker' = "finished" /\ UNCHANGED verifier /\ UNCHANGED NotSessions /\ UNCHANGED RevVars
WorkerFails == ~End /\ FULL_ENV /\ worker = "busy" /\ worker' = "failed" /\ UNCHANGED verifier /\ UNCHANGED NotSessions /\ UNCHANGED RevVars
WorkerIdles == ~End /\ FULL_ENV /\ worker = "busy" /\ worker' = "idle" /\ UNCHANGED verifier /\ UNCHANGED NotSessions /\ UNCHANGED RevVars
WorkerAsks == ~End /\ FULL_ENV /\ worker = "busy" /\ worker' = "idleBlocked" /\ UNCHANGED verifier /\ UNCHANGED NotSessions /\ UNCHANGED RevVars
WorkerPrompted == ~End /\ FULL_ENV /\ worker = "busy" /\ worker' = "prompt" /\ UNCHANGED verifier /\ UNCHANGED NotSessions /\ UNCHANGED RevVars
\* #65: the process dies (kill -9, a crash): the row stays live with no status and no pid. The CLI may start it
\* again (status idle, a new pid), or the row stays; after 30 quiet minutes it counts as ended (ghostGone).
WorkerGhosts == ~End /\ FULL_ENV /\ worker = "busy" /\ worker' = "ghost" /\ UNCHANGED verifier /\ UNCHANGED NotSessions /\ UNCHANGED RevVars
WorkerGhostReturns == ~End /\ FULL_ENV /\ worker = "ghost" /\ worker' = "idle" /\ UNCHANGED verifier /\ UNCHANGED NotSessions /\ UNCHANGED RevVars
WorkerGhostStays == ~End /\ FULL_ENV /\ worker \in {"ghost", "ghostStopped"} /\ worker' = "ghostGone" /\ UNCHANGED verifier /\ UNCHANGED NotSessions /\ UNCHANGED RevVars


\* A worker files one result per revision of an attempt, as its last step (worker.md "Report": run check-report, fix what it
\* names, then the one report command). A report that check-report refuses (too few Evidence: lines, a path
\* that does not exist) is rewritten, or filed as it is when the worker cannot fix it (step 1 -> 2): either
\* way the row that lands is one of these three, so the refusal is no state of its own. Its process may still
\* show as live for a while after that.
WorkerFilesUnchanged ==
  UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, stopReason,
              vv, vIssues, vManager, vNewer, vfiled, worker, verifier, vreport, wtDirty, stopOrder, fault, faulted,
              inRound, rounds, mainConflicts, roundPushed, unverifiedMerge>>
\* A round's PASS is the same change as round_from, or not (same_change): a free choice. Outside a round it is FALSE.
\* #127: mailbox.py report refuses while a finding steer has no ack (REGRESS_127A drops the check). A worker that filed PASS
\* is kept for a revision.
ReportAllowed == ~findingsOpen \/ REGRESS_127A
WorkerFilesPass ==
  /\ ~End /\ worker = "busy" /\ workerResult = "none" /\ lastTask' = "PASS" /\ workerResult' = "PASS"
  /\ ReportAllowed
  /\ roundSame' \in (IF inRound THEN BOOLEAN ELSE {FALSE})
  /\ WorkerFilesUnchanged
  /\ workerKept' = (REVISION_CAP > 0) /\ UNCHANGED <<revision, verifierKept, findingsOpen, verifierAt, vvRev>>
WorkerFilesIssues ==
  ~End /\ worker = "busy" /\ workerResult = "none" /\ lastTask' = "ISSUES" /\ workerResult' = "ISSUES"
  /\ ReportAllowed /\ UNCHANGED roundSame /\ WorkerFilesUnchanged /\ UNCHANGED RevVars
WorkerFilesBlocked ==
  ~End /\ worker = "busy" /\ workerResult = "none" /\ lastTask' = "BLOCKED" /\ workerResult' = "BLOCKED"
  /\ ReportAllowed /\ UNCHANGED roundSame /\ WorkerFilesUnchanged /\ UNCHANGED RevVars

WorkerDirties ==
  /\ ~End /\ FULL_ENV /\ worker = "busy" /\ ~wtDirty /\ wtDirty' = TRUE
  /\ UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, stopReason, workerResult,
                 vv, vIssues, vManager, vNewer, vfiled, worker, verifier, vreport, stopOrder, fault, faulted>>
  /\ UNCHANGED RoundVars /\ UNCHANGED RevVars

VerifierEnds == ~End /\ verifier = "busy" /\ verifier' = "finished" /\ UNCHANGED worker /\ UNCHANGED NotSessions /\ UNCHANGED RevVars
VerifierFails == ~End /\ FULL_ENV /\ verifier = "busy" /\ verifier' = "failed" /\ UNCHANGED worker /\ UNCHANGED NotSessions /\ UNCHANGED RevVars
VerifierIdles == ~End /\ FULL_ENV /\ verifier = "busy" /\ verifier' = "idle" /\ UNCHANGED worker /\ UNCHANGED NotSessions /\ UNCHANGED RevVars
VerifierWakes == ~End /\ FULL_ENV /\ verifier = "idle" /\ verifier' = "busy" /\ UNCHANGED worker /\ UNCHANGED NotSessions /\ UNCHANGED RevVars
VerifierQuiet == ~End /\ FULL_ENV /\ verifier = "idle" /\ verifier' = "idleQuiet" /\ UNCHANGED worker /\ UNCHANGED NotSessions /\ UNCHANGED RevVars
VerifierAsks == ~End /\ FULL_ENV /\ verifier = "busy" /\ verifier' = "idleBlocked" /\ UNCHANGED worker /\ UNCHANGED NotSessions /\ UNCHANGED RevVars
VerifierPrompted == ~End /\ FULL_ENV /\ verifier = "busy" /\ verifier' = "prompt" /\ UNCHANGED worker /\ UNCHANGED NotSessions /\ UNCHANGED RevVars
VerifierGhosts == ~End /\ FULL_ENV /\ verifier = "busy" /\ verifier' = "ghost" /\ UNCHANGED worker /\ UNCHANGED NotSessions /\ UNCHANGED RevVars
VerifierGhostReturns == ~End /\ FULL_ENV /\ verifier = "ghost" /\ verifier' = "idle" /\ UNCHANGED worker /\ UNCHANGED NotSessions /\ UNCHANGED RevVars
VerifierGhostStays == ~End /\ FULL_ENV /\ verifier \in {"ghost", "ghostStopped"} /\ verifier' = "ghostGone" /\ UNCHANGED worker /\ UNCHANGED NotSessions /\ UNCHANGED RevVars

\* The verifier files its one verify row (result_command, 1720-1725: a plain `tg result add`). Its brief runs
\* `check-report --verifier` first (1761, 1775-1780; verifier_problems 5809-5825): an ISSUES report needs a
\* `blocking:` line under Issues:, and findings that do not block go under Follow-ups: in a PASS report. A
\* report that passes the check: verify-failed with blocking findings, or another level with none under Issues:.
VerifierFilesUnchanged ==
  UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, stopReason, workerResult,
              vManager, worker, verifier, vreport, wtDirty, stopOrder, fault, faulted>>
  /\ UNCHANGED RoundVars
\* #127: the row judges the head the verifier's seat shows, and the verifier is kept for a resume.
VerifierFiles ==
  /\ ~End /\ verifier = "busy"
  /\ vv' \in Levels /\ vNewer' = TRUE /\ vfiled' = TRUE
  /\ vIssues' = IF vv' = "verify-failed" THEN "blocking" ELSE "none"
  /\ VerifierFilesUnchanged
  /\ vvRev' = verifierAt /\ verifierKept' = (REVISION_CAP > 0)
  /\ UNCHANGED <<revision, workerKept, findingsOpen, verifierAt>>

\* The check is advisory: worker.md "Report" step 1 says that a problem the session cannot fix, or a refused
\* command, goes on to step 2, the filing, and the filing command checks nothing (ALLOW_UNCHECKED_REPORT). So
\* an ISSUES report with no `blocking:` line can land; since 8006a3c record and close judge it (Verdicts).
VerifierFilesUnchecked ==
  /\ ALLOW_UNCHECKED_REPORT
  /\ ~End /\ verifier = "busy"
  /\ vv' = "verify-failed" /\ vNewer' = TRUE /\ vfiled' = TRUE /\ vIssues' = "unlabelled"
  /\ VerifierFilesUnchanged
  /\ vvRev' = verifierAt /\ verifierKept' = (REVISION_CAP > 0)
  /\ UNCHANGED <<revision, workerKept, findingsOpen, verifierAt>>

VerifierLeavesReport ==
  /\ ~End /\ FULL_ENV /\ verifier = "busy" /\ ~vreport /\ vreport' = TRUE
  /\ UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, stopReason, workerResult,
                 vv, vIssues, vManager, vNewer, vfiled, worker, verifier, wtDirty, stopOrder, fault, faulted>>
  /\ UNCHANGED RoundVars /\ UNCHANGED RevVars

\* The code host, in pr mode. BaseUnchanged leaves out pr and the round variables.
BaseUnchanged ==
  UNCHANGED <<status, attempt, abandoned, verdict, merged, mainHas, lastTask, stopReason, workerResult,
              vv, vIssues, vManager, vNewer, vfiled, worker, verifier, vreport, wtDirty, stopOrder, fault, faulted>>
  /\ UNCHANGED RevVars
HostUnchanged == BaseUnchanged /\ UNCHANGED RoundVars
HostDecides == ~End /\ PrMode /\ pr = "pending" /\ pr' \in {"clean", "behind", "blocked", "dirty"} /\ HostUnchanged
TargetMoves == ~End /\ PrMode /\ pr \in {"clean", "blocked"} /\ pr' = "behind" /\ HostUnchanged
CheckFails == ~End /\ PrMode /\ pr = "clean" /\ pr' = "blocked" /\ HostUnchanged
CheckPasses == ~End /\ PrMode /\ pr = "blocked" /\ pr' = "clean" /\ HostUnchanged
SomeoneMerges == ~End /\ PrMode /\ pr \in OpenPr /\ pr' = "merged" /\ HostUnchanged
SomeoneCloses == ~End /\ PrMode /\ pr \in OpenPr /\ pr' = "closed" /\ HostUnchanged
SomeoneReopens == ~End /\ PrMode /\ pr = "closed" /\ pr' = "pending" /\ HostUnchanged
\* #119: another request merges first and its change conflicts with ours; or a later merge or a revert clears it.
TargetConflicts == ~End /\ FULL_ENV /\ PrMode /\ pr \in {"clean", "behind", "blocked"} /\ pr' = "dirty" /\ HostUnchanged
ConflictClears == ~End /\ FULL_ENV /\ PrMode /\ pr = "dirty" /\ pr' \in {"clean", "behind"} /\ HostUnchanged
\* #119: a CI verify of the round (verify_mode ci:*, otherwise out of the model) pushes the round's head to the request.
RoundHeadPushed ==
  /\ ~End /\ FULL_ENV /\ PrMode /\ inRound /\ ~roundPushed /\ pr \in OpenPr /\ workerResult = "PASS"
  /\ roundPushed' = TRUE /\ pr' = "pending" /\ BaseUnchanged
  /\ UNCHANGED <<inRound, roundSame, rounds, mainConflicts, unverifiedMerge>>

\* Local mode: the operator merges the branch by hand; record then finds it in HEAD (merged_into, 3967).
OperatorMerges ==
  /\ ~End /\ ~PrMode /\ Awaiting /\ ~mainHas /\ mainHas' = TRUE /\ mainConflicts' = FALSE
  /\ UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, lastTask, stopReason, workerResult,
                 vv, vIssues, vManager, vNewer, vfiled, worker, verifier, vreport, wtDirty, stopOrder, fault, faulted>>
  /\ UNCHANGED <<inRound, roundSame, rounds, roundPushed, unverifiedMerge>> /\ UNCHANGED RevVars
\* #119, local mode: the target branch moves and conflicts with the verified commit (git merge-tree); or it clears.
MainConflicts ==
  /\ ~End /\ FULL_ENV /\ ~PrMode /\ (Awaiting \/ inRound) /\ ~mainHas /\ ~mainConflicts /\ mainConflicts' = TRUE
  /\ UNCHANGED pr /\ BaseUnchanged /\ UNCHANGED <<inRound, roundSame, rounds, roundPushed, unverifiedMerge>>
MainConflictClears ==
  /\ ~End /\ FULL_ENV /\ ~PrMode /\ mainConflicts /\ mainConflicts' = FALSE
  /\ UNCHANGED pr /\ BaseUnchanged /\ UNCHANGED <<inRound, roundSame, rounds, roundPushed, unverifiedMerge>>

\* The operator's standing orders: a STOP first line pauses launches and merges (Orders.stop); the operator
\* lifts it later. A pause is `run.py stop` under that line. Both are behind OPERATOR_PAUSES.
OrdersUnchanged ==
  UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, stopReason, workerResult,
              vv, vIssues, vManager, vNewer, vfiled, worker, verifier, vreport, wtDirty, fault, faulted>>
  /\ UNCHANGED RoundVars /\ UNCHANGED RevVars
OperatorOrdersStop == ~End /\ OPERATOR_PAUSES /\ ~stopOrder /\ stopOrder' = TRUE /\ OrdersUnchanged
OperatorLiftsStop == ~End /\ OPERATOR_PAUSES /\ stopOrder /\ stopOrder' = FALSE /\ OrdersUnchanged

\* 0.18.0 faults (FAULTS), once per run so that a broken-then-fixed copy of a dead end is still a dead end:
\* the role file of the task (or of [roles] default) goes missing or breaks, which launch (choose, 2353) and
\* verify (verify_role, 2684) refuse while close and record read the values stored at launch; or info/exclude
\* turns read-only, which launch (2338-2340) and verify (2696-2698) refuse before they stop or commit anything
\* (ff2c8b0). The operator's repair is the only way out of a broken state (each refusal says so), and it is
\* enabled only there.
FaultUnchanged ==
  UNCHANGED <<status, attempt, abandoned, verdict, merged, pr, mainHas, lastTask, stopReason, workerResult,
              vv, vIssues, vManager, vNewer, vfiled, worker, verifier, vreport, wtDirty, stopOrder>>
  /\ UNCHANGED RoundVars /\ UNCHANGED RevVars
RoleBreaks == ~End /\ FAULTS /\ ~faulted /\ fault' = "role" /\ faulted' = TRUE /\ FaultUnchanged
ExcludeBreaks == ~End /\ FAULTS /\ ~faulted /\ fault' = "exclude" /\ faulted' = TRUE /\ FaultUnchanged
OperatorRepairs == ~End /\ fault # "none" /\ fault' = "none" /\ UNCHANGED faulted /\ FaultUnchanged

\* ---------------------------------------------------------------- revisions (#127)

\* cmd_revise: one revise row; one tg edit (phase verdict_failed -> running, revision, verdict and verdict_ref unset); one
\* finding steer per blocking line; one doorbell wakes the kept worker in the same folder. The verifier stays idle.
Revise ==
  /\ Hint = "revise"
  /\ status = "in_progress" /\ ~abandoned /\ RevisionOK
  /\ revision' = revision + 1 /\ verdict' = "none"
  /\ lastTask' = "none" /\ stopReason' = "none" /\ workerResult' = "none"
  /\ vv' = "none" /\ vIssues' = "none" /\ vManager' = "none" /\ vNewer' = FALSE /\ vfiled' = TRUE
  /\ worker' = "busy" /\ findingsOpen' = TRUE /\ roundSame' = FALSE
  /\ UNCHANGED <<status, attempt, abandoned, merged, pr, mainHas, verifier, vreport, wtDirty, stopOrder, fault,
                 faulted, workerKept, verifierKept, verifierAt, vvRev,
                 inRound, rounds, mainConflicts, roundPushed, unverifiedMerge>>

\* The woken worker acks every finding steer (mailbox.py ack, one per finding) before it may report.
WorkerAcksFindings ==
  /\ ~End /\ worker = "busy" /\ findingsOpen
  /\ findingsOpen' = FALSE
  /\ UNCHANGED <<revision, workerKept, verifierKept, verifierAt, vvRev, worker, verifier>>
  /\ UNCHANGED NotSessions

\* Time: the keep time ends ([verify] keep_sessions_minutes), or the session is gone; record then stops it.
WorkerKeepEnds ==
  /\ ~End /\ workerKept /\ workerKept' = FALSE
  /\ UNCHANGED <<revision, verifierKept, findingsOpen, verifierAt, vvRev, worker, verifier>> /\ UNCHANGED NotSessions
VerifierKeepEnds ==
  /\ ~End /\ verifierKept /\ verifierKept' = FALSE
  /\ UNCHANGED <<revision, workerKept, findingsOpen, verifierAt, vvRev, worker, verifier>> /\ UNCHANGED NotSessions

\* ---------------------------------------------------------------- spec

Init ==
  /\ status = "open" /\ attempt = 0 /\ abandoned = FALSE /\ verdict = "none"
  /\ merged = FALSE /\ pr = "none" /\ mainHas = FALSE
  /\ lastTask = "none" /\ stopReason = "none" /\ workerResult = "none"
  /\ vv = "none" /\ vIssues = "none" /\ vManager = "none" /\ vNewer = FALSE /\ vfiled = TRUE
  /\ worker = "none" /\ verifier = "none" /\ vreport = FALSE /\ wtDirty = FALSE
  /\ stopOrder = FALSE /\ fault = "none" /\ faulted = FALSE
  /\ inRound = FALSE /\ roundSame = FALSE /\ rounds = 0 /\ mainConflicts = FALSE
  /\ roundPushed = FALSE /\ unverifiedMerge = FALSE
  /\ revision = 0 /\ workerKept = FALSE /\ verifierKept = FALSE /\ findingsOpen = FALSE
  /\ verifierAt = 0 /\ vvRev = 0

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
  \/ StartRound \/ RoundCancel \/ RoundMerged
  \/ TargetConflicts \/ ConflictClears \/ RoundHeadPushed \/ MainConflicts \/ MainConflictClears
  \/ Revise \/ WorkerAcksFindings \/ VerifyResume \/ WorkerKeepEnds \/ VerifierKeepEnds

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
  /\ inRound \in BOOLEAN /\ roundSame \in BOOLEAN /\ mainConflicts \in BOOLEAN
  /\ roundPushed \in BOOLEAN /\ unverifiedMerge \in BOOLEAN /\ rounds \in 0..ROUND_CAP
  /\ revision \in 0..(REVISION_CAP + 2)    \* one past RevisionBound, as for attempt: such states are checked, not explored
  /\ workerKept \in BOOLEAN /\ verifierKept \in BOOLEAN /\ findingsOpen \in BOOLEAN
  /\ verifierAt \in 0..(REVISION_CAP + 2) /\ vvRev \in 0..(REVISION_CAP + 2)
  /\ Hint \in Hints

\* Once the verifier's session ended or its turn ended, the attempt has a verify row that covers it, or
\* record is about to write one, or record says that the verdict is missing (no-verdict). A pending pause
\* (a STOPPED row without a Head line) is allowed: record finishes it first by design (3744-3746), and the lost
\* verifier is found by the record that follows the commit. An invariant, not a liveness property: the model
\* has no fairness, and a state is easier to read than a lasso.
VerdictNotLost ==
  (verifier # "none" /\ Over(verifier) /\ ~vfiled)
    => (RecordHasEffect \/ Event = "no-verdict" \/ lastTask = "STOPPED")

\* A done or merged task has a passing verdict, and a verify row of the attempt carries it: the verifier's, the
\* Manager's (close --verdict), or the Manager's carried row (#119: round --cancel, a clean round's close, the merge of
\* round_from during a round). Or record recorded the operator's merge of a head no verdict covers: a round's head that
\* a CI verify pushed, merged on the host (merged_by=operator, as pr_status records any merge done on the host).
NoMergeWithoutPassingVerdict ==
  (status = "done" \/ merged) =>
    ((verdict \in Passing /\ (vv = verdict \/ vManager \in {"manual", "carried"})) \/ unverifiedMerge)

\* The owner's rule (#59): the attempt passes MAX_ATTEMPTS only by a launch after a pause the operator ordered
\* (the newest row is STOPPED with Reason: pause); a stop that recovers a quiet or broken session, a stop by
\* close, and DIED all count as an attempt. An action property: it names the step that passes the cap. A round
\* (#119) does not count toward the cap: [rounds] cap limits the rounds.
AttemptCap ==
  [][(attempt' > MAX_ATTEMPTS /\ attempt' # attempt)
       => ((lastTask = "STOPPEDhead" /\ stopReason = "pause") \/ rounds' > rounds)]_vars

\* cmd_launch line 2489: "A dirty worktree never reaches a worker silently: commit what the last attempt left."
LaunchCommitsLeftovers == [][Launch => wtDirty' = FALSE]_vars

\* commit_stopped line 3673: "Phase 2 of a pause: commit the WIP of a stopped worker that has exited."
PausedWipCommitted == (lastTask = "STOPPEDhead") => ~wtDirty

\* record_in_progress line 3746: "finish the pause first: launch needs its Head line". Once the stopped worker
\* has exited, the next step is record, which commits the WIP.
PauseFinishedFirst ==
  (status = "in_progress" /\ ~abandoned /\ ~Closed /\ lastTask = "STOPPED" /\ worker # "stopping") => Hint = "record"

\* cleanup line 4564: "Remove the sessions and worktrees of a merged task." stop_live and cmd_abandon stop the
\* task's live sessions (#57). So an end state leaves no live session of the task. A young ghost row is not one:
\* `claude stop` cannot end it, it ends by itself after 30 quiet minutes, and cleanup removes it with `claude rm`
\* once the task is done (#65). Before 0.12.1 (REGRESS_65) cleanup skipped it as live, so it was left.
LeftAtEnd(s) == Live(s) /\ (~Ghost(s) \/ REGRESS_65)
\* #127: a session kept idle for a revision is stopped too (stop_live, abandon, the merge record).
NoSessionLeftAtEnd == End => (~LeftAtEnd(worker) /\ ~LeftAtEnd(verifier) /\ ~workerKept /\ ~verifierKept)

\* idle_and_filed (2323-2331): "launch stops such a session itself instead of refusing." A launch that stops the
\* idle rows and passes every other check starts the next attempt; it does not refuse on the row it stopped.
\* The step must be the launch itself (a STOP order written in that state exits launch before it stops anything,
\* as pause.md says, and the environment's own steps do not start attempts). Since ff2c8b0 the exclude check is
\* an early one (2338-2340, in EarlyChecks), so no refusal follows the stops but the pause and the cap.
StoppedIdleNeverRefuses ==
  [][(Hint = "launch" /\ EarlyChecks /\ LaunchStopsIdle /\ LateChecks /\ (Launch \/ LaunchStopsIdleThenRefuses))
       => attempt' = attempt + 1]_vars

\* 0.19.0 (#97): "A task is done only when its change is merged" (README, Task lifecycle). The other way round holds
\* too: every merge record runs `tg done` (mark_merged), and record finishes one that stopped between the two writes.
\* With REGRESS_97 a passing close marks the task done before the merge, and this breaks.
DoneOnlyWhenMerged == (status = "done") <=> merged

\* cmd_launch line 2530: "Never unset pr, pr_branch, pushed or target: one request per task across attempts."
OneRequestPerTask == [][pr # "none" => pr' # "none"]_vars

\* 0.18.0 (#89 rule 1, README "Blocking and non-blocking findings", manager.md "No follow-up dropped"): a fix
\* round is opened only for a blocking finding; non-blocking findings never open one. In the model's words: when
\* a verifier's verify-failed verdict drives the next step (a fix round, or abandon at the cap), its report has
\* a `blocking:` line. A Manager's own verify-failed (close --verdict) is not a verifier's finding. Since
\* 8006a3c such a verdict is never recorded: record hints `verify --again`, close refuses (REGRESS_89 undoes both).
\* #127: a revision is a fix round inside the attempt, so the revise hint needs a blocking line too.
FixRoundNeedsBlocking ==
  (verdict = "verify-failed" /\ vv = verdict /\ vManager # "manual" /\ Hint \in {"launch", "abandon", "revise"})
    => vIssues = "blocking"

\* #119: a round has no passing verdict beside it: its phase is in flight, never awaiting_merge, and the task is in
\* progress.
RoundIsInFlight == inRound => (~Closed /\ status = "in_progress")

\* #119: following record's hints never abandons a task that waits for its merge: a conflict gets a round on the same
\* request. REGRESS_119 (the redo hint at a conflict: abandon, then launch --attempt) breaks it.
NoHintAbandonsWaitingWork == [][(abandoned' /\ ~abandoned) => ~Awaiting]_vars

\* #127: revisions are bounded: a revision starts only below the cap. REGRESS_127C breaks it.
RevisionCap == [][revision' > revision => revision < REVISION_CAP]_vars

\* #127: the closing verdict judges the final head: a passing close that rests on a verifier row rests on a row about the
\* newest revision's head. REGRESS_127H (the resumed verifier still sees the old head) breaks it.
ClosingVerdictOnFinalHead ==
  (Closed /\ vManager \notin {"manual", "carried"}) => vvRev = revision

\* #127: with the verifier in the task worktree, the worker and the verifier never work in it at once. REGRESS_127W
\* breaks it.
NoConcurrentWriters == (SEAT = "task") => ~(worker = "busy" /\ verifier = "busy")

\* #127: a revision's report comes after the ack of every finding. REGRESS_127A breaks it.
FindingsAckedBeforeReport == (workerResult # "none") => ~findingsOpen

====
