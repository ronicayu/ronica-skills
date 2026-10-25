# Drain

**Completions are queue events, not interrupts.** Record each one and return
to what you were doing. Review happens at drain points, in batches.

## On arrival

When a worker's report arrives:

1. Save it to `.agentic-team/reports/task-<id>-<attempt>.md`.
2. Run `tg edit <id> --meta report_status=<PASS|ISSUES|BLOCKED> state_at="<Checkpoint line>"`.
3. Go back to your current step. Do not review the work now.

A verifier's report has a `Verdict:` line. Save it as
`task-<id>-<attempt>-verify.md`, do not change `report_status`, and handle it
in verify-and-close step 3 at the next drain.

A report whose task id, session, or attempt does not match the task's current
metadata comes from a superseded session. Before you use anything in it,
check it against the current state. Salvage useful findings through a fresh
attempt, never by merging them blindly.

## Drain points

Drain after you finish a critical section (writing a brief, a launch, a
verification, a gate, a plan change) and before every report to the operator.
Reports that arrive during a drain wait for the next drain.

1. **List the queue.** Find in-progress tasks with `report_status` set and no
   `verdict`, plus verifier reports saved since the last drain.
2. **Classify each.**
   - `PASS`: run the verify-and-close playbook.
   - `ISSUES` with proven defects: start a fix round. Add any new directive
     to the standing orders, then launch a fresh session. `brief.py` adds the
     previous report to the new brief.
   - `ISSUES` because the timebox or context ran out: split the remaining work
     in Taskgraph and launch a fresh session on the smaller scope.
   - `BLOCKED`: apply the decision-forks principle. If evidence can answer
     it, answer and relaunch. Otherwise write a gate.
3. **Check liveness, read only.** For each in-flight task without a report,
   use `claude agents --json`, `claude logs <id>`, the `progress.tool` command if one
   is set, its output files, and `git status`. Token counts show activity,
   not progress. Never message a session to check on it: a message restarts an
   idle session. A session that is gone and sent no report has died. Record
   `--meta failure=died` and retry it.
4. **Retry by failure mode.** Infrastructure failures (network, API, a dead
   session) retry as they are. A tool error or a stuck model retries on the
   next higher tier. Unknown failures retry once. After two retries, abandon
   the task: record `--meta failure=<mode>`, write a gate if the operator must
   decide, and re-plan around it.
5. **Check consultants.** Each session in `consultants.sessions` must
   appear in `ListAgents`. Restart a missing one with `consultants.restart`.
6. **Refill.** Run the launch playbook up to the session cap.

## Fresh, not resumed

Give new work to a fresh session with a newly rendered brief: fix rounds,
retries, and follow-ups alike. Resume an old session
(`claude --bg --resume <id>`) only when the work needs state that lives only
in it, such as uncommitted changes or a running process. A stop or hold order
to a running session is not a resume. When you resume, paste the current
standing orders into the message.

**Reply** at the end of each drain: counts by state, what changed, and gates
open. Use the report playbook for anything longer.
