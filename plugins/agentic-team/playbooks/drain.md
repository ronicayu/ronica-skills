# Drain

**Completions are queue events, not interrupts.** A worker's last action is one
`tg result add`; it sends you no message. You find results at drain points, in
batches, and return to what you were doing.

## Results

Each result in the Taskgraph result log has a `kind` and a `status`:

- `task`, written by a worker: `PASS`, `ISSUES`, or `BLOCKED`. Its body holds
  the report, including `Branch`, `Head`, `Worktree`, and `Checkpoint`.
- `task` with `--by manager`: `DIED`, written by you for a session that ended
  with no result, or `BLOCKED`, written by you for a session stuck on a
  permission prompt. A worker report that you copied from `claude logs` (step
  3) is also filed `--by manager`, with the worker's own status.
- `verify`, written by a verifier. Its body has a `Verdict:` line. Read it in
  verify-and-close step 3.

A result whose `attempt` is not the task's current `attempt` comes from a
superseded session. Before you use anything in it, check it against the
current state. Salvage useful findings through a fresh attempt, never by
merging them blindly.

## Drain points

Drain after you finish a critical section (writing a brief, a launch, a
verification, a gate, a plan change) and before every report to the operator.

1. **List the queue.** List the in-progress tasks and the project's results:
   `ls --status in_progress` and `result ls --brief`. An attempt has arrived
   when a result exists for the task's current `attempt` and the task has no
   `verdict`. Skip a task whose verifier session
   (`verify-<id>-<attempt>`) is still running. Read the result body with
   `result ls <id> --latest`. An in-progress task that has a `verdict` is
   also in the queue: `verify-blocked` waits for you to retry the check when
   its cause is fixed (verify-and-close step 2), `verify-failed` starts a fix
   round, and a verified task that is not closed goes back to verify-and-close
   step 4.
2. **Classify each.**
   - `PASS`: run the verify-and-close playbook.
   - `ISSUES` with proven defects: start a fix round, subject to step 4's cap
     (`brief.py` exits 2 when the next attempt would be the fourth). Add any
     new directive to the standing orders, then launch a fresh session.
     `brief.py` adds the previous report to the new brief.
   - `ISSUES` because the timebox or context ran out: split the remaining work
     in Taskgraph and launch a fresh session on the smaller scope.
   - `BLOCKED`: apply the decision-forks principle. If evidence can answer
     it, answer and relaunch. Otherwise write a gate.
   - `DIED`: retry it by step 4.
3. **Check liveness, read only.** For each in-flight task without a result for
   its current attempt, use `claude agents --json --all`, `claude logs <id>`,
   the `progress.tool` command if one is set, its output files, and the
   task's results. `--all` includes finished background sessions. Each row has
   an `id`, a `name`, a `cwd`, a `status` (`busy`, `idle`, or `waiting`), and
   a `state` (`done`, `blocked`, and others). Match a session to its task and
   attempt by `name` (`task-<id>-<attempt>-<keyword>`). Where you need
   certainty, match its `cwd`, which is the worker's worktree path ending
   `.claude/worktrees/task-<id>-<attempt>`. A finished worker is `idle` with
   state `done`. Token counts show activity, not progress. Never message a
   session to check on it: a message restarts an idle session.
   - A row with `waitingFor` set, or `state` of `blocked`, is waiting on a
     prompt that nobody will answer. Stop it with `claude stop <id>`. Write a
     `BLOCKED` result for the current attempt with `--by manager` and the
     `waitingFor` text as the body, then handle it as a `BLOCKED` report in
     step 2.
   - A session that `.agentic-team/handoff.md` lists as stopped by a pause is
     not dead. Resume it with `claude --bg --resume <id>`, or stop it and file
     `BLOCKED` with the reason.
   - A session that is no longer running and has no result for the current
     attempt has died. First read `claude logs <id>`. If it ends with a
     complete report that the worker could not file, file it yourself with
     `result add ... --by manager --status <its status>` and the report as the
     body, then classify it in step 2. Otherwise write the `DIED` result, then
     retry the task:

   ```sh
   "$PY" "$TG" --project <project> result add <id> --kind task --attempt <attempt> --by manager --status DIED --body "<one line: what you saw>"
   ```

   Write the `BLOCKED` result the same way, with `--status BLOCKED`.
4. **Retry by failure mode.** Infrastructure failures (network, API, a dead
   session) retry as they are. A tool error or a stuck model retries on the
   next higher tier. Unknown failures retry once. Fix rounds count as
   attempts, and `brief.py` refuses a fourth attempt. Abandon when the next
   attempt would be the fourth (attempt 3 has failed). To abandon, run `tg edit <id> --meta abandoned=<mode>`, where
   `<mode>` is one word: `died`, `tool-error`, `stuck`, or `unknown`. Write a
   gate if the operator must decide, and re-plan around the task.
5. **Check consultants.** Each session in `consultants.sessions` must
   appear in `ListAgents`. Restart a missing one with `consultants.restart`.
6. **Remove merged work.** Run `"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/status.py" --tg "$TG"`
   (without `--mark`) and read "Done, branch not merged". For each task
   there, check whether the branch is merged: the operator said so, or
   `git merge-base --is-ancestor <Head> HEAD` succeeds in the main checkout.
   If so, record `merged_at` and `merged_by=operator`
   (verify-and-close step 6), then run verify-and-close step 8. A task whose
   dependency is still in that list stays blocked from launch (launch
   step 1).
7. **Refill.** Run the launch playbook up to the session cap.

## Fresh, not resumed

Give new work to a fresh session with a newly rendered brief: fix rounds,
retries, and follow-ups alike. Resume an old session
(`claude --bg --resume <id>`) only when the work needs state that lives only
in it, such as a session you stopped with `claude stop` while it held
uncommitted changes. When you resume, paste the current standing orders into
the message.

**Reply** at the end of each drain: counts by state, what changed, and gates
open. Say plainly which tasks wait on an unmerged dependency branch, and name
the branch, so the operator knows to merge it. Use the report playbook for anything longer.
