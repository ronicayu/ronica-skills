# The mailbox model

`Mailbox.tla` models the message design of the ADR "How the Manager and its workers talk across Claude profiles": `ronica-skills-adr` `docs/plans/2026-11-09-agentic-team-channel-adr.md` (status proposed, 2026-11-09). It covers sections 1, 4.1 to 4.8, 5 and "Live check results". "L<n>" below is a line of that file as read on 2026-11-09.

Round 2 (2026-11-09) maps the model to the code: `scripts/run.py` and `scripts/mailbox.py` at commit 3330fc7 (branch agentic-team-messaging), run on the Claude CLI 2.1.319. Line numbers in the round-2 sections are of those two files at that commit (`git show 3330fc7:plugins/agentic-team/scripts/run.py`). See "Round 2: the code at 3330fc7" below. Keep them current when the code moves, as `../NOTES.md` does for `Lifecycle.tla`.

The build ships Phase 1 and Phase 2 together: socket first, resume as the fallback, and the hook for a busy worker (`PHASE2 = TRUE`). With every `FIX_*` FALSE and every round-2 switch FALSE, the model is the ADR as written. Each `FIX_*` is one change that the model suspects the ADR needs. Each one names an ADR line below.

Status: round 1 ran on 2026-11-09. With every `FIX_*` on, every rule held (`fixed.cfg`: 1,038,611 distinct states; `supersede.cfg`: 18,819,492). Not every round-1 prediction held: `phase1` also broke rules 2 and 4b, which the table below predicted to hold. Round 2 ran on 2026-11-09: every round-2 prediction held, and every round-1 config gave the same result with the same state count ("Round 2: results"). Round 3 (the fixes of `msg-fixes-r3.md`) is written, and SANY parses it. TLC has not run it: "Round 3: predictions" comes before any run.

## What the model holds

- One task, up to `MaxAttempts` attempts (1, 2 or 3). Each attempt has an original session (`w1`, `w2`, `w3`) and room for one resume copy (`c1`, `c2`, `c3`). With `IMPL_RESUME_COPIES` a copy takes the attempt's other slot, which may be the original's once that has no process. `cur[a]` is the session id that run.py recorded for the attempt.
- Per session:
  - `proc` is the process: `unborn`, `none`, `busy`, `idle` or `failed`. `none` means no pid: parked, stopped, dead or a ghost. `idle` means the turn is over and the process is alive.
  - `conv` is the conversation: `kept` or `lost`.
  - `wst` is where the worker is in its brief: `work`, `wait` (a blocking ask is filed and the turn ended), `checked` (check-report passed) or `done` (report filed).
  - `bell` is a doorbell in the session that the worker has not read yet.
  - `seen` holds the rows that its last `inbox` printed and that are not acked yet.
- `msgs` are the message rows in row order: `ask`, `answer` and `steer`. Each row has `att`, `re` (the ask that an answer answers) and `st`. For an answer or a steer, `st` is `pending`, `rung`, `delivered`, `copied`, `acked`, `carried` or `superseded`. Each row also has `via` and `sockF` (the next deliver skips the socket).
  - An ack is not a row of its own. It marks the rows it covers `acked` and moves `lastAck[a]`, the inbox cursor. The ack rows come after every row filed so far.
- `addr[a]` is the `.addr` checkin file. It has `sid`, `cur` (the socket path still belongs to the process that wrote it), `reused` (another process now owns that path) and `fresh` (the file is newer than the start of `sid`'s current process).
- `flag` is the hook flag: the rows that run.py touched it for. It is one file per task (L175).
- `ends[a]`: the end row of attempt `a`. `taskEnd`: the task is closed or abandoned. `acct`: the account. `faults`: the fault budget used so far.
- `dpc`, `dmsg`, `dsess`: where each deliverer is in `deliver`. The deliverers are the Manager's run.py (`mgr`) and the operator's terminal run.py (`op`).
- History variables for rules: `stray` (where doorbells went that should not have), `resumeOverProc` and `overflow`.
- Round 2: each answer and steer row also has `tries` (deliver calls that count toward the cap). `untracked`: the copies that run.py did not record. `metaGone`: the attempts whose `mailbox` meta run.py has dropped. `bad`: history for the round-2 rules (`endOverBusy`, `reportOverSteer`, `settledShownOpen`, `carriedLost`), kept only with `TRACK_NEW_RULES`.

## Actions and the ADR text they model

| Action | ADR |
|---|---|
| `WorkerAsks` | L149 `mailbox.py ask`; L16, L341 (end the turn, "Waiting for answer to ask #N"); L276 (cap: `ASKS` = 0 or 1 here) |
| `WorkerReadsInbox` | L150 `inbox` (this task and attempt, rows after the last ack); L345; triggers: a doorbell (L12, L13), the hook pointer (L14, L175), a checkpoint (L14, L348) |
| `WorkerAcks` | L151 `ack`; L303 (two answers: ack the latest); L175 (record removes the flag on an ack; done here at the ack, before the Manager acts on record's next hint) |
| `WorkerChecksReport`, `WorkerReports` | L310, T12 L409: `check-report` refuses while a steer has no ack; then the result row (the attempt's end row) |
| `Die` | L301 (the worker dies; the conversation is kept or lost) |
| `SupervisorStops` | #15 L83, L302 (an idle session with no terminal is stopped after about 1 h; no pid, conversation kept) |
| `AccountFails` | L309 (from then on, a resume starts and fails at once) |
| `PidReused` | L306 (a pid is reused; `/tmp/cc-socks/<pid>.sock` belongs to another process) |
| `Answer` | L158, L280, T6 L400 (refuses an ended attempt; refuses a second answer without `--supersede`); runs `deliver` in the same command |
| `ManagerSteers` | L159, T7 L401 (refuses "a task with no live worker in its current attempt"); runs `deliver` |
| `OperatorSteers` | 9.8 L436 (`run.py steer --by operator` from a terminal): a second run.py, concurrent with the Manager's |
| `RecordRetries` | L163, L325 ("Retry pending deliveries") |
| `RecordTimesOut` | L166, L282, T8b L403 (Rung with no ack within `pending_minutes` → pending; the next deliver skips the socket) |
| `RecordFilesDied` | L325, L277, L301, T3 L397, T8c L404 (DIED/stuck/ghost end for a turn that is over with no task row; skipped while an open blocking ask exists) |
| `RecordFilesFailed` | L309 (a failed row; the profiles spec's handling, read as an end row) |
| `DeliverDecide` | L165 step 1 (the live session of the *current* attempt); L166 step 2 (the socket post and its guard; Rung); L307 (ECONNREFUSED → fallback; a held post); L168 step 4 (busy, no socket: touch the flag → Rung, L285); L167 step 3, first half (`claude stop` when alive, wait until the row shows no process) |
| `DeliverResume` | L167 step 3, second half (`--bg --resume`); #12 L80 and L284 (a copy and a `note:` line); L301 (no transcript → DIED, the open ask Carried); L309 (account) |
| `DeliverSettle` | L167, L284, T10 L407 (record the copy's id, stop the original, `deliver-copy`) |
| `Launch` | Lifecycle `cmd_launch`: refuses a busy row of the attempt, stops idle rows; L324 (a fresh session; the SessionStart checkin, L148) |
| `Close`, `Abandon`, `ManagerStops` | L329 (stop, close and abandon mark open asks and unacked steers of the attempt Carried); close stops the live sessions (Lifecycle `stop_live`) |
| `Finished` | the end state: the task is closed or abandoned, and no deliver runs |

## Merged values, and why

- `proc = none` covers a parked process (supervisor stop or `claude stop`), a dead one and a ghost. L301 says that the row shape cannot tell them apart, and record and deliver treat them the same: step 3 resumes all of them.
- `ends = DIED` also stands for stuck (`file_stuck`) and a ghost end. Rule 2 names all three, and each ends the attempt with a Manager row.
- Asks: at most one per attempt, and always blocking. A non-blocking ask (9.5 L433) behaves like a steer to a busy worker, so it adds no new branch.
- Time is not modelled. `pending_minutes` passes whenever `RecordTimesOut` runs. The supervisor's hour passes whenever `SupervisorStops` runs. Due times and `ask-due` are left out: they print hints and change no state.
- The `.addr` timestamp comparison (L166) is the boolean `fresh`. A checkin at process start makes it TRUE; a start without the checkin makes it FALSE. So the model cannot find a flaw in the clock comparison itself (see "Ambiguous or suspect", item 13).
- "Socket delivery fails twice in a run, so it is turned off" (L307) is approximated per row by `sockF`.
- Delivery state lives in meta (L140). `via: hook` is set when the flag is touched (L285 puts the row in Rung then), not "when the worker acks it" (L168).

## Switches (round 1)

| Switch | What it does | ADR text it questions |
|---|---|---|
| `PHASE2` | TRUE: deliver step 2 (socket) is on, `doorbell = "socket"`; FALSE: `doorbell = "resume"` | L331 |
| `DESIGN_SID_CHECK` | step 2 posts only when the `.addr` session_id matches the agents row and the file is fresh | L166, L306 (TRUE is the ADR; FALSE is the sensitivity check) |
| `MANAGER_STOPS` | the Manager may `run.py stop` an attempt at any time (a free move: it hides dead ends from the deadlock check) | L329 |
| `ALLOW_DIE`, `ALLOW_SUP_STOP`, `ALLOW_ACCOUNT_FAIL`, `ALLOW_PID_REUSE`, `ALLOW_NO_CHECKIN`, `ALLOW_SOCKET_HOLD` | environment faults; each spends one unit of `MaxFaults` | L301, L302, L309, L306, L90 (#21b) and L417 to L420 (L1, L4), L307 and #7 L75 |
| `ALLOW_OPERATOR` | the operator's terminal steer, concurrent with the Manager | L436 |
| `ALLOW_SUPERSEDE` | `run answer --supersede` | L303 |
| `FIX_ASK_OPEN_UNTIL_ACK` | record treats an ask as open until its answer is acked | L325 "an open blocking ask" (as written: an ask with no answer row) |
| `FIX_CARRY_ON_EVERY_END` | report, DIED, a failed row and launch also mark Carried | L329 lists only stop, close and abandon; L287 and L266 to L269 say any attempt end |
| `FIX_DELIVER_OWN_ATTEMPT` | deliver targets the row's attempt and carries a row whose attempt has ended | L165 "the live worker session for the current attempt", with L325 "retry pending deliveries" |
| `FIX_FLAG_PER_ATTEMPT` | the flag is keyed by attempt | L175 `task-<id>.flag`, removed only on an ack |
| `FIX_DELIVERED_TIMES_OUT` | Delivered goes back to pending with no ack, like Rung | L263 to L264: only Rung → Pending |
| `FIX_SUPERSEDE_SETTLES` | an older answer is settled when the newer one is acked | L303 (the worker acks only the latest) |
| `FIX_INBOX_UNACKED` | inbox prints every unacked row | L150 "rows ... that come after the last ack" |
| `FIX_STEER_REFUSES_ENDED` | steer refuses after the attempt's report | L159 "no live worker" (a reported worker's process can still be live) |
| `FIX_REPORT_CHECK_ATOMIC` | the report command itself refuses while a steer is unacked | L310, T12 L409 (check-report is a separate step) |
| `FIX_DELIVER_LOCK` | one run.py lock per task: a deliver, and record's DIED / failed rows, launch, close, abandon and stop, run only when no deliver runs | L167 "wait until the row shows no process" is a check, then an act; L436 allows a second run.py; L329 stop/close/abandon are not serialised with it |

## Rules (round 1)

| Rule | In words | Source |
|---|---|---|
| `DoorbellOnlyToOwnAttempt` | 1. No answer or steer is delivered to a session of another attempt: no doorbell for a row (socket post, resume prompt, hook pointer) reaches a session of another attempt or another process. | L291; L306 |
| `NoDoorbellAfterAttemptEnds` | 1b. No doorbell reaches a session after its attempt has ended (a report, DIED, a stop, or a later attempt). | L305 "run steer and run answer refuse an ended attempt" |
| `AskerNeverFiledDead` | 2. An attempt whose worker waits on a blocking ask is never filed DIED or stuck while its conversation exists. | L292; L301 |
| `OneLiveSessionPerAttempt` | 3. At most one live session per attempt; a resume copy is settled before the next deliver starts. | L293 |
| `SteersSettledOnceAttemptOver` | 4. Every steer ends Acked or Carried: once the Manager has moved past its attempt, each steer of it is Acked or Carried. | L294; L287 |
| `AnswersSettledOnceAttemptOver` | 4b. An answer is never lost: the same rule for answers (a superseded answer counts as settled). | L287; L303 |
| `NoResumeOverLiveProcess` | 5. deliver never runs `--bg --resume` while the session still has a process. | L295 |
| `ClosedTaskHasNoUnreadSteer` | 6. A task that closes after its report has no steer of that attempt that the worker did not read. | L310; L271 (Carried means "the next brief pastes it", and a closed task has no next brief) |
| `InboxShowsEveryUnreadMessage` | 7. The inbox shows every answer and steer of a running attempt that the worker has not acked. An answer that a newer answer to the same ask replaced is the one exception. | L150; L310 |
| `NoWorkerLeftAtEnd` | 8. When the task is over and no deliver runs, no worker session of the task has a process. | Lifecycle `NoSessionLeftAtEnd` |
| `TypeOK` | the bounds hold; no second copy is needed (`overflow`) | — |
| no deadlock | every state has a step out; `Finished` is the end | — |
| `SteersSettle`, `AnswersSettle` (live.cfg) | every steer, and every answer, is eventually Acked or Carried (`FairSpec`) | L294 |

Two readings to check:

- **Rule 1 reads "delivered" as "the doorbell reaches".** `inbox` prints only the rows of the worker's own task and attempt (L150). So a session of another attempt can never *read* the row: in the model, reading the row is safe by construction. The ADR also calls a stray doorbell harmless (L306). But a stray doorbell starts a turn, interrupts a step (resume) or repeats a pointer at every tool call (the hook). That is the cost the rule watches. If you read rule 1 as "reads the row", it holds by construction and the model cannot check it.
- **Rule 4 has two forms.** The main form is the invariant `SteersSettledOnceAttemptOver`, which every config except the live ones runs. The liveness form `SteersSettle` runs only in `live.cfg` and `live-fixed.cfg`, under `FairSpec`. FairSpec gives weak fairness to the worker's reads, acks and reports, to every deliver step, to the first answer of each ask, to record's retries, timeouts, DIED and failed rows, and to launch, close and abandon. The environment, the steers, a supersede and `run.py stop` get no fairness. It is not checked whether the statechart runner handles a SPECIFICATION other than `Spec` and temporal properties. Confirm that before you trust the live configs, or run them with plain TLC.

## What the model leaves out, and where it is blind

- **Blind spots:**
  - Rules 3 and 5 hold by construction without `ALLOW_OPERATOR`: one run.py is sequential, and the operator's terminal is the only source of a resume copy. Only `operator.cfg`, `need-lock.cfg` and `fixed-operator.cfg` check them.
  - Checkpoint reads (L14, L348) let a busy worker read new rows at any time, without a doorbell. So for a busy worker, a lost doorbell shows only as a timeout loop, not as a stuck row.
  - The freshness check (L166) holds by construction (see "Merged values").
- **Left out:**
  - Verifier sessions: they get no messages (L351, 9.7).
  - Forged rows and the `mailbox` meta id list (L317, T14).
  - The SCOPE print and the steer limits (L316).
  - Decisions and `ask-due` (L278 to L279; they change no delivery state).
  - `--interrupt` (L159): it forces step 3 on a busy worker.
  - The Manager's own doorbell (`notify`, `manager.addr`, L152, L161) and `wait`: they only wake the Manager, which then runs record.
  - The asks cap above one, and non-blocking asks.
  - A "claude stop that fails".
  - A third session per attempt.
  - The profiles spec beyond "a failed row ends the attempt".
- **Worker model:** the worker acts only on rows that `inbox` printed (L315, L345; live check L6b L58 supports it). So "a worker never acts on a message it did not read through inbox" is a modelling assumption, not a checked rule.
- **A woken session of an ended attempt** (a stray doorbell, a late steer) ends its turn again when inbox prints nothing for it. When inbox does print something, it acks and works on, and it can file a late report that changes no end row. `Launch` refuses while such a session is busy, as `cmd_launch` refuses a busy live row.

## Round 1: predictions (written before any run)

"Breaks" names the shortest path I expect, in actions.

| Config | Expect |
|---|---|
| `adr-nofault` (ADR as written, no fault, 2 attempts) | **Breaks:** <br>• Rule 1b in 4 steps: `WorkerChecksReport`, `WorkerReports`, `ManagerSteers` (the reported worker's process is still live, L159), `DeliverDecide` (a post into the reported worker). <br>• Rule 2 in 4 steps: `WorkerAsks`, `Answer`, `DeliverDecide` (the post lands; the worker is still idle), `RecordFilesDied` (the ask has an answer row, so it is not "open", L325). <br>• Rule 4 in 5 steps: report, steer, post, `Launch` (launch does not carry, L329). <br>• Rule 4b in 5 steps: the rule-2 path, then `Launch`. <br>• Rule 6 in 5 steps: `WorkerChecksReport`, `ManagerSteers`, `WorkerReports` (no doorbell yet), `DeliverDecide`, `Close` (the steer is Carried, never read). <br>• Rule 7 in 6 steps: `WorkerAsks`, `Answer`, `DeliverDecide`, `WorkerReadsInbox`, `ManagerSteers`, `WorkerAcks` (the steer's row is before the ack: never printed again). <br>• Rule 1 in about 8 steps, by one of two paths. (a) A pending steer of attempt 1 is retried into attempt 2's socket (L165). (b) A busy worker's steer goes to the hook after a timed-out post; `ManagerStops` carries it but leaves the flag; attempt 2's worker sees the pointer (L175). <br>**Hold:** rules 3, 5 and 8, `TypeOK`, no deadlock. |
| `check` (ADR as written, environment on, 1 fault) | The same breaks as `adr-nofault`, with the same or shorter paths. A fault adds new ways to reach rule 2: a held post (`ALLOW_SOCKET_HOLD`), or a resumed waiter that dies after its answer row. Rule 1 does not break by `otherProcess` (the sid check holds). Rules 3, 5 and 8 and `TypeOK` hold. |
| `phase1` (doorbell = "resume") | **Breaks:** <br>• Rule 1 in 5 steps: steer to a busy worker → hook flag, `ManagerStops`, `Launch`, attempt 2 reads at a tool call. <br>• Rule 1b in 5 steps: report, steer, stop, resume of the reported worker. <br>• Rule 4. <br>• Rule 6 (via the hook path). <br>• Rule 7 in 7 steps. <br>**Holds:** rule 2. Without the socket, an answer always reaches a waiter by resume, which makes it busy at once, and record cannot run while run.py delivers. So rule 2 is a Phase 2 gap. Rule 4b also holds. |
| `operator` (Phase 1, the operator's terminal, 1 attempt) | **Breaks:** <br>• Rule 5 in about 7 steps: the worker asks; the operator steers, stops the idle worker and waits to resume; the Manager answers and also prepares a resume; the operator resumes; the Manager's resume finds a process and starts a copy. <br>• Rule 3 in about 9 steps: the operator's resume makes the copy, and the Manager starts its own steer while the operator still has to settle. <br>• Rule 8 and rule 1b in 5 steps: report, operator steer, operator stops the worker, the Manager closes, the operator resumes after the close. <br>• Rules 6 and 7 as in `phase1`. <br>**Holds:** `TypeOK` (one copy at most). |
| `fixed` (every FIX on, environment on, 1 fault) | **Every rule holds**; no deadlock. |
| `fixed-die`, `fixed-supstop`, `fixed-account`, `fixed-pid`, `fixed-hold` (2 faults, no `run.py stop`) | **Every rule holds; no deadlock.** A deadlock here would be a state that needs a manual stop. |
| `fixed-operator` | **Every rule holds**: the lock serialises delivers, and it also holds back stop, close, abandon, launch and record's end rows. Without that wider guard, rule 1b breaks in 5 steps: the worker asks; the operator steers, stops the idle worker and waits to resume; the Manager runs `run.py stop`; the operator resumes into a STOPPED attempt. That is why the lock covers those commands. |
| `regress-no-sid-check` (sensitivity check) | **Must break rule 1** (`otherProcess`) in about 10 steps: ask; supervisor stop; answer; resume without the checkin (the `.addr` file keeps the old pid); read and ack; the pid is reused; steer; the post goes to the reused socket. If it does not break, the model is blind to pid reuse. |
| `need-ask-open` | must break rule 2 (path as in `adr-nofault`) |
| `need-carry` (`ALLOW_DIE`) | must break rule 4: steer, post, the busy worker dies, `RecordFilesDied`, `Launch` before record retries |
| `need-own-attempt` | **Holds:** redundant once `FIX_CARRY_ON_EVERY_END` is on. It stays as belt and braces. |
| `need-flag` | must break rule 1 by the hook-flag path (5 to 8 steps, see `adr-nofault` (b)) |
| `need-delivered-timeout` (`ALLOW_DIE`, no `run.py stop`) | must **deadlock**: ask, answer, post, timeout, retry, stop and resume (Delivered), the resumed worker dies (conversation kept) before it reads. Nothing retries a Delivered row, record skips DIED (the ask is open), and steer refuses (no live process). |
| `need-inbox` | must break rule 7 (6 steps, as in `adr-nofault`) |
| `need-steer-ended` | must break rule 6: report, steer, the deliver carries it (own-attempt fix), close |
| `need-report-atomic` | must break rule 6: check, steer, report, deliver carries it, close |
| `need-lock` | must break rules 5 and 3 (as in `operator`) |
| `supersede` (every FIX on except `FIX_SUPERSEDE_SETTLES`, `ALLOW_SUPERSEDE`) | **Holds.** The cost (the superseded answer is redelivered until the attempt ends) breaks no rule. |
| `overview-ask` | Chart. Breaks rule 2 (4 steps) and rule 1b (a retry resumes the worker after the DIED). |
| `overview-steer` | Chart. Breaks rule 1b (steer after report) and rule 6. |
| `live` (ADR as written) | **`SteersSettle` breaks** as a lasso: the rule-7 path; the worker cannot report (check-report refuses on the unprinted steer); the steer cycles through rung (hook), timeout, pending and retry for ever. **`AnswersSettle` holds**: abandon carries it. |
| `live-fixed` | both hold |

A surprise means that the model or my reading is wrong. Find out which before going on.

## Round 1: state-space estimates (not measured)

| Config | Estimate |
|---|---|
| `overview-ask`, `overview-steer` | 100 to 400 states each (aim: under the chart's 500). If one goes above 500, set `MANAGER_STOPS` FALSE (already FALSE), then `PHASE2 = FALSE`. |
| `operator`, `fixed-operator`, `need-lock`, `regress-no-sid-check`, `live`, `live-fixed` (1 attempt) | 2k to 30k |
| `adr-nofault`, `phase1`, `need-*` (2 attempts, at most 1 fault), `supersede` | 10k to 100k |
| `check`, `fixed` (2 attempts, 6 fault kinds, 1 fault) | 50k to 500k: likely above the runner's 100,000 bound for reruns |
| `fixed-*` (2 attempts, 2 faults, one or three kinds) | 20k to 300k |

If a run goes past 100,000 distinct states, the runner lists the rules it did not check under "Rules not checked". Shrink in this order:

1. `MaxAttempts = 2` → 1 for configs whose predicted paths stay inside one attempt: `fixed-hold`, `fixed-supstop`, `fixed-pid`, `fixed-account`. Rules 1 (otherAttempt), 4 and 4b need 2 attempts. `adr-nofault`, `need-carry`, `need-flag` and `fixed` keep 2 attempts.
2. `MaxFaults` 2 → 1 in the `fixed-*` configs.
3. For `check.cfg` and `fixed.cfg`, split the six `ALLOW_*` faults over two configs.
4. Last: `ASKS = 0` or `MaxSteers = 0`. These remove whole rules, so avoid them.

## Round 2: the code at 3330fc7

### Actions and the code they model

`run.py` and `mailbox.py` at commit 3330fc7. "mb" marks a line of `mailbox.py`; every other line is of `run.py`.

| Action | Function | Lines |
|---|---|---|
| `WorkerAsks` | `cmd_ask`: the cap (`asks_cap` 919-927), the OPEN ask row, "End your turn now" | mb 269-292 |
| `WorkerReadsInbox` | `cmd_inbox`, `open_messages` (listed in the `mailbox` meta, no ack, not settled by a newer acked answer: `listed_ids`, `acked_ids`, `settled_ids`); the hook: `cmd_hook` with `--match` (this task and attempt), `flag_file` (per attempt), `worker_settings` (the PostToolUse and SessionStart hooks) | mb 295-318, mb 95-128, mb 233-245; 875-878, 952-965 |
| `WorkerAcks` | `cmd_ack` (one id at a time; refuses an id that is not open); record lowers the flag once nothing is unacked (`mailbox_events`) | mb 321-333; 2398-2399 |
| `WorkerChecksReport` | `cmd_check_report` with `unacked_steers_of` (refuses an unacked steer); with `IMPL_SALVAGE` the report file is written at this step (worker.md REPORT) | 4360-4399 |
| `WorkerReports` | `cmd_report`: the steer check and the task row under the task lock (`locked`, `lock_file`) | mb 336-351, mb 164-184; 885-887 |
| `Die`, `SupervisorStops`, `AccountFails`, `PidReused` | the environment, as the code reads it: `Session` (finished, live, ghost, stuck), `Run.sessions` (the stopped-sessions file), `socket_address` (the .addr session id and its age against `startedAt`), `registry_socket` | 499-544, 404-448, 2161-2176, 2143-2158 |
| `Answer` | `cmd_answer`: `refuse_unless_running`, the ask's attempt, `refuse_ended`, `--supersede`, `file_message`, `deliver` | 2466-2508, 2428-2434, 2448-2454 |
| `ManagerSteers`, `OperatorSteers` | `cmd_steer`: refuses an attempt with a task row, and a worker whose row is not live unless `Thread.holds`; `file_message`; `deliver`. Both run.py commands hold the task lock (`LOCKED`, `task_lock`) | 2511-2533; 4670-4685, 890-912 |
| `RecordRetries` | `mailbox_events`: a row with `via == "pending"` is delivered again at every record; `DELIVERIES_MAX` (steer-pending) | 2357, 2408-2423 |
| `RecordTimesOut` | `mailbox_events`: `via` socket or resume with no ack after `pending_minutes` goes back to pending (socket: `socket_failed`) | 2401-2407 |
| `RecordFilesDied` | `record_in_progress`: `holds` (2853-2864) returns before any end row (2929-2930); stuck (2934-2941, not modelled); salvage (`salvage` 2674-2694) or DIED (2949-2966); `carry_thread` | 2836-2966, 2318-2330 |
| `RecordFilesFailed` | no such branch in the code: a failed row is finished (`Session.finished`) and takes the salvage-or-DIED branch (`IMPL_DETAILS`) | 534 |
| `DeliverDecide` | `deliver`: the own-attempt check (carried), `worker_session`, the socket (`socket_address`, `post_line`, `socket_failed`), the hook (`touch_flag`; the row stays pending), step 3's stop (`stop_session`, `wait_for_exit`) | 2226-2272, 2130-2135, mb 189-205, 2191-2195, 2289-2294, 572-584, 2207-2215 |
| `DeliverResume` | `resume_with`: no transcript → `file_died`; `claude --bg --resume <sessionId> --settings <json> <doorbell>`; the copy check reads stdout only; in place: `forget_stopped`, `lower_flag` | 2275-2315, 2218-2223, 2179-2188, 2198-2204 |
| `DeliverSettle` | `resume_with` after a `note:` line on stdout: a `sessions` entry for the copy, `claude stop` of the original | 2303-2312 |
| `Launch` | `cmd_launch`: live rows and stopped-idle (1627-1641), the blocking-ask refusal (1642-1652), `render` → `carried_text` (1703), `carry_thread` (1755-1756), `write_ctx` (drops the attempt's old .addr, 936-949), the meta prune (1775-1782), `lower_flag` | 1571-1790, 2333-2354 |
| `Relaunch` | `cmd_launch` with `--attempt` after an abandon (1592-1593; 1782 unsets `abandoned`) | 1571-1790 |
| `Close` | `cmd_close` → `stop_live` (stops live rows it can tie to the task; a STOPPED row and `carry_thread` only for a live worker row) | 4183-4254, 4059-4079 |
| `Abandon` | `cmd_abandon`: stops live rows, ABANDONED rows, `drop_mailbox` (the whole `mailbox` meta and the inbox files); no `carry_thread` | 4328-4355, 2562-2574 |
| `ManagerStops` | `cmd_stop`: refuses an attempt with no live row; STOPPED, `carry_thread` | 4303-4325 |
| the brief (`BriefFlaws`) | `render` → `carried_text` → `Thread` (counts only answers and steers that the meta lists) | 2333-2354, 2077-2114 |

### Where the code departs from the model with every round-1 `FIX_*` on

The code implements every round-1 fix: `FIX_ASK_OPEN_UNTIL_ACK` (`Thread.blocking`), `FIX_CARRY_ON_EVERY_END` (`carry_thread` in launch, stop, record, `file_died`), `FIX_DELIVER_OWN_ATTEMPT` (2238-2243), `FIX_FLAG_PER_ATTEMPT` (`flag_file`, `--match`), `FIX_DELIVERED_TIMES_OUT` (2402), `FIX_SUPERSEDE_SETTLES` (`settled_ids`), `FIX_INBOX_UNACKED` (`open_messages`), `FIX_STEER_REFUSES_ENDED` (2525), `FIX_REPORT_CHECK_ATOMIC` (`cmd_report` under the lock), `FIX_DELIVER_LOCK` (`LOCKED`, record's per-task lock, the report's lock). Where it departs:

| # | The code | Effect | Switch |
|---|---|---|---|
| D1 | `resume_with` passes `--settings` (2295), so on CLI 2.1.319 every resume starts a copy, also of a session with no process. The `note:` line goes to stderr; the check reads stdout (2301-2303). The copy is not recorded, the original stays the attempt's session, `forget_stopped` drops it from the stopped file, the flag is lowered, the row reads delivered by resume. (Round 2 A.1, A.2) | an untracked live worker; record files DIED (or salvages) from the stopped original while the copy works; close and abandon leave the copy running; the next resume starts a second copy | `IMPL_RESUME_COPIES`, `IMPL_COPY_NOTE_MISSED`, `CLI_COPY_IN_WORKTREE` |
| D2 | Even when the note is seen, the copy's `sessions` entry carries the original's `sessionId` (2305). `resume_id` prefers the row's own id (2138-2140); once `claude agents` no longer lists the copy, a resume uses the original's id and forks the conversation from before the copy | a resume from a stale conversation | not modelled (round 2 A.2 already says "its full sessionId") |
| D3 | A flag touch leaves `via` pending (2271), every `deliver` call counts a try (2237), record redelivers every pending row at each record (2408-2417) and stops at 3 (2409-2413). `holds` counts pending rows (2864) (B1) | after two records the cap is spent; a worker that goes idle or dies unread is never resumed, and `holds` keeps record from filing DIED: a dead end, apart from the hint's `run.py stop` | `IMPL_HOOK_IS_A_TRY`, `IMPL_DELIVERY_CAP`, `IMPL_HOLDS` |
| D4 | record's `holds` counts unacked rows with `via` pending or socket only (2864); a row delivered by resume does not hold; salvage files the worker's report file (2949-2960) (B4) | a report is filed, and the task can close, over a steer that the worker never read | `IMPL_HOLDS`, `IMPL_SALVAGE`, `FIX_SALVAGE_REFUSES_UNACKED_STEER` |
| D5 | launch drops the meta of earlier attempts after it renders (1775-1782); abandon drops all of it (4346, 2562-2567); `carried_text` reads which answers and steers count from that meta (2339, 2087-2088) (B2) | attempt 3's brief shows attempt 1's settled ask as OPEN when attempt 2 had no message rows; after abandon and `launch --attempt`, the brief shows every ask OPEN and pastes no answer and no steer | `IMPL_PRUNE_META`, `ALLOW_RELAUNCH` |
| D6 | A failed row (an account that fails at resume) has no branch in record: it is finished (534) and goes to salvage-or-DIED, but `holds` returns first (2929). `Thread.blocking` holds while the answer has no ack, so record files nothing; `mailbox_events` resumes the failed session until the cap; the steer-pending hint names `run.py stop`, which refuses a row that is not live (4308-4310) | no hinted command leads out on a failed account while an answer waits for its ack (ADR item 12 asked this). `cmd_abandon` needs only `in_progress` (4331), so the Manager can still abandon by hand; the model's `Abandon` keeps the round-1 guard (an end row), so this shows as a deadlock, the Lifecycle model's "no dead end" convention. Not in the round-2 list; measured: `impl-r2-env1` deadlocks in 17 steps | `IMPL_DETAILS`, `IMPL_HOLDS`, `IMPL_LIVE_ROWS`; round 3: `FIX_FAILED_ENDS` |
| D7 | `cmd_steer` refuses a worker whose row is not live unless `Thread.holds` (2527); `cmd_stop` refuses a row that is not live (4309). An idle worker whose turn is over reads as finished (state done, 534); a parked asker (state blocked) is live | steer and stop act on fewer states than the ADR's "a process is alive"; a steer to a parked worker with an open ask is accepted with no process | `IMPL_LIVE_ROWS`; round 3: `FIX_STOP_OPEN_THREAD` |
| D8 | `holds` returns before the stuck check (2929-2930 before 2931-2941) | a worker on a permission prompt with an unacked message is never filed BLOCKED; deliver stops and resumes it instead (B6) | blind spot (no stuck state) |
| D9 | `socket_failed` is set when the address is missing or stale (2265), not only when a post fails | that row never uses the socket again, even after a fresh checkin: more resumes (at 3330fc7, more copies) | round 3: `IMPL_STALE_ADDR_FAILS` (FALSE in the impl and impl-r2 configs, as they were measured) |
| D10 | deliver posts only to a live row with a pid (2257); a finished row with a process is stopped and resumed | benign: such a worker has ended its turn after its report | not modelled |
| D11 | A report's thread is carried by the next record (2856-2859), not by the report; close carries only for a live worker row (4074-4078); abandon carries nothing (it drops the meta) | benign while record runs before close (the Lifecycle's verify step makes it so); the abandon part is D5 | `FIX_CARRY_ON_EVERY_END` stands for it |
| D12 | `carried_text` pastes the newest earlier attempt that has message rows (2336-2339), so with meta kept an ask that attempt 1 left open is pasted into attempt 2's brief and again into attempt 3's | a duplicate, not a loss; no rule names it | not a rule |
| D13 | A row with no `sessions` entry is tied to the task by its folder with attempt None (532-541) and counts for every attempt (`own_sessions` 587-591) | with `CLI_COPY_IN_WORKTREE`, run.py targets and stops the copy although no entry names it; a later attempt's launch refuses on it while it is busy | `CLI_COPY_IN_WORKTREE` |
| D14 | `cmd_report` waits for the task lock; the model's `WorkerReports` does not | the model is more permissive: safe for the safety rules | not modelled |
| D15 | `wait_for_exit` gives up after 20 reads and leaves the row pending (2291-2294), a try | a process that does not exit spends the cap in three records | round 3: `ALLOW_NO_EXIT`, `FIX_EXIT_TIMEOUT_NOT_A_TRY` |
| D16 | `resume_with` files DIED when `claude --resume` exits non-zero for any reason (2298-2300), not only for a missing transcript | a transient CLI error files DIED for a waiting asker | not modelled (no such fault) |
| D17 | `Thread.blocking` holds until the newest answer is acked; the round-1 fix holds until any answer is acked | differs only with `--supersede` | `IMPL_HOLDS` uses the code's |
| D18 | In the live run the copy did not rewrite the `.addr` file (msg-live-findings.md) | while the copy is untracked the sid check rejects its socket anyway | the model lets a copy check in or not |

B3 (the session rows are cached across tasks in one record) and B7 (`manager.addr`) are under "Round 2: blind spots". B5 (pid reuse) is `CLI_WAKE_KEEPS_START` with `FIX_ADDR_AFTER_WAKE` and `FIX_SOCKET_PID_MATCH`.

### Round-2 switches

Every new switch FALSE gives the round-1 model. The round-1 configs list them all as FALSE, with `TRACK_NEW_RULES = FALSE`, so their state counts must not change: rerunning them is the regression check of the round-2 edits.

| Switch | TRUE means | Code |
|---|---|---|
| `IMPL_RESUME_COPIES` | every deliver resume starts a copy in the attempt's other slot (a second live copy is `overflow`) | 2295, CLI 2.1.319 |
| `IMPL_COPY_NOTE_MISSED` | the copy is not recorded (`untracked`), the row reads delivered by resume, the flag is lowered, no settle step | 2301-2315 |
| `CLI_COPY_IN_WORKTREE` | run.py ties the unrecorded copy to the task by its folder: it becomes the attempt's target (`cur`) and close, abandon, launch and stop see it. FALSE: run.py does not see it (the live check's reading: "stop/rm/record cannot see it") | 532-541 |
| `IMPL_HOOK_IS_A_TRY` | a flag touch leaves the row pending (via hook) and counts a try | 2268-2271 |
| `IMPL_DELIVERY_CAP` | `RecordRetries` needs `tries < 3`; a try is a socket post, a step-3 stop/resume and (with the switch above) a flag touch | 2237, 2357, 2409 |
| `IMPL_HOLDS` | record's DIED guard is `RecordHolds`: `Blocking` or an unacked row that is pending or rung | 2864, 2929 |
| `IMPL_SALVAGE` | `WorkerChecksReport` (wst "checked") also means the report file is written; `RecordFilesDied` files a report row instead of DIED when a session of the attempt is "checked" | 2949-2960, 2674-2694 |
| `IMPL_LIVE_ROWS` | `SteerAllowed`: no end row, and `RowLive(cur)` or `ThreadHolds`; `ManagerStops` needs a live row it can see | 2525-2528, 4308-4310 |
| `IMPL_DETAILS` | a resume (in place, failed, or an unrecorded copy) lowers the attempt's flag; a failed row goes to `RecordFilesDied` (no FAILED row) | 2314, 534 |
| `IMPL_PRUNE_META` | launch adds the earlier attempts to `metaGone` after the brief; abandon adds every attempt; a brief whose thread attempt is in `metaGone` shows every ask OPEN and pastes no answer or steer | 1775-1782, 2562-2567, 2333-2354 |
| `ALLOW_RELAUNCH` | `Relaunch`: the operator's `launch --attempt n+1` after an abandon | 1592-1593 |
| `CLI_WAKE_KEEPS_START` | an in-place resume without a checkin leaves the .addr fresh (startedAt is the first start); an open question about the CLI (B5) | 2169-2171 |
| `FIX_ADDR_AFTER_WAKE` | round-2 A.3: an .addr from before the wake is never fresh | — |
| `FIX_SOCKET_PID_MATCH` | round-2 B5: a post needs the .addr's socket to be the current process's | — |
| `FIX_SALVAGE_REFUSES_UNACKED_STEER` | round-2 B4: with an unacked steer, record files DIED (and carries) instead of the salvaged report | — |
| `TRACK_NEW_RULES` | the actions record `bad` for the round-2 rules | — |

Assumed for the round-2 code, which is not written yet: a flag-touched row (rung by the hook, B1 fixed) still counts for `holds` until it times out. If the B1 fix makes it not hold, `RecordHolds` must count pending rows and socket-rung rows only.

"The code at 3330fc7 on CLI 2.1.319" (`impl-*.cfg`): every round-1 `FIX_*` TRUE, every `IMPL_*` TRUE, `CLI_COPY_IN_WORKTREE = FALSE`, `CLI_WAKE_KEEPS_START = TRUE`, the three new `FIX_*` FALSE. "The code with the round-2 fixes" (`impl-r2*.cfg`): the same, with `IMPL_RESUME_COPIES`, `IMPL_COPY_NOTE_MISSED`, `IMPL_HOOK_IS_A_TRY` and `IMPL_PRUNE_META` FALSE (A.1, A.2, B1, B2) and `FIX_ADDR_AFTER_WAKE`, `FIX_SOCKET_PID_MATCH`, `FIX_SALVAGE_REFUSES_UNACKED_STEER` TRUE (A.3, B5, B4). The delivery cap, `holds`, salvage, the live-row guards and the details stay: the round-2 list keeps them. A.4 (the fake claude) is a test change, outside the model. The configs are written by `mailbox-gen/gen_r2.py` in the scratchpad.

### Round-2 rules

| Rule | In words | Catches |
|---|---|---|
| `EveryLiveWorkerIsRecorded` | 9. Every live worker session of the task is in the sessions record: no untracked copy | D1 |
| `NoEndRowOverRunningWorker` | 10. record never files an end row (DIED, a salvaged report, a failed row) while a session of the attempt has a running turn | D1 with D4 |
| `NoReportOverUnackedSteer` | 11. No report row, the worker's or a salvaged one, is filed while a steer of the attempt has no ack | D4 (B4) |
| `BriefNeverShowsSettledAsOpen` | 12. A later brief never shows an ask whose answer was acked as OPEN | D5 (B2) |
| `BriefPastesEveryCarriedMessage` | 13. The next brief pastes every answer and steer that the ended attempt left without an ack | D5 (abandon) |

No new liveness property: the B1 dead end is a deadlock (the configs that show it have no `run.py stop`), and `SteersSettle` already says "a steer is eventually acked or carried". `impl-r2-live` runs it on the round-2 code.

## Round 2: predictions (written before any run)

"Breaks" names the shortest path I expect, in actions. Every impl config also lists the rules that it should still hold.

| Config | Expect |
|---|---|
| `impl` (the code, 2 attempts, no fault) | **Breaks:** <br>• `EveryLiveWorkerIsRecorded` in 7: `WorkerAsks`, `Answer`, `DeliverDecide` (post), `RecordTimesOut`, `RecordRetries`, `DeliverDecide` (stop), `DeliverResume` (an unrecorded copy). <br>• `NoEndRowOverRunningWorker` and `AskerNeverFiledDead` in 10: the same, then the copy reads and acks the answer, and `RecordFilesDied` files DIED from the stopped original (its wst is still "wait") while the copy works. <br>• `NoWorkerLeftAtEnd` in 11: the same, then `Abandon` leaves the copy running. <br>• `TypeOK` (overflow) in 11: after the copy, the answer times out, a retry resumes the original again and needs a second live copy. That is a real second copy in the code, not only a model limit. <br>**Holds:** rules 1, 1b, 3, 4, 4b, 5, 6, 7, 11, 12, 13; no deadlock (low confidence: `run.py stop` cannot reach a stopped original). |
| `impl-die` (1 attempt, a steer, doorbell = resume, one death, no stop) | **Breaks:** <br>• `EveryLiveWorkerIsRecorded` in 4: `ManagerSteers`, `Die`, `DeliverDecide` (step 3), `DeliverResume` (copy). <br>• `NoEndRowOverRunningWorker` in 5: then `RecordFilesDied` (the steer was delivered by resume, so it does not hold). <br>• `NoReportOverUnackedSteer` in 6: `WorkerChecksReport` first, then the same; record salvages the report file. <br>• `NoWorkerLeftAtEnd` in 6 (DIED, then `Abandon`). <br>• `ClosedTaskHasNoUnreadSteer` in 7: the salvage path, then `Close`. <br>• deadlock (B1) in 7: `ManagerSteers`, `DeliverDecide` (flag, try 1), `RecordRetries`, `DeliverDecide` (try 2), `RecordRetries`, `DeliverDecide` (try 3), `Die`. The row is pending, so `holds` blocks DIED; the cap blocks retries. <br>• `TypeOK` (overflow) in 8. <br>**Holds:** rules 1, 1b, 2, 3, 4, 4b, 5, 7, 12, 13. |
| `impl-copy-cwd` (the code, if the copy's row is in the worktree; 1 attempt) | **Breaks:** `EveryLiveWorkerIsRecorded` in 7 (as `impl`). <br>**Holds:** everything else: run.py targets the copy, so record does not file DIED over it, and a later copy takes the stopped original's slot. |
| `impl-brief` (the code, 3 attempts, one ask each, no steer) | **Breaks:** `BriefNeverShowsSettledAsOpen` in 9: `WorkerAsks`, `Answer`, `DeliverDecide` (post), `WorkerReadsInbox`, `WorkerAcks`, `ManagerStops`, `Launch`, `ManagerStops`, `Launch` (attempt 2 has no rows; attempt 1's meta is gone). Also the `impl` breaks with the same paths. <br>**Holds:** rules 1, 1b, 3 to 7, 11, 13. |
| `impl-relaunch` (the code, abandon and `launch --attempt`) | **Breaks:** `BriefPastesEveryCarriedMessage` in 5: `ManagerSteers`, `DeliverDecide` (post), `ManagerStops` (Carried), `Abandon` (meta dropped), `Relaunch`. `BriefNeverShowsSettledAsOpen` in 8: ask, answer, post, read, ack, `ManagerStops`, `Abandon`, `Relaunch`. Also the `impl` breaks. |
| `impl-r2` | **Every rule holds; no deadlock.** |
| `impl-r2-env1` (death, supervisor stop, account; 1 fault) | **Breaks: deadlock** (D6, not in the round-2 list) in about 17: `WorkerAsks`, `AccountFails`, `Answer`, `DeliverDecide` (post, try 1), `RecordTimesOut`, `RecordRetries`, `DeliverDecide` (stop, try 2), `DeliverResume` (fails at once), `RecordTimesOut`, `RecordRetries`, `DeliverDecide` (try 3), `DeliverResume` (fails), `RecordTimesOut`, plus about 4 steps that spend the Manager's one steer (`steer` is still allowed, since the thread holds, and its row ends the same way). The answer has no ack, so `holds` blocks DIED; the cap blocks retries; `run.py stop` refuses a failed row; the model's `Abandon` needs an end row (the code's `cmd_abandon` does not: the Manager can abandon by hand, but no hint says so). <br>**Holds:** every invariant. |
| `impl-r2-env2` (pid reuse, no checkin, held post; 1 fault) | **Every rule holds; no deadlock.** |
| `impl-r2-die2` (1 attempt, a steer, two deaths) | **Every rule holds; no deadlock**: the B4 fix files DIED, and a flag touch no longer spends the cap. |
| `impl-r2-brief`, `impl-r2-relaunch` | **Every rule holds.** Rules 12 and 13 hold by construction once the brief reads the rows (the model has no other way to get a brief wrong). |
| `impl-r2-wake` (CLI keeps startedAt; stop, no checkin, pid reuse; 3 faults) | **Every rule holds.** |
| `impl-r2-operator` (the operator's terminal steer) | **Every rule holds** (as `fixed-operator`). |
| `impl-r2-live` (FairSpec) | `SteersSettle` and `AnswersSettle` **hold**. |
| `need-r2-a1` (A.1 off: every resume copies; A.2 records it) | **Holds**: A.2 covers A.1 in the model. The cost (a new session id at every delivery) breaks no rule. |
| `need-r2-a12` (A.1 and A.2 off; 1 attempt) | **Must break** `EveryLiveWorkerIsRecorded` (7), `NoEndRowOverRunningWorker` and `AskerNeverFiledDead` (10), `NoWorkerLeftAtEnd` and `TypeOK` (11), as in `impl`. A.2 alone off holds by construction (no copy is ever started), so it has no config. |
| `need-r2-a3`, `need-r2-b5` | **Hold**: either fix alone covers the stale .addr. |
| `need-r2-a3b5` (A.3 and B5 off) | **Must break** `DoorbellOnlyToOwnAttempt` (otherProcess) in 8: `WorkerAsks`, `SupervisorStops`, `PidReused`, `Answer`, `DeliverDecide` (step 3), `DeliverResume` (in place, no checkin: the old .addr still looks fresh), `ManagerSteers`, `DeliverDecide` (the post goes to the reused path). |
| `need-r2-b1` (B1 off) | **Must deadlock** in 7, as in `impl-die`. |
| `need-r2-b2` (B2 off, 3 attempts) | **Must break** `BriefNeverShowsSettledAsOpen` in 9, as in `impl-brief`. |
| `need-r2-b2-abandon` (B2 off, relaunch) | **Must break** `BriefPastesEveryCarriedMessage` (5) and `BriefNeverShowsSettledAsOpen` (8), as in `impl-relaunch`. |
| `need-r2-b4` (B4 off; two deaths) | **Must break** `NoReportOverUnackedSteer` in 7: `WorkerChecksReport`, `ManagerSteers`, `Die`, `DeliverDecide` (step 3), `DeliverResume` (in place), `Die`, `RecordFilesDied` (salvage); and `ClosedTaskHasNoUnreadSteer` in 8 (`Close`). |
| every round-1 config | the round-1 result, with **the same distinct-state count** (for example `fixed` 1,038,611, `supersede` 18,819,492). A different count means a round-2 edit changed round-1 behaviour. |

### Size estimates (not measured)

Round-1 counts for scale: `fixed-operator` 29,983; `regress-no-sid-check` 37,572; `fixed-hold` 64,304; `fixed` 1,038,611. The breaking configs may stop early.

| Config | Estimate |
|---|---|
| `impl-die`, `need-r2-b1`, `need-r2-b4`, `impl-r2-die2` | 1k to 20k |
| `need-r2-a3`, `need-r2-b5`, `need-r2-a3b5`, `impl-r2-wake`, `impl-copy-cwd`, `need-r2-a12`, `impl-r2-operator`, `impl-r2-live` | 10k to 100k |
| `impl`, `impl-r2`, `need-r2-a1` (2 attempts, no fault) | 100k to 600k |
| `impl-relaunch`, `impl-r2-relaunch`, `need-r2-b2-abandon` | 150k to 900k |
| `impl-brief`, `impl-r2-brief`, `need-r2-b2` (3 attempts, no steer) | 100k to 1M |
| `impl-r2-env1`, `impl-r2-env2` (2 attempts, 1 fault of 3 kinds) | 500k to 2M |

If one goes far past 2M: set `MANAGER_STOPS = FALSE` where no predicted path uses it, then `MaxAttempts` 2 → 1 for `impl-r2-env*` (they then lose rules 4 and 4b), then split the fault kinds once more.

## Round 2: blind spots

- **B3** (record caches the session rows across tasks, and rereads rows and meta under the lock only when it saw message rows before): the model has one task, and its record reads the state at each step. A stale read needs a second task in the same record command, and the harm (an end row next to a STOPPED row of a pause, the cap) is a Lifecycle question. Not modelled; check it in a test, as the round-2 list asks.
- **B6** (a stuck worker after a steer is stopped, resumed and stopped again) and D8: the model has no stuck state (a permission prompt). Adding one doubles the worker states for one path; a test is cheaper.
- **B7** (`manager.addr`): the Manager's own doorbell is out of the model (round 1 left out `notify` and `wait`).
- The ghost row (a dead process, live for 30 minutes) is merged into "ended": the code lets a steer through and files nothing for a young ghost, then treats it as ended. The model takes the second half only.
- `CLI_COPY_IN_WORKTREE` is an open question about the CLI. `CLI_WAKE_KEEPS_START` is settled (live, c2, 2026-11-09): a wake with no flags changed `startedAt` (1794232669270 → 1794232946304), same id and sessionId, new pid. The round-3 configs set it FALSE; the impl and impl-r2 configs keep TRUE, as they were measured (the A.3 and B5 fixes make it moot there). Two live checks settle them: the copy's `claude agents --json` row (its `cwd`), and `startedAt` before and after a wake without flags.
- D2, D9, D10, D14 to D16 are not modelled (see the table).
- With `IMPL_RESUME_COPIES`, a copy takes the stopped original's slot again. A third live session in one attempt is still `overflow` (TypeOK), so a trace that needs one ends there.

## Round 2: results (measured, 2026-11-09)

Every prediction held. Run by the main session; reports in the scratchpad, `mbx/<config>-r2/report.md` and `mbx/<config>-r2b/report.md`.

| Config | Result | Distinct states |
|---|---|---|
| every round-1 config | the round-1 result, the same break sets | the same counts (`fixed` 1,038,611; `supersede` 18,819,492) |
| `impl`, `impl-die`, `impl-brief`, `impl-relaunch`, `impl-copy-cwd` | break as predicted | stopped at the breaks |
| `impl-r2` | holds | 181,886 |
| `impl-r2-env2` | holds | 885,632 |
| `impl-r2-operator` | holds | 39,958 |
| `impl-r2-wake` | holds | 48,027 |
| `impl-r2-brief` | holds | 61,302 |
| `impl-r2-relaunch` | holds | 181,886 |
| `impl-r2-die2` | holds | 305 |
| `impl-r2-live` | `SteersSettle`, `AnswersSettle` hold | 3,684 |
| `impl-r2-env1` | deadlock in 17 steps (D6) | stopped at the deadlock |
| `need-r2-b1`, `need-r2-b2`, `need-r2-b2-abandon`, `need-r2-b4`, `need-r2-a12`, `need-r2-a3b5` | break as predicted | stopped at the breaks |
| `need-r2-a1`, `need-r2-a3`, `need-r2-b5` | hold, as predicted | — |

One spec fix during the run: TLC enumerates a `\/` inside an action as branches, so `MaxOf({})` was evaluated (a CHOOSE failure) in 16 configs. `Blocking` now reads `IF AnswersTo(k) = {} THEN TRUE ELSE ...`, and `BriefFlaws` uses nested IFs. Keep that form for any `MaxOf`.

## Round 3: the fixes of msg-fixes-r3.md

`msg-fixes-r3.md` (scratchpad) lists six fixes; the model takes four.

| Switch | TRUE means | Item |
|---|---|---|
| `FIX_FAILED_ENDS` | `RecordFilesDied` ignores `holds` when the attempt's session is `failed` and files a salvaged report or a `FAILED` end (never DIED), carrying the thread; `DeliverDecide` never resumes a failed row (the row stays pending, no try) | 1 (D6) |
| `FIX_STOP_OPEN_THREAD` | `ManagerStops` also accepts the attempt with no live row when its thread holds | 5 (D7) |
| `ALLOW_NO_EXIT` | a fault: `ProcessIgnoresStop(s)` puts a live session in `noExit`; deliver's step 3 then stops it, the process does not exit, and the row stays pending (`wait_for_exit` gives up) | environment for item 4 |
| `FIX_EXIT_TIMEOUT_NOT_A_TRY` | that timeout does not count a try | 4 (D15) |
| `IMPL_STALE_ADDR_FAILS` | 3330fc7 (D9): when the socket step is entered (live row with a pid) but the address is missing or stale, the row is marked `sockF` for good. FALSE is the item-2 fix | 2 (D9) |

Not modelled: item 3 (D16: the model has no non-zero `claude --resume` exit other than a lost transcript) and item 6 (D2: the copy path is off in the round-2 code). The other process actions of run.py (`run.py stop`, close, launch) still kill a `noExit` process: the model applies the fault to deliver's wait only.

`impl-r3*.cfg` = the round-2 code (`impl-r2*`) with `FIX_FAILED_ENDS`, `FIX_STOP_OPEN_THREAD`, `FIX_EXIT_TIMEOUT_NOT_A_TRY` TRUE, `IMPL_STALE_ADDR_FAILS` FALSE, and `CLI_WAKE_KEEPS_START = FALSE` (the live fact). Every older config lists the five new constants as FALSE, which is the round-2 behaviour. `noExit` stays empty without `ALLOW_NO_EXIT`, so their state counts must not change. The configs are written by `mailbox-gen/gen_r3.py` in the scratchpad.

## Round 3: predictions (written before any run)

| Config | Expect | Size |
|---|---|---|
| `impl-r3` (2 attempts, no fault) | **Every rule holds; no deadlock.** About `impl-r2`'s 181,886: the wider stop guard adds few states, since without a fault a thread rarely holds with no live row | 180k to 200k |
| `impl-r3-env1` (death, supervisor stop, account; 1 fault) | **Every rule holds; no deadlock.** The D6 path now ends: after the first failed resume, `RecordFilesDied` files FAILED and carries the answer; the next launch (or abandon) goes on | 400k to 1.5M |
| `impl-r3-env1-nostop` (the same, no `run.py stop`) | **Holds; no deadlock**: item 1 alone leads out, without the Manager's stop | 300k to 1.2M |
| `impl-r3-env2` (pid reuse, no checkin, held post) | **Every rule holds**, with about `impl-r2-env2`'s 885,632 states | 850k to 950k |
| `impl-r3-noexit` (1 attempt, doorbell = resume, a process that ignores `claude stop`, `run.py stop` on) | **Every rule holds; no deadlock.** The row stays pending with no try, record retries it at every record, and `run.py stop` ends the attempt. Without `run.py stop` this is a loop that the deadlock check cannot see: item 4 relies on the operator reading the hint | 1k to 20k |
| `need-r3-d6` (items 1 and 5 off) | **Must deadlock** in 17 steps, as `impl-r2-env1` | 300k to 1.5M (stops at the deadlock) |
| `need-r3-d6-nostop` (item 1 off, item 5 on, no `run.py stop`) | **Must deadlock** in 17 steps: item 5 is only a manual way out. (Item 1 off with item 5 on and `run.py stop` on would hold, because the model's stop is a free move; no config.) | as above |
| `need-r3-d15` (item 4 off; 1 attempt, one ask, no steer, no stop) | **Must deadlock** in 8: `WorkerAsks`, `ProcessIgnoresStop`, `Answer`, `DeliverDecide` (timeout, try 1), `RecordRetries`, `DeliverDecide` (try 2), `RecordRetries`, `DeliverDecide` (try 3). The cap blocks retries; the open ask holds DIED | 500 to 5k |
| `need-r3-d9` (item 2 off; 1 attempt, no checkin) | **Holds.** The cost of D9 (a resume where a post would do) breaks no rule; the model has no rule for it. The run only shows that the switch changes nothing else | 10k to 60k |
| every older config | its last result and state count (D9, D15 and item 1 are FALSE there) | unchanged |

## Round 3: run (new and changed configs only)

```sh
M=/Users/ronica/projects/ronica-skills-msg/plugins/agentic-team/model/mailbox
RUNNER=/Users/ronica/projects/ronica-skills-msg/plugins/statechart/skills/statechart/scripts/statechart
OUT=/private/tmp/claude-501/-Users-ronica-projects/5e0c1f80-e89e-517b-8af4-7440e1660cbe/scratchpad/mbx
cd $M
for c in need-r3-d15 impl-r3-noexit need-r3-d9 impl-r3 need-r3-d6 need-r3-d6-nostop \
         impl-r3-env1-nostop impl-r3-env1 impl-r3-env2; do
  TLA2TOOLS=$HOME/.cache/statechart/tla2tools.jar JAVA=/opt/homebrew/opt/openjdk/bin/java \
    $RUNNER $M/Mailbox.tla --config $M/$c.cfg --view $M/view.mjs --out $OUT/$c-r3
done
```

Every older config gained five constants set to FALSE and is otherwise unchanged. To confirm, rerun `impl-r2` (181,886) and `fixed` (1,038,611) with `--out $OUT/<c>-r3`.

## Run

The main session runs these. A subagent may not: the permission classifier blocks the runner. SANY parses the round-2 spec (`java -cp tla2tools.jar tla2sany.SANY Mailbox.tla`, 2026-11-09). Use a new `--out` folder per run. Round 2 first runs the new configs, smallest first, then reruns every round-1 config as the regression check (same result, same distinct-state count).

```sh
M=/Users/ronica/projects/ronica-skills-msg/plugins/agentic-team/model/mailbox
RUNNER=/Users/ronica/projects/ronica-skills-msg/plugins/statechart/skills/statechart/scripts/statechart
OUT=/private/tmp/claude-501/-Users-ronica-projects/5e0c1f80-e89e-517b-8af4-7440e1660cbe/scratchpad/mbx
cd $M
for c in impl-die need-r2-b1 need-r2-b4 impl-r2-die2 need-r2-a3b5 need-r2-a3 need-r2-b5 impl-r2-wake \
         impl-copy-cwd need-r2-a12 impl-r2-operator impl-r2-live \
         impl impl-r2 need-r2-a1 impl-relaunch impl-r2-relaunch need-r2-b2-abandon \
         impl-brief impl-r2-brief need-r2-b2 impl-r2-env2 impl-r2-env1 \
         overview-ask overview-steer adr-nofault phase1 operator \
         need-ask-open need-carry need-own-attempt need-flag need-delivered-timeout need-inbox \
         need-steer-ended need-report-atomic need-lock supersede regress-no-sid-check \
         fixed-operator fixed-die fixed-supstop fixed-account fixed-pid fixed-hold \
         check fixed live live-fixed; do
  TLA2TOOLS=$HOME/.cache/statechart/tla2tools.jar JAVA=/opt/homebrew/opt/openjdk/bin/java \
    $RUNNER $M/Mailbox.tla --config $M/$c.cfg --view $M/view.mjs --out $OUT/$c-r2
done
```

`supersede` took 18.8M states in round 1; run it last or skip it if time is short. The round-1 configs were generated by `mailbox-gen/gen.py` and the round-2 configs by `mailbox-gen/gen_r2.py`, both in the scratchpad and not kept in the repo. Edit the `.cfg` files directly, or rerun `gen_r2.py` from this folder. Every config lists every constant.

## Ambiguous or suspect in the ADR (found while modelling)

1. **L325 "an open blocking ask"**: as written, an ask is open until an answer row exists. A worker whose answer is filed but not yet read can then be filed DIED or stuck. That happens when the post is held (L307), when the worker is idle before it reads the post, or when the resumed worker dies before it reads. That contradicts L292 and L301. Suggested fix: open until the answer is acked (`FIX_ASK_OPEN_UNTIL_ACK`).
2. **L329 vs L287 and L266 to L269**: the lifecycle says that any attempt end (report, stop, died) makes open messages Carried. §5 marks Carried only in `stop`, `close` and `abandon`. Not in `launch`, record's DIED, or a report. So messages of an ended attempt stay pending (`FIX_CARRY_ON_EVERY_END`).
3. **L165 with L325**: deliver step 1 targets "the live worker session for the *current* attempt", and record retries every pending row. So a pending row of attempt 1 is rung into attempt 2's session (`FIX_DELIVER_OWN_ATTEMPT`).
4. **L175**: the flag is `task-<id>.flag`, one per task, and it is removed only when the worker acks. A flag left by a stopped or ended attempt shows its pointer to the next attempt's worker at every tool call. The ADR also does not say what text the hook prints: "the doorbell text" of which row? (`FIX_FLAG_PER_ATTEMPT`)
5. **L263 to L264 and L283**: only Rung returns to Pending. A Delivered row (resume continued in place) whose session dies or fails before it reads stays Delivered for ever, and nothing retries it (`FIX_DELIVERED_TIMES_OUT`).
6. **L150 "rows ... that come after the last ack"**: a row filed between the worker's `inbox` and its `ack` sits before the ack row, and `inbox` never prints it again. `check-report` (L310) then refuses the report for ever, because inbox cannot show that steer (`FIX_INBOX_UNACKED`).
7. **L303 with L150**: the worker acks only the latest answer. The older answer stays pending, and record retries it until the attempt ends (`FIX_SUPERSEDE_SETTLES`).
8. **L159 "no live worker in its current attempt"**: "live" is not defined. (a) A worker that has filed its report but whose process is still idle is live. Then a steer after the report wakes the reported worker, possibly while its verifier runs, and close later carries the steer unread. (b) Under `Session.live`, a waiting worker whose row reads done/idle (T3 L397) is not live, and neither is a parked worker with no pid. Then steer is refused exactly where L13 says resume is for ("idle workers ... workers whose process the supervisor stopped"). The model uses "a process of the current attempt is alive" (`FIX_STEER_REFUSES_ENDED` adds "and no end row").
9. **L310 and T12 L409**: `check-report` is a step before the report. A steer filed between the two is closed over: close Carries it, and a closed task has no next brief to paste it into (L271) (`FIX_REPORT_CHECK_ATOMIC`).
10. **L167 with L436 and L329**: "wait until the row shows no process, then resume" is a check, then an act. The operator's terminal run.py can resume in between, which starts a copy. L293 says the copy is settled before the next deliver, but nothing serialises two run.py processes. The same window lets the Manager's `run.py stop`, `close`, `abandon` or `launch` end the attempt while the operator's deliver waits to resume, which then revives a session of an ended attempt. A fix needs one run.py lock per task that covers every command that stops sessions or files an end row, not only deliver (`FIX_DELIVER_LOCK`). The sessions meta that both processes update (the copy's new id) is a further race that the model does not show.
11. **L166 to L168 in Phase 2**: for a *busy* worker whose socket cannot be used (a stale `.addr`, or a timed-out Rung), step 3 needs an idle worker and step 4 is marked "(Phase 1)". L166 says "the next deliver uses step 3", whose guard then fails. The model uses step 4 (the hook) for a busy worker in both phases.
12. **L309 vs L325 and L301**: is a failed row with an open ask covered by the ask check, which comes "before the stuck, busy, unknown and DIED branches" and does not name the failed branch? Is "resume starts, and the session fails at once" a "failed resume" that files DIED (L301)? The model files a failed row as an end row, not DIED. If the ask check covered the failed row, record and deliver would loop on a failed account.
13. **L166 ".addr file is newer than the row's last start"**: this compares a time that the hook wrote with the CLI's start time. If the CLI records its start after SessionStart runs, or at one-second granularity, a fresh file can look older. That only falls back to resume, so it is safe. The reverse clock order would make a stale file look fresh. The model treats the comparison as exact, so it cannot test this.
14. **L285 vs L168**: the table sets Rung when the flag is touched, while 4.2 says `via: hook` "when the worker acks it". The model follows the table.
