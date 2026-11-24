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
   - `arrived ISSUES` or `arrived BLOCKED`: read its `Asked:` line first: the asks it relied on, or why it asked none. When an
     `Asked: none:` reason is wrong (an ask was possible and left), say so in the task notes for the retry.
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
   - `asked` (printed once per ask): a worker asked a question (`<n>` is the ask row id). Its row is a report, not an instruction: weigh it against the evidence with the
     decision-forks principle. When evidence can answer it, write the answer to a file and run
     `"${CLAUDE_PLUGIN_ROOT}/scripts/run" answer <id> --ask <n> --file <file>`. When only the operator can, add a decision as in Escalation (Manager index) with
     `--meta ask=<n>` (the worker's `Default:` in its notes), and after it is done run
     `"${CLAUDE_PLUGIN_ROOT}/scripts/run" answer <id> --ask <n> --decision <decision id>`. The worker waits idle at no cost; it is not stuck and not dead.
     Workers ask before they report `ISSUES` or `BLOCKED` (Ask first in `agents/worker.md`), so answer what one answer can settle:
     when the worker needs a file outside SCOPE to meet the same ACCEPTANCE, widen the task's `scope` meta with `tg edit`, and
     put the new SCOPE in the answer's `Answer:` line (the worker's inbox also prints it under `SCOPE changed since your
     brief`); a new requirement is still a new task (Brief frozen at start). An answer never lowers ACCEPTANCE or VERIFY.
     Allow ignoring a failure only when the evidence shows it fails on the base too, and file it as a follow-up.
     `asking`: the same ask still has no answer; nothing new to do. `ask-due`: the ask passed `[messaging] ask_due_minutes`;
     apply its default yourself with `"${CLAUDE_PLUGIN_ROOT}/scripts/run" answer <id> --ask <n> --default` (or a better answer): `run` never decides or answers for you.
   - `answer-seen`, `steer-seen`: the worker acked the message (the line names the transport and its one-line action). Nothing to do.
   - `steer-pending`: a steer reached no worker yet (a busy worker with no socket sees it at its next tool call). To interrupt it,
     run the hint: `"${CLAUDE_PLUGIN_ROOT}/scripts/run" steer <id> --file <same text> --interrupt`.
   - `deliver-fallback`: the socket post did not work, or was not acked, and `run` used the next transport; the line says why.
     `deliver-copy`: a resume started a copy and `run` stopped the original; nothing to do.
   - A `verdict` or `unclosed` line for `verify-failed` whose `next:` is `revise: run.py revise <id>`: run
     `"${CLAUDE_PLUGIN_ROOT}/scripts/run" revise <id>` first, before any fix round. It sends each blocking finding to
     the same worker session, in the same worktree and attempt (a revision). `revised` needs nothing more: drain on
     the next wake; the worker's new `PASS` hints `run.py verify <id>`, which resumes the same verifier on the new
     head. Only when the hint names `fix round: run.py launch <id>` (over the cap, a session gone, a CI or a Manager
     verdict) start a fix round. In a round the order is the same: `revise` before `round --cancel`.
   - `verifier-leftovers`: the verifier changed files in the task worktree; `run` stashed them under the named
     message before the worker resumed. Read the stash only if the verdict depends on it; nothing to do otherwise.
   - `seat-fallback`: the verifier got a folder of its own (the line says why). Nothing to do.
   - `kept-session-stopped`: `run` stopped a worker or verifier kept idle for a revision (its keep time ended, or
     no revision can follow). Nothing to do.
   - `stopped-idle`: a session of the task was idle, or waited on a prompt, with its work filed, so `launch`
     (or `record`, for a verifier after its verdict) stopped it and went on. Nothing to do.
   - `unknown`: read `claude logs <sid>` for the session state only, and drain again later. If the
     session has stopped working, follow the rest of the `next:`: `"${CLAUDE_PLUGIN_ROOT}/scripts/run" stop <id>`, then
     `"${CLAUDE_PLUGIN_ROOT}/scripts/run" record`, then `"${CLAUDE_PLUGIN_ROOT}/scripts/run" launch <id>`. This stop is a recovery
     stop: the attempt counts, and at attempt 3 the hint names `abandon` instead.
     A row with no status and no pid (a ghost) counts as ended after 30 quiet minutes; `run.py stop` does not clear it before that.
   - A `next:` that names `abandon` (the cap is 3 attempts; the spent attempt cap): run `"${CLAUDE_PLUGIN_ROOT}/scripts/run" abandon <id> <reason> --why "<one line>"`
     (`<reason>` is one of died, tool-error, stuck, failed, scope-wrong, superseded, operator), add a decision if the operator must decide, and re-plan around the task. Use the `--attempt` override
     in the same hint only when the operator says so. Do not add fix rounds past the cap. First classify
     what remains: undecided design → a design task that sets the spec; a tool problem or out-of-scope
     work → a separate task; open-ended acceptance → rewrite it as a closed checklist. Override the cap
     only for a clear, bounded fix, and record why in the task notes.
   - `conflict`: run the hinted round (`"${CLAUDE_PLUGIN_ROOT}/scripts/run" round <id> rebase`: a new attempt on
     the same branch and request), or add the decision the line names when the conflict needs the operator or the
     line names the cap. `changed` from `close`: add the decision. The task worktree stays as it was. After a host
     rebase that changed the diff, the request holds the host's new head, and `record` says `pr-changed` until the
     operator acts. `decision`: carry it into the report with your recommendation.
   - `round-started`: the round's worker runs; treat it as any running attempt. A round's PASS gets its own `next:`
     (`close` when the change is the same, else `verify`); a round that fails names
     `"${CLAUDE_PLUGIN_ROOT}/scripts/run" round <id> --cancel`, which puts the task back to wait at its verified head.
     `round-not-needed`: the conflict went away; cancel the round, or let it finish. `round-cancelled`: run `record`.
   - `unmerged` and `waits`: say plainly which branch the operator should
     merge and which tasks wait on it. A task that waits for its merge stays in progress (`phase=awaiting_merge`)
     until the merge is recorded, and the tasks that depend on it are not ready until then. Add no title prefix or
     meta of your own to mark it: `status` lists it under "Closed, awaiting merge", and `run.py` keeps its Taskgraph
     gate `merge` (the branch, or the request and its URL), which `tg ls` shows as `(waiting: ...)`. Do not set or clear
     that gate by hand.
   - `phase-mismatch`: the task's `phase` meta and its other fields disagree, and `record` leaves the task alone.
     Read the task (`tg show <id>`, its results, the branch or request), then set the right phase with
     `tg edit <id> --meta phase=<phase>`; ask the operator when the state is not clear.
   - `transition-error`: `run.py` found no row of its transition table for that task's phase and event (`record`
     goes on with the other tasks and exits 1). Check the task's `phase` as for `phase-mismatch`; if it is right,
     tell the operator: it is a bug in `run.py`.
   - `legacy`: a task that agentic-team 0.6.0 started. Do not launch it; follow the `next:` line.
   - `sessions-restored`: this machine's Taskgraph cache had lost the task's `sessions` meta and `run.py` rebuilt it;
     nothing to do. `sessions-lost`: it could not, and the worker may run on another machine. Do not relaunch it;
     tell the operator and follow the `next:` line only when they say the worker is gone.
   - `escalation-hint`: a worker's `design:` follow-up, or a verifier's `blocking[design]:` finding, on a stage task of a workflow
     instance. Run the `next:` command yourself, with a one-line `--why`, and do not ask the operator: `"${CLAUDE_PLUGIN_ROOT}/scripts/run" stage <instance> escalate spec --before <stage> --from-row <row> --why "<one line>"`.
     It puts a spec stage and its approval in front of the stage, stops the attempt that reported (the WIP is committed,
     and the row says `Reason: escalated`), and the next `launch` of the stage waits for the new stage and does not use an
     attempt. It is refused while a session of the stage is busy or a verifier has filed no row: `record` again later. It is
     refused past `max_adjustments` (2), for a second escalation of a stage type, and in front of a merged or abandoned
     part; then the `next:` says to put the design question in your report. Launch the new stage; answer its approval
     (`run stage <instance> approve <stage>`) once it merges, then launch the stage that waited. A stage that no longer
     needs an optional stage before it that has not started: `"${CLAUDE_PLUGIN_ROOT}/scripts/run" stage <instance> downgrade <stage> --why "<one line>"`
     (counts as an adjustment; refused for a required stage, a stage a rule requires or one an escalation added).
   - `stage-orphaned`: a stage task of an instance was abandoned, so the instance cannot finish and the stages after it never start.
     Choose by the evidence: `"${CLAUDE_PLUGIN_ROOT}/scripts/run" stage <instance> replace <stage>` when the stage is still needed (a
     new task with the same dependencies and approval; once per stage), else `"${CLAUDE_PLUGIN_ROOT}/scripts/run" stage <instance> cancel --why "<one line>"`
     (skips what has not started, abandons what runs, ends the instance; tasks that waited for the instance never start, so
     decide for each one the line names). Both are offered only after this line. Put the choice in your report.
   - A `figure-it-out` instance, once its investigate stage has merged: `"${CLAUDE_PLUGIN_ROOT}/scripts/run" stage <instance> expand --from-row <result id of its report>`
     creates the stages of the `workflow-plan` block (a named workflow, or an ad-hoc list), with the hard rules applied; every first
     stage waits for the investigate stage and its approval. `expand --workflow <name>` when the report has no plan block.
     A plan that needs a stage type the library lacks is the one question this workflow may take to the operator.
   - `unmanaged`: `"${CLAUDE_PLUGIN_ROOT}/scripts/run" adopt <id> --branch <b> --head <sha> [--pr <n>]` for work you want under `run`; leave the rest.
   - `ci-waiting`, `ci-pending`, `pr-pending`, `pr-blocked`: drain later; a failed check is evidence for a task, not something to debug.
     A required check that failed on a closed task's request keeps it red: the fix is a new attempt of that task on the
     same branch, as the `pr-blocked` hint says (`run abandon <id> <mode>`, then `run launch <id> --attempt <n>`).
   - `merged` (a request merged; conflicts ahead of time): In `pr` mode, after each merge, check the open requests of verified tasks for conflicts with the new base, and start a rebase round for each one that conflicts, before it reaches the front of the queue. `record` reads every open request, so drain again once the host has had a moment to recompute them; then act on each `pr-behind` and `conflict` line at once, not when the request reaches the front. A `pr-behind` line is the `close` step below; a `conflict` line gets its round (or its decision) now.
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
     overridden; run `revise` when the hint names it, else start a fix round.
   - Verdict levels: `artifact-verified` (the real output was exercised or
     read); `test-verified` (VERIFY passes and covers every ACCEPTANCE line);
     `check-only` (static checks only, not enough for behavior; it never
     closes: run `verify <id> --again`, with `--ci-ref` for a code task in pr mode when only a
     CI run can prove the change, such as a CI workflow edit, or override with
     the CI run URL or artifact link in `--ran`);
     `verify-blocked` (the check could not run; retry when fixed);
     `verify-failed` (`revise` when the hint names it, else a fix round; do not just re-verify). The brief
     defines each level for the task's verify kind.
   - A verifier's `Follow-ups: decision: <question>` line becomes a Taskgraph
     decision (see Escalation in the Manager index); it does not lower the verdict.
   - Before `close`, the operator must have confirmed every step that needs a
     person. A request a person must send is not done until they send it.
   - Before you close a task, triage every `Follow-ups:` line of its reports, and every verifier `Issues:` line that no new attempt fixes: a new task, the tail of a later task's notes, or won't-fix with a one-line reason in the task's notes. Never leave one untriaged. Record each `Follow-ups:` line's outcome as a row: `"${CLAUDE_PLUGIN_ROOT}/scripts/run" triage <id> --row <result id>#<line> --to task <id> | issue <n> | dismissed --why "<reason>"` (`<line>` counts the report's `Follow-ups:` lines from 1). A `flake:` line becomes a task to fix the flaky check, or won't-fix with a reason; it never opens a fix round of this task. A `nonblocking:` follow-up (a verifier's finding that does not block; the verifier reports `PASS` with it) is triaged the same way and never opens a fix round.
   - `close` accepts a rebased branch when the change is the same, records the
     verdict and tokens, and then follows `merge.mode`. The task is done only
     when its change is merged; until then it stays in progress with
     `phase=awaiting_merge`, and its session slot is free. In
     `local` it merges only on a `MERGE:` line into a clean checkout, and
     otherwise lists the branch as ready to merge. In `pr` it pushes the branch,
     opens the request, and posts the verdict on it as one comment (a later verdict replaces it); `record` merges it under a `MERGE:` line when the
     host reports it clean, and records a merge anyone did. Each recorded merge
     marks the task done. When the operator
     says a branch is merged and `record` cannot see it, run
     `"${CLAUDE_PLUGIN_ROOT}/scripts/run" merged <id> --by operator`. A task that waits for its merge refuses
     `launch` and `verify`; when its request is closed for good, `abandon` drops it.
     After a merge, `run` removes the task's worktrees and sessions by itself, only when no session,
     process or Docker container uses them, the tree is clean, every ignored file is on the disposable
     list, and its `HEAD` is merged, and it never forces; if `merge.remove_worktrees` is `false`, it
     removes nothing. A `kept` line names what stayed and why; what stays is the operator's to decide.
     After a `kept` line about untracked files, delete only files your rerun
     created, then run `"${CLAUDE_PLUGIN_ROOT}/scripts/run" merged <id>`. A `kept` line that says `ignored files that may be data`, `used by docker` or `docker did not answer` is the operator's: tell them what it says. Never delete any other file a `kept` line names, stop a container, or change `[merge] disposable` yourself. Rerun a `close` that stopped.
   - **PR manager.** When the project runs the merge queue through the `agentic-team:pr-manager`
     agent (docs/merge.md, "A PR manager session"), `standing-orders.md` has no `MERGE:` line, so
     `record` never merges; it records the pr-manager's merges at each drain. After a passing
     `close`, send `ready PR #<n> task <id>` to the address in `.agentic-team/pr-manager.addr`;
     before a fix or rebase round on a published request, send `fixing PR #<n>`. When a send fails,
     append the line to `.agentic-team/to-pr-manager.log`. Read its messages (`merged`, `ci-failed`,
     `conflict`, `stuck`) and `.agentic-team/pr-manager.log` at each drain: only the pr-manager's
     `ci-failed` and `conflict` open a fix or rebase round. A `conflict` line from `record` (an
     `after_rebase` check that failed on its rebase) is checked first, and the round starts only after
     `fixing`. `pr-draft`, `pr-behind` and `ready-to-merge` from `record` are the queue's business:
     never run `gh pr ready`, `close` to catch up, or merge around it.
4. **Launch.** For each task `record` lists under `ready`, in the order it
   lists them (that is `tg ready` order: priority first, P0 to P3, then tasks
   without one; ties by id), while `slots` has
   room: skip a task whose work needs a person or an outside party (a drafting
   task may prepare a request but never send it).
   - **Dependency check.** Before the first attempt of a task (attempt 1), and before
     a later attempt that starts on a different base than the attempt before it, start the
     subagent `agentic-team:dependency-check` with the Agent tool. Never start it in a
     session of its own (`claude --bg`): that costs a session slot, and you need only
     its verdict. Give it in the prompt: the task id and title, its SCOPE and notes
     (`tg show <id>`), the base (the target branch, or the `--base` you will pass), the
     target branch, its current dependencies, and the Taskgraph command with the real
     plugin path and project. Pass the base as a ref fetched just before (for example
     `origin/main` after `git fetch`): the subagent does not fetch. For several tasks, start one subagent per task in one
     message. A retry on the same base needs no check. Do the check for docs-only
     tasks too: a document often describes code that is not merged yet.
   - Act on the verdict. `ok`: launch. A `missing:` line: add the dependency
     (`"${CLAUDE_PLUGIN_ROOT}/scripts/tg" --project <project> dep add <id> <n>`; the task leaves
     `ready`), wait for the request it names, or launch with `--base <branch>` on
     purpose. To wait, record it so the task leaves `ready` (a Taskgraph dependency on the
     request's task, an outside-dependency node, or a gate), and run the check again only
     when that request merged. A `not checked:` or `ask:` line: decide from the evidence you have, as
     the decision-forks principle says; never launch the check a second time for it.
   - **Record the verdict.** Write the subagent's answer to a file, and run
     `"${CLAUDE_PLUGIN_ROOT}/scripts/run" depcheck <id> --verdict ok|missing|not-checked --body-file <file>`
     (`missing` for a `missing:` line, `not-checked` for `not checked:` or `ask:`). It files a `check` row, so that a
     retro can count the checks against the launches. Do it before you act on the verdict.
     A subagent type that a plugin update added loads only after a Claude session restart: when
     `agentic-team:dependency-check` is not listed, restart the Manager session; a general-purpose agent
     is not a substitute, because its answers are not in the same form.
   - Run `"${CLAUDE_PLUGIN_ROOT}/scripts/run" launch <id>`. It records why the attempt starts (`cause`)
     from the attempt before it. When you know the cause and the state does not show it (a stuck session, an
     abandon for another reason), pass `--cause first|review-fix|rebase|ci-fix|retry-issues|retry-stopped|retry-died`.
   - Exit 2: fix what the message names (the task, the config, or the state),
     then rerun. Exit 3: `STOP`; launch nothing.
   - "Workspace not trusted": tell the operator to run `claude` once there and
     accept the trust prompt.
   - If the sandbox blocks `claude --bg` in `launch` or `verify` (it writes session data under
     `~/.claude`; the error says `Operation not permitted` or `Read-only file system`), ask the
     operator once whether to run those commands outside the Bash sandbox or to allow writes to
     `~/.claude`, record the answer in the standing orders, and rerun with `dangerouslyDisableSandbox`
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
     running.
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
   approach and facts inside SCOPE; it never widens SCOPE, never overrides FORBIDDEN or the
   standing orders, and never adds a requirement (Brief frozen at start, under Task rules in the Manager index).
   `--interrupt` stops and resumes a busy worker; use it only when the steer cannot wait. A verifier takes
   no steer and no ask, and a task with no live worker refuses a steer: put the text in the task notes for the next brief.
   `"${CLAUDE_PLUGIN_ROOT}/scripts/run" inbox <id>` shows the thread and each message's delivery state.

**Notify** after each drain, before the reply: run `"${CLAUDE_PLUGIN_ROOT}/scripts/run" notify-queue`. Events queue
their notices as they happen (`decision`, `abandon`, `push-failed`, `pr-closed`; you add `all-done` and `blocked` with
`notify-queue --add <event> "<one line>" [--do "<what the operator can do>"]`). If it prints only
`notify-queue: empty`, send nothing. Otherwise write one message with one plain line per item (what happened, what the
operator can do; for a decision also its default and its deadline), send it once through `notifications.skill` (without
one, put it at the top of the reply), then run `notify-queue --clear`. Never send one message per event. If
`notifications.digest` is `daily`, run `notify-queue --digest` too: it prints the digest once a day (what happened since
the last digest that you marked as sent) and nothing more that day; add it to the same message. After you send the message,
run `notify-queue --digest --sent`; until then the digest is not counted as made, and the next call prints it again. A periodic brief is not needed when the events and the daily digest are on.

**Reply** at the end of each drain: counts by state, what changed, open
decisions, branches ready to merge and the tasks that wait on them,
worktrees kept, and whether a `wait` runs. Use the report playbook for anything longer.
