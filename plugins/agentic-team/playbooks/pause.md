# Pause

**You own a clean stop.** Use this only when the operator asks to pause. On
"keep going" or "don't stop", do not pause.

1. **Stop launching.** Add `STOP: paused by operator <time>` as the first line
   of `.agentic-team/standing-orders.md`. `STOP` halts `run.py launch` only:
   verifiers may still start and verified work may still close, but `close`
   does not merge while `STOP` is set.
2. **Bring sessions to a safe point.** Run `run.py record`. Let a worker that
   is close to done, and every verifier, finish. Run `run.py stop <id>` on each
   other worker. Its uncommitted work stays in its worktree. Do not record it
   as `DIED`.
3. **Record the stop.** Run `run.py record` again. It classifies every result
   and commits the WIP of each stopped worker that has exited (`stopped ...
   WIP committed`). If a line says `stopping`, run it again later. Take no
   irreversible action to pause.

To resume, remove the `STOP:` line, run `run.py record`, then follow the run
playbook. Each stopped task relaunches as a fresh attempt that builds on its
WIP commit.

**Reply:** what stopped where, what is on disk, and the first action on
resume. This is a pause, not a final report.
