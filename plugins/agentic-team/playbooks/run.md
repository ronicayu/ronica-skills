# Run

**Completions are queue events, not interrupts.** A worker's last action is one
`tg result add`. `run.py record` finds results, dead and stuck sessions, merges,
and decisions, one line each. Drain after every critical section (a launch, a
verification, a decision, a plan change) and before every report.

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
   - `died`: retry by failure mode. Infrastructure failures retry as they are.
     A tool error or a stuck model retries one `--tier` higher. An unknown
     cause retries once.
   - `stuck`: read the `next:` hint and the BLOCKED row. The row holds the item the session
     waited for and its last output; the hint lists the remedies. `--model sonnet`
     is not the fix unless the hint names a pinned model id (it does so only for one). `stopped`: after the pause,
     `"${CLAUDE_PLUGIN_ROOT}/scripts/run" launch <id>`.
   - `unknown`: read `claude logs <sid>` for the session state only, and drain again later. If the
     session is gone, run `"${CLAUDE_PLUGIN_ROOT}/scripts/run" stop <id>`, then `"${CLAUDE_PLUGIN_ROOT}/scripts/run" record`.
   - `attempt 3 failed`: run `"${CLAUDE_PLUGIN_ROOT}/scripts/run" abandon <id> <mode>`, add a decision if
     the operator must decide, and re-plan around the task.
   - `conflict`: add the decision the line names. `decision`: carry it into
     the report with your recommendation.
   - `unmerged` and `waits`: say plainly which branch the operator should
     merge and which tasks wait on it.
   - `legacy`: a task that agentic-team 0.6.0 started. Do not launch it; follow the `next:` line.
   - `unmanaged`: `"${CLAUDE_PLUGIN_ROOT}/scripts/run" adopt <id> --branch <b> --head <sha> [--pr <n>]` for work you want under `run`; leave the rest.
   - `ci-waiting`, `ci-pending`, `pr-pending`, `pr-blocked`: drain later; a failed check is evidence for a task, not something to debug.
   - `pr-behind`: `"${CLAUDE_PLUGIN_ROOT}/scripts/run" close <id>` rebases and pushes.
   - `pr-changed`, `pr-closed`, `pr-unpinned`, `push-refused`, `merge-failed`, `host-error`, `comment-failed`: tell the operator what the line says; add a
     decision when they must choose. `published`, `pushed`, `rebased`, `commented`: no action.

   A result whose attempt is not the task's current attempt is superseded.
   Check it against the current state before you use anything in it, and
   salvage through a fresh attempt.
3. **Verify.** A worker's PASS is a claim, not a verdict.
   - `risk=low` with a cheap VERIFY: rerun the VERIFY commands yourself, or in
     a subagent, inside the result's `Worktree:`. Check that
     `git -C <worktree> rev-parse HEAD` equals its `Head:`, spot-check the
     output, and delete only the files your rerun created
     (`git -C <worktree> status --porcelain`). Never start the project's shared services (a fixed container name or port, a shared database) from the worktree. Then run
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
4. **Launch.** For each task `record` lists under `ready`, while `slots` has
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
   - `launch <id> --base <sha|branch>` starts from that commit; use it for a fix on an unmerged feature
     branch. It lifts the unmerged-dependency refusal when the base contains the dependency's commit.
     `--base` applies to a first attempt; a retry continues in the task worktree.
5. **Fresh, not resumed.** Every attempt is a fresh session with a fresh brief,
   in the task's one worktree, on top of the earlier attempts' commits. A
   stopped attempt's WIP commit is where the next one starts.

**Reply** at the end of each drain: counts by state, what changed, open
decisions, branches ready to merge and the tasks that wait on them, and
worktrees kept. Use the report playbook for anything longer.
