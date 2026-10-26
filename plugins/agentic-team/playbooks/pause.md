# Pause

**You own a clean stop.** Use this only when the operator asks to pause. On
"keep going" or "don't stop", do not pause.

1. **Stop launching.** Add `STOP: paused by operator <time>` as the first line
   of `.agentic-team/standing-orders.md`.
2. **Bring sessions to a safe point.** Let a session that is close to done
   finish. Run `claude stop <id>` on each worker that cannot finish soon. Its
   uncommitted changes stay in its worktree. Do not record it as `DIED`. For
   each stopped session, note its session id, its worktree, and the output of
   `git -C <worktree> status --porcelain` in the handoff. To pick it up,
   resume it with `claude --bg --resume <id>`, as the drain playbook allows.
3. **Drain.** Run the drain playbook so every result is classified. Each
   result holds its own checkpoint.
4. **Write the handoff.** In `.agentic-team/handoff.md`, record what is in
   flight and its last checkpoint, the sessions you stopped (step 2), what waits
   for verification, branches ready to merge, open gates, standing orders added this run, and the first action
   on resume. Take no irreversible action to pause.

To resume, remove the `STOP:` line and run the pickup playbook.

**Reply:** what stopped where, what is on disk, and the first action on
resume. This is a pause, not a final report.
