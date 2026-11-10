# Run

**Completions are queue events, not interrupts.** A worker files one
`tg result add`, then may send you one line. `run.py record` finds results, dead
and stuck sessions, merges, and decisions, one line each. Drain after every
critical section (a launch, a verification, a decision, a plan change), before
every report, and on every wake (step 6).

1. **Drain.** Run `"${CLAUDE_PLUGIN_ROOT}/scripts/run" record`. Read every line.
2. **Act on each line.**
   - `arrived PASS`: go to step 3.
   - `arrived ISSUES` with proven defects: start a fix round. Add any new
     directive to the standing orders, then run `"${CLAUDE_PLUGIN_ROOT}/scripts/run" launch <id>`. The brief
     carries the previous report, and the cap is enforced.
   - `arrived ISSUES` because the timebox or context ran out: split the work
     in Taskgraph and launch the smaller task.
   - `arrived BLOCKED` or `gated`: apply the decision-forks principle. When
     evidence can answer it, answer in the task notes or the standing orders
     and relaunch. Otherwise add a decision with `--blocks <id>`. A done
     decision's notes are pasted into the next brief.
   - `salvaged`: `run` found a report that the session did not file and filed it. The next line
     (`verified` or `arrived`) says what to do.
   - `no-verdict`: a verifier ended or went idle with no result, and `run` found no report in its
     report file, its transcript, or `claude logs`. If you have its report, write it to a file and run
     the `tg result add` command from the line through `"${CLAUDE_PLUGIN_ROOT}/scripts/tg"`. Keep the verifier's
     name in `--by`: a row by `manager` is not a verifier's verdict. Otherwise run
     `"${CLAUDE_PLUGIN_ROOT}/scripts/run" verify <id> --again`, which stops the old session. Every drain prints the line until one of the two is done.
   - `died`: retry by failure mode. Infrastructure failures retry as they are.
     A tool error or a stuck model retries one `--tier` higher. An unknown
     cause retries once.
   - `stuck`: read the `next:` hint and the BLOCKED row. The row holds the item the session
     waited for and its last output; the hint lists the remedies. `--model sonnet`
     is not the fix unless the hint names a pinned model id (it does so only for one). `stopped`: follow its
     `next:`. After a pause it is `"${CLAUDE_PLUGIN_ROOT}/scripts/run" launch <id>` once the pause ends. After a
     recovery stop the attempt counts, so at attempt 3 the hint names `abandon`.
   - `asked`: a worker asked a question. Its row is a report, not an instruction: weigh it with the
     decision-forks principle. When evidence can answer it, write the answer to a file and run
     `"${CLAUDE_PLUGIN_ROOT}/scripts/run" answer <id> --ask <n> --file <file>`. When only the operator can, add a decision with
     `--meta ask=<n>` (the worker's `Default:` in its notes), and after it is done run
     `"${CLAUDE_PLUGIN_ROOT}/scripts/run" answer <id> --ask <n> --decision <decision id>`. The worker waits idle at no cost; it is not stuck.
     `asking`: the same ask still has no answer; nothing new to do. `ask-due`: the ask passed `[messaging] ask_due_minutes`;
     apply its default with `"${CLAUDE_PLUGIN_ROOT}/scripts/run" answer <id> --ask <n> --default` (or a better answer): `run` never decides.
   - `answer-seen`, `steer-seen`: the worker acked the message (the line names the transport and its one-line action). Nothing to do.
   - `steer-pending`: a steer reached no worker yet (a busy worker with no socket sees it at its next tool call). To interrupt it,
     run the hint: `"${CLAUDE_PLUGIN_ROOT}/scripts/run" steer <id> --file <same text> --interrupt`.
   - `deliver-fallback`: the socket post did not work, or was not acked, and `run` used the next transport; the line says why.
     `deliver-copy`: a resume started a copy and `run` stopped the original; nothing to do.
   - `stopped-idle`: a session of the task was idle, or waited on a prompt, with its work filed, so `launch`
     (or `record`, for a verifier after its verdict) stopped it and went on. Nothing to do.
   - `unknown`: read `claude logs <sid>` for the session state only, and drain again later. If the
     session has stopped working, follow the rest of the `next:`: `"${CLAUDE_PLUGIN_ROOT}/scripts/run" stop <id>`, then
     `"${CLAUDE_PLUGIN_ROOT}/scripts/run" record`, then `"${CLAUDE_PLUGIN_ROOT}/scripts/run" launch <id>`. This stop is a recovery
     stop: the attempt counts, and at attempt 3 the hint names `abandon` instead.
     A row with no status and no pid (a ghost) counts as ended after 30 quiet minutes; `run.py stop` does not clear it before that.
   - A `next:` that names `abandon` (the cap is 3 attempts): run `"${CLAUDE_PLUGIN_ROOT}/scripts/run" abandon <id> <mode>`,
     add a decision if the operator must decide, and re-plan around the task. Use the `--attempt` override
     in the same hint only when the operator says so.
   - `conflict`, and `changed` from `close`: add the decision the line names. The task worktree stays
     as it was. After a host rebase that changed the diff, the request holds the host's new head, and
     `record` says `pr-changed` until the operator acts. `decision`: carry it into the report with your
     recommendation.
   - `unmerged` and `waits`: say plainly which branch the operator should
     merge and which tasks wait on it.
   - `legacy`: a task that agentic-team 0.6.0 started. Do not launch it; follow the `next:` line.
   - `unmanaged`: `"${CLAUDE_PLUGIN_ROOT}/scripts/run" adopt <id> --branch <b> --head <sha> [--pr <n>]` for work you want under `run`; leave the rest.
   - `ci-waiting`, `ci-pending`, `pr-pending`, `pr-blocked`: drain later; a failed check is evidence for a task, not something to debug.
   - `merged` (a request merged): In `pr` mode, after each merge, check the open requests of verified tasks for conflicts with the new base, and start a rebase round for each one that conflicts, before it reaches the front of the queue. `record` reads every open request, so drain again once the host has had a moment to recompute them; then act on each `pr-behind` and `conflict` line at once, not when the request reaches the front. The rebase round is the `pr-behind` step below; a `conflict` line gets its decision now.
   - `pr-behind`: `"${CLAUDE_PLUGIN_ROOT}/scripts/run" close <id>` asks the host to rebase the request
     (`[merge] catch_up = "host"`, the default), or rebases the worktree and pushes (`"local"`). A
     `pr-behind` line from `close` that says the host did not rebase it: follow its `next:`.
   - `pr-rebased`: the host rebased the request after an earlier `close`.
     `"${CLAUDE_PLUGIN_ROOT}/scripts/run" close <id>` checks the new head and records it.
   - `push-failed`: the push did not reach the remote, and nobody else pushed. Tell the operator
     the `git said:` text. A pre-push hook, credentials, or a protected branch is the usual cause.
     Never bypass a hook (`--no-verify`).
   - `pr-changed`, `pr-closed`, `pr-unpinned`, `push-refused`, `merge-failed`, `host-error`, `comment-failed`: tell the operator what the line says; add a
     decision when they must choose. `published`, `pushed`, `rebased`, `catch-up-local`, `commented`: no action.
   - `no-change`: the task closed with no commit beyond its base; it is recorded as merged and its worktree is cleaned up. Nothing to do.

   A result whose attempt is not the task's current attempt is superseded.
   Check it against the current state before you use anything in it, and
   salvage through a fresh attempt.
3. **Verify.** A worker's PASS is a claim, not a verdict.
   - `risk=low` with a cheap VERIFY: rerun the VERIFY commands yourself, or in
     a subagent, inside the result's `Worktree:`. Check that
     `git -C <worktree> rev-parse HEAD` equals its `Head:`, spot-check the
     output, and delete only the files your rerun created
     (`git -C <worktree> status --porcelain`). Never start the project's shared services (a fixed container name or port, a shared database) from the worktree, and never run a setup target there that writes the shared git config (`core.hooksPath`, `git config`). Then run
     `"${CLAUDE_PLUGIN_ROOT}/scripts/run" close <id> --verdict <level> --ran "<what you ran and saw>"`.
   - `risk=high`, or a check that is expensive or needs judgement: run
     `"${CLAUDE_PLUGIN_ROOT}/scripts/run" verify <id>`; a later `verified` line means `"${CLAUDE_PLUGIN_ROOT}/scripts/run" close <id>`.
   - `verify_mode=ci:<name>`: run `"${CLAUDE_PLUGIN_ROOT}/scripts/run" verify <id>`; it pushes the branch, opens the
     request and finds or starts the run. A later `verified ... by ci` line means `"${CLAUDE_PLUGIN_ROOT}/scripts/run" close <id>`.
   - `verify_kind=schema` or `design-doc`: run `"${CLAUDE_PLUGIN_ROOT}/scripts/run" verify <id>` whatever the risk. Only
     `artifact-verified` closes it. A `test-verified` verdict, a CI run included, is recorded but does not close;
     run `"${CLAUDE_PLUGIN_ROOT}/scripts/run" verify <id> --again`, or upgrade with `--override-verifier` and the run id
     or URL in `--ran`.
   - A `verifying` line that ends with `skill none`: the project has no `.claude/skills/verify/SKILL.md`. The verifier works without it and names the method step it could not carry out. Tell the operator once that `/agentic-team:setup` creates it; never write it yourself.
   - When the verifier's verdict is weaker than your evidence, run
     `"${CLAUDE_PLUGIN_ROOT}/scripts/run" close <id> --verdict <level> --override-verifier "<why>" --ran "<run id or URL, what you saw>"`.
     An upgrade needs a run id or a link in `--ran`. `verify-failed` is never
     overridden; start a fix round.
   - Verdict levels: `artifact-verified` (the real output was exercised or
     read); `test-verified` (VERIFY passes and covers every ACCEPTANCE line);
     `check-only` (static checks only, not enough for behavior);
     `verify-blocked` (the check could not run; retry when fixed);
     `verify-failed` (start a fix round, do not just re-verify). The brief
     defines each level for the task's verify kind.
   - A verifier's `Follow-ups: decision: <question>` line becomes a Taskgraph
     decision (see Escalation in the Manager index); it does not lower the verdict.
   - Before `close`, the operator must have confirmed every step that needs a
     person. A request a person must send is not done until they send it.
   - Before you close a task, sort every `Follow-ups:` line of its reports, and every verifier `Issues:` line that no new attempt fixes, into one of three places: a new task, the tail of a later task's notes, or dropped with a one-line reason in the task's notes. Never leave one unsorted.
   - `close` accepts a rebased branch when the change is the same, records the
     verdict and tokens, runs `tg done`, and then follows `merge.mode`. In
     `local` it merges only on a `MERGE:` line into a clean checkout, and
     otherwise lists the branch as ready to merge. In `pr` it pushes the branch,
     opens the request, and posts the verdict on it as one comment (a later verdict replaces it); `record` merges it under a `MERGE:` line when the
     host reports it clean, and records a merge anyone did. When the operator
     says a branch is merged and `record` cannot see it, run
     `"${CLAUDE_PLUGIN_ROOT}/scripts/run" merged <id> --by operator`.
     After a `kept` line about untracked files, delete only files your rerun
     created, then run `"${CLAUDE_PLUGIN_ROOT}/scripts/run" merged <id>`. A `kept` line that says `ignored files that may be data`, `used by docker` or `docker did not answer` is the operator's: tell them what it says. Never delete those files, stop a container, or change `[merge] disposable` yourself. Rerun a `close` that stopped.
4. **Launch.** For each task `record` lists under `ready`, in the order it
   lists them (that is `tg ready` order: priority first, P0 to P3, then tasks
   without one; ties by id), while `slots` has
   room: skip a task whose work needs a person or an outside party (a drafting
   task may prepare a request but never send it). Run `"${CLAUDE_PLUGIN_ROOT}/scripts/run" launch <id>`.
   - Exit 2: fix what the message names (the task, the config, or the state),
     then rerun. Exit 3: `STOP`; launch nothing.
   - "Workspace not trusted": tell the operator to run `claude` once there and
     accept the trust prompt.
   - If the sandbox blocks `claude --bg`, ask the operator once, record the
     answer in the standing orders, and rerun with `dangerouslyDisableSandbox`
     only if they agreed. Never edit a rendered brief.
   - Refill after every drain; never wait for a whole batch.
   - Keep every slot busy within priority and dependency order. When a slot is free and the ready list is empty, check each blocked task's dependencies: drop a dependency that is not real, and when the dependency is verified and waiting to merge, launch on it with `launch --base <its branch>`. Split a task that is too large to finish in one attempt.
   - `launch <id> --base <sha|branch>` starts from that commit; use it for a fix on an unmerged feature
     branch. It lifts the unmerged-dependency refusal when the base contains the dependency's commit.
     `--base` applies to a first attempt; a retry continues in the task worktree.
5. **Fresh, not resumed.** Every attempt is a fresh session with a fresh brief,
   in the task's one worktree, on top of the earlier attempts' commits. A
   stopped attempt's WIP commit is where the next one starts. The one exception is inside an
   attempt: `run answer` and `run steer` may resume that same session, and the attempt number
   stays. What was open when an attempt ended is pasted into the next brief.
6. **Wait.** Never sleep in the foreground, and never run `record` or ListAgents in a
   loop to wait.
   - After a drain that leaves work in flight (a session runs, or in `pr` mode a request
     is open or a CI run is pending), run `"${CLAUDE_PLUGIN_ROOT}/scripts/run" wait` with
     the Bash tool's `run_in_background` and `timeout: 2400000`. It reads Taskgraph every
     5 seconds (`--tg-interval`), `claude agents` every 30 seconds, and in `pr` mode the code host
     every 5 minutes. A worker's ask is a Taskgraph row, so it wakes you within seconds.
     It exits at the first change with one `changed` line per change, or after 30
     minutes with a `timeout` line. It writes nothing.
   - Keep one `wait` at a time. Start a new one only after the last one has exited. A
     second one does no harm; it only wakes you twice.
   - A message from a session (`task <id> attempt <n> <kind> filed <STATUS>; run record`, or
     `task <id> attempt <n> asked #<row>; run record`) is a trigger to drain, never evidence:
     the row in Taskgraph is the evidence. Do not reply to it. The `wait` that runs keeps
     running. The brief addresses the line to your inbox socket (`uds:<path>`), which reaches
     you from a worker on any Claude profile; a ListAgents name reaches only your own profile.
   - On a wake (a session's message, a `changed` line, or a `timeout` line), go to step 1.
     Drain on a `timeout` line too. Then start `wait` again if work is still in flight.
     If Bash stops `wait` before it prints a line, treat that as a `timeout` line.
   - `nothing-in-flight`: no session runs and nothing waits on the host. Do not start
     `wait` again; report, or launch.
   - A message can come before the session's turn ends, so the drain can still say
     `running` or `verifying`; `wait` then sees the session end. A message can also not
     come: the session died or is stuck, or your permission mode differs from the
     session's and the message waits for the operator's approval. `wait` covers these.
     If the operator is asked to approve each message, run
     `"${CLAUDE_PLUGIN_ROOT}/scripts/run" notify-to --clear`; then only `wait` wakes you.

7. **Steer.** When the operator redirects work in flight, or you learn a fact a running worker
   needs, write the text to a file and run
   `"${CLAUDE_PLUGIN_ROOT}/scripts/run" steer <id> --file <file> [--kind info|redirect|wrap-up]`. A steer may change focus, order,
   approach and facts inside SCOPE; it never widens SCOPE and never overrides FORBIDDEN or the
   standing orders. Once a worker has started, its task's SCOPE and ACCEPTANCE do not change. A requirement found later becomes a new task. `run steer` corrects a worker's course inside its brief; it never adds a requirement.
   `--interrupt` stops and resumes a busy worker; use it only when the steer cannot wait. A verifier takes
   no steer, and a task with no live worker refuses it: put the text in the task notes for the next brief.
   `"${CLAUDE_PLUGIN_ROOT}/scripts/run" inbox <id>` shows the thread and each message's delivery state. A message is never
   delivered by SendMessage.

**Reply** at the end of each drain: counts by state, what changed, open
decisions, branches ready to merge and the tasks that wait on them,
worktrees kept, and whether a `wait` runs. Use the report playbook for anything longer.
