# Messaging

Asks, answers and steers between a worker and the Manager.

A worker may ask the Manager a question, and the Manager may answer it or steer a running worker. This works
across Claude profiles: a worker on `~/.claude-2` cannot be reached with ListAgents or SendMessage by name, so
the messages are Taskgraph rows, and a one-line doorbell only wakes the receiver.

**Rows.** Every message is a Taskgraph result row (see [Results](reference.md#results)). The row id is the message id. `run.py` lists the
id of each `answer` and `steer` row that it files in the task's `mailbox` meta, and a worker acts only on listed
ids that were filed by `manager` or `operator`. Rows are history: nothing deletes them.

```text
worker: mailbox.py ask      -> ask row (OPEN) -> worker ends its turn: "Waiting for answer to ask #41" (no tokens)
Manager: run.py record      -> asked #12 attempt 2: #41 <question>      (not stuck, not DIED)
Manager: run.py answer 12 --ask 41 --file a.md
                            -> answer row (ANSWERED) -> doorbell -> the same session wakes
worker: mailbox.py inbox    -> prints the answer row; mailbox.py ack 44 --action "use v2"
Manager: run.py record      -> answer-seen #12 attempt 2: #44 acked by task-12-2 (via socket): use v2
```

**The doorbell** is one fixed line, built by `run.py` and never by a message:
`agentic-team: task <id> attempt <n> has message #<row> (<kind>). Run: <inbox command>`. It carries no
instructions. The brief and the worker agent say that this line means one thing, to run the inbox command, and
that the worker acts only on the rows that command prints. In a live check a session refused to run a script
because a peer message asked it to, so the command comes from the brief, not from the message.

**Ask first (#130).** Before a worker reports `ISSUES` or `BLOCKED` for a question that one Manager answer can
settle, it asks: a file outside SCOPE is needed, the brief's premise is false, fix it in this task or not, may a
failure be ignored, ACCEPTANCE has two readings, or the root cause is in another module (work around it now with a
follow-up, or stop). It reports `ISSUES` or `BLOCKED` only when the answer does not settle it, no ask is left (or
the brief allows none), the work cannot be finished (time, access), or a rule says `BLOCKED` at once (HEAD is not
the CONTEXT commit, a missing brief section, a `STOP:` order, a VERIFY that needs a hooks or setup target). Such a report has an `Asked:` line: the ask
ids it relied on (`Asked: #41, #43`, optionally followed by a note such as `(answered: widen)`) or
`Asked: none: <one-line reason>`; `check-report` refuses a worker's
`ISSUES` or `BLOCKED` report without one (a verifier's report needs none). A steer or a finding that conflicts with
SCOPE or a rule is still `BLOCKED`, but the worker asks about it first when it has an ask left. When the worker needs
a file outside SCOPE to meet the same ACCEPTANCE, the Manager may widen the task's `scope` meta and put the new
SCOPE in the answer's `Answer:` line; the worker's `mailbox.py inbox` also prints it (it compares the meta with the
SCOPE stored in the attempt's context file at launch), and the worker lists it under `Deviations:` as
`scope: answer #<id>: <paths added>`. An answer never lowers ACCEPTANCE or VERIFY. A new requirement is still a new
task. The `rebase` role asks with the conflicting hunks before it reports `BLOCKED`.

**Transports**, best first; the first that works is used:

1. **Socket post.** Every Claude Code session binds a Unix socket in `/tmp/cc-socks/`, shared by all profiles;
   only the same OS user can connect. `run.py` posts one JSON line (`{"type":"user","message":{...}}`). A busy
   worker reads it between tool calls; an idle one starts a new turn. `run.py` posts only when the worker's
   process runs and its session id is matched: the `SessionStart` check-in hook writes
   `.agentic-team/inbox/<task>-<attempt>.addr` (the socket from `$CLAUDE_CODE_MESSAGING_SOCKET` and the hook's
   `session_id`), and the post goes ahead only when that id equals the `sessionId` of the `claude agents` row and
   the file is not older than the row's start. When the file is missing or stale, `run.py` reads
   `<profile dir>/sessions/<pid>.json` (an internal format, observed on CLI 2.1.319) and accepts its
   `messagingSocketPath` only when that file's `sessionId` equals the row's. The row must have a pid, and the socket path
   must name it (`<pid>.sock`), so a reused pid is never posted to. A post that works proves nothing: only
   the worker's `ack` row does. With no ack after `pending_minutes`, the message goes back to pending.
2. **Stop plus resume.** For an idle, parked or stopped worker, for `steer --interrupt`, and as the fallback:
   `claude stop <id>` (when its process runs), then `claude --bg --resume <sessionId> "<doorbell>"` with no other flag,
   run under the worker's own profile, in its worktree. On CLI 2.1.319 a flag after `--resume` starts a copy under a new
   id, while the bare command wakes the same session (same id and session id, a new process and socket) with its saved
   options, hooks included; so `run.py` passes none, and removes the old socket address first (the wake's
   `SessionStart` hook writes a new one). If a copy starts anyway (the printed id differs), `run.py` records it as a
   new `sessions` entry with its session id, stops the original and prints `deliver-copy`. A resume that cannot start, or a conversation with no transcript, files `DIED`: only then is a
   waiting worker called dead.
3. **Pointer flag.** For a busy worker whose socket post failed: `run.py` writes the doorbell line to
   `.agentic-team/inbox/task-<id>-<attempt>.flag`, and the worker's `PostToolUse` hook shows it after the next tool call
(the flag is per attempt, and the hook prints it only when its text starts with its own task and attempt). After
   `pending_minutes` `record` prints `steer-pending` with the hint `run.py steer <id> --file <same text> --interrupt`.

A message delivered by a socket post or by a resume that the worker does not ack within `pending_minutes` goes
back to pending and is delivered again, at most 3 times (the count is socket posts and resumes; a pointer-flag touch is
not a try); then `record` prints `steer-pending` and stops. A `claude --resume` that exits non-zero files `DIED` only when the conversation cannot be resumed (no transcript, or
the CLI says the session is not found); any other failure leaves the message pending and counts one try. A session whose
row is `failed` (an account out of credit, say) is never resumed: `record` files the attempt end even while the
thread holds, carries the open asks and unacked messages, and the hint names `run.py launch <id> --profile <name>` or
`abandon`. A process that does not exit after `claude stop` is not a try; the line names its pid and `run.py stop <id>`.
A missing or stale socket address skips the socket for that try only; a post that fails turns it off for that message.
`run.py stop` also accepts a parked or failed session that holds an open thread (there is nothing to kill).
`claude rm` removes a job's row and keeps its transcript: a blocking ask with no session row still holds while the
transcript exists. A delivery then resumes the recorded session id in the worktree with the flags a launch passes
(`--agent`, `--model`, `--effort`, `--permission-mode`, `--name`, `--settings`; no `--worktree`), because the job's saved
options went with it, and counts a try; with no transcript `record` files `DIED` and carries the thread. `stop` and
`abandon` accept such an attempt: `abandon` files the end row (`ABANDONED`) and carries, so `launch --attempt` works.
A worker that waits on a permission prompt is never sent a doorbell by `steer` or `answer` either (the line names
`claude attach <id>`). If another run.py holds a task's lock past the wait (`AGENTIC_TEAM_LOCK_SECONDS`, default 120;
the worker's report command waits 90), `record` prints `locked #<id>: held by another run.py; record skips it this time`
and goes on with the other tasks. A worker that waits on a permission prompt gets no doorbell and
no resume: `record` stops it once and files `BLOCKED`. `record` reads each task's rows, meta and session rows again under
the task's lock, and files no `DIED` or salvaged report while a steer of the attempt has no ack. A blocking
ask stays open until the worker acks its answer, not merely until an answer row exists, so a worker that was
answered and has not acked is never filed `DIED` or `stuck`, and `launch` refuses its task. When a newer answer to an ask
is acked, the older answers to it are settled. `steer` refuses an attempt that has a filed report, whatever the process
shows, and takes a waiting or parked worker. The worker's `inbox` prints every unacked row of its attempt.

**Finding steers (#127, #133).** `run.py revise` files one steer of kind `finding` that holds every `blocking:` line
of the verifier's row, numbered `F1` to `Fn`; `run.py steer --kind finding` is refused. The body:

```text
Steer: 2 blocking findings of verify #57; fix each, and ack this steer once with one line per finding
Kind: finding
Revision: 1 (verify #57)
F1: blocking: src/a.py:12: the parser drops the last line
F2: blocking: tests/test_a.py: no test covers an empty file
```

The worker answers with one ack, `mailbox.py ack <id> --action "F1: <what I will change>" --action "F2: ..."`,
whose body is `Re: #<id>`, `Action: one line per finding: F1, F2` and one `F<n>: <action>` line per finding. `ack`
refuses an ack that leaves out a finding, names one twice, or names one the steer does not hold. The steer counts as
acked only through an ack that names each of its findings, so `mailbox.py report`, `check-report --mailbox` and
`record`'s salvage refuse a report until then, and name the missing findings. One row each way keeps a revision to two
result rows however many findings it has (#133: on the Taskgraph GitHub backend each row is a comment, unless its kind
is [local](github-backend.md#result-kinds-on-the-taskgraph-github-backend)). A `revise` row opens the attempt
to messages again: a steer filed after it is delivered, not carried, because "ended" means a report of the current
revision (the rows after the newest `revise` row). One doorbell wakes the kept worker: a resume with
`--name <name>-r<r>`, whose new session id `run.py` records. The worker does not answer the verifier; a finding that
conflicts with SCOPE, FORBIDDEN, STANDING ORDERS or ACCEPTANCE is reported `BLOCKED`, as for any steer (after an ask, when one is left).

Two socket failures in one `run.py` command turn the socket off for the rest of that command.
**The worker's doorbell to the Manager** is the existing SendMessage notify step. Its `to` is
`uds:<the Manager's inbox socket>` when `.agentic-team/manager.addr` holds it, else the Manager's session name. Only
`record`, `launch` and `notify-to`, when they run in the Manager's own Bash (not `--dry-run`), refresh that file from
`$CLAUDE_CODE_MESSAGING_SOCKET`, so a new Manager session never leaves a worker with an old address. A worker
after an `ask` wakes the Manager with the line `task <id> attempt <n> asked #<id>; run record`. Without the
`notify-to` switch no step is rendered, and `run.py wait` (it reads Taskgraph every 5 seconds) still wakes the Manager.

**Hooks.** `launch` passes one `--settings` JSON to a worker, and a resume keeps it (saved options): a `SessionStart` hook
(matchers `startup` and `resume`) that runs `mailbox.py checkin`, a `PostToolUse` hook that runs `mailbox.py hook`,
and, for `sessions.permission_mode = "bypassPermissions"`, `"crossSessionInbound": "accept"` (that mode holds a
peer message for approval otherwise; a doorbell has no authority, so accepting it is safe). Hook commands are in
exec form with absolute paths. The `checkin` hook, not the worker, writes the address file. A verifier gets no
`--settings`: it is read only, asks nothing and takes no steer.

**Limits.** A steer may change focus, order, approach and facts inside SCOPE. It never widens SCOPE and never
overrides FORBIDDEN or STANDING ORDERS. Once a worker has started, its task's ACCEPTANCE does not change, and its SCOPE
widens only to answer the worker's ask (Ask first, above): the Manager turns a requirement found later into a new task.
A worker asks first, and reports `BLOCKED` when a steer conflicts with a rule and the answer does not settle it, and lists each applied steer under
`Deviations:`. A worker that has a steer with no ack cannot pass `check-report`. `tg` keeps no author check, so a
worker could file a row `--by manager`; `inbox` ignores every row whose id `run.py` did not list.

**One lock per task.** `launch`, `adopt`, `verify`, `close`, `merged`, `stop`, `abandon`, `answer`, `steer`, each task's
part of `record`, and the worker's report command hold `.agentic-team/locks/task-<id>.lock` (an `flock`, waited for at
most 2 minutes), so the operator's terminal and the Manager cannot interleave a stop or a close with a resume, and a
steer cannot arrive between the check and the filing of a report.

**When an attempt ends** (a report, `stop`, `close`, `abandon`, `DIED`, a stuck session, the next `launch`) its open
asks and unacked messages are marked carried in the `mailbox` meta, and its pointer flag is removed, and the next brief's CONTEXT pastes them under `### Open thread of attempt <n>`.
The `mailbox` meta, and the inbox files of the task (`<task>-<attempt>.ctx.json`, `.addr`, `task-<id>-<attempt>.flag`), are run
state: a new attempt drops the entries of earlier attempts, and the cleanup of a merged task and `abandon` remove
the meta and the files. `manager.addr` is overwritten, never removed.

**Set up.** Nothing per profile beyond [Workers on more than one Claude profile](configuration.md#workers-on-more-than-one-claude-profile).
A Manager in `bypassPermissions` holds a worker's doorbell for approval: run `run.py notify-to --clear`, and let
`wait` wake it.
