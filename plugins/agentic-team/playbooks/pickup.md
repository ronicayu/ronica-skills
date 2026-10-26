# Pickup

**You own the resume point. Read the trail; do not redo it.** Use this when a
new Manager session takes over a project with work in flight.

1. **Load state.** Run `config.py check` (the Manager's Start step 3), then
   read `.agentic-team/standing-orders.md`, `.agentic-team/gates.md`, and
   `.agentic-team/handoff.md` if it exists.
2. **Reconcile sessions with tasks.** Compare `claude agents --json --all`
   and `result ls --json` with in-progress tasks and their `session` and
   `attempt` metadata. Match sessions to tasks and attempts by the row's `name`
   (`task-<id>-<attempt>-<keyword>`), or by its `cwd` ending
   `.claude/worktrees/task-<id>-<attempt>` where you need certainty. For each
   task, the outcome is one of:
   - a live session (`status` `busy`, or `idle` with state not `done`);
   - a session that `handoff.md` lists as stopped by a pause. It is not dead.
     Resume it with `claude --bg --resume <id>`, or stop it and file `BLOCKED`
     with the reason;
   - a result for the current `attempt` that you have not handled yet;
   - died: no running session and no result for the current `attempt`.
   Handle a result with the drain playbook's classification step. Record a
   death with the drain playbook's liveness step. Also run `status.py` (without
   `--mark`) and read "Done, branch not merged": those branches are ready to
   merge, and their dependents must not launch yet.
3. **Trust the record, then prove the claims.** Do not rerun finished work. A
   task closed with a verdict stays closed. A `PASS` without a verdict still
   goes through verify-and-close.
4. **Resume.** Run a drain, then continue with the launch playbook.

**Reply:** where the last Manager stopped, the state of each in-flight task,
open gates, and your first action.
