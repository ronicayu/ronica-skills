# Pause

**You own a clean stop.** Use this only when the operator asks to pause. On
"keep going" or "don't stop", do not pause.

1. **Stop launching.** Add `STOP: paused by operator <time>` as the first line
   of `.agentic-team/standing-orders.md`.
2. **Bring sessions to a safe point.** Let a session that is close to done
   finish. Send the others a stop order; they report at a safe point.
3. **Drain.** Record every report, and update `state_at` for every in-flight
   task.
4. **Write the handoff.** In `.agentic-team/handoff.md`, record what is in
   flight and its last checkpoint, what waits for verification, open gates,
   standing orders added this run, and the first action on resume. Take no
   irreversible action to pause.

To resume, remove the `STOP:` line and run the pickup playbook.

**Reply:** what stopped where, what is on disk, and the first action on
resume. This is a pause, not a final report.
