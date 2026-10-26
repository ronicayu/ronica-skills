# Plan

**You own the execution plan, never the work.** Use Taskgraph's planning
guidance for structure, dependencies, dates, and critical path. This playbook
adds what Taskgraph cannot decide.

1. **Check what exists.** List every task in the project with its status.
   Reuse or update an existing task. Never create a duplicate.
2. **Scope each implementation task in Taskgraph.** Taskgraph holds the task
   content; `run.py` only copies it. `run.py launch` refuses an unscoped task
   and names the `tg edit` that fixes it. Fix the task, never the brief:
   - notes: a sentence on why the task is needed, then its acceptance
     criteria as `- [ ]` items or an `Exit test:` line, one checkable
     criterion per item;
   - `--meta scope="<paths it may write; paths it may not>"`;
   - `--meta verify="<exact commands or checks>"`;
   - `--meta estimate=<hours>`. The worker's timebox is twice the estimate;
   - `--meta tier=<mechanical|implementation|judgement|override key>`;
   - `--meta risk=low|high`. Use `high` when a check is expensive or needs
     judgement, when other work builds on the output, or when readers rely on it.
3. **Separate shared writes.** First try to give each task its own files. When
   tasks must write the same file or area, record the order as a dependency.
4. **Relay context through dependencies.** A task that needs an upstream
   result depends on that task. The brief pastes the upstream result.
5. **Ask through decisions.** A question only the operator can answer is a
   `decision` node with `--blocks`, `--due`, and options and a default in its
   notes.
6. **Size the plan.** Show the operator a short plan before you add more than
   three tasks. For work the operator already asked for, add one or two tasks
   without asking again.
7. **Re-plan on evidence.** When a report changes scope, assumptions, or
   dependencies, update Taskgraph first, then continue.

**Reply:** tasks added or changed, the critical path, and the first tasks you
will launch, with tier and risk for each.
