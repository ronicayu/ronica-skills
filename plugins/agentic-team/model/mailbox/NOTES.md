# The mailbox model

`Mailbox.tla` models the message design of the ADR "How the Manager and its workers talk across Claude profiles": `ronica-skills-adr` `docs/plans/2026-11-09-agentic-team-channel-adr.md` (status proposed, 2026-11-09). It covers sections 1, 4.1 to 4.8, 5 and "Live check results". Nothing in the ADR is implemented, so the model reads the ADR text, not code. "L<n>" below is a line of that file as read on 2026-11-09. When `run.py` and `mailbox.py` implement the design, re-map each action to its function and line range, as `../NOTES.md` does for `Lifecycle.tla`.

The build ships Phase 1 and Phase 2 together: socket first, resume as the fallback, and the hook for a busy worker (`PHASE2 = TRUE`). With every `FIX_*` FALSE, the model is the ADR as written. Each `FIX_*` is one change that the model suspects the ADR needs. Each one names an ADR line below.

Status: written 2026-11-09. Not run yet: TLC was not run, and the spec has not been parsed. The predictions below come before any run.

## What the model holds

- One task, up to `MaxAttempts` attempts (1 or 2). Each attempt has an original session (`w1`, `w2`) and room for one resume copy (`c1`, `c2`). `cur[a]` is the session id that run.py recorded for the attempt.
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

## Switches

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

## Rules

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

## Predictions (written before any run)

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

## State-space estimates (not measured)

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

## Run

The main session runs these. A subagent may not: the permission classifier blocks the runner. The spec has not been parsed yet, so start with `overview-ask`. It is the smallest, and a syntax error shows there first. Use a new `--out` folder per run.

```sh
M=/Users/ronica/projects/ronica-skills-msg/plugins/agentic-team/model/mailbox
RUNNER=/Users/ronica/projects/ronica-skills-msg/plugins/statechart/skills/statechart/scripts/statechart
OUT=/private/tmp/claude-501/-Users-ronica-projects/5e0c1f80-e89e-517b-8af4-7440e1660cbe/scratchpad
cd $M
for c in overview-ask overview-steer adr-nofault phase1 operator \
         need-ask-open need-carry need-own-attempt need-flag need-delivered-timeout need-inbox \
         need-steer-ended need-report-atomic need-lock supersede regress-no-sid-check \
         fixed-operator fixed-die fixed-supstop fixed-account fixed-pid fixed-hold \
         check fixed live live-fixed; do
  TLA2TOOLS=$HOME/.cache/statechart/tla2tools.jar JAVA=/opt/homebrew/opt/openjdk/bin/java \
    $RUNNER $M/Mailbox.tla --config $M/$c.cfg --view $M/view.mjs --out $OUT/mailbox-$c-r1
done
```

For round 2, use `--out $OUT/mailbox-$c-r2`, and so on. The configs were generated by a script (`mailbox-gen/gen.py` in the scratchpad), which is not kept in the repo. Edit the `.cfg` files directly. Every config lists every constant.

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
