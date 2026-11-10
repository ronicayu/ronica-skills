---------------------------- MODULE Mailbox ----------------------------
\* The mailbox-and-doorbell design of the ADR "How the Manager and its workers talk across Claude
\* profiles": ronica-skills-adr docs/plans/2026-11-09-agentic-team-channel-adr.md (status proposed,
\* 2026-11-09; read on 2026-11-09), sections 1, 4.1-4.8, 5 and "Live check results". Round 1 read the ADR
\* text; round 2 maps it to scripts/run.py and scripts/mailbox.py at commit 3330fc7 (the IMPL_* switches).
\* ADR and code line numbers are in NOTES.md.
\*
\* The build ships Phase 1 and Phase 2 together: socket doorbell first, stop + resume as the fallback,
\* the PostToolUse hook pointer for a busy worker (PHASE2 = TRUE). PHASE2 = FALSE is `doorbell = "resume"`.
\*
\* One task, up to MaxAttempts attempts. Each attempt has one worker session (w1, w2) and room for one
\* resume copy (c1, c2). The message rows are a sequence (the row order is the index); an ack is not a
\* row of its own here: it marks the rows it covers "acked" and moves the inbox cursor (lastAck).
\* The delivery state of 4.1 (pending, rung, delivered, copied) and Carried are run.py's task meta.
\*
\* Switches. ALLOW_*: what the world (or the operator) can do; a fault spends one unit of MaxFaults.
\* PHASE2, DESIGN_*: alternatives the ADR itself offers. FIX_*: a change to the ADR text where the model
\* suspects a gap; FALSE everywhere is the ADR as written. MANAGER_STOPS: the Manager's free `run.py stop`.
\*
\* Round 2 (the code): IMPL_*: what scripts/run.py and scripts/mailbox.py do at commit 3330fc7 where it departs
\* from the ADR or from the round-1 FIX_* (NOTES.md maps each action to its lines). CLI_*: facts or open questions
\* about the Claude CLI 2.1.319. FIX_* added in round 2: the fixes of the round-2 list (msg-fixes-r2.md) that are not
\* simply an IMPL_* switch turned off. Every new switch FALSE is the round-1 model. TRACK_NEW_RULES: record the
\* history that the round-2 rules read; FALSE in the round-1 configs, so that their state counts stay as they were.
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS
  MaxAttempts,          \* 1, 2 or 3 (run.py allows 3)
  ASKS,                 \* blocking asks per attempt: 0 or 1 (asks_per_attempt is 3)
  MaxSteers,            \* steers the Manager files in the whole run
  MaxFaults,            \* how many environment faults one behaviour may contain
  PHASE2,               \* deliver step 2 (socket post) is on: doorbell = "socket"
  DESIGN_SID_CHECK,     \* step 2 posts only when .addr session_id = the agents row's sessionId and .addr is newer than the row's start
  MANAGER_STOPS,        \* the Manager may run `run.py stop` on an attempt in progress
  ALLOW_DIE,            \* a worker process dies; its conversation is kept or lost
  ALLOW_SUP_STOP,       \* the supervisor stops an idle unattended session: no pid, conversation kept
  ALLOW_ACCOUNT_FAIL,   \* the worker profile's account fails; a later resume starts and fails at once
  ALLOW_PID_REUSE,      \* a gone process's pid is reused, so its socket path now belongs to another process
  ALLOW_NO_CHECKIN,     \* a process starts but the SessionStart checkin does not run (L1/L4 not confirmed)
  ALLOW_SOCKET_HOLD,    \* a socket post "succeeds" but the worker holds the message (bypass, hold, format change)
  ALLOW_OPERATOR,       \* the operator runs `run.py steer --by operator` from a terminal, concurrently (9.8)
  ALLOW_SUPERSEDE,      \* the Manager may give a second answer with --supersede
  FIX_ASK_OPEN_UNTIL_ACK,  \* record treats an ask as open until its answer is acked, not until an answer row exists
  FIX_CARRY_ON_EVERY_END,  \* every attempt end (report, DIED, failed row, launch) marks its messages Carried, not only stop/close/abandon
  FIX_DELIVER_OWN_ATTEMPT, \* deliver targets the message's own attempt and drops (carries) a message whose attempt has ended
  FIX_FLAG_PER_ATTEMPT,    \* the hook flag file is keyed by task and attempt, not by task
  FIX_DELIVERED_TIMES_OUT, \* a resumed (Delivered) message with no ack goes back to pending like Rung
  FIX_SUPERSEDE_SETTLES,   \* when the newer answer is acked, the older answers of that ask are settled (superseded)
  FIX_INBOX_UNACKED,       \* inbox prints every unacked row of the attempt, not only rows after the last ack
  FIX_STEER_REFUSES_ENDED, \* run.py steer refuses once the attempt has an end row (a report), even if a process is live
  FIX_REPORT_CHECK_ATOMIC, \* the report command itself refuses while a steer is unacked (check and file are one step)
  FIX_DELIVER_LOCK,        \* one run.py lock per task: a deliver, and every command that stops sessions or files an end row, waits for a running deliver
  \* ---- round 2: the code at 3330fc7 (TRUE = as built) and the CLI 2.1.319
  IMPL_RESUME_COPIES,      \* every deliver resume starts a copy: resume_with passes --settings, and the CLI copies on any flag
  IMPL_COPY_NOTE_MISSED,   \* run.py looks for the note: line on stdout; the CLI prints it on stderr: the copy is not recorded,
                           \* the row is marked delivered by resume, the flag is lowered, the original stays the attempt's session
  IMPL_HOOK_IS_A_TRY,      \* a flag touch leaves the row pending (every record touches it again) and counts toward the cap
  IMPL_DELIVERY_CAP,       \* record stops retrying a row after DELIVERIES_MAX = 3 tries (steer-pending)
  IMPL_HOLDS,              \* record files no DIED while `holds`: an ask open until its newest answer is acked, or an unacked
                           \* answer or steer whose delivery is pending, hook or socket; a resume-delivered one does not hold
  IMPL_SALVAGE,            \* the worker writes its report file before the report command (wst "checked"); record files that
                           \* report (salvage) instead of DIED when the turn is over with no task row
  IMPL_LIVE_ROWS,          \* steer and stop act on a live row: busy, or idle and waiting on an ask; steer also when the thread holds
  IMPL_DETAILS,            \* small code details: a resume lowers the attempt's flag; a failed row goes to salvage or DIED
  IMPL_PRUNE_META,         \* launch drops the mailbox meta of earlier attempts after it renders the brief; abandon drops it all;
                           \* the brief's thread (carried_text) counts only answers and steers that the meta lists
  ALLOW_RELAUNCH,          \* the operator runs `run.py launch <id> --attempt n+1` after an abandon
  CLI_COPY_IN_WORKTREE,    \* the copy's row has its cwd in the task worktree: run.py ties it to the task by folder and targets it
                           \* (FALSE: run.py does not see it, the live check's reading)
  CLI_WAKE_KEEPS_START,    \* an in-place resume does not change the row's startedAt: an .addr from before the wake looks fresh
  FIX_ADDR_AFTER_WAKE,     \* round-2 A.3: an .addr written before the wake is never used
  FIX_SOCKET_PID_MATCH,    \* round-2 B5: post only when the socket path's pid is the row's pid
  FIX_SALVAGE_REFUSES_UNACKED_STEER, \* round-2 B4: salvage files no report while a steer has no ack (DIED instead)
  TRACK_NEW_RULES,         \* record the history that the round-2 rules read (bad)
  \* ---- round 3 (msg-fixes-r3.md)
  FIX_FAILED_ENDS,         \* item 1 (D6): a failed row of the current attempt ends it even while the thread holds
                           \* (salvage or a FAILED row, carried); deliver never resumes a failed row
  FIX_STOP_OPEN_THREAD,    \* item 5 (D7): run.py stop also accepts the attempt's session with no live row when its thread holds
  ALLOW_NO_EXIT,           \* a process does not exit after `claude stop` (wait_for_exit gives up); spends a fault
  FIX_EXIT_TIMEOUT_NOT_A_TRY, \* item 4 (D15): that timeout does not count toward the cap
  IMPL_STALE_ADDR_FAILS,   \* D9 (3330fc7, item 2 open): a missing or stale address marks the row socket_failed for good
  \* ---- round 4 (msg-fixes-r4.md items 2 and 4; the code at b75b176)
  ALLOW_ROW_GONE,          \* a fault: the attempt's session disappears from `claude agents` (no row at all)
  ROW_GONE_KEEPS_PROCESS,  \* the session's process keeps running after its row is gone (FALSE: it is gone too)
  ALLOW_ABANDON_OPEN,      \* the Manager may abandon an attempt that has no end row (cmd_abandon needs only in_progress)
  FIX_NO_ROW_ENDS,         \* item 2: an attempt whose session has no row: record files DIED and carries, even while it holds
  FIX_NO_ROW_RESUMES,      \* an alternative (not in the list): deliver resumes a session with no row by its recorded sessionId
  FIX_ABANDON_ENDS,        \* item 2: abandon of an attempt with no end row files its end row (and carries)
  CLI_ROW_LAG,             \* item 4: right after an in-place resume, the row still reads "no process" for one read
  FIX_RESUMED_HOLDS        \* item 4: an attempt that run.py just resumed holds for the rest of the command (no end row)

ASSUME MaxAttempts \in {1, 2, 3} /\ ASKS \in {0, 1} /\ MaxSteers \in Nat /\ MaxFaults \in Nat

VARIABLES
  attempt,      \* the current attempt (attempt meta)
  ends,         \* ends[a]: the end row of attempt a: "none", "report" (the worker's result), "DIED"
                \* (also stands for stuck and a ghost end: record's Manager rows), "FAILED" (a failed row,
                \* the profiles spec's handling), "STOPPED" (run.py stop)
  taskEnd,      \* "no", "closed" (close after a report), "abandoned"
  proc,         \* proc[s]: the process of session s: "unborn", "none" (no pid: parked, stopped, dead,
                \* ghost), "busy", "idle" (turn over, process alive), "failed" (resumed, failed at once)
  conv,         \* conv[s]: the conversation on disk: "kept" or "lost"
  wst,          \* wst[s]: where the worker is in its brief: "work", "wait" (blocking ask filed, turn ended),
                \* "checked" (check-report passed, the report is next), "done" (report filed)
  bell,         \* bell[s]: a doorbell (socket post or resume prompt) is in session s, not yet read
  seen,         \* seen[s]: the rows the worker's last `inbox` printed, not yet acked
  cur,          \* cur[a]: the session id run.py has recorded for attempt a (sessions meta)
  addr,         \* addr[a]: the .addr checkin file of attempt a: [sid, cur (the socket path still belongs
                \* to the process that wrote it), reused (that path now belongs to another process),
                \* fresh (the file is newer than the start of the sid's current process)]
  msgs,         \* the message rows: [kind, att, re (the ask an answer answers), st, via, sockF]
  lastAck,      \* lastAck[a]: rows 1..lastAck[a] come before the attempt's newest ack row (inbox cursor)
  flag,         \* the hook flag: the rows run.py touched it for (one file per task)
  acct,         \* the worker profile's account: "ok" or "failed"
  faults,       \* environment faults so far
  dpc,          \* dpc[d]: where deliverer d (the Manager's run.py, the operator's run.py) is in deliver
  dmsg,         \* dmsg[d]: the row it delivers
  dsess,        \* dsess[d]: the session it stopped and will resume
  mgrSteers,    \* steers the Manager filed
  opSteers,     \* steers the operator filed
  stray,        \* where doorbells went that should not have: "otherAttempt", "otherProcess", "endedAttempt"
  resumeOverProc, \* deliver ran --bg --resume while the session still had a process
  overflow,     \* a second copy was needed for one attempt: beyond what the model tracks
  untracked,    \* copies that run.py did not record in the sessions meta (round 2)
  bad,          \* history for the round-2 rules: "endOverBusy", "reportOverSteer", "settledShownOpen", "carriedLost"
  metaGone,     \* the attempts whose mailbox meta entries run.py has dropped (launch prune, abandon)
  noExit,       \* sessions whose process does not exit after `claude stop` (round 3, ALLOW_NO_EXIT)
  rowGone,      \* sessions that `claude agents` no longer lists (round 4, ALLOW_ROW_GONE)
  lag           \* sessions resumed in place whose row still reads "no process" until the Manager's next step (CLI_ROW_LAG)

vars == <<attempt, ends, taskEnd, proc, conv, wst, bell, seen, cur, addr, msgs, lastAck, flag, acct,
          faults, dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow, untracked, bad, metaGone, noExit,
          rowGone, lag>>
newVars == <<untracked, bad, metaGone, noExit, rowGone>>

\* ---------------------------------------------------------------- values

Attempts == 1..MaxAttempts
\* Each attempt has two session slots: the original and room for one resume copy. With IMPL_RESUME_COPIES a
\* copy may take the other slot again once the session in it has no process.
Orig(a) == <<"w1", "w2", "w3">>[a]
CopyOf(a) == <<"c1", "c2", "c3">>[a]
SessOf(a) == {Orig(a), CopyOf(a)}
Sids == UNION {SessOf(a) : a \in Attempts}
AttOf == [s \in Sids |-> CHOOSE a \in Attempts : s \in SessOf(a)]
Other(s) == IF s = Orig(AttOf[s]) THEN CopyOf(AttOf[s]) ELSE Orig(AttOf[s])
NoSid == "none"
Deliverers == {"mgr", "op"}
AnswersPerAsk == IF ALLOW_SUPERSEDE THEN 2 ELSE 1
MaxMsgs == MaxAttempts * ASKS * (1 + AnswersPerAsk) + MaxSteers + (IF ALLOW_OPERATOR THEN 1 ELSE 0)
DeliveriesMax == 3
NoAddr == [sid |-> NoSid, cur |-> FALSE, reused |-> FALSE, fresh |-> FALSE]
NewMail(k, a, r) == [kind |-> k, att |-> a, re |-> r, st |-> "pending", via |-> "none", sockF |-> FALSE, tries |-> 0]
MaxOf(S) == CHOOSE x \in S : \A y \in S : y <= x
BadIf(b, F) == IF TRACK_NEW_RULES THEN b \cup F ELSE b

\* ---------------------------------------------------------------- derived

Ids == 1..Len(msgs)
Alive(s) == proc[s] \in {"busy", "idle"}
IsMail(i) == msgs[i].kind \in {"answer", "steer"}
Settled(i) == msgs[i].st \in {"acked", "carried", "superseded"}
\* The attempt has an end row, or the Manager has moved past it.
AttemptEnded(a) == a < attempt \/ ends[a] # "none" \/ taskEnd # "no"
\* The Manager has moved past the attempt: the next attempt runs, or the task is over.
AttemptOver(a) == a < attempt \/ taskEnd # "no"
AsksOf(a) == {i \in Ids : msgs[i].kind = "ask" /\ msgs[i].att = a}
AnswersTo(k) == {i \in Ids : msgs[i].kind = "answer" /\ msgs[i].re = k}
AskAcked(k) == \E i \in AnswersTo(k) : msgs[i].st = "acked"
NewerAnswer(i) == msgs[i].kind = "answer" /\ \E j \in AnswersTo(msgs[i].re) : j > i
\* What record_in_progress reads as "an open blocking ask" of attempt a (5, row record_in_progress).
\* As written: an ask row with no answer row. FIX: until the answer is acked.
AskOpenForRecord(a) ==
  \E k \in AsksOf(a) : IF FIX_ASK_OPEN_UNTIL_ACK THEN ~AskAcked(k) ELSE AnswersTo(k) = {}
\* mailbox.py inbox (4.2): answer and steer rows of this task and attempt that come after the last ack.
Inbox(a) == {i \in Ids : IsMail(i) /\ msgs[i].att = a /\ ~Settled(i) /\ (FIX_INBOX_UNACKED \/ i > lastAck[a])}
\* check-report (4.7, T12): a steer of the attempt with no ack.
UnackedSteers(a) == {i \in Ids : msgs[i].kind = "steer" /\ msgs[i].att = a /\ msgs[i].st \notin {"acked", "carried"}}
\* The rows whose pointer the PostToolUse hook shows in session s (one flag file per task, 4.3).
HookShows(s) == {i \in flag : FIX_FLAG_PER_ATTEMPT => msgs[i].att = AttOf[s]}
\* A doorbell for rows I lands in session s: where it should not.
StrayOf(I, s) ==
  (IF \E i \in I : msgs[i].att # AttOf[s] THEN {"otherAttempt"} ELSE {})
  \cup (IF I # {} /\ AttemptEnded(AttOf[s]) THEN {"endedAttempt"} ELSE {})
\* ---- round 2: what the code reads
\* Thread.blocking (run.py 2101-2106): an ask stays open until its newest answer is acked.
Blocking(a) ==
  \E k \in AsksOf(a) :
     IF AnswersTo(k) = {} THEN TRUE ELSE msgs[MaxOf(AnswersTo(k))].st # "acked"
\* Thread.holds (2112-2114), which cmd_steer reads: blocking, or any answer or steer with no ack.
ThreadHolds(a) == Blocking(a) \/ \E i \in Ids : IsMail(i) /\ msgs[i].att = a /\ msgs[i].st \notin {"acked", "superseded"}
\* record's holds (2864): blocking, or an unacked row whose delivery is pending (a hook touch too, when the hook is
\* a try) or rung (socket, or the hook when it is not a try). A row delivered by resume does not hold.
RecordHolds(a) ==
  \/ Blocking(a)
  \/ \E i \in Ids : IsMail(i) /\ msgs[i].att = a /\ ~Settled(i) /\ msgs[i].st \in {"pending", "rung"}
\* Session.live (499-544): a row with a running turn, or a parked asker (state blocked). A row whose turn is over
\* (state done), a stopped row and a failed row have ended. A dead process (a young ghost) is merged into "ended":
\* the model has no time, and after 30 quiet minutes the code ends it too.
RowLive(s) == proc[s] = "busy" \/ (proc[s] = "idle" /\ wst[s] = "wait")
\* What run.py sees: a copy that it did not record is invisible unless its row is tied to the task by its folder.
Visible(s) == (s \notin untracked \/ CLI_COPY_IN_WORKTREE) /\ s \notin rowGone
VisibleSet(S) == {s \in S : Visible(s)}

\* run.py steer refuses "a task with no live worker in its current attempt" (4.2). The code (cmd_steer, 2511-2533)
\* refuses an attempt with a task row, and a worker whose row is not live unless its thread holds.
SteerAllowed ==
  /\ taskEnd = "no"
  /\ IF IMPL_LIVE_ROWS
       THEN ends[attempt] = "none" /\ cur[attempt] \notin rowGone /\ (RowLive(cur[attempt]) \/ ThreadHolds(attempt))
       ELSE /\ \E s \in SessOf(attempt) : Alive(s)
            /\ FIX_STEER_REFUSES_ENDED => ends[attempt] = "none"
\* With the lock, a deliver starts, and record's DIED / failed rows, launch, close, abandon and stop run,
\* only when no deliver runs.
LockFree == FIX_DELIVER_LOCK => \A e \in Deliverers : dpc[e] = "idle"

CarryAtt(ms, a) ==
  [j \in 1..Len(ms) |->
     IF ms[j].att = a /\ ms[j].kind \in {"answer", "steer"} /\ ms[j].st \notin {"acked", "carried", "superseded"}
     THEN [ms[j] EXCEPT !.st = "carried"] ELSE ms[j]]
CarryIf(ms, a) == IF FIX_CARRY_ON_EVERY_END THEN CarryAtt(ms, a) ELSE ms

\* Processes. A stop or an exit ends the process; the socket file no longer belongs to it.
StopSet(p, S) == [s \in Sids |-> IF s \in S /\ p[s] \in {"busy", "idle"} THEN "none" ELSE p[s]]
AddrStop(ad, S) == [a \in Attempts |-> IF ad[a].sid \in S THEN [ad[a] EXCEPT !.cur = FALSE] ELSE ad[a]]
\* A process of session s starts. The SessionStart hook (matchers startup and resume) writes the .addr
\* file with the new socket and the session id (4.2 checkin). Without the checkin the file stays: when it
\* names s, it is now older than s's start and its socket path is the old process's. `wake`: an in-place resume of s;
\* if the CLI keeps the row's startedAt then, the old file still passes the freshness check (unless A.3 is fixed).
AddrStart(ad, s, ci, wake) ==
  IF ci THEN [ad EXCEPT ![AttOf[s]] = [sid |-> s, cur |-> TRUE, reused |-> FALSE, fresh |-> TRUE]]
  ELSE IF ad[AttOf[s]].sid = s
       THEN [ad EXCEPT ![AttOf[s]].fresh = IF wake /\ CLI_WAKE_KEEPS_START /\ ~FIX_ADDR_AFTER_WAKE THEN @ ELSE FALSE,
                       ![AttOf[s]].cur = FALSE]
  ELSE ad
\* The brief of attempt n (render -> carried_text, 2333-2354): the thread of the newest earlier attempt E with
\* message rows. With E's meta gone, every ask of E reads OPEN and no answer or steer of E is pasted.
\* "settledShownOpen": an ask whose answer was acked is shown OPEN. "carriedLost": E is the attempt that just ended
\* and an answer or steer of it with no ack is not pasted (Carried means "the next brief pastes it").
BriefFlaws(n) ==
  LET withRows == {e \in 1..(n - 1) : \E i \in Ids : msgs[i].att = e}
      E == MaxOf(withRows)
  IN IF ~IMPL_PRUNE_META THEN {} ELSE IF withRows = {} THEN {} ELSE IF E \notin metaGone THEN {}
     ELSE (IF \E k \in AsksOf(E) : AskAcked(k) THEN {"settledShownOpen"} ELSE {})
          \cup (IF E = n - 1 /\ \E i \in Ids : IsMail(i) /\ msgs[i].att = E /\ msgs[i].st \notin {"acked", "superseded"}
                THEN {"carriedLost"} ELSE {})
\* launch drops the mailbox meta of the attempts before n (2775-2782), after it renders the brief.
PruneBefore(n) == IF IMPL_PRUNE_META THEN metaGone \cup {e \in Attempts : e < n} ELSE metaGone
CheckinChoices == IF ALLOW_NO_CHECKIN /\ faults < MaxFaults THEN {TRUE, FALSE} ELSE {TRUE}
HoldChoices == IF ALLOW_SOCKET_HOLD /\ faults < MaxFaults THEN {FALSE, TRUE} ELSE {FALSE}

\* ---------------------------------------------------------------- init

Init ==
  /\ attempt = 1
  /\ ends = [a \in Attempts |-> "none"]
  /\ taskEnd = "no"
  /\ proc = [s \in Sids |-> IF s = "w1" THEN "busy" ELSE "unborn"]
  /\ conv = [s \in Sids |-> "kept"]
  /\ wst = [s \in Sids |-> "work"]
  /\ bell = [s \in Sids |-> FALSE]
  /\ seen = [s \in Sids |-> {}]
  /\ cur = [a \in Attempts |-> Orig(a)]
  /\ addr = [a \in Attempts |-> IF a = 1 THEN [sid |-> "w1", cur |-> TRUE, reused |-> FALSE, fresh |-> TRUE] ELSE NoAddr]
  /\ msgs = <<>>
  /\ lastAck = [a \in Attempts |-> 0]
  /\ flag = {}
  /\ acct = "ok"
  /\ faults = 0
  /\ dpc = [d \in Deliverers |-> "idle"]
  /\ dmsg = [d \in Deliverers |-> 0]
  /\ dsess = [d \in Deliverers |-> NoSid]
  /\ mgrSteers = 0
  /\ opSteers = 0
  /\ stray = {}
  /\ resumeOverProc = FALSE
  /\ overflow = FALSE
  /\ untracked = {}
  /\ bad = {}
  /\ metaGone = {}
  /\ noExit = {}
  /\ rowGone = {}
  /\ lag = {}

\* ---------------------------------------------------------------- the worker

\* mailbox.py ask: file the ask row (OPEN), end the turn with "Waiting for answer to ask #N" (worker.md, Asking).
WorkerAsks(s) ==
  /\ proc[s] = "busy" /\ wst[s] = "work" /\ seen[s] = {}
  /\ Cardinality(AsksOf(AttOf[s])) < ASKS
  /\ msgs' = Append(msgs, [kind |-> "ask", att |-> AttOf[s], re |-> 0, st |-> "open", via |-> "none", sockF |-> FALSE, tries |-> 0])
  /\ wst' = [wst EXCEPT ![s] = "wait"]
  /\ proc' = [proc EXCEPT ![s] = "idle"]
  /\ UNCHANGED <<attempt, ends, taskEnd, conv, bell, seen, cur, addr, lastAck, flag, acct, faults,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED newVars
  /\ UNCHANGED lag

\* mailbox.py inbox: after a doorbell (a post wakes an idle session; a resume prompt), a hook pointer at a
\* tool call, or a checkpoint (after a commit, before REPORT). It prints this attempt's rows only.
WorkerReadsInbox(s) ==
  LET a == AttOf[s]
      hook == IF proc[s] = "busy" THEN HookShows(s) ELSE {}
  IN
  /\ Alive(s) /\ seen[s] = {}
  /\ bell[s] \/ (proc[s] = "busy" /\ (Inbox(a) # {} \/ hook # {}))
  /\ seen' = [seen EXCEPT ![s] = Inbox(a)]
  /\ bell' = [bell EXCEPT ![s] = FALSE]
  /\ stray' = stray \cup StrayOf(hook, s)
  /\ wst' = [wst EXCEPT ![s] = IF @ = "checked" /\ Inbox(a) # {} THEN "work" ELSE @]
  \* Something to act on: the turn goes on. Nothing: a waiting or reported worker ends its turn again.
  /\ proc' = [proc EXCEPT ![s] = IF Inbox(a) # {} \/ wst[s] \in {"work", "checked"} THEN "busy" ELSE "idle"]
  /\ UNCHANGED <<attempt, ends, taskEnd, conv, cur, addr, msgs, lastAck, flag, acct, faults,
                 dpc, dmsg, dsess, mgrSteers, opSteers, resumeOverProc, overflow>>
  /\ UNCHANGED newVars
  /\ UNCHANGED lag

\* mailbox.py ack: one ack row per row it read; for an ask with two answers it acks the latest it read
\* (4.7 "Two answers"). The ack rows come after every row filed so far, which moves the inbox cursor.
\* record removes the hook flag when it sees the ack (4.3); the model does that here, before the Manager
\* can act on record's next hint.
WorkerAcks(s) ==
  LET a == AttOf[s]
      isAns(x, k) == msgs[x].kind = "answer" /\ msgs[x].re = k
      latest(k) == CHOOSE j \in seen[s] : isAns(j, k) /\ \A x \in seen[s] : isAns(x, k) => x <= j
      toAck == {i \in seen[s] : ~Settled(i) /\ (msgs[i].kind = "answer" => i = latest(msgs[i].re))}
      ackedAsks == {msgs[i].re : i \in {j \in toAck : msgs[j].kind = "answer"}}
      newW == IF wst[s] = "wait" /\ (\E k \in AsksOf(a) : k \in ackedAsks) THEN "work"
              ELSE IF wst[s] = "checked" /\ toAck # {} THEN "work"
              ELSE wst[s]
  IN
  /\ proc[s] = "busy" /\ seen[s] # {}
  /\ msgs' = [j \in Ids |->
                IF j \in toAck THEN [msgs[j] EXCEPT !.st = "acked"]
                ELSE IF FIX_SUPERSEDE_SETTLES /\ msgs[j].kind = "answer" /\ msgs[j].re \in ackedAsks /\ ~Settled(j)
                     THEN [msgs[j] EXCEPT !.st = "superseded"]
                ELSE msgs[j]]
  /\ lastAck' = IF toAck = {} THEN lastAck ELSE [lastAck EXCEPT ![a] = Len(msgs)]
  /\ flag' = IF flag \cap toAck # {} THEN {} ELSE flag
  /\ seen' = [seen EXCEPT ![s] = {}]
  /\ wst' = [wst EXCEPT ![s] = newW]
  /\ proc' = [proc EXCEPT ![s] = IF newW \in {"wait", "done"} THEN "idle" ELSE "busy"]
  /\ UNCHANGED <<attempt, ends, taskEnd, conv, bell, cur, addr, acct, faults,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED newVars
  /\ UNCHANGED lag

\* check-report: refuses while a steer of the attempt has no ack (4.7, T12). A doorbell that arrived
\* between tool calls is read first.
CanReport(s) ==
  /\ proc[s] = "busy" /\ seen[s] = {} /\ ~bell[s]
  /\ UnackedSteers(AttOf[s]) = {}

\* With IMPL_SALVAGE, "checked" also means: the report file is written (worker.md REPORT: write the file, run
\* check-report, then the report command), so record can salvage it.
WorkerChecksReport(s) ==
  /\ ~FIX_REPORT_CHECK_ATOMIC \/ IMPL_SALVAGE
  /\ wst[s] = "work" /\ CanReport(s)
  /\ wst' = [wst EXCEPT ![s] = "checked"]
  /\ UNCHANGED <<attempt, ends, taskEnd, proc, conv, bell, seen, cur, addr, msgs, lastAck, flag, acct, faults,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED newVars
  /\ UNCHANGED lag

\* The worker files its result row and ends its turn. A late report of an attempt that already has an
\* end row changes no end row. The code: mailbox.py cmd_report (336-351), check and file under the task lock.
WorkerReports(s) ==
  LET a == AttOf[s] IN
  /\ IF FIX_REPORT_CHECK_ATOMIC THEN wst[s] = (IF IMPL_SALVAGE THEN "checked" ELSE "work") /\ CanReport(s)
     ELSE wst[s] = "checked" /\ proc[s] = "busy" /\ seen[s] = {} /\ ~bell[s]
  /\ wst' = [wst EXCEPT ![s] = "done"]
  /\ proc' = [proc EXCEPT ![s] = "idle"]
  /\ IF a = attempt /\ ends[a] = "none" /\ taskEnd = "no"
     THEN /\ ends' = [ends EXCEPT ![a] = "report"]
          /\ msgs' = CarryIf(msgs, a)
          /\ bad' = BadIf(bad, IF UnackedSteers(a) # {} THEN {"reportOverSteer"} ELSE {})
     ELSE UNCHANGED <<ends, msgs, bad>>
  /\ UNCHANGED <<attempt, taskEnd, conv, bell, seen, cur, addr, lastAck, flag, acct, faults,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED <<untracked, metaGone, noExit, rowGone>>
  /\ UNCHANGED lag

\* ---------------------------------------------------------------- the environment

\* The worker process dies (4.7 "The worker dies while it waits"); the conversation is kept or lost.
Die(s) ==
  /\ ALLOW_DIE /\ faults < MaxFaults /\ taskEnd = "no" /\ Alive(s)
  /\ \E c \in {"kept", "lost"} : conv' = [conv EXCEPT ![s] = c]
  /\ proc' = [proc EXCEPT ![s] = "none"]
  /\ bell' = [bell EXCEPT ![s] = FALSE]
  /\ seen' = [seen EXCEPT ![s] = {}]
  /\ addr' = AddrStop(addr, {s})
  /\ faults' = faults + 1
  /\ UNCHANGED <<attempt, ends, taskEnd, wst, cur, msgs, lastAck, flag, acct,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED newVars
  /\ UNCHANGED lag

\* The supervisor stops an idle session with no terminal after about 1 hour (#15; 4.7).
SupervisorStops(s) ==
  /\ ALLOW_SUP_STOP /\ faults < MaxFaults /\ taskEnd = "no" /\ proc[s] = "idle"
  /\ proc' = [proc EXCEPT ![s] = "none"]
  /\ bell' = [bell EXCEPT ![s] = FALSE]
  /\ seen' = [seen EXCEPT ![s] = {}]
  /\ addr' = AddrStop(addr, {s})
  /\ faults' = faults + 1
  /\ UNCHANGED <<attempt, ends, taskEnd, conv, wst, cur, msgs, lastAck, flag, acct,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED newVars
  /\ UNCHANGED lag

\* "Credit balance too low" (4.7): from now on a resume starts and fails at once.
AccountFails ==
  /\ ALLOW_ACCOUNT_FAIL /\ faults < MaxFaults /\ taskEnd = "no" /\ acct = "ok"
  /\ acct' = "failed"
  /\ faults' = faults + 1
  /\ UNCHANGED <<attempt, ends, taskEnd, proc, conv, wst, bell, seen, cur, addr, msgs, lastAck, flag,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED newVars
  /\ UNCHANGED lag

\* The pid in the .addr socket path is reused: /tmp/cc-socks/<pid>.sock now belongs to another process (4.7).
PidReused(a) ==
  /\ ALLOW_PID_REUSE /\ faults < MaxFaults /\ taskEnd = "no"
  /\ addr[a].sid # NoSid /\ ~addr[a].cur /\ ~addr[a].reused
  /\ addr' = [addr EXCEPT ![a].reused = TRUE]
  /\ faults' = faults + 1
  /\ UNCHANGED <<attempt, ends, taskEnd, proc, conv, wst, bell, seen, cur, msgs, lastAck, flag, acct,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED newVars
  /\ UNCHANGED lag

\* A process stops answering `claude stop` (round 3, D15): from now on a stop from deliver does not end it.
ProcessIgnoresStop(s) ==
  /\ ALLOW_NO_EXIT /\ faults < MaxFaults /\ taskEnd = "no" /\ Alive(s) /\ s \notin noExit
  /\ noExit' = noExit \cup {s}
  /\ faults' = faults + 1
  /\ UNCHANGED <<attempt, ends, taskEnd, proc, conv, wst, bell, seen, cur, addr, msgs, lastAck, flag, acct,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow, untracked, bad, metaGone,
                 rowGone, lag>>

\* The attempt's session disappears from `claude agents` (round 4, msg-fixes-r4 item 2): removed, pruned, never
\* recorded. The conversation is kept or lost; the process ends too unless ROW_GONE_KEEPS_PROCESS.
RowGone(s) ==
  /\ ALLOW_ROW_GONE /\ faults < MaxFaults /\ taskEnd = "no" /\ s \notin rowGone /\ proc[s] # "unborn"
  /\ rowGone' = rowGone \cup {s}
  /\ \E c \in {"kept", "lost"} : conv' = [conv EXCEPT ![s] = c]
  /\ proc' = IF ROW_GONE_KEEPS_PROCESS THEN proc ELSE StopSet(proc, {s})
  /\ bell' = IF ROW_GONE_KEEPS_PROCESS THEN bell ELSE [bell EXCEPT ![s] = FALSE]
  /\ seen' = IF ROW_GONE_KEEPS_PROCESS THEN seen ELSE [seen EXCEPT ![s] = {}]
  /\ addr' = IF ROW_GONE_KEEPS_PROCESS THEN addr ELSE AddrStop(addr, {s})
  /\ faults' = faults + 1
  /\ UNCHANGED <<attempt, ends, taskEnd, wst, cur, msgs, lastAck, flag, acct, dpc, dmsg, dsess, mgrSteers, opSteers,
                 stray, resumeOverProc, overflow, untracked, bad, metaGone, noExit, lag>>

\* ---------------------------------------------------------------- the Manager's run.py commands

\* run.py answer: refuses an ask of an ended attempt, and a second answer without --supersede (4.2, T6).
\* Files the answer row, then runs deliver in the same command.
Answer(k) ==
  /\ dpc["mgr"] = "idle" /\ LockFree /\ taskEnd = "no"
  /\ k \in Ids /\ msgs[k].kind = "ask" /\ msgs[k].att = attempt /\ ends[attempt] = "none"
  /\ Cardinality(AnswersTo(k)) < AnswersPerAsk
  /\ msgs' = Append(msgs, NewMail("answer", attempt, k))
  /\ dpc' = [dpc EXCEPT !["mgr"] = "decide"]
  /\ dmsg' = [dmsg EXCEPT !["mgr"] = Len(msgs) + 1]
  /\ UNCHANGED <<attempt, ends, taskEnd, proc, conv, wst, bell, seen, cur, addr, lastAck, flag, acct, faults,
                 dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED newVars
  /\ lag' = {}

\* Only the first answer gets fairness (live.cfg): a supersede is the Manager's choice.
FirstAnswer(k) == k \in Ids /\ AnswersTo(k) = {} /\ Answer(k)

\* run.py steer: refuses a task with no live worker in its current attempt (4.2, T7). Files the steer
\* row (SENT), then runs deliver.
ManagerSteers ==
  /\ dpc["mgr"] = "idle" /\ LockFree /\ mgrSteers < MaxSteers /\ SteerAllowed
  /\ msgs' = Append(msgs, NewMail("steer", attempt, 0))
  /\ dpc' = [dpc EXCEPT !["mgr"] = "decide"]
  /\ dmsg' = [dmsg EXCEPT !["mgr"] = Len(msgs) + 1]
  /\ mgrSteers' = mgrSteers + 1
  /\ UNCHANGED <<attempt, ends, taskEnd, proc, conv, wst, bell, seen, cur, addr, lastAck, flag, acct, faults,
                 dsess, opSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED newVars
  /\ lag' = {}

\* The operator's `run.py steer --by operator` from a terminal (9.8): a second run.py, concurrent with the Manager's.
OperatorSteers ==
  /\ ALLOW_OPERATOR /\ dpc["op"] = "idle" /\ LockFree /\ opSteers < 1 /\ SteerAllowed
  /\ msgs' = Append(msgs, NewMail("steer", attempt, 0))
  /\ dpc' = [dpc EXCEPT !["op"] = "decide"]
  /\ dmsg' = [dmsg EXCEPT !["op"] = Len(msgs) + 1]
  /\ opSteers' = opSteers + 1
  /\ UNCHANGED <<attempt, ends, taskEnd, proc, conv, wst, bell, seen, cur, addr, lastAck, flag, acct, faults,
                 dsess, mgrSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED newVars
  /\ UNCHANGED lag

\* record retries a pending delivery (5, record_in_progress: "Retry pending deliveries"). The code
\* (mailbox_events, 2357-2425) stops after DELIVERIES_MAX tries and prints steer-pending.
RecordRetries(i) ==
  /\ dpc["mgr"] = "idle" /\ LockFree /\ taskEnd = "no"
  /\ i \in Ids /\ IsMail(i) /\ msgs[i].st = "pending"
  /\ IMPL_DELIVERY_CAP => msgs[i].tries < DeliveriesMax
  \* round 4: with no session row, deliver only prints "record tries again" (a step that changes nothing)
  /\ (cur[msgs[i].att] \in rowGone /\ ~AttemptEnded(msgs[i].att)) => FIX_NO_ROW_RESUMES
  /\ dpc' = [dpc EXCEPT !["mgr"] = "decide"]
  /\ dmsg' = [dmsg EXCEPT !["mgr"] = i]
  /\ UNCHANGED <<attempt, ends, taskEnd, proc, conv, wst, bell, seen, cur, addr, msgs, lastAck, flag, acct, faults,
                 dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED newVars
  /\ lag' = {}

\* record: a Rung row with no ack within pending_minutes goes back to pending; the next deliver skips
\* the socket for it (4.2 step 2, T8b). FIX: a Delivered row too.
RecordTimesOut(i) ==
  /\ dpc["mgr"] = "idle" /\ taskEnd = "no"
  /\ i \in Ids /\ IsMail(i)
  /\ msgs[i].st = "rung" \/ (FIX_DELIVERED_TIMES_OUT /\ msgs[i].st = "delivered")
  /\ msgs' = [msgs EXCEPT ![i].st = "pending", ![i].sockF = (@ \/ msgs[i].via = "socket")]
  /\ UNCHANGED <<attempt, ends, taskEnd, proc, conv, wst, bell, seen, cur, addr, lastAck, flag, acct, faults,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED newVars
  /\ lag' = {}

\* record files DIED for a worker whose turn is over (or with no pid) and no task row, unless an open
\* blocking ask stops it (5, record_in_progress; 4.7). DIED also stands for stuck and a ghost end.
\* The code (record_in_progress 2927-2966): no end row while `holds`; else salvage the report file when there is
\* one (a report row), else DIED. A failed row takes the same branch (IMPL_DETAILS).
RecordFilesDied ==
  LET a == attempt
      failedEnd == FIX_FAILED_ENDS /\ proc[cur[a]] = "failed"
      noRow == cur[a] \in rowGone
      \* CLI_ROW_LAG: the row of a session resumed just now still reads "no process"
      readProc == IF cur[a] \in lag THEN "none" ELSE proc[cur[a]]
      salvaged == /\ IMPL_SALVAGE
                  /\ \E s \in SessOf(a) : wst[s] = "checked"
                  /\ ~(FIX_SALVAGE_REFUSES_UNACKED_STEER /\ UnackedSteers(a) # {})
  IN
  /\ dpc["mgr"] = "idle" /\ LockFree /\ taskEnd = "no" /\ ends[a] = "none"
  /\ noRow \/ readProc \in (IF IMPL_DETAILS THEN {"idle", "none", "failed"} ELSE {"idle", "none"})
  /\ FIX_RESUMED_HOLDS => cur[a] \notin lag
  /\ failedEnd \/ (FIX_NO_ROW_ENDS /\ noRow) \/ (IF IMPL_HOLDS THEN ~RecordHolds(a) ELSE ~AskOpenForRecord(a))
  /\ ends' = [ends EXCEPT ![a] = IF salvaged THEN "report" ELSE IF failedEnd THEN "FAILED" ELSE "DIED"]
  /\ msgs' = CarryIf(msgs, a)
  /\ bad' = BadIf(bad, (IF \E s \in SessOf(a) : proc[s] = "busy" THEN {"endOverBusy"} ELSE {})
                       \cup (IF salvaged /\ UnackedSteers(a) # {} THEN {"reportOverSteer"} ELSE {}))
  /\ UNCHANGED <<attempt, taskEnd, proc, conv, wst, bell, seen, cur, addr, lastAck, flag, acct, faults,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED <<untracked, metaGone, noExit, rowGone>>
  /\ lag' = {}

\* record sees a failed row: the profiles spec's handling applies (4.7, account row); read as an end row.
\* The code has no such branch (IMPL_DETAILS: RecordFilesDied takes it).
RecordFilesFailed ==
  /\ ~IMPL_DETAILS
  /\ dpc["mgr"] = "idle" /\ LockFree /\ taskEnd = "no" /\ ends[attempt] = "none"
  /\ proc[cur[attempt]] = "failed"
  /\ ends' = [ends EXCEPT ![attempt] = "FAILED"]
  /\ msgs' = CarryIf(msgs, attempt)
  /\ bad' = BadIf(bad, IF \E s \in SessOf(attempt) : proc[s] = "busy" THEN {"endOverBusy"} ELSE {})
  /\ UNCHANGED <<attempt, taskEnd, proc, conv, wst, bell, seen, cur, addr, lastAck, flag, acct, faults,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED <<untracked, metaGone, noExit, rowGone>>
  /\ lag' = {}

\* run.py launch of the next attempt: refuses while a session of the attempt is busy; stops the idle
\* ones (stopped-idle). A fresh session; its SessionStart hook checks in. The code (cmd_launch 1571-1790) renders
\* the brief (1703) before it carries the thread (1756) and prunes the mailbox meta (1775-1782). It sees only the
\* sessions it can tie to the task.
Launch ==
  LET a == attempt  n == attempt + 1  vis == VisibleSet(SessOf(a)) IN
  /\ dpc["mgr"] = "idle" /\ LockFree /\ taskEnd = "no"
  /\ ends[a] # "none" /\ a < MaxAttempts
  /\ \A s \in vis : proc[s] # "busy"
  /\ \E ci \in CheckinChoices :
       /\ proc' = [StopSet(proc, vis) EXCEPT ![Orig(n)] = "busy"]
       /\ addr' = AddrStart(AddrStop(addr, vis), Orig(n), ci, FALSE)
       /\ faults' = IF ci THEN faults ELSE faults + 1
  /\ bell' = [s \in Sids |-> IF s \in vis THEN FALSE ELSE bell[s]]
  /\ seen' = [s \in Sids |-> IF s \in vis THEN {} ELSE seen[s]]
  /\ attempt' = n
  /\ msgs' = CarryIf(msgs, a)
  /\ bad' = BadIf(bad, BriefFlaws(n))
  /\ metaGone' = PruneBefore(n)
  /\ UNCHANGED <<ends, taskEnd, conv, wst, cur, lastAck, flag, acct,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED <<untracked, noExit, rowGone>>
  /\ lag' = {}

\* The operator's `run.py launch <id> --attempt <n+1>` after an abandon (cmd_launch 1592-1593 asks for --attempt).
\* Abandon stopped the sessions it saw and dropped the mailbox meta.
Relaunch ==
  LET n == attempt + 1 IN
  /\ ALLOW_RELAUNCH /\ taskEnd = "abandoned" /\ attempt < MaxAttempts
  \* cmd_launch refuses while the attempt has no end row and an open ask (1642-1652)
  /\ ends[attempt] # "none" \/ ~Blocking(attempt)
  /\ \A e \in Deliverers : dpc[e] = "idle"
  /\ \E ci \in CheckinChoices :
       /\ proc' = [proc EXCEPT ![Orig(n)] = "busy"]
       /\ addr' = AddrStart(addr, Orig(n), ci, FALSE)
       /\ faults' = IF ci THEN faults ELSE faults + 1
  /\ attempt' = n
  /\ taskEnd' = "no"
  /\ bad' = BadIf(bad, BriefFlaws(n))
  /\ metaGone' = PruneBefore(n)
  /\ UNCHANGED <<ends, conv, wst, bell, seen, cur, msgs, lastAck, flag, acct,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED <<untracked, noExit, rowGone>>
  /\ lag' = {}

\* run.py close after a report (PASS): stops the task's live sessions; marks open asks and unacked
\* steers of the attempt Carried (5, stop/close/abandon). The code (stop_live 4059-4079) stops the rows it sees.
Close ==
  LET vis == VisibleSet(Sids) IN
  /\ dpc["mgr"] = "idle" /\ LockFree /\ taskEnd = "no" /\ ends[attempt] = "report"
  /\ proc' = StopSet(proc, vis)
  /\ addr' = AddrStop(addr, vis)
  /\ bell' = [s \in Sids |-> IF s \in vis THEN FALSE ELSE bell[s]]
  /\ seen' = [s \in Sids |-> IF s \in vis THEN {} ELSE seen[s]]
  /\ taskEnd' = "closed"
  /\ msgs' = CarryAtt(msgs, attempt)
  /\ UNCHANGED <<attempt, ends, conv, wst, cur, lastAck, flag, acct, faults,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED newVars
  /\ lag' = {}

\* run.py abandon after an end row. The code (cmd_abandon 4328-4355) stops the rows it sees and drops the mailbox
\* meta (drop_mailbox 2562-2574); it marks nothing Carried. The model still marks the rows Carried (no delivery is
\* owed any more) and checks what a relaunched brief pastes (BriefPastesEveryCarriedMessage).
Abandon ==
  LET vis == VisibleSet(Sids) IN
  /\ dpc["mgr"] = "idle" /\ LockFree /\ taskEnd = "no" /\ (ends[attempt] # "none" \/ ALLOW_ABANDON_OPEN)
  \* an attempt with no end row: b75b176 files ABANDONED only for a live row it sees (4336-4340); item 2 always
  /\ ends' = IF ends[attempt] = "none"
                /\ (FIX_ABANDON_ENDS \/ \E s \in VisibleSet(SessOf(attempt)) : RowLive(s))
             THEN [ends EXCEPT ![attempt] = "ABANDONED"] ELSE ends
  /\ proc' = StopSet(proc, vis)
  /\ addr' = AddrStop(addr, vis)
  /\ bell' = [s \in Sids |-> IF s \in vis THEN FALSE ELSE bell[s]]
  /\ seen' = [s \in Sids |-> IF s \in vis THEN {} ELSE seen[s]]
  /\ taskEnd' = "abandoned"
  /\ msgs' = CarryAtt(msgs, attempt)
  /\ metaGone' = IF IMPL_PRUNE_META THEN metaGone \cup {e \in Attempts : e <= attempt} ELSE metaGone
  /\ UNCHANGED <<attempt, conv, wst, cur, lastAck, flag, acct, faults,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED <<untracked, bad, noExit, rowGone>>
  /\ lag' = {}

\* run.py stop of an attempt in progress (a pause or a recovery): STOPPED row; Carried. The code (cmd_stop
\* 4303-4325) refuses an attempt with no live row.
ManagerStops ==
  LET vis == VisibleSet(SessOf(attempt)) IN
  /\ MANAGER_STOPS /\ dpc["mgr"] = "idle" /\ LockFree /\ taskEnd = "no" /\ ends[attempt] = "none"
  /\ IMPL_LIVE_ROWS => ((\E s \in vis : RowLive(s)) \/ (FIX_STOP_OPEN_THREAD /\ cur[attempt] \notin rowGone /\ ThreadHolds(attempt)))
  /\ proc' = StopSet(proc, vis)
  /\ addr' = AddrStop(addr, vis)
  /\ bell' = [s \in Sids |-> IF s \in vis THEN FALSE ELSE bell[s]]
  /\ seen' = [s \in Sids |-> IF s \in vis THEN {} ELSE seen[s]]
  /\ ends' = [ends EXCEPT ![attempt] = "STOPPED"]
  /\ msgs' = CarryAtt(msgs, attempt)
  /\ UNCHANGED <<attempt, taskEnd, conv, wst, cur, lastAck, flag, acct, faults,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED newVars
  /\ lag' = {}

\* ---------------------------------------------------------------- deliver(run, task, row), 4.2

\* Step 1: the task's live worker session for the current attempt (FIX: for the row's own attempt).
TargetAtt(d) == IF FIX_DELIVER_OWN_ATTEMPT THEN msgs[dmsg[d]].att ELSE attempt
Target(d) == cur[TargetAtt(d)]
\* Step 2's guard: the process is alive (pid set); with the check, the .addr session_id equals the
\* agents row's sessionId and the .addr file is newer than the row's last start. B5: the socket path's pid is
\* the row's pid (the .addr's socket belongs to the current process).
SocketUsable(d) ==
  LET ta == TargetAtt(d)  t == Target(d) IN
  /\ PHASE2 /\ ~msgs[dmsg[d]].sockF /\ Alive(t) /\ addr[ta].sid # NoSid
  /\ DESIGN_SID_CHECK => (addr[ta].sid = t /\ addr[ta].fresh)
  /\ FIX_SOCKET_PID_MATCH => addr[ta].cur

\* The code: deliver (2226-2272). tries counts each deliver call (2237); with B1 fixed, socket posts and
\* resumes only.
DeliverDecide(d) ==
  LET i == dmsg[d]  ta == TargetAtt(d)  t == Target(d)  ad == addr[ta]
      tried(ms, yes) == IF IMPL_DELIVERY_CAP /\ yes THEN [ms EXCEPT ![i].tries = @ + 1] ELSE ms
      \* D9 (2256-2265): the socket step was entered (live row with a pid) but had no usable address
      staleFail == IMPL_STALE_ADDR_FAILS /\ PHASE2 /\ ~msgs[i].sockF /\ Alive(t) /\ ~SocketUsable(d)
      sf(ms) == IF staleFail THEN [ms EXCEPT ![i].sockF = TRUE] ELSE ms
  IN
  /\ dpc[d] = "decide"
  /\ IF msgs[i].st # "pending" THEN
        \* acked (a checkpoint read it) or carried meanwhile: nothing to deliver
        /\ dpc' = [dpc EXCEPT ![d] = "idle"]
        /\ UNCHANGED <<msgs, flag, bell, seen, proc, addr, dsess, stray, faults>>
     ELSE IF FIX_DELIVER_OWN_ATTEMPT /\ AttemptEnded(msgs[i].att) THEN
        /\ msgs' = [msgs EXCEPT ![i].st = "carried"]
        /\ dpc' = [dpc EXCEPT ![d] = "idle"]
        /\ UNCHANGED <<flag, bell, seen, proc, addr, dsess, stray, faults>>
     ELSE IF t \in rowGone /\ FIX_NO_ROW_RESUMES THEN
        \* the alternative fix: resume the recorded sessionId although `claude agents` lists no row
        /\ proc' = StopSet(proc, {t})
        /\ bell' = [bell EXCEPT ![t] = FALSE]
        /\ seen' = [seen EXCEPT ![t] = {}]
        /\ addr' = AddrStop(addr, {t})
        /\ dpc' = [dpc EXCEPT ![d] = "resume"]
        /\ dsess' = [dsess EXCEPT ![d] = t]
        /\ msgs' = tried(msgs, TRUE)
        /\ UNCHANGED <<flag, stray, faults>>
     ELSE IF t \in rowGone THEN
        \* b75b176 (deliver 2251-2253): "no session row for attempt N; record tries again", no try
        /\ dpc' = [dpc EXCEPT ![d] = "idle"]
        /\ UNCHANGED <<msgs, flag, bell, seen, proc, addr, dsess, stray, faults>>
     ELSE IF SocketUsable(d) /\ ad.cur THEN
        \* step 2: the post reaches the process that checked in; it may hold the message
        \E held \in HoldChoices :
          /\ msgs' = tried([msgs EXCEPT ![i].st = "rung", ![i].via = "socket"], TRUE)
          /\ bell' = IF held THEN bell ELSE [bell EXCEPT ![ad.sid] = TRUE]
          /\ stray' = IF held THEN stray ELSE stray \cup StrayOf({i}, ad.sid)
          /\ faults' = IF held THEN faults + 1 ELSE faults
          /\ dpc' = [dpc EXCEPT ![d] = "idle"]
          /\ UNCHANGED <<flag, seen, proc, addr, dsess>>
     ELSE IF SocketUsable(d) /\ ad.reused THEN
        \* step 2: the post "succeeds" into the process that now owns the old socket path
        /\ msgs' = tried([msgs EXCEPT ![i].st = "rung", ![i].via = "socket"], TRUE)
        /\ stray' = stray \cup {"otherProcess"}
        /\ dpc' = [dpc EXCEPT ![d] = "idle"]
        /\ UNCHANGED <<flag, bell, seen, proc, addr, dsess, faults>>
     ELSE IF SocketUsable(d) THEN
        \* step 2: ECONNREFUSED; deliver-fallback to step 3 or 4
        /\ msgs' = [msgs EXCEPT ![i].sockF = TRUE]
        /\ UNCHANGED <<dpc, flag, bell, seen, proc, addr, dsess, stray, faults>>
     ELSE IF proc[t] = "busy" THEN
        \* step 4: touch the flag; the PostToolUse hook shows the pointer at the next tool call (Rung).
        \* The code (2268-2271): the row stays pending ("hook"), so the next record touches the flag again.
        /\ msgs' = sf(IF IMPL_HOOK_IS_A_TRY THEN tried([msgs EXCEPT ![i].via = "hook"], TRUE)
                      ELSE [msgs EXCEPT ![i].st = "rung", ![i].via = "hook"])
        /\ flag' = flag \cup {i}
        /\ dpc' = [dpc EXCEPT ![d] = "idle"]
        /\ UNCHANGED <<bell, seen, proc, addr, dsess, stray, faults>>
     ELSE IF FIX_FAILED_ENDS /\ proc[t] = "failed" THEN
        \* round 3 item 1: a failed row is never resumed; record files its end
        /\ dpc' = [dpc EXCEPT ![d] = "idle"]
        /\ UNCHANGED <<msgs, flag, bell, seen, proc, addr, dsess, stray, faults>>
     ELSE IF Alive(t) /\ t \in noExit THEN
        \* step 3: `claude stop` is sent, the process does not exit, wait_for_exit gives up (2291-2294): the row
        \* stays pending; at 3330fc7 that is a try (round 3 item 4: not a try)
        /\ msgs' = sf(tried(msgs, ~FIX_EXIT_TIMEOUT_NOT_A_TRY))
        /\ dpc' = [dpc EXCEPT ![d] = "idle"]
        /\ UNCHANGED <<flag, bell, seen, proc, addr, dsess, stray, faults>>
     ELSE
        \* step 3: idle, waiting or parked: `claude stop` when a process is alive, wait until the row
        \* shows no process; the resume is the next step
        /\ proc' = IF Alive(t) THEN [proc EXCEPT ![t] = "none"] ELSE proc
        /\ bell' = [bell EXCEPT ![t] = FALSE]
        /\ seen' = [seen EXCEPT ![t] = {}]
        /\ addr' = AddrStop(addr, {t})
        /\ dpc' = [dpc EXCEPT ![d] = "resume"]
        /\ dsess' = [dsess EXCEPT ![d] = t]
        /\ msgs' = sf(tried(msgs, TRUE))
        /\ UNCHANGED <<flag, stray, faults>>
  /\ UNCHANGED <<attempt, ends, taskEnd, conv, wst, cur, lastAck, acct, dmsg, mgrSteers, opSteers,
                 resumeOverProc, overflow>>
  /\ UNCHANGED newVars
  /\ UNCHANGED lag

\* Step 3, second half: CLAUDE_CONFIG_DIR=<profile> claude --bg --resume <sessionId> "<doorbell>".
\* The code: resume_with (2275-2315). The copy takes the attempt's other slot.
DeliverResume(d) ==
  LET i == dmsg[d]  t == dsess[d]  a == AttOf[t]  c == Other(t)
      mark(newSt) == IF msgs[i].st = "pending" THEN [msgs EXCEPT ![i].st = newSt, ![i].via = "resume"] ELSE msgs
      copying == Alive(t) \/ IMPL_RESUME_COPIES
      slotTaken == IF IMPL_RESUME_COPIES THEN Alive(c) ELSE proc[c] # "unborn"
      lowered == IF IMPL_DETAILS THEN {j \in flag : msgs[j].att # a} ELSE flag
      ending == a = attempt /\ ends[a] = "none" /\ taskEnd = "no"
  IN
  /\ dpc[d] = "resume"
  /\ resumeOverProc' = (resumeOverProc \/ Alive(t))
  /\ IF conv[t] = "lost" THEN
        \* the resume errors (no transcript): only a failed resume files DIED; the open ask is Carried (4.7)
        /\ ends' = IF ending THEN [ends EXCEPT ![a] = "DIED"] ELSE ends
        /\ bad' = IF ending /\ \E s \in SessOf(a) : proc[s] = "busy" THEN BadIf(bad, {"endOverBusy"}) ELSE bad
        /\ msgs' = CarryAtt(msgs, a)
        /\ dpc' = [dpc EXCEPT ![d] = "idle"]
        /\ UNCHANGED <<proc, conv, wst, bell, seen, cur, addr, flag, faults, stray, overflow, untracked, rowGone, lag>>
     ELSE IF acct = "failed" /\ ~Alive(t) THEN
        \* the resume starts and the session fails at once (4.7, account row)
        /\ proc' = [proc EXCEPT ![t] = "failed"]
        /\ msgs' = mark("delivered")
        /\ flag' = lowered
        /\ dpc' = [dpc EXCEPT ![d] = "idle"]
        /\ rowGone' = rowGone \ {t}
        /\ UNCHANGED <<ends, conv, wst, bell, seen, cur, addr, faults, stray, overflow, untracked, bad, lag>>
     ELSE IF copying /\ slotTaken THEN
        \* a second live copy for one attempt: not tracked (TypeOK fails)
        /\ overflow' = TRUE
        /\ dpc' = [dpc EXCEPT ![d] = "idle"]
        /\ UNCHANGED <<ends, msgs, proc, conv, wst, bell, seen, cur, addr, flag, faults, stray, untracked, bad, rowGone, lag>>
     ELSE IF copying THEN
        \* the CLI starts a copy (#12: the session still runs; CLI 2.1.319: any flag) and prints a note: line
        \E ci \in CheckinChoices :
          /\ proc' = [proc EXCEPT ![c] = "busy"]
          /\ conv' = [conv EXCEPT ![c] = "kept"]
          /\ wst' = [wst EXCEPT ![c] = wst[t]]
          /\ bell' = [bell EXCEPT ![c] = TRUE]
          /\ seen' = [seen EXCEPT ![c] = {}]
          /\ addr' = AddrStart(addr, c, ci, FALSE)
          /\ faults' = IF ci THEN faults ELSE faults + 1
          /\ stray' = stray \cup StrayOf({i}, c)
          /\ IF IMPL_COPY_NOTE_MISSED THEN
               \* the note is on stderr: run.py takes the copy for an in-place resume (2301-2315)
               /\ msgs' = mark("delivered")
               /\ dpc' = [dpc EXCEPT ![d] = "idle"]
               /\ untracked' = untracked \cup {c}
               /\ cur' = IF CLI_COPY_IN_WORKTREE THEN [cur EXCEPT ![a] = c] ELSE cur
               /\ flag' = lowered
             ELSE
               /\ msgs' = mark("copied")
               /\ dpc' = [dpc EXCEPT ![d] = "settle"]
               /\ untracked' = untracked \ {c}
               /\ UNCHANGED <<cur, flag>>
          /\ UNCHANGED <<ends, overflow, bad, rowGone, lag>>
     ELSE
        \* the session continues in place with the doorbell as its prompt (Delivered)
        \E ci \in CheckinChoices :
          /\ proc' = [proc EXCEPT ![t] = "busy"]
          /\ bell' = [bell EXCEPT ![t] = TRUE]
          /\ addr' = AddrStart(addr, t, ci, TRUE)
          /\ faults' = IF ci THEN faults ELSE faults + 1
          /\ stray' = stray \cup StrayOf({i}, t)
          /\ msgs' = mark("delivered")
          /\ flag' = lowered
          /\ dpc' = [dpc EXCEPT ![d] = "idle"]
          /\ rowGone' = rowGone \ {t}
          /\ lag' = IF CLI_ROW_LAG THEN lag \cup {t} ELSE lag
          /\ UNCHANGED <<ends, conv, wst, seen, cur, overflow, untracked, bad>>
  /\ UNCHANGED <<attempt, taskEnd, lastAck, acct, dmsg, dsess, mgrSteers, opSteers, metaGone, noExit>>

\* After a note: line: record the copy's session id, stop the original, print deliver-copy (4.2, T10).
\* The code: resume_with 2303-2312.
DeliverSettle(d) ==
  LET i == dmsg[d]  t == dsess[d]  a == AttOf[t] IN
  /\ dpc[d] = "settle"
  /\ proc' = IF Alive(t) THEN [proc EXCEPT ![t] = "none"] ELSE proc
  /\ bell' = [bell EXCEPT ![t] = FALSE]
  /\ seen' = [seen EXCEPT ![t] = {}]
  /\ addr' = AddrStop(addr, {t})
  /\ cur' = [cur EXCEPT ![a] = Other(t)]
  /\ msgs' = IF msgs[i].st = "copied" THEN [msgs EXCEPT ![i].st = "delivered"] ELSE msgs
  /\ dpc' = [dpc EXCEPT ![d] = "idle"]
  /\ UNCHANGED <<attempt, ends, taskEnd, conv, wst, lastAck, flag, acct, faults,
                 dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>
  /\ UNCHANGED newVars
  /\ UNCHANGED lag

\* ---------------------------------------------------------------- next

\* The end states: the task is closed or abandoned and no deliver runs.
Finished ==
  /\ taskEnd # "no"
  /\ \A d \in Deliverers : dpc[d] = "idle"
  /\ UNCHANGED vars

Next ==
  \/ \E s \in Sids :
       \/ WorkerAsks(s) \/ WorkerReadsInbox(s) \/ WorkerAcks(s) \/ WorkerChecksReport(s) \/ WorkerReports(s)
       \/ Die(s) \/ SupervisorStops(s) \/ ProcessIgnoresStop(s) \/ RowGone(s)
  \/ \E k \in Ids : Answer(k)
  \/ ManagerSteers \/ OperatorSteers
  \/ \E i \in Ids : RecordRetries(i) \/ RecordTimesOut(i)
  \/ RecordFilesDied \/ RecordFilesFailed
  \/ \E d \in Deliverers : DeliverDecide(d) \/ DeliverResume(d) \/ DeliverSettle(d)
  \/ Launch \/ Relaunch \/ Close \/ Abandon \/ ManagerStops
  \/ AccountFails \/ \E a \in Attempts : PidReused(a)
  \/ Finished

Spec == Init /\ [][Next]_vars

\* live.cfg only: the Manager, run.py and the worker keep going; the environment, the steers, the
\* supersede and run.py stop are not forced.
Fairness ==
  /\ \A s \in Sids : WF_vars(WorkerReadsInbox(s)) /\ WF_vars(WorkerAcks(s))
                     /\ WF_vars(WorkerChecksReport(s)) /\ WF_vars(WorkerReports(s))
  /\ \A d \in Deliverers : WF_vars(DeliverDecide(d) \/ DeliverResume(d) \/ DeliverSettle(d))
  /\ \A k \in 1..MaxMsgs : WF_vars(FirstAnswer(k)) /\ WF_vars(RecordRetries(k)) /\ WF_vars(RecordTimesOut(k))
  /\ WF_vars(RecordFilesDied) /\ WF_vars(RecordFilesFailed)
  /\ WF_vars(Launch) /\ WF_vars(Close) /\ WF_vars(Abandon)

FairSpec == Spec /\ Fairness

\* ---------------------------------------------------------------- rules, in the reader's words

TypeOK ==
  /\ attempt \in Attempts
  /\ Len(msgs) <= MaxMsgs
  /\ faults \in 0..MaxFaults
  /\ ~overflow
  /\ \A s \in Sids : proc[s] \in {"unborn", "none", "busy", "idle", "failed"} /\ wst[s] \in {"work", "wait", "checked", "done"}
  /\ \A d \in Deliverers : dpc[d] \in {"idle", "decide", "resume", "settle"}
  /\ untracked \subseteq Sids /\ metaGone \subseteq Attempts /\ noExit \subseteq Sids /\ rowGone \subseteq Sids /\ lag \subseteq Sids
  /\ bad \subseteq {"endOverBusy", "reportOverSteer", "settledShownOpen", "carriedLost"}

\* 1. No answer or steer is delivered to a session of another attempt: no doorbell for a row (socket
\*    post, resume prompt, hook pointer) reaches a session of another attempt or another process.
DoorbellOnlyToOwnAttempt == stray \cap {"otherAttempt", "otherProcess"} = {}

\* 1b. No doorbell reaches a session after its attempt has ended (a report, DIED, a stop, or a later attempt).
NoDoorbellAfterAttemptEnds == "endedAttempt" \notin stray

\* 2. An attempt whose worker waits on a blocking ask is never filed DIED (or stuck) while its
\*    conversation exists.
AskerNeverFiledDead ==
  \A a \in Attempts : ends[a] = "DIED" => ~(wst[cur[a]] = "wait" /\ conv[cur[a]] = "kept")

\* 3. At most one live session per attempt; a resume copy is settled before the next deliver starts.
OneLiveSessionPerAttempt ==
  \A a \in Attempts :
     \/ Cardinality({s \in SessOf(a) : Alive(s)}) <= 1
     \/ \E d \in Deliverers :
          /\ dpc[d] = "settle" /\ dsess[d] \in SessOf(a)
          /\ \A e \in Deliverers \ {d} : dpc[e] = "idle"

\* 4. Every steer ends Acked or Carried: once the Manager has moved past its attempt (the next attempt
\*    runs, or the task is over), each steer of that attempt is Acked or Carried.
SteersSettledOnceAttemptOver ==
  \A i \in Ids : (msgs[i].kind = "steer" /\ AttemptOver(msgs[i].att)) => Settled(i)

\* 4b. An answer is never lost: once the Manager has moved past its attempt, each answer is Acked or
\*     Carried (or settled by a newer answer the worker acked).
AnswersSettledOnceAttemptOver ==
  \A i \in Ids : (msgs[i].kind = "answer" /\ AttemptOver(msgs[i].att)) => Settled(i)

\* 5. deliver never runs --bg --resume while the session still has a process.
NoResumeOverLiveProcess == ~resumeOverProc

\* 6. A task that closes after its report has no steer of that attempt the worker did not read.
ClosedTaskHasNoUnreadSteer ==
  taskEnd = "closed" => \A i \in Ids : (msgs[i].kind = "steer" /\ msgs[i].att = attempt) => msgs[i].st = "acked"

\* 7. The inbox shows every answer and steer of a running attempt that the worker has not acked
\*    (an answer replaced by a newer answer to the same ask excepted).
InboxShowsEveryUnreadMessage ==
  \A i \in Ids :
     (IsMail(i) /\ ~AttemptEnded(msgs[i].att) /\ ~Settled(i) /\ ~NewerAnswer(i)) => i \in Inbox(msgs[i].att)

\* 8. When the task is over and no deliver runs, no worker session of the task has a process.
NoWorkerLeftAtEnd ==
  (taskEnd # "no" /\ \A d \in Deliverers : dpc[d] = "idle") => \A s \in Sids : ~Alive(s)

\* ---- round 2 (configs impl-*, need-r2-*; TRACK_NEW_RULES on)

\* 9. Every live worker session of the task is in the sessions record: run.py recorded it (no untracked copy).
EveryLiveWorkerIsRecorded == \A s \in Sids : Alive(s) => s \notin untracked

\* 10. record never files an end row (DIED, a salvaged report, a failed row) while a session of the attempt has a
\*     running turn.
NoEndRowOverRunningWorker == "endOverBusy" \notin bad

\* 11. No report row (the worker's, or one that record salvaged) is filed while a steer of the attempt has no ack.
NoReportOverUnackedSteer == "reportOverSteer" \notin bad

\* 12. A later brief never shows a settled ask (its answer was acked) as open.
BriefNeverShowsSettledAsOpen == "settledShownOpen" \notin bad

\* 13. The brief of the next attempt pastes every answer and steer that the ended attempt left without an ack
\*     (Carried: "the next brief pastes it").
BriefPastesEveryCarriedMessage == "carriedLost" \notin bad

\* 14. (round 4) An abandoned task that has attempts left can be launched again: cmd_launch does not refuse it on an
\*     open ask of an attempt that has no end row. (Abandoned is an end state, so the deadlock check cannot see this.)
AbandonedTaskCanBeRelaunched ==
  (ALLOW_RELAUNCH /\ taskEnd = "abandoned" /\ attempt < MaxAttempts) => (ends[attempt] # "none" \/ ~Blocking(attempt))

\* Liveness (live.cfg, with FairSpec): every steer, and every answer, is eventually Acked or Carried.
SteersSettle ==
  \A i \in 1..MaxMsgs : (i \in Ids /\ msgs[i].kind = "steer") ~> (i \in Ids /\ Settled(i))
AnswersSettle ==
  \A i \in 1..MaxMsgs : (i \in Ids /\ msgs[i].kind = "answer") ~> (i \in Ids /\ Settled(i))

=============================================================================
