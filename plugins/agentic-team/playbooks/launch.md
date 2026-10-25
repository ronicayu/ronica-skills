# Launch

**You own the brief. A worker cannot ask you a question, so a vague brief fails
quietly.**

1. **Pick candidates.** Run `ready`, then `show` each candidate. Skip a task
   that has a live session (`claude agents --json`) or whose work needs a
   person or an outside party. A drafting task may prepare a request but never
   send it.
2. **Respect the cap.** Keep in-flight sessions at or below
   `config.py get sessions.max_parallel`. Refill as sessions finish; never
   wait for a whole batch.
3. **Render the brief.** Run from the repository root:

   ```sh
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/brief.py" --tg "$TG" --task <id> --session <your session name>
   ```

   It copies GOAL, ACCEPTANCE, SCOPE, VERIFY, and the timebox from Taskgraph,
   adds config (read through `config.py`), standing orders, and upstream
   reports, and saves the brief to
   `.agentic-team/briefs/task-<id>-<attempt>.md`. It prints the path, and the
   attempt number on stderr. Never edit a rendered brief.
4. **Fix refusals at the source.** Exit 2 lists what is missing and the
   `tg edit` or config change that fixes it. Make the change in Taskgraph or
   the config (`config.py check` lists config problems), then render again.
   Exit 3 means the standing orders start with `STOP`; launch nothing.
5. **Pick the model.** Run
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config.py" model "<work type>"`
   when a `models.overrides` key names the work, else
   `config.py model <tier>` with the task's `tier` meta, else the next
   higher tier. It prints `{"model": ..., "effort": ...}`; pass `--effort`
   only when `effort` is not null.
6. **Launch.** Get `<mode>` from `config.py get sessions.permission_mode`.
   Run from the repository root:

   ```sh
   claude --bg --agent agentic-team:worker --model <model> [--effort <level>] \
     --permission-mode <mode> --name task-<id>-<keyword> \
     "$(cat <brief path>)"
   ```

   The keyword is one or two words naming the work, for example
   `task-41-domain-sweep`. If the sandbox blocks the launch, rerun with
   `dangerouslyDisableSandbox` only when
   `config.py get sessions.launch_outside_sandbox` prints `true`; otherwise
   record a gate.
7. **Record the start.** Run `tg start <id>`, then
   `tg edit <id> --meta started_at="<now>" session=<name> model=<model> attempt=<n>`,
   where `<n>` is the attempt `brief.py` printed.
   For a fresh attempt, also run `--unset-meta report_status verdict verdict_ref`.

**Reply:** each task launched, with its model and session name.
