---------------------------- MODULE Mailbox ----------------------------
\* The mailbox-and-doorbell design of the ADR "How the Manager and its workers talk across Claude
\* profiles": ronica-skills-adr docs/plans/2026-11-09-agentic-team-channel-adr.md (status proposed,
\* 2026-11-09; read on 2026-11-09), sections 1, 4.1-4.8, 5 and "Live check results". Nothing in the
\* ADR is implemented, so the model reads the ADR text, not code. ADR line numbers are in NOTES.md.
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
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS
  MaxAttempts,          \* 1 or 2 (run.py allows 3)
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
  FIX_DELIVER_LOCK         \* one run.py lock per task: a deliver, and every command that stops sessions or files an end row, waits for a running deliver

ASSUME MaxAttempts \in {1, 2} /\ ASKS \in {0, 1} /\ MaxSteers \in Nat /\ MaxFaults \in Nat

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
  overflow      \* a second copy was needed for one attempt: beyond what the model tracks

vars == <<attempt, ends, taskEnd, proc, conv, wst, bell, seen, cur, addr, msgs, lastAck, flag, acct,
          faults, dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>

\* ---------------------------------------------------------------- values

Attempts == 1..MaxAttempts
Sids == {"w1", "c1", "w2", "c2"}
AttOf == [s \in Sids |-> IF s \in {"w1", "c1"} THEN 1 ELSE 2]
Orig(a) == IF a = 1 THEN "w1" ELSE "w2"
CopyOf(a) == IF a = 1 THEN "c1" ELSE "c2"
SessOf(a) == {Orig(a), CopyOf(a)}
NoSid == "none"
Deliverers == {"mgr", "op"}
AnswersPerAsk == IF ALLOW_SUPERSEDE THEN 2 ELSE 1
MaxMsgs == MaxAttempts * ASKS * (1 + AnswersPerAsk) + MaxSteers + (IF ALLOW_OPERATOR THEN 1 ELSE 0)
NoAddr == [sid |-> NoSid, cur |-> FALSE, reused |-> FALSE, fresh |-> FALSE]
NewMail(k, a, r) == [kind |-> k, att |-> a, re |-> r, st |-> "pending", via |-> "none", sockF |-> FALSE]

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
\* run.py steer refuses "a task with no live worker in its current attempt" (4.2).
SteerAllowed ==
  /\ taskEnd = "no"
  /\ \E s \in SessOf(attempt) : Alive(s)
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
\* names s, it is now older than s's start and its socket path is the old process's.
AddrStart(ad, s, ci) ==
  IF ci THEN [ad EXCEPT ![AttOf[s]] = [sid |-> s, cur |-> TRUE, reused |-> FALSE, fresh |-> TRUE]]
  ELSE IF ad[AttOf[s]].sid = s THEN [ad EXCEPT ![AttOf[s]].fresh = FALSE, ![AttOf[s]].cur = FALSE]
  ELSE ad
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

\* ---------------------------------------------------------------- the worker

\* mailbox.py ask: file the ask row (OPEN), end the turn with "Waiting for answer to ask #N" (worker.md, Asking).
WorkerAsks(s) ==
  /\ proc[s] = "busy" /\ wst[s] = "work" /\ seen[s] = {}
  /\ Cardinality(AsksOf(AttOf[s])) < ASKS
  /\ msgs' = Append(msgs, [kind |-> "ask", att |-> AttOf[s], re |-> 0, st |-> "open", via |-> "none", sockF |-> FALSE])
  /\ wst' = [wst EXCEPT ![s] = "wait"]
  /\ proc' = [proc EXCEPT ![s] = "idle"]
  /\ UNCHANGED <<attempt, ends, taskEnd, conv, bell, seen, cur, addr, lastAck, flag, acct, faults,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>

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

\* check-report: refuses while a steer of the attempt has no ack (4.7, T12). A doorbell that arrived
\* between tool calls is read first.
CanReport(s) ==
  /\ proc[s] = "busy" /\ seen[s] = {} /\ ~bell[s]
  /\ UnackedSteers(AttOf[s]) = {}

WorkerChecksReport(s) ==
  /\ ~FIX_REPORT_CHECK_ATOMIC
  /\ wst[s] = "work" /\ CanReport(s)
  /\ wst' = [wst EXCEPT ![s] = "checked"]
  /\ UNCHANGED <<attempt, ends, taskEnd, proc, conv, bell, seen, cur, addr, msgs, lastAck, flag, acct, faults,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>

\* The worker files its result row and ends its turn. A late report of an attempt that already has an
\* end row changes no end row.
WorkerReports(s) ==
  LET a == AttOf[s] IN
  /\ IF FIX_REPORT_CHECK_ATOMIC THEN wst[s] = "work" /\ CanReport(s)
     ELSE wst[s] = "checked" /\ proc[s] = "busy" /\ seen[s] = {} /\ ~bell[s]
  /\ wst' = [wst EXCEPT ![s] = "done"]
  /\ proc' = [proc EXCEPT ![s] = "idle"]
  /\ IF a = attempt /\ ends[a] = "none" /\ taskEnd = "no"
     THEN ends' = [ends EXCEPT ![a] = "report"] /\ msgs' = CarryIf(msgs, a)
     ELSE UNCHANGED <<ends, msgs>>
  /\ UNCHANGED <<attempt, taskEnd, conv, bell, seen, cur, addr, lastAck, flag, acct, faults,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>

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

\* "Credit balance too low" (4.7): from now on a resume starts and fails at once.
AccountFails ==
  /\ ALLOW_ACCOUNT_FAIL /\ faults < MaxFaults /\ taskEnd = "no" /\ acct = "ok"
  /\ acct' = "failed"
  /\ faults' = faults + 1
  /\ UNCHANGED <<attempt, ends, taskEnd, proc, conv, wst, bell, seen, cur, addr, msgs, lastAck, flag,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>

\* The pid in the .addr socket path is reused: /tmp/cc-socks/<pid>.sock now belongs to another process (4.7).
PidReused(a) ==
  /\ ALLOW_PID_REUSE /\ faults < MaxFaults /\ taskEnd = "no"
  /\ addr[a].sid # NoSid /\ ~addr[a].cur /\ ~addr[a].reused
  /\ addr' = [addr EXCEPT ![a].reused = TRUE]
  /\ faults' = faults + 1
  /\ UNCHANGED <<attempt, ends, taskEnd, proc, conv, wst, bell, seen, cur, msgs, lastAck, flag, acct,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>

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

\* The operator's `run.py steer --by operator` from a terminal (9.8): a second run.py, concurrent with the Manager's.
OperatorSteers ==
  /\ ALLOW_OPERATOR /\ dpc["op"] = "idle" /\ LockFree /\ opSteers < 1 /\ SteerAllowed
  /\ msgs' = Append(msgs, NewMail("steer", attempt, 0))
  /\ dpc' = [dpc EXCEPT !["op"] = "decide"]
  /\ dmsg' = [dmsg EXCEPT !["op"] = Len(msgs) + 1]
  /\ opSteers' = opSteers + 1
  /\ UNCHANGED <<attempt, ends, taskEnd, proc, conv, wst, bell, seen, cur, addr, lastAck, flag, acct, faults,
                 dsess, mgrSteers, stray, resumeOverProc, overflow>>

\* record retries a pending delivery (5, record_in_progress: "Retry pending deliveries").
RecordRetries(i) ==
  /\ dpc["mgr"] = "idle" /\ LockFree /\ taskEnd = "no"
  /\ i \in Ids /\ IsMail(i) /\ msgs[i].st = "pending"
  /\ dpc' = [dpc EXCEPT !["mgr"] = "decide"]
  /\ dmsg' = [dmsg EXCEPT !["mgr"] = i]
  /\ UNCHANGED <<attempt, ends, taskEnd, proc, conv, wst, bell, seen, cur, addr, msgs, lastAck, flag, acct, faults,
                 dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>

\* record: a Rung row with no ack within pending_minutes goes back to pending; the next deliver skips
\* the socket for it (4.2 step 2, T8b). FIX: a Delivered row too.
RecordTimesOut(i) ==
  /\ dpc["mgr"] = "idle" /\ taskEnd = "no"
  /\ i \in Ids /\ IsMail(i)
  /\ msgs[i].st = "rung" \/ (FIX_DELIVERED_TIMES_OUT /\ msgs[i].st = "delivered")
  /\ msgs' = [msgs EXCEPT ![i].st = "pending", ![i].sockF = (@ \/ msgs[i].via = "socket")]
  /\ UNCHANGED <<attempt, ends, taskEnd, proc, conv, wst, bell, seen, cur, addr, lastAck, flag, acct, faults,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>

\* record files DIED for a worker whose turn is over (or with no pid) and no task row, unless an open
\* blocking ask stops it (5, record_in_progress; 4.7). DIED also stands for stuck and a ghost end.
RecordFilesDied ==
  /\ dpc["mgr"] = "idle" /\ LockFree /\ taskEnd = "no" /\ ends[attempt] = "none"
  /\ proc[cur[attempt]] \in {"idle", "none"}
  /\ ~AskOpenForRecord(attempt)
  /\ ends' = [ends EXCEPT ![attempt] = "DIED"]
  /\ msgs' = CarryIf(msgs, attempt)
  /\ UNCHANGED <<attempt, taskEnd, proc, conv, wst, bell, seen, cur, addr, lastAck, flag, acct, faults,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>

\* record sees a failed row: the profiles spec's handling applies (4.7, account row); read as an end row.
RecordFilesFailed ==
  /\ dpc["mgr"] = "idle" /\ LockFree /\ taskEnd = "no" /\ ends[attempt] = "none"
  /\ proc[cur[attempt]] = "failed"
  /\ ends' = [ends EXCEPT ![attempt] = "FAILED"]
  /\ msgs' = CarryIf(msgs, attempt)
  /\ UNCHANGED <<attempt, taskEnd, proc, conv, wst, bell, seen, cur, addr, lastAck, flag, acct, faults,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>

\* run.py launch of the next attempt: refuses while a session of the attempt is busy; stops the idle
\* ones (stopped-idle). A fresh session; its SessionStart hook checks in.
Launch ==
  LET a == attempt  n == attempt + 1 IN
  /\ dpc["mgr"] = "idle" /\ LockFree /\ taskEnd = "no"
  /\ ends[a] # "none" /\ a < MaxAttempts
  /\ \A s \in SessOf(a) : proc[s] # "busy"
  /\ \E ci \in CheckinChoices :
       /\ proc' = [StopSet(proc, SessOf(a)) EXCEPT ![Orig(n)] = "busy"]
       /\ addr' = AddrStart(AddrStop(addr, SessOf(a)), Orig(n), ci)
       /\ faults' = IF ci THEN faults ELSE faults + 1
  /\ bell' = [s \in Sids |-> IF s \in SessOf(a) THEN FALSE ELSE bell[s]]
  /\ seen' = [s \in Sids |-> IF s \in SessOf(a) THEN {} ELSE seen[s]]
  /\ attempt' = n
  /\ msgs' = CarryIf(msgs, a)
  /\ UNCHANGED <<ends, taskEnd, conv, wst, cur, lastAck, flag, acct,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>

\* run.py close after a report (PASS): stops the task's live sessions; marks open asks and unacked
\* steers of the attempt Carried (5, stop/close/abandon).
Close ==
  /\ dpc["mgr"] = "idle" /\ LockFree /\ taskEnd = "no" /\ ends[attempt] = "report"
  /\ proc' = StopSet(proc, Sids)
  /\ addr' = AddrStop(addr, Sids)
  /\ bell' = [s \in Sids |-> FALSE]
  /\ seen' = [s \in Sids |-> {}]
  /\ taskEnd' = "closed"
  /\ msgs' = CarryAtt(msgs, attempt)
  /\ UNCHANGED <<attempt, ends, conv, wst, cur, lastAck, flag, acct, faults,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>

\* run.py abandon after an end row.
Abandon ==
  /\ dpc["mgr"] = "idle" /\ LockFree /\ taskEnd = "no" /\ ends[attempt] # "none"
  /\ proc' = StopSet(proc, Sids)
  /\ addr' = AddrStop(addr, Sids)
  /\ bell' = [s \in Sids |-> FALSE]
  /\ seen' = [s \in Sids |-> {}]
  /\ taskEnd' = "abandoned"
  /\ msgs' = CarryAtt(msgs, attempt)
  /\ UNCHANGED <<attempt, ends, conv, wst, cur, lastAck, flag, acct, faults,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>

\* run.py stop of an attempt in progress (a pause or a recovery): STOPPED row; Carried.
ManagerStops ==
  /\ MANAGER_STOPS /\ dpc["mgr"] = "idle" /\ LockFree /\ taskEnd = "no" /\ ends[attempt] = "none"
  /\ proc' = StopSet(proc, SessOf(attempt))
  /\ addr' = AddrStop(addr, SessOf(attempt))
  /\ bell' = [s \in Sids |-> IF s \in SessOf(attempt) THEN FALSE ELSE bell[s]]
  /\ seen' = [s \in Sids |-> IF s \in SessOf(attempt) THEN {} ELSE seen[s]]
  /\ ends' = [ends EXCEPT ![attempt] = "STOPPED"]
  /\ msgs' = CarryAtt(msgs, attempt)
  /\ UNCHANGED <<attempt, taskEnd, conv, wst, cur, lastAck, flag, acct, faults,
                 dpc, dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>

\* ---------------------------------------------------------------- deliver(run, task, row), 4.2

\* Step 1: the task's live worker session for the current attempt (FIX: for the row's own attempt).
TargetAtt(d) == IF FIX_DELIVER_OWN_ATTEMPT THEN msgs[dmsg[d]].att ELSE attempt
Target(d) == cur[TargetAtt(d)]
\* Step 2's guard: the process is alive (pid set); with the check, the .addr session_id equals the
\* agents row's sessionId and the .addr file is newer than the row's last start.
SocketUsable(d) ==
  LET ta == TargetAtt(d)  t == Target(d) IN
  /\ PHASE2 /\ ~msgs[dmsg[d]].sockF /\ Alive(t) /\ addr[ta].sid # NoSid
  /\ DESIGN_SID_CHECK => (addr[ta].sid = t /\ addr[ta].fresh)

DeliverDecide(d) ==
  LET i == dmsg[d]  ta == TargetAtt(d)  t == Target(d)  ad == addr[ta] IN
  /\ dpc[d] = "decide"
  /\ IF msgs[i].st # "pending" THEN
        \* acked (a checkpoint read it) or carried meanwhile: nothing to deliver
        /\ dpc' = [dpc EXCEPT ![d] = "idle"]
        /\ UNCHANGED <<msgs, flag, bell, seen, proc, addr, dsess, stray, faults>>
     ELSE IF FIX_DELIVER_OWN_ATTEMPT /\ AttemptEnded(msgs[i].att) THEN
        /\ msgs' = [msgs EXCEPT ![i].st = "carried"]
        /\ dpc' = [dpc EXCEPT ![d] = "idle"]
        /\ UNCHANGED <<flag, bell, seen, proc, addr, dsess, stray, faults>>
     ELSE IF SocketUsable(d) /\ ad.cur THEN
        \* step 2: the post reaches the process that checked in; it may hold the message
        \E held \in HoldChoices :
          /\ msgs' = [msgs EXCEPT ![i].st = "rung", ![i].via = "socket"]
          /\ bell' = IF held THEN bell ELSE [bell EXCEPT ![ad.sid] = TRUE]
          /\ stray' = IF held THEN stray ELSE stray \cup StrayOf({i}, ad.sid)
          /\ faults' = IF held THEN faults + 1 ELSE faults
          /\ dpc' = [dpc EXCEPT ![d] = "idle"]
          /\ UNCHANGED <<flag, seen, proc, addr, dsess>>
     ELSE IF SocketUsable(d) /\ ad.reused THEN
        \* step 2: the post "succeeds" into the process that now owns the old socket path
        /\ msgs' = [msgs EXCEPT ![i].st = "rung", ![i].via = "socket"]
        /\ stray' = stray \cup {"otherProcess"}
        /\ dpc' = [dpc EXCEPT ![d] = "idle"]
        /\ UNCHANGED <<flag, bell, seen, proc, addr, dsess, faults>>
     ELSE IF SocketUsable(d) THEN
        \* step 2: ECONNREFUSED; deliver-fallback to step 3 or 4
        /\ msgs' = [msgs EXCEPT ![i].sockF = TRUE]
        /\ UNCHANGED <<dpc, flag, bell, seen, proc, addr, dsess, stray, faults>>
     ELSE IF proc[t] = "busy" THEN
        \* step 4: touch the flag; the PostToolUse hook shows the pointer at the next tool call (Rung)
        /\ msgs' = [msgs EXCEPT ![i].st = "rung", ![i].via = "hook"]
        /\ flag' = flag \cup {i}
        /\ dpc' = [dpc EXCEPT ![d] = "idle"]
        /\ UNCHANGED <<bell, seen, proc, addr, dsess, stray, faults>>
     ELSE
        \* step 3: idle, waiting or parked: `claude stop` when a process is alive, wait until the row
        \* shows no process; the resume is the next step
        /\ proc' = IF Alive(t) THEN [proc EXCEPT ![t] = "none"] ELSE proc
        /\ bell' = [bell EXCEPT ![t] = FALSE]
        /\ seen' = [seen EXCEPT ![t] = {}]
        /\ addr' = AddrStop(addr, {t})
        /\ dpc' = [dpc EXCEPT ![d] = "resume"]
        /\ dsess' = [dsess EXCEPT ![d] = t]
        /\ UNCHANGED <<msgs, flag, stray, faults>>
  /\ UNCHANGED <<attempt, ends, taskEnd, conv, wst, cur, lastAck, acct, dmsg, mgrSteers, opSteers,
                 resumeOverProc, overflow>>

\* Step 3, second half: CLAUDE_CONFIG_DIR=<profile> claude --bg --resume <sessionId> "<doorbell>".
DeliverResume(d) ==
  LET i == dmsg[d]  t == dsess[d]  a == AttOf[t]  c == CopyOf(a)
      mark(newSt) == IF msgs[i].st = "pending" THEN [msgs EXCEPT ![i].st = newSt, ![i].via = "resume"] ELSE msgs
  IN
  /\ dpc[d] = "resume"
  /\ resumeOverProc' = (resumeOverProc \/ Alive(t))
  /\ IF conv[t] = "lost" THEN
        \* the resume errors (no transcript): only a failed resume files DIED; the open ask is Carried (4.7)
        /\ ends' = IF a = attempt /\ ends[a] = "none" /\ taskEnd = "no" THEN [ends EXCEPT ![a] = "DIED"] ELSE ends
        /\ msgs' = CarryAtt(msgs, a)
        /\ dpc' = [dpc EXCEPT ![d] = "idle"]
        /\ UNCHANGED <<proc, wst, bell, addr, faults, stray, overflow>>
     ELSE IF Alive(t) /\ proc[c] # "unborn" THEN
        \* a second copy for one attempt: not tracked (TypeOK fails)
        /\ overflow' = TRUE
        /\ dpc' = [dpc EXCEPT ![d] = "idle"]
        /\ UNCHANGED <<ends, msgs, proc, wst, bell, addr, faults, stray>>
     ELSE IF Alive(t) THEN
        \* the session is still running: the CLI starts a copy and prints a note: line (#12)
        \E ci \in CheckinChoices :
          /\ proc' = [proc EXCEPT ![c] = "busy"]
          /\ wst' = [wst EXCEPT ![c] = wst[t]]
          /\ bell' = [bell EXCEPT ![c] = TRUE]
          /\ addr' = AddrStart(addr, c, ci)
          /\ faults' = IF ci THEN faults ELSE faults + 1
          /\ stray' = stray \cup StrayOf({i}, c)
          /\ msgs' = mark("copied")
          /\ dpc' = [dpc EXCEPT ![d] = "settle"]
          /\ UNCHANGED <<ends, overflow>>
     ELSE IF acct = "failed" THEN
        \* the resume starts and the session fails at once (4.7, account row)
        /\ proc' = [proc EXCEPT ![t] = "failed"]
        /\ msgs' = mark("delivered")
        /\ dpc' = [dpc EXCEPT ![d] = "idle"]
        /\ UNCHANGED <<ends, wst, bell, addr, faults, stray, overflow>>
     ELSE
        \* the session continues in place with the doorbell as its prompt (Delivered)
        \E ci \in CheckinChoices :
          /\ proc' = [proc EXCEPT ![t] = "busy"]
          /\ bell' = [bell EXCEPT ![t] = TRUE]
          /\ addr' = AddrStart(addr, t, ci)
          /\ faults' = IF ci THEN faults ELSE faults + 1
          /\ stray' = stray \cup StrayOf({i}, t)
          /\ msgs' = mark("delivered")
          /\ dpc' = [dpc EXCEPT ![d] = "idle"]
          /\ UNCHANGED <<ends, wst, overflow>>
  /\ UNCHANGED <<attempt, taskEnd, conv, seen, cur, lastAck, flag, acct, dmsg, dsess, mgrSteers, opSteers>>

\* After a note: line: record the copy's session id, stop the original, print deliver-copy (4.2, T10).
DeliverSettle(d) ==
  LET i == dmsg[d]  t == dsess[d]  a == AttOf[t] IN
  /\ dpc[d] = "settle"
  /\ proc' = IF Alive(t) THEN [proc EXCEPT ![t] = "none"] ELSE proc
  /\ bell' = [bell EXCEPT ![t] = FALSE]
  /\ seen' = [seen EXCEPT ![t] = {}]
  /\ addr' = AddrStop(addr, {t})
  /\ cur' = [cur EXCEPT ![a] = CopyOf(a)]
  /\ msgs' = IF msgs[i].st = "copied" THEN [msgs EXCEPT ![i].st = "delivered"] ELSE msgs
  /\ dpc' = [dpc EXCEPT ![d] = "idle"]
  /\ UNCHANGED <<attempt, ends, taskEnd, conv, wst, lastAck, flag, acct, faults,
                 dmsg, dsess, mgrSteers, opSteers, stray, resumeOverProc, overflow>>

\* ---------------------------------------------------------------- next

\* The end states: the task is closed or abandoned and no deliver runs.
Finished ==
  /\ taskEnd # "no"
  /\ \A d \in Deliverers : dpc[d] = "idle"
  /\ UNCHANGED vars

Next ==
  \/ \E s \in Sids :
       \/ WorkerAsks(s) \/ WorkerReadsInbox(s) \/ WorkerAcks(s) \/ WorkerChecksReport(s) \/ WorkerReports(s)
       \/ Die(s) \/ SupervisorStops(s)
  \/ \E k \in Ids : Answer(k)
  \/ ManagerSteers \/ OperatorSteers
  \/ \E i \in Ids : RecordRetries(i) \/ RecordTimesOut(i)
  \/ RecordFilesDied \/ RecordFilesFailed
  \/ \E d \in Deliverers : DeliverDecide(d) \/ DeliverResume(d) \/ DeliverSettle(d)
  \/ Launch \/ Close \/ Abandon \/ ManagerStops
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

\* Liveness (live.cfg, with FairSpec): every steer, and every answer, is eventually Acked or Carried.
SteersSettle ==
  \A i \in 1..MaxMsgs : (i \in Ids /\ msgs[i].kind = "steer") ~> (i \in Ids /\ Settled(i))
AnswersSettle ==
  \A i \in 1..MaxMsgs : (i \in Ids /\ msgs[i].kind = "answer") ~> (i \in Ids /\ Settled(i))

=============================================================================
