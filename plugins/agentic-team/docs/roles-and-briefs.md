# Briefs and roles

What a worker brief holds, and how task roles shape it.

## Briefs

[templates/task-brief.md](../templates/task-brief.md) is the one brief template.
Its sections are GOAL, SCOPE, CONTEXT, ACCEPTANCE, VERIFY, TIMEBOX, FORBIDDEN,
AUTONOMY, ROLE (the role's Method in a worker brief and its Review in a verifier brief; `None.` for a task with no role; see [Roles](#roles)), STANDING ORDERS, MAILBOX (the `inbox`, `ack` and `ask` commands, the asks cap, and the rule that the pointer line means "run inbox"; a verifier's says None), and REPORT (the `check-report` command, the command that files the report, and a notify step while an address is set). The
report format lives in the worker agent. `run.py` fills the template from
Taskgraph, the config, and the run directory. Task content is copied from
Taskgraph, never written by hand: GOAL is the title plus the prose in the
notes, ACCEPTANCE is the `- [ ]` items and `Exit test:` or `Acceptance:` lines,
SCOPE and VERIFY are the `scope` and `verify` meta, and TIMEBOX is twice the
`estimate` meta (2 hours without one). CONTEXT holds the base commit, the last
checkpoint, the previous report of a fix round, and the latest report of each
task this one depends on (see "Carried reports" below). To change the brief for every task, edit the
template. `run.py verify` fills the same template, with verifier values in
GOAL, SCOPE, SETUP, UPSTREAM, and AUTONOMY, and a `Verdict:` line request in
REPORT. `run.py verify` fills VERIFY with the task's VERIFY meta, then a `### Project verify skill` note (where `.claude/skills/verify/SKILL.md` is, or that it is missing), then
`templates/verify-<kind>.md` for the task's verify kind, and CONTEXT with the
base commit, how it was found, and the head commit. A verifier that needs the
base commit first runs every check of the head commit (the head's test suites
and the VERIFY commands), then exports the base with `git archive` into
`.agentic-team-scratch/base` in its own worktree and runs only the base-side
checks there. It leaves the export in place; `run.py` removes it with the
worktree. A verifier in the task worktree (`[verify] seat = "task"`) is read
only there and exports the base to `<run dir>/scratch/<session>/base`, outside
the repository, so the task's test runner never collects it; it runs git with
`--no-optional-locks`. A worker brief, while revisions are on, has a
`Revision.` paragraph in MAILBOX: after its report the worker stays idle; a
later pointer can be a revision, whose one `finding` steer it acks once with
one `F<n>: <action>` line per finding, fixes in SCOPE with new commits, and
answers with a new, complete report (`Revision: <n>` after `Status:`, each
finding under `Deviations:` as `finding F<n>: <what changed>`). A resumed verifier gets a short revision brief
(`briefs/task-<id>-<n>-verify-r<r>.md`): the old and new heads, the diff, the
worker's new report, its own earlier findings, and the order to rerun every VERIFY
command and every `Checks` command of the project verify skill at the new head, then
check the fixed findings and the code that the diff touched.

Carried reports are short. Every carried report (the previous attempt, each
upstream dependency, the worker report in a verify brief) drops its `Ran:`
block and keeps every other section. A report section runs from its `Label:`
line at column 0 to the next one, so a section of many lines is dropped or kept
whole. The `Ran:` block ends earlier at a blank line followed by a line at column
0 that reads `<label>:` (a few words, then an ASCII colon and a space or the
line end, or a full-width colon), outside a ``` fence: what follows, such as a
`Root cause:` paragraph, stays. A list item, an indented line, or a `Label:`
line with no blank line before it (`Exit code: 0`) is still the log. An upstream
report is a summary: the result line, then `Status`, `Head`, `Branch`, `Files`,
`Issues`, `Findings`, `Follow-ups` and `Deviations`. Every carried report ends
with a line that names the result id and the command that prints the full result
with its `Ran:` log (`tg result ls <task> --kind task --attempt <n>`), cut or
not. A decision's notes stay whole. Each report is at most
`[brief] carried_report_bytes` UTF-8 bytes (default 3000); a report over it is
cut at a line boundary, `Status`, `Head`, `Branch`, `Files`, `Issues`,
`Findings`, `Follow-ups`, `Deviations` and `Evidence` first, and its last line
says it was cut. All carried reports of one brief are at most
`carried_total_bytes` (default 12000). Over that, the previous attempt keeps its
place, then the upstream reports whose `Files:` share a path with SCOPE get the
room, then the others in order; a report with too little room left becomes one
line under "Reports not shown" (result id, status, attempt, and one shared print
command). Those lines are not counted in the total. The previous attempt's
`Issues`, `Findings` and `Checkpoint` are never cut, so that report may pass its
cap; its other sections are cut first. When a verifier judged that attempt, the
brief also carries the latest verifier report of the attempt (its `Status`,
`Verdict`, `Issues`, `Findings` and `Follow-ups`), whose `Issues` and `Findings`
are never cut either: after a `verify-failed` verdict on a worker's `PASS`, they
are what the fix round must fix. In a verify brief the worker report's
`Deviations` is never cut either: the verifier checks its `adjacent:` lines.

The worker runs `mailbox.py report` and `run.py check-report` from its own session, so
its permission mode must allow both. Allow only a `--body-file` path in the
worktree's `.agentic-team/` folder if you write a permission rule for it. In `auto` mode nothing enforces that rule: the
brief gives the worker the paths to `mailbox.py`, its context file, `tg.py` and the database, and only the
worker's instructions keep it to the one report command. A verifier files with `mailbox.py file-verify`, which takes every value on its command line and runs the same `tg result add`; it needs no context file. It runs `tg.py` with the interpreter that runs `mailbox.py`, and refuses a `--tg` that is not an existing file named `tg.py`.

## Roles

A role is a method for one kind of task. A task names its role in the `role` meta (or the config's `[roles] default`). The role does three things:

- Its **Method** goes into the worker's brief, in the ROLE section.
- Its **Review** checks go into the verifier's brief, in the ROLE section, in addition to the method for the task's verify kind.
- Its **defaults** fill the task's tier and verify kind when the task sets none.

Every worker is still the one worker agent with the one report format. ROLE guides how the worker works. It never overrides SCOPE, ACCEPTANCE, FORBIDDEN or STANDING ORDERS, and the brief says so. A task that needs two roles is two tasks. A task with no role and no `roles.default` is unchanged, except that its brief has a ROLE section that reads `None.`.

Three roles ship with the plugin, in [templates/roles/](../templates/roles/):

| Role | Fits | Tier | Verify kind | Skills |
|------|------|------|-------------|--------|
| `architect` | design documents, ADRs, specs, interface contracts, data models, migration plans | `judgement` | `design-doc` | `architecture-design:architecture-design`, `writing-editor:writing-editor` |
| `software-engineer` | code changes: features, bug fixes, refactors, tests, scripts, build and CI changes | `implementation` | `code` | none |
| `rebase` | rounds only: the role of `run.py round <id> rebase`, not of a task | none (the last attempt's) | none (the task's) | none |

A round's kind names its role: `run.py round <id> rebase` gives the worker the Method, and the verifier the Review, of the role `rebase`, instead of the task's role. A project changes what a round does by replacing that file or extending it (below): for example a project that resolves conflicts with `git merge` instead of a rebase.

`run.py roles` lists the roles a project has. The Manager runs it once while planning and sets `--meta role=<name>` on the task whose work matches a role's `fits`.

### Where a role file is found

A role has a name of lowercase letters, digits and `-`, and a file `<name>.md`. `run.py` looks in two places and the first wins:

1. The project: `.claude/agentic-team/roles/<name>.md` in the main checkout. Track it in git. It is not `.agentic-team/`, which is run state and is git-ignored.
2. The plugin: `templates/roles/<name>.md`.

The roles a project has are the union of both folders. A project file with the name of a shipped role replaces it completely, unless it sets `extends` (see [Extending a role](#extending-a-role)).

### The file format

```markdown
---
fits: one line: what kinds of task this role is for (the Manager's role table shows it)
tier: judgement              # optional; a tier name or a models.overrides key
verify_kind: design-doc      # optional; code | schema | design-doc
skills: [plugin:skill, ...]  # optional; [] or absent means none
---

## Method
...text pasted into the worker brief...

## Review
...text pasted into the verifier brief...
```

The frontmatter is the lines between the first two `---` lines. Each line is `key: value`, split at the first colon, so a `fits` value may hold colons. A `#` that starts a value or follows a space starts a comment, except inside a list. There is no YAML library: only these keys (and `extends`, below), one per line, and `skills` as `[a, b]` or empty. A section's text runs to the next `## ` heading or the end of the file. `## Method` is required and may not be empty; `## Review` is optional.

A file with no `fits`, no `## Method`, an unknown key, a `tier` that the config does not know (or a tier with no model), a `verify_kind` that is not `code`, `schema` or `design-doc`, or a `skills` value that is not a list of names is broken. `launch`, `adopt` and `verify` refuse a task whose role is broken or has no file, and name the file, the problem and the roles there are. `run.py roles` lists a broken file with its error and exits 1. No other command fails because of a role: see "What a role fixes at launch".

When Method plus Review is over 600 words, `launch` and `verify` print a `warn` line (an event in `--json`) and go on. A long role is followed less closely; keep it short. The shipped roles are under 600 words.

### Extending a role

A project role can add to another role instead of replacing it, so it keeps the changes that later plugin versions make to the shipped role (#114):

```markdown
---
extends: software-engineer   # the parent role
---

## Method
1. Paste the red line of each new test at base; it fails for the right reason.

## Review
1. Mutation check: delete each new guard; its named test goes red.
```

- **The parent.** When `extends` names the file's own role (`software-engineer.md` with `extends: software-engineer`), the parent is the shipped file of that name, and tasks with `role=software-engineer` get the merged role. Any other name is the role `run.py` finds for it, project first. The parent must not set `extends` itself: a role extends one level only, so there is no chain and no cycle.
- **The text.** The merged Method is the parent's Method, then the child's Method; the same for Review. A numbered item is a line at column 0 that starts with `N. `, with the lines under it up to the next one. The child's items are numbered on from the parent's, so the child's `1.` above becomes `14.` after the 13 shipped items. Text before the first numbered item stays in place. A child may leave out `## Method` or `## Review`; the parent's section is then used as it is.
- **Only adds.** An extending role cannot remove or change a parent item. When a project rule contradicts one, such as a project that bans every TODO while Review item 5 of `software-engineer` allows a TODO with a task id, write the project rule as a standing order: STANDING ORDERS win over ROLE, and the brief says so. To change many parent items, replace the role instead (a file of the same name with no `extends`).
- **The keys.** `fits`, `tier`, `verify_kind` and `skills` come from the parent when the child has no line for them, so an extending role needs no `fits` line. `skills: []` is a line: it clears the parent's skills.
- **What shows.** `run.py roles` shows the source as `project, extends plugin:software-engineer` (or `project:<name>`). The ROLE line of a brief names both files. The 600-word warning counts the merged text.
- **Broken.** An `extends` that names no role, and a parent that is broken or extends another role, make the role broken, with the same refusals as any broken role.

### Variables in role text

`launch`, `round` and `verify` fill `{{NAME}}` placeholders in a role's Method and Review: `{{TASK_ID}}`, `{{TASK_TITLE}}` and `{{PROJECT}}` in every brief, and in a round `{{ROUND_KIND}}`, `{{ROUND_FROM}}` (the verified head), `{{ROUND_ONTO}}` (the target commit), `{{ROUND_OLD_BASE}}` (`git merge-base` of the two), `{{ROUND_OVERLAP}}` (the files that both the change and the target changed since then, in backticks, at most 30, else `none`) and `{{ROUND_VERDICT}}`. A placeholder with no value stays as it is.

### Tier and verify kind

| | Order, first match wins |
|---|---|
| Tier | `launch --tier`, the task's `tier` meta, the role's `tier`, then `implementation`. A round: `round --tier`, the kind role's `tier`, the tier stored for the last attempt, then the order above |
| Verify kind | the task's `verify_kind` meta, the role's `verify_kind`, then `verify.kind` from the config |

The `launched` line says where the tier came from, for example `tier judgement (role architect)`, `tier implementation (meta)` or `tier implementation (default)`. Set `tier` or `verify_kind` on a task only to depart from its role.

### What a role fixes at launch

`launch` and `adopt` work out the role, the tier and the verify kind once and store them in the attempt's `sessions` entry as `"role"` (a name or `null`), `"tier"` and `"verify_kind"`. Every later command for that attempt uses the stored values: a `--tier` given at launch survives a rowless resume, and `close` and `record` need the role file no more. You can change, break or delete a role file after a launch without hurting `close`, `merged`, `record`, `status`, `stop`, `abandon` or a resume. `verify` is the exception: it reads the Review from the role file, and it refuses when that file is gone or broken, so a verifier never runs without the checks silently. An attempt launched before 0.17.0 has no stored values; its role is worked out from the meta and the config, and a role problem there reads as no role, with one `warn` line. A `verify_kind` meta always wins, also when you set or change it after a launch; the stored kind replaces only the role's.

### Skills

A role's `skills` are loaded by the worker with the Skill tool, as its brief tells it. Skills belong to a Claude profile, so a worker on another profile may not have them. The brief tells the worker to say so under `Deviations:` when a skill does not load, and to follow the Method text instead. The Method must therefore work without the skills. `run.py` does not check that a profile has them.

## Workflows

A workflow is a markdown playbook for one kind of work: a frontmatter that lists its stages (prd, spec, impl, test, ...) with their roles, verify kinds, approval levels and order, and a prose body that tells the Manager when to use it. The design is in [docs/design/workflow-templates.md](design/workflow-templates.md). Workflows are off by default (`[workflow_policy] enabled = false`).

Five workflows ship with the plugin, in [templates/workflows/](../templates/workflows/): `hotfix` (`impl → test`), `fix` (`spec? → impl → test`), `change` (`prd → impl → test`), `feature` (`prd → ux? → spec → impl* → test`) and `figure-it-out` (`investigate`, which decides the rest). `?` marks an optional stage and `*` a stage that may be split. `run.py workflows` lists the workflows a project has.

### The commands

| Command | Use | Section |
|---|---|---|
| `run.py workflows [--check]` | List the workflows and their stages; check the files | [Where workflow files are found](#where-workflow-files-are-found) |
| `run.py workflows --pick-prompt --seed <n> ...` | Print the prompt that asks which workflow fits a piece of work | [Picking a workflow](#picking-a-workflow) |
| `run.py workflows --resolve "<a>,<b>"` | Show how two answers resolve; creates nothing | [Picking a workflow](#picking-a-workflow) |
| `run.py add --workflow <name>` or `--pick "<a>,<b>" --seed <n>` | Create an instance and its stage tasks | [Adding work with a workflow](#adding-work-with-a-workflow) |
| `run.py stage <instance> approve <stage>` | Answer a stage's approval (`--by operator`, `--default`, `--decline-split`) | [Approvals](#approvals) |
| `run.py stage <instance> split <stage> --part ...` | Split a splittable stage into parts | [Splitting a stage](#splitting-a-stage) |
| `run.py stage <instance> recheck` / `rechoose <workflow>` | Match the hard rules again; the owner's override of the pick | [Hard rules](#hard-rules) |
| `run.py stage <instance> escalate / downgrade / replace / cancel / expand` | Change an instance in flight | [Changes in flight](#changes-in-flight) |
| `run.py workflows --stats [--since <date>] [--json]` | The retro read of the workflow records, with candidate changes | [Running a workflow retro](operations.md#running-a-workflow-retro) |

### Where workflow files are found

| What | Plugin default | Project override (track it in git) |
|---|---|---|
| Workflows | `templates/workflows/<name>.md` | `.claude/agentic-team/workflows/<name>.md` |
| Stage library | `templates/workflows/stages.toml` | `.claude/agentic-team/workflows/stages.toml` |

The project folder is the one that holds the project's roles. The workflows a project has are the union of both folders, and a project file replaces a plugin file of the same name, unless it sets `extends`. A project `stages.toml` adds stage types or overrides fields of a shipped type.

### The stage library

`stages.toml` has one table per stage type, `[stage.<type>]`, read with `tomllib`. Keys: `role`, `verify` (`code`, `schema` or `design-doc`), `approval` (`auto`, `manager` or `human`), `estimate` (hours), `scope` (`"instance"`, or a path template with `{design_dir}` and `{slug}`), `verify_cmd` and `acceptance` (a list of lines). A new type needs `role`, `verify` and `approval`. The shipped types are `investigate`, `prd`, `ux`, `spec`, `impl` and `test`; `{design_dir}` is `[workflow_policy] design_dir`.

### The file format

```markdown
---
name: feature                 # the file name, without .md
description: One or two sentences, at most 300 characters. The Manager reads it to pick a workflow.
extends: other                # optional; project files only
stages:
  - {id: prd}
  - {id: ux, optional: true, after: [prd]}
  - {id: spec, after: [prd, ux]}
  - {id: impl, after: [spec], split: true, estimate: 4}
---

## When to use
...

## Steps
...
```

There is no YAML library. The frontmatter is flat `key: value` lines (split at the first colon) and one `stages:` key whose items are flow maps, one per line. A stage takes these fields:

| Field | Meaning |
|---|---|
| `id` | Required. Lowercase letters, digits and `-`, unique in the workflow. It names a library type unless `type` is given |
| `type` | A library type, so that one type can appear twice (`impl-api`, `impl-web`) |
| `role`, `verify`, `approval`, `estimate` | Override the library values. The role must exist and not be broken |
| `after` | A list of stage ids that come before, `[]` for a root stage. The graph must have no cycle |
| `optional` | `true` or `false` (default). A workflow needs at least one required stage |
| `split` | `true` lets the Manager split the stage into parts. Only for a stage whose verify kind is `code` |
| `decides` | `true` on the only stage of a workflow, a root stage whose result names the remaining stages |

A project workflow with `extends: <name>` takes the stages of that workflow (with `extends: <its own name>`, the plugin's), then lays its own over them: a stage with the same `id` overrides the parent's fields, a new `id` is appended. It cannot remove a stage or make a required stage optional, and the parent may not extend another workflow. To remove a stage, replace the file.

A file with an unknown key, a missing `name` or `description`, a `name` that is not the file name, a stage with an unknown field or an id that is not a library type, a `role`, `verify` or `approval` that is not valid, an `after` that names no stage, or a cycle is broken. Each problem is one line, `<file>:<line>: <problem>`. `run.py workflows` lists a broken file with its problems and exits 1, and so does a broken `stages.toml`. `run.py workflows --check` prints only the problems, or one `workflows-checked` line. `config.py check` runs the same check when `[workflow_policy] enabled` is true or the project has a workflow file. It also needs the stage type `spec` in the library and one workflow that has it, because a hard rule forces a spec stage.

The body is prose for the Manager: `## When to use`, `## Steps` and an optional `## Stage notes` with one `### <id>` subsection per stage. It is not checked, except that a body over 600 words gets a `warn` line.

### Adding work with a workflow

With `[workflow_policy] enabled = true`, `run.py add "<title>" --workflow <name> [--with <stage>]... [--skip <stage>]... --notes "..." --meta scope=... verify=... (--depends ids | --blocks ids | --independent "<reason>")` creates one piece of work in one locked run:

- **The instance**: a parent task with your title and notes, and the meta `workflow` and `workflow_record` (the stages, what happened to each optional stage, the rule that applied). It is never launched, `record` leaves it out of `unmanaged`, and its status is the derived status of its stages. A task that `--blocks` waits for the instance, so for every stage.
- **One task for each required stage and each `--with` stage**, under the instance, titled `<title> — <stage id>`, with the stage's role, verify kind, estimate and a SCOPE and VERIFY: a code stage takes the instance's `scope=` and `verify=`; a design stage writes one document, `<design_dir>/<title slug>-<stage id>.md`. Each carries the workflow's `### <stage id>` notes as `Workflow notes`. The notes you give must hold a why sentence and acceptance lines (`- [ ] <line>` or `Acceptance: <line>`): an impl or test stage carries them, and a design stage must cover each of them.
- **Real dependencies.** A root stage takes the external `--depends` (or your `--independent` reason). Every other stage depends on each upstream stage and on that stage's approval decision, so `launch` refuses it until both are done. An optional stage that is in neither `--with` nor `--skip` is left out like a skipped one (the lighter choice); a stage that came after it depends on its upstream stages instead, so nothing waits for a stage that does not exist. `--with` and `--skip` name optional stages only.
- **The brief** of a stage names its place (`Workflow: feature #41, stage impl (4 of 5)`), and for each upstream stage its `Summary:`, the `Files:` that name its documents and its `Head`, and the answer in the approval decision. A downstream brief already carries the upstream report; the line points at what to read first.

### Approvals

A stage whose `approval` is `manager` or `human` gets a decision under the instance that depends on the stage, and the next stage depends on it. The approval is the highest of the stage's workflow value, the `approval` of a `[[workflow_rule]]` that matches the instance's SCOPE write paths or `area` meta (`match_paths`, `match_area`; a rule also sets `risk` on every stage task), and `[workflow_policy] approval_floor` for the stage's verify kind. Nothing lowers an approval during a run.

| Approval | Decider | Due | At the due time |
|---|---|---|---|
| `auto` | none | none | none |
| `manager` | The Manager: `run.py stage <instance> approve <stage>` | `manager_due_hours` (2) after the stage merges | `record` approves it by default |
| `human` | The owner: the decision is created with `decider=manager`, and the merge record turns it into `decider=operator`, queues one `decision` notice and sets the due time | `human_due_hours` (48) after the stage merges | `record` approves it by default, unless the rule that raised it sets `on_timeout = "hold"`: it then has no due time and waits for the owner |

The due time starts when the stage merges, not when the decision is created. It is stored as `due_at` (UTC) on the decision, and as `decide_by`, its date, for Taskgraph. `record` applies the default of every decision that is past `due_at` (`approval-due`): it writes the answer into the decision's notes, which a downstream brief pastes, and marks it done. A held approval stays in every digest until the owner answers; `stage approve <stage> --by operator` records that answer.

A `manager` approval checks workflow facts only, never the work: the stage is merged, every `decision:` follow-up of the stage is triaged (`run.py triage`), and a stage after it that may be split is split or declined (`--decline-split "<one line>"`). A failed check is a task or a decision, not a rejection. A split stage has one approval for all its parts: it opens, and can be answered, only when every part has merged, and the triage check reads every part. An abandoned stage task prints `stage-orphaned` with the stages and the approval that wait for it (`abandon`, and `record` on every run); `run.py stage <instance> replace <stage>` and `cancel` answer it (see [Changes in flight](#changes-in-flight)). `add --workflow` that fails after it created tasks removes them and prints one `workflow-rollback` line, with no `added` lines.

### Splitting a stage

A stage with `split: true` may be split into parts before its first attempt, normally at the spec approval, along the spec's phase table: `run.py stage <instance> split <stage> --part "<title>" --meta scope=<the part's files>`. The first call names part 1, the stage's own task; each later call creates a part with the same upstream dependencies, and every stage after it then depends on all parts. A part whose files overlap a sibling's must name it with `--depends <id>`. Do not split by estimate alone.

### Picking a workflow

`run.py workflows --pick-prompt --seed <n> --title "<title>" --notes-file <file> [--scope "<paths>"]` prints the prompt that asks which workflow fits a piece of work: the task text, the workflows as `A. <name>: <description>` with `unsure` among them, and the answer format `PICK: <name|unsure>`, `WHY: <one line>`. `--seed` is required and fixes the order of the options; the same seed gives the same order, and another seed may give another. A broken workflow file is left out of the prompt, with a `warn:` line on stderr (a `warnings` list with `--json`); a broken `stages.toml` stops the command.

Two answers, then one workflow. The Manager's own typed answer comes first; one non-fork Sonnet subagent gives the second, from the same prompt rendered with seed `n+1`. `run.py add "<title>" --pick "<a>,<b>" --seed <n> ...` (leave out `--workflow`) resolves them, and `run.py workflows --resolve "<a>,<b>"` shows the result without creating anything. Each answer is a workflow name or `unsure`.

| Answers | Result |
|---------|--------|
| the same name | that workflow |
| two different names | the one with fewer required stages, then fewer stages with an approval, then the name; `heavier` takes the other |
| a name and `unsure` | the name |
| both `unsure` | `figure-it-out`; `heavier` takes the heaviest workflow |

`figure-it-out` is outside the light-to-heavy order: it wins only when both answers name it or both are `unsure`, and a named workflow beats it. `[workflow_policy] when_unsure` is `lighter` (the default), `heavier` or `figure-it-out`; with `figure-it-out`, every row that has an `unsure` or a disagreement takes it. The Manager never asks the owner which workflow to use.

The record of the instance (`workflow_record.pick`) holds both answers, the seeds, the workflow resolved, the resolution rule (`agree`, `fewer-stages`, `more-stages`, `name-over-unsure`, `named-over-deciding`, `both-unsure`, `when-unsure-<mode>`; `named` for `--workflow`) and `unsure`. `add` prints a `workflow-picked` line and the pick in its `workflow-added` line. The unsure picks and rule changes of a period are in the Workflow picks section of `run.py status` and in the daily digest. `notifications.events` may list `workflow-pick`, which queues one notice for each of them; it is not in the default list. The owner overrides a choice with `run.py stage <instance> rechoose <workflow> --by operator [--note "<why>"]`, which replaces the stages while no stage has started, applies the rules again and is recorded under `overrides`.

### Hard rules

A `[[workflow_rule]]` with `require_stage = "spec"` matches the SCOPE write paths of the instance (`match_paths`, globs) or its `area` meta (`match_area`), never the words of the title. When a rule matches:
- the required stage is optional in the picked workflow: `add` forces it on, as if `--with` named it (a billing fix becomes `fix --with spec`);
- the picked workflow has no such stage: the work moves to the lightest workflow that has one for every matching rule (fewest stages, then fewest approvals, then name);
- `--skip` of a stage that a rule requires is refused; nothing skips it later;
- the picked workflow decides its own stages (`figure-it-out`): the rule is recorded as `deferred-to-expand` and applies when the stages are created.

Each match is a `workflow-rule` line and a row in `workflow_record.rules` (`rule`, `action`: `satisfied`, `forced-with`, `moved` with `from` and `to`, `matched`, `deferred-to-expand`, `recheck-satisfied` or `recheck-missing`). `run.py stage <instance> recheck` matches the rules again against the paths of the stages and the `area`; run it after the SCOPE of a stage changes (`stage split` does it for the part it adds). A rule that is new to the record gets a line, and one whose stage the instance lacks gets the way out: `rechoose` while no stage has started, otherwise the escalation command (`run.py stage <instance> escalate <type> --before <stage> --rule <name>`, see [Changes in flight](#changes-in-flight)). `recheck` raises the approvals that are not done to the level of a rule that matched late, and sets its risk on the stages that have not started; a stage whose approval was `auto` and that a rule raises gets its approval decision at that moment (pending, or open when every part has merged), and the stages after it that have not started wait for it.

### Changes in flight

Four commands change an instance after it started; `run.py stage <instance> <action>` runs each. They bound each other (no flapping): at most `[workflow_policy] max_adjustments` (default 2) escalations plus downgrades per instance (the owner's `rechoose` does not count), one escalation per stage type, and at most `max_replacements` (default 1) replacements per stage. Past a limit the command is refused with the need named; the Manager puts it in its report and never asks the owner. `TLA+`: `model/Workflow.tla` checks these rules; `model/NOTES.md` ("Guidance for W4") says what each command must keep.

| Command | When | Effect |
|---|---|---|
| `escalate <type> --before <stage> --why "..." [--from-row R] [--rule <name>]` | `record` prints an `escalation-hint`: a worker's `Follow-ups:` line labelled `design:` (any status), or a verifier's `blocking[design]:` finding, on a stage task. A rule that matched late (`recheck-missing`) names it too. The Manager runs the hint itself, with no question to the owner | A new stage (normally `spec`, from the stage library, `stage_origin=escalate`) with its approval decision goes in front of the stage. It depends on the stage's upstream; the stage, and every part of it, now also depends on the new stage and its approval. |
| `downgrade <stage> --why "..."` | The stage is optional (made by `--with`) and has no attempt; no rule requires it and no escalation added it | The stage's upstream tasks and approval decisions move to the stages after it (as `add` does for a stage it leaves out), its approval closes (`skipped`), and the stage is done with `stage_state=skipped`. Marking it done alone would let a stage after it start before the skipped stage's upstream was approved. |
| `replace <stage>` | Only after `stage-orphaned`: a task of the stage was abandoned | A new task for the stage, with the same dependencies and approval decision; the tasks that waited for the abandoned one wait for it; the abandoned one leaves the instance. |
| `cancel --why "..."` | Only after `stage-orphaned` | Every stage that has not started is skipped, every stage that has, in a parallel branch too, is abandoned (marked `abandoned=cancelled`, its sessions stop), every approval closes, and the instance is marked ended. A task that waits for the instance never starts; the `workflow-cancelled` line lists it, the queued `decision` notices of the closed approvals are dropped, and one `workflow-cancelled` notice (when `notifications.events` lists it) names the waiting tasks. |

`escalate` refuses a stage with a busy session, an attempt with a passing verdict (`close` it), an attempt at the 3-attempt cap whose newest row is a failure (the next launch would be refused: `abandon`, or `launch --attempt 4`), a `--rule` that is not a configured rule, a verifier that has filed no row, a merged part or one that waits for its merge, an abandoned part, a stage in a round, and an instance that ended. When a part has reported, the escalation stops its idle sessions (a revision can no longer follow), commits its WIP and files one `STOPPED` row with the `Head:` and `Reason: escalated`. `record` reads that row before the verifier and verdict rows, and its next step is `launch`, which waits for the new stage and its approval. That launch does not use an attempt of the 3-attempt cap: `refuse_past_cap` reads the row (not `--cause escalated`, which only records why the attempt starts). A failed verdict keeps the task's phase `verdict_failed`; a `reported` or `verifying` task goes to `stopped`.

`figure-it-out` has no other stage until the investigation is done. `run.py stage <instance> expand --from-row <result id>` reads the `workflow-plan` block of the merged investigate stage's report (`workflow: <name>`, or `stages: [{id: spec}, {id: impl, after: [spec]}]` for an ad-hoc plan, recorded as workflow `adhoc`), applies the hard rules that were deferred to it (whatever SCOPE `--meta scope=` names now; the deferred row gets a `resolved` entry) and the rules that match the paths of the instance, and creates the stages: every first stage depends on the investigate stage and on its approval. `expand --workflow <name>` does the same without a plan row. An ad-hoc plan that lacks a stage a rule requires is refused. An instance expands once.

### An example flow

A bug in the export code, on a project that has a billing rule. Every command is one the Manager runs; the owner sees the lines it reports.

```
# 1. Pick. Print the prompt, answer it yourself (PICK: fix), and give the same prompt with seed 8 to one Sonnet subagent (it says: unsure).
run.py workflows --pick-prompt --seed 7 --title "Export drops rows" --notes-file notes.md --scope "src/export/"

# 2. Add. "fix" and "unsure" resolve to fix; the record keeps both answers, the seeds, the rule and unsure = true.
run.py add "Export drops rows" --pick "fix,unsure" --seed 7 --notes "$(cat notes.md)" \
    --meta scope="src/export/" verify="pytest tests/test_export.py" --independent "bug report"
#   -> workflow-added #41 fix: stages impl #42, test #43 (pick fix/unsure -> fix (name-over-unsure; unsure -> lighter))

# 3. Run impl as any task (launch, verify, close). The verifier files `blocking[design]: the row model is undefined`.
#    record prints an escalation-hint whose next step is the command in 4.
# 4. Escalate. A spec stage and its approval go in front of impl. The attempt that had reported is stopped and does not count
#    toward the 3-attempt cap.
run.py stage 41 escalate spec --before impl --from-row 812 --why "the row model is undefined"

# 5. Run spec, merge it, then approve it. Manager approval checks workflow facts only.
run.py stage 41 approve spec --by manager
# 6. Split, in a feature instance #50 (only a stage with split: true can be split; fix has none). After the spec's approval, the Manager
#    follows the spec's phase table, one part for each phase after the first:
run.py stage 50 split impl --part "Phase 2: export writer" --meta scope=src/export/writer.py

# 7. If a stage's session is abandoned for good, record prints stage-orphaned. Replace it once, or cancel the instance.
run.py stage 41 replace impl
run.py stage 41 cancel --why "the export moves to the new service"
```

After step 2 the owner's reply or digest lists the pick. An owner who disagrees runs `run.py stage 41 rechoose change --by operator` before any stage starts; that is recorded as an override. The retro reads all of this: [Running a workflow retro](operations.md#running-a-workflow-retro).

## Judgement-tier brief

The ROLE section of a worker brief for a task on the `judgement` tier ends with one line: for reading or searching code,
start a non-fork Sonnet subagent with a narrow question and use its answer; do not read large files yourself. A
`[models.overrides]` key whose model is Opus or Fable gets it too. A rebase round and the other tiers do not get it.
