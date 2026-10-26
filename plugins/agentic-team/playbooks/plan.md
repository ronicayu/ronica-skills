# Plan

**You own the execution plan, never the work.** Use Taskgraph's planning
guidance for structure, dependencies, dates, and critical path. This playbook
adds what Taskgraph cannot decide.

1. **Check what exists.** List every task in the project with its status.
   Reuse or update an existing task. Never create a duplicate.
2. **Scope each implementation task in Taskgraph.** Taskgraph holds the task
   content; `brief.py` only copies it. A task it refuses to render is not
   scoped yet; fix the task, never the brief:
   - notes: a sentence on why the task is needed, then its acceptance
     criteria as `- [ ]` items or an `Exit test:` line, one checkable
     criterion per item;
   - `--meta scope="<paths it may write; paths it may not>"`;
   - `--meta verify="<exact commands or checks>"`;
   - `--meta estimate=<hours>`. The worker's timebox is twice the estimate;
   - `--meta tier=mechanical|implementation|judgement`;
   - `--meta risk=low|high`. Use `high` when a check is expensive or needs
     judgement, when other work builds on the output, or when readers rely on
     it.
3. **Separate shared writes.** First try to give each task its own files. When
   tasks must write the same file or area, order them per
   `serialization.rules` (`config.py get serialization.rules`) and record
   each order as a Taskgraph dependency.
4. **Relay context through dependencies.** When a task needs an upstream
   task's result, record the dependency. `brief.py` pastes the upstream
   task's latest result into the brief.
5. **Size the plan.** Show the operator a short plan before you add more than
   three tasks. For work the operator already asked for, add one or two tasks
   without asking again.
6. **Re-plan on evidence.** When a report changes scope, assumptions, or
   dependencies, update Taskgraph first, then continue.

**Reply:** tasks added or changed, the critical path, and the first tasks you
will launch, with tier and risk for each.
