# Launch

**You own the brief. A worker cannot ask you a question, so a vague brief fails
quietly.**

1. **Pick candidates.** Run `ready`, then `show` each candidate. Skip a task
   that has a live session (`claude agents --json`) or whose work needs a
   person or an outside party. A drafting task may prepare a request but never
   send it. Run `"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/status.py" --tg "$TG"`
   (without `--mark`) and read "Done, branch not merged". Skip a task that
   depends on a task in that list: its worktree starts from the main checkout
   and would lack that output. Wait for the merge, or write a gate, and say
   plainly in your reply that the task waits on that branch.
2. **Respect the cap.** Keep in-flight sessions, workers and verifiers, at or
   below `config.py get sessions.max_parallel`. Refill as sessions finish;
   never wait for a whole batch.
3. **Render the brief.** Choose a keyword of one or two hyphenated words
   naming the work, for example `domain-sweep`. `brief.py` builds the worker's
   session name from it, `task-<id>-<attempt>-<keyword>`, for example
   `task-41-1-domain-sweep`. Run from the repository root:

   ```sh
   "$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/brief.py" --tg "$TG" --task <id> --keyword <keyword>
   ```

   It copies GOAL, ACCEPTANCE, SCOPE, VERIFY, and the timebox from Taskgraph,
   adds config (read through `config.py`), standing orders, and upstream
   reports from the Taskgraph result log, and saves the brief to
   `.agentic-team/briefs/task-<id>-<attempt>.md`. The brief ends with the
   exact `tg result add` command the worker runs last. `brief.py` prints the
   path, and the attempt number and session name on stderr. It refuses a
   fourth attempt (exit 2): abandon the task instead (drain step 4). Never
   edit a rendered brief.
4. **Fix refusals at the source.** Exit 2 lists what is missing and the
   `tg edit` or config change that fixes it. Make the change in Taskgraph or
   the config (`config.py check` lists config problems), then render again.
   Exit 3 means the standing orders start with `STOP`; launch nothing.
5. **Pick the model.** Run
   `"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/config.py" model "<work type>"`
   when a `models.overrides` key names the work, else
   `config.py model <tier>` with the task's `tier` meta, else the next
   higher tier. It prints `{"model": ..., "effort": ...}`; pass `--effort`
   only when `effort` is not null. Prefer model aliases (`haiku`, `sonnet`,
   `opus`). An older pinned id, such as `claude-haiku-4-5-20251001`, drops
   out of `auto` mode and waits on a permission prompt that nobody answers;
   drain stops such a session and records it as `BLOCKED`.
6. **Launch.** Get `<mode>` from `config.py get sessions.permission_mode`.
   Run from the repository root. `<attempt>` and `<session>` are what
   `brief.py` printed:

   ```sh
   claude --bg --worktree task-<id>-<attempt> --agent agentic-team:worker \
     --model <model> [--effort <level>] --permission-mode <mode> \
     --name <session> "$(cat <brief path>)"
   ```

   Each worker gets its own worktree (under `.claude/worktrees/`) and a new
   branch, `worktree-task-<id>-<attempt>`. It starts from the default branch,
   so its brief tells it to reset to the base commit first. If the launch says
   the workspace is not trusted, tell the operator to run `claude` once in the
   repository and accept the trust prompt (a trusted parent folder does not
   count), then retry. If the sandbox blocks the launch, rerun with
   `dangerouslyDisableSandbox` only when
   `config.py get sessions.launch_outside_sandbox` prints `true`; otherwise
   record a gate.
7. **Record the start.** Run `tg start <id>`, then
   `tg edit <id> --meta started_at="<now>" session=<session> model=<model> attempt=<n>`,
   where `<n>` is the attempt `brief.py` printed.
   On every launch, also run `--unset-meta verdict verdict_ref abandoned`.

**Reply:** each task launched, with its model, session name, and worktree name.
