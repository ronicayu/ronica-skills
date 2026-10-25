# Pickup

**You own the resume point. Read the trail; do not redo it.** Use this when a
new Manager session takes over a project with work in flight.

1. **Load state.** Run `config.py check` (the Manager's Start step 2), then
   read `.agentic-team/standing-orders.md`, `.agentic-team/gates.md`, and
   `.agentic-team/handoff.md` if it exists.
2. **Reconcile sessions with tasks.** Compare `claude agents --json` with
   in-progress tasks and their `session` and `attempt` metadata. For each
   task, the outcome is one of:
   - a live session;
   - a report saved under `.agentic-team/reports/` but not yet recorded;
   - died: no session and no report.
   Record any report you find with the drain playbook's arrival steps.
3. **Trust the record, then prove the claims.** Do not rerun finished work. A
   task closed with a verdict stays closed. A `PASS` without a verdict still
   goes through verify-and-close.
4. **Resume.** Run a drain, then continue with the launch playbook.

**Reply:** where the last Manager stopped, the state of each in-flight task,
open gates, and your first action.
