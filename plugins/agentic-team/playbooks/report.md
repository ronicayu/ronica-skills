# Report

**Numbers come from Taskgraph, not from memory.** Build every report from the
data, then add only the judgement the data cannot give.

1. **Drain first.** Run the drain playbook so the data is current.
2. **Generate the facts.** Run:

   ```sh
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status.py" --tg "$TG" --mark
   ```

   It prints, from Taskgraph and `.agentic-team/`:
   - the overall status and plan changes since the last report;
   - closed tasks, with times, tokens, and verdicts;
   - work in flight, with checkpoints;
   - work waiting for verification;
   - failed or abandoned tasks;
   - open gates;
   - ready tasks.

   It reads the project from the config. `--mark` records this report's
   time, so the next one starts from here. Pass `--since 7d` or a date to
   cover a different period.
3. **Add judgement.** Add only what the tables cannot say: why the plan
   changed, what is next on the critical path, and what you recommend for
   each gate.
4. **Report in this order:**
   1. what is done, with the times, tokens, and verdict of each closed task;
   2. what changed in the plan, and what is next on the critical path;
   3. what waits for the operator: open gates and files to send. These are
      the only questions you ask;
   4. what is unmet or stuck.

Copy the figures from the script output. Say that token counts cover only
each session's own transcript, not sub-agents or consultants, and that end
times are the last message. Do not call a draft done. Keep it short and follow
the project's document style.
