# Report

**Numbers come from Taskgraph, not from memory.** Build every report from the
data, then add only the judgement the data cannot give.

1. **Drain first.** Run `"${CLAUDE_PLUGIN_ROOT}/scripts/run" record` so the data is current.
2. **Generate the facts.** Run `"${CLAUDE_PLUGIN_ROOT}/scripts/run" status --mark`. It prints:
   - the overall status and plan changes since the last report;
   - closed tasks, with the done time, tokens, verdict, and verifier;
   - work in flight, with each task's latest result status and checkpoint;
   - work waiting for verification, and verdicts not closed;
   - done tasks whose branch is not merged;
   - failed or abandoned tasks, open decisions, and ready tasks.

   `--mark` records this report's time for the next one. Pass `--since 7d` or a
   date for a different period.
3. **Add judgement.** Add only what the tables cannot say: why the plan
   changed, what is next on the critical path, and your advice on each decision.
4. **Report in this order:**
   1. what is done, with the time, tokens, and verdict of each closed task;
   2. what changed in the plan, and what is next on the critical path;
   3. what waits for the operator: open decisions with your recommendation,
      files to send, branches ready to merge and the tasks that wait on them,
      requests waiting on the host (pending checks, approvals, behind, closed)
      with the request link, and kept or abandoned worktrees (from the `kept` and `abandoned` lines)
      to remove. These are the only questions you ask;
   4. what is unmet or stuck.

Copy the figures from the script output. Say that token counts cover only each
session's own transcript, not its sub-agents. Do not call a draft done. Keep
it short and follow the project's document style.
