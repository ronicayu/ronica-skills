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
   - `--priority P0|P1|P2|P3` (optional; P0 is the highest, no priority is the
     default). `record` lists ready tasks in priority order, then by id. Never
     pass it with `--meta`;
   - `--meta role=<name>`: run `"${CLAUDE_PLUGIN_ROOT}/scripts/run" roles` once while
     planning and pick the role whose `fits` matches the task. Set `tier` or
     `verify_kind` only to depart from the role's defaults. A task that needs two
     roles is two tasks. No role is fine for work no role fits.
   - `--meta tier=<mechanical|implementation|judgement|override key>`;
   - `--meta risk=low|high`. Use `high` when a check is expensive or needs
     judgement, when other work builds on the output, or when readers rely on it;
   - `--meta verify_mode=ci:<workflow>` when CI on the pushed branch is the
     right verifier (GitLab: `ci:pipeline` or `ci:<job>`); needs
     `merge.mode = "pr"`. Default: a verifier session.
   - `--meta asks=<n>` (optional): how many questions the worker may ask the Manager in one
     attempt. `0` forbids asks, as for a mechanical sweep (the mechanical tier defaults to 0);
     unset takes `[messaging] asks_per_attempt` (3).
   - `--meta verify_kind=code|schema|design-doc` (default: the config's
     `verify.kind`, else `code`). `schema`: a data model, DDL or migration; the
     verifier recomputes numbers and runs the DDL. `design-doc`: an ADR, RFC or
     architecture document; the verifier checks sources, completeness and
     contradictions. Only `artifact-verified` closes these two kinds. A `design-doc` task's
     ACCEPTANCE lists the full template in round 1, unless its role names its own structure
     (`product-manager`, `ux-designer`): the problem statement with measurable
     outcomes, ranked quality goals, options with "do nothing" and why each lost, the
     rejected alternative of each decision, failure modes (half-migrated, rolled back),
     migration steps, and a closed checklist for the coders who follow. The checklist
     refers to no git-ignored scratch file; census scripts go into the repository.
   **With workflows on** (`[workflow_policy] enabled = true`): create the work with
   `run.py add "<title>" --pick "<answer 1>,<answer 2>" --seed <n> ...` instead of one
   task per stage. Pick the workflow in four moves, for each piece of work:
   1. Write the notes to a scratch file. Render the prompt with
      `run.py workflows --pick-prompt --seed <n> --title "<title>" --notes-file <file>
      --scope "<paths or area>"`. Use any whole number for `n`, and another for each item.
   2. **Answer 1 is yours.** Read the prompt and type the answer in its format, for
      example `PICK: fix`, before you start the subagent. It is a workflow name or
      `unsure`; answer `unsure` when no description fits or you cannot tell.
   3. **Answer 2 is the subagent's.** Render the same prompt with `--seed <n+1>`. Start
      one non-fork subagent with the Agent tool: `subagent_type: "Explore"`,
      `model: "sonnet"`. Its prompt is the rendered text and nothing else: not your
      answer, your reasons or the workflow you favour. With several items, send all
      their prompts in one call, each under its own heading, and read one answer for
      each. The agent type exists already, so no restart is needed.
   4. Resolve, then add. First run `run.py workflows --resolve "<yours>,<subagent's>"`:
      it shows the workflow that the two answers give and adds nothing (the same name
      wins, two names take the one with fewer stages, a name beside `unsure` takes the
      name, two `unsure` take `figure-it-out`). Read that workflow's "Steps" and choose
      `--with <stage>` or `--skip <stage>` for its optional stages. Then add:
      `run.py add "<title>" --pick "<yours>,<subagent's>" --seed <n> [--with ...]
      [--skip ...] --notes ... --meta scope=... verify=... (--depends ... | --independent ...)`.
      Do not pass `--workflow`: `--pick` replaces it.
   Never ask the owner which workflow to use. A `[[workflow_rule]]` that matches the
   SCOPE paths or the `area` forces its stage on, or moves the work to the lightest
   workflow that has it, and a stage that a rule requires cannot be skipped. The
   `workflow-picked` and `workflow-rule` lines of the add show what was chosen: list
   every unsure pick and every rule change in your next report. After you change the
   SCOPE of a stage, run `run.py stage <instance> recheck`. The owner overrides with
   `run.py stage <instance> rechoose <workflow> --by operator`, before any stage has
   started. Read `run.py workflows` for the descriptions; with a workflow named by hand
   (`--workflow <name>`, no pick), take the lighter one when unsure. The workflow sets each
   stage's role, verify kind, estimate, SCOPE,
   dependencies and approval: set a meta key yourself only to depart from it.
   The notes you give need a why sentence and `- [ ]` acceptance lines, and
   `--meta scope=` and `verify=` are the instance's. A stage whose approval is
   `manager` gets a decision after it merges: answer it with
   `run.py stage <instance> approve <stage>` once the stage's `decision:`
   follow-ups are triaged. At the approval of a `spec` stage, split a stage that
   may be split along the spec's phase table (`run.py stage <instance> split
   <stage> --part "<title>" --meta scope=...`, one call for each part), or
   decline the split in one line (`approve --decline-split "<why>"`). A `human`
   approval is the owner's: it turns into an owner decision when its stage
   merges, and `record` approves it by default at its due time. Hand-planned
   tasks keep working beside workflow instances.
3. **Separate shared writes.** First try to give each task its own files. When
   tasks must write the same file or area, record the order as a dependency.
   Record only a dependency that is real, and split a task that is too large to
   finish in one attempt (every slot busy: the run playbook, step 4).
   Settle both when you create the task, with `run.py add "<title>" ...`
   (`"${CLAUDE_PLUGIN_ROOT}/scripts/run" add`): it takes the options of `tg add`,
   needs `--depends`, `--blocks` or `--independent "<reason>"`, and lists the open
   tasks that may be related, with the reason (same SCOPE path, same issue or
   request, similar title). Write the paths a task must not change after `;` in
   its SCOPE: only the paths before it count as write paths. Read the list; a candidate shown as `not linked` is
   one you may have missed. Never create a task with `tg add`.
4. **Relay context through dependencies.** A task that needs an upstream
   result depends on that task. The brief pastes the upstream result.
   A task that builds on code in an open request or another task's branch
   depends on that task too. Look the other way as well: which existing tasks
   must come after the new one (they read its output or write after it)? Name
   them with `--blocks`. The dependency check before each launch (the run
   playbook, step 4) finds one that you missed; it does not replace this step.
5. **Ask through decisions.** A question only the operator can answer is a
   `decision` node, written as Escalation in the Manager index says.
6. **Size the plan.** Show the operator a short plan before you add more than
   three tasks. For work the operator already asked for, add one or two tasks
   without asking again.
7. **Re-plan on evidence.** When a report changes scope, assumptions, or
   dependencies, update Taskgraph first, then continue. A started task's brief stays
   frozen (Task rules in the Manager index).

**Reply:** tasks added or changed, the critical path, and the first tasks you
will launch, with tier and risk for each.
