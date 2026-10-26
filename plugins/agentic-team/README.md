# agentic-team

A Manager agent that runs project work through [Taskgraph](../taskgraph). It
writes briefs for ready tasks, launches a background worker session for each
in its own git worktree, reads the results the workers file in Taskgraph,
verifies them, and reports from Taskgraph data. Taskgraph owns the plan, task
state, and worker results. The Manager owns briefs, sessions, verification,
and integration. Workers do the work and commit it on their own branch.

The design adapts the playbook, and principle structure of
[pstack](https://github.com/cursor/plugins/tree/main/pstack) by Lauren Tan
(MIT).

## Install

```text
/plugin install agentic-team@ronica-skills
```

This also installs its dependency, `taskgraph`. Select `agentic-team:manager`
in the agent picker, or mention `@agent-agentic-team:manager`.

The scripts need Python 3.11 or later.
[scripts/python-path.sh](scripts/python-path.sh) finds one (`python3.13`,
`python3.12`, `python3.11`, then `python3`). Set `AGENTIC_TEAM_PYTHON` to an
interpreter path to choose one yourself.

## Set up a project

Run `/agentic-team:setup` in the repository. It creates `.agentic-team.toml`
from [the template](templates/agentic-team.toml), fills what it can find,
asks for the rest, and gitignores `.agentic-team.local.toml`, the run
directory `.agentic-team/`, and the worktree directory `.claude/worktrees/`. It finishes only when `config.py check` prints
`ok`. The Manager does not start work while the check fails.

`claude --bg` refuses to start in a workspace that is not trusted. A trusted
parent folder does not count. Run `claude` once in the repository and accept
the trust prompt before the Manager launches its first worker.

## How it works

![The Manager reads config through config.py, renders briefs with brief.py from Taskgraph and the run directory, launches worker and verifier sessions, reads their results from Taskgraph, and reports to the operator](assets/diagrams/overview.svg)

| Part | Role |
|------|------|
| [Manager](agents/manager.md) | A short index: startup, playbook routing, principles, escalation, standing orders, and session rules. |
| [Playbooks](playbooks/) | One file per situation: `plan`, `launch`, `drain`, `verify-and-close`, `report`, `pickup`, and `pause`. The Manager copies the matching playbook's steps into its todo list word for word, and marks any it skips with a reason. |
| [Worker](agents/worker.md) | Each task session runs as `--agent agentic-team:worker`, in its own worktree. The worker agent holds the fixed rules and the report format (`PASS`, `ISSUES`, or `BLOCKED`), so briefs carry only task content. |
| [Principles](skills/) | One skill per principle (`principle-<name>`), hidden from automatic invocation. The Manager keeps a one-line index and reads the full rule only when it applies. |
| [Config script](scripts/config.py) | The only reader of the project config. It merges, fills defaults, validates, and answers `get`, `show`, `check`, and `model`. |
| [Brief script](scripts/brief.py) | Renders each brief from Taskgraph, the config, and the run directory. It refuses to render an unscoped task or a fourth attempt, and it writes the worker's session name and `result add` command into the brief. |
| [Status script](scripts/status.py) | Builds every status report from Taskgraph metadata, Taskgraph results, and the run directory, including done tasks whose branch is not merged. |

Three rules carry the rest:

- Completions are queue events. A worker's last action is one
  `tg result add`, and it sends no message. The Manager finds results at
  drain points, in batches, and returns to its current step.
- A worker cannot ask a question, so the brief is the product. Its task
  content comes only from Taskgraph. `brief.py` refuses a task with no
  purpose, acceptance criteria, scope, or verify command, and the Manager
  fixes the task in Taskgraph rather than writing the brief by hand.
- A worker's `PASS` is a claim. A task closes only on a verdict tied to the
  exact output: the commit SHA the worker reports.

### Task lifecycle

Nothing is patched in place. A refused brief is fixed in Taskgraph, a retry
or fix round renders a fresh brief, and a closed task unblocks the next. Only
calls that need the operator leave the loop, as gates.

Each attempt runs in its own worktree (`.claude/worktrees/task-<id>-<attempt>`),
on its own branch (`worktree-task-<id>-<attempt>`). A new worktree starts from
the default branch, so the brief gives the worker a base commit, and the
worker's first step is `git reset --keep <base>`. The base is the Manager's
`HEAD`, or the `Head` commit of the task's previous worker result in a fix
round. Before it files its report, whatever the status, the worker commits on
its branch (a `WIP task <id> attempt <n>: <status>` commit for `ISSUES` or
`BLOCKED`), so `Head` is always set and the worktree is clean. It files its
report with `tg result add`. The report names the `Branch`, the `Head` commit
SHA, and the `Worktree` path. The Manager never messages a worker; it stops one
with `claude stop`.

At a drain point the Manager finds the result, then verifies the commit: it
reruns VERIFY inside the worker's worktree, or launches a verifier in a
worktree of its own that checks out the `Head` commit. The Manager does not
merge by default. It lists the branch as ready to merge, and merges only when
the standing orders say it may, and only into the checked-out branch of a clean
main checkout. On a conflict it aborts the merge and writes a gate naming both
branches. It records a confirmed merge as `merged_at` and `merged_by`, and an
operator who says a branch is merged, by any method including squash or rebase,
counts. A task that builds on a done but unmerged branch waits, and the Manager
says so plainly in its replies and reports. After the merge it
removes every session and worktree of the task with `claude rm`, which refuses
work that is on no remote until the Manager has confirmed the merge with
`git merge-base --is-ancestor`. A session that ends with no result is recorded
as `DIED` and retried. A session stuck on a permission prompt is stopped and
recorded as `BLOCKED`. Attempt 3 is the last (`brief.py` refuses a fourth): when it fails, the task is
abandoned. Its worktrees stay, and the report lists them for the operator to
remove.

![A ready task is rendered by brief.py, launched, drained, then verified and closed, retried in a fix round, split, or gated for the operator](assets/diagrams/lifecycle.svg)

### One task, end to end

![Sequence: the Manager checks config, renders a brief, launches a worker in its own worktree, finds the worker's PASS result at a drain point, has a verifier confirm the commit, closes the task, and reports](assets/diagrams/sequence.svg)

The diagrams are rendered with [Pele](https://pele.run) from the Mermaid
sources in [assets/diagrams/](assets/diagrams/). After editing a `.mmd` file,
run `npm install -g pele` once, then
`node plugins/agentic-team/assets/diagrams/render.mjs`.

## Configuration

The project config is `.agentic-team.toml` in the repository root, in TOML.
An optional, gitignored `.agentic-team.local.toml` holds private or
machine-specific values. It is merged into the tracked file table by table;
its keys win, and a list there replaces the tracked list. Omit a key to use
its default. `""` or `[]` means the item does not apply. The string `"TODO"`
marks a value someone still has to fill in. Never put credentials or secrets
in either file.

Model values are either a model id (`"opus"`) or a table
(`{ model = "sonnet", effort = "high" }`).

### `[taskgraph]`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `project` | string | none; required | Taskgraph project name (`tg projects` lists them). |
| `plan` | string | `""` | Repository-relative plan file read as context only. |

### `[consultants]`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `sessions` | list | `[]` | Long-running sessions that workers may ask when the repository has no answer. Use bare session names. |
| `restart` | string | `""` | How the Manager restarts a consultant that is missing from `ListAgents`. |

### `[constraints]`

These become the FORBIDDEN section of every brief. They affect safety, so the
template sets the first four to `"TODO"` until someone confirms each one,
even if the answer is `""`.

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `read_only` | string | `""` | Sources workers may read but never change. |
| `pinned_versions` | string | `""` | Versions workers must not change. |
| `do_not_send` | string | `""` | Messages, requests, or data workers must never send. |
| `do_not_modify` | string | `""` | Files or areas workers must not modify. |
| `other` | list | `[]` | Further constraints, one per item. |

### `[serialization]`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `rules` | list | `[]` | Files or areas only one task may change at a time, and the order to use: `"path or area: ordering rule"`. The Manager first tries to give each task its own files, and records each ordering as a Taskgraph dependency. |

### `[progress]`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `tool` | string | `""` | A tool or command for checking session progress read-only. The Manager also checks `claude agents`, `claude logs`, output files, and the task's results. |

### `[autonomy]`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `grant` | string | `""` | Decisions and actions the Manager may take without asking. `""` means no standing grant. |
| `always_pause` | list | `[]` | Gates that always need the operator, even under the grant. |

The grant never overrides safety rules, required approvals, or constraints.
See the [decision-forks principle](skills/principle-decision-forks/SKILL.md).

### `[sessions]`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `brief_template` | string | [task-brief.md](templates/task-brief.md) | Path to a custom brief template, relative to the repository root. `config.py` resolves it to an absolute path. |
| `max_parallel` | positive integer | `4` | Cap on in-flight worker sessions. The Manager refills as sessions finish. |
| `permission_mode` | string | `"auto"` | `--permission-mode` for worker sessions. |
| `launch_outside_sandbox` | boolean | `false` | `true` lets the Manager retry `claude --bg` outside the Bash sandbox when the sandbox blocks it. |
| `timezone` | string | System zone (`/etc/localtime`), else `"UTC"` | IANA zone name, for example `"Asia/Singapore"`. Used for all recorded times. |
| `timezone_label` | string | Derived from `timezone` | Label written after times, for example `"SGT"`. Set it when the derived label is an offset such as `+08`. |

### `[models]`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `mechanical` | model | `"haiku"` | Sweeps, counts, diffs, summaries. Use an alias: an older pinned id such as `claude-haiku-4-5-20251001` drops out of `auto` mode in a `--bg` worker and waits on a permission prompt. |
| `implementation` | model | `{ model = "sonnet", effort = "high" }` | Well-scoped build or edit work with a known answer shape. |
| `judgement` | model | `"opus"` | Judgement, review, prose readers rely on, long unattended runs. |
| `verifier` | model | unset | Verification sessions. Unset means a different model from the worker's: `opus`, or `sonnet` if the worker ran on `opus`. |
| `overrides` | table | `{}` | `[models.overrides]` maps a work type to a model, for example `"data migration" = { model = "opus", effort = "high" }`. Matched case-insensitively before the tiers. |

### `[notifications]`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `skill` | string | `""` | Skill for messages when all work is complete or the Manager is blocked, for example `"telegram-send:telegram-send"`. With `""`, the Manager reports only in the conversation. |

### Reading config

Agents read config only through [scripts/config.py](scripts/config.py), run
from the repository root (or pass `--root DIR`). Workers never read it; their
brief carries what they need.

```sh
PY=$("${CLAUDE_PLUGIN_ROOT}/scripts/python-path.sh")
C="$PY ${CLAUDE_PLUGIN_ROOT}/scripts/config.py"
$C check                          # every problem, one per line; else "ok"
$C get sessions.max_parallel      # one value; tables and lists print as JSON
$C get models --json              # always JSON
$C show                           # the merged config with defaults filled in
$C model implementation           # {"model": "sonnet", "effort": "high"}
$C model "data migration"         # a models.overrides key, else a tier
```

`check` reports a missing file, TOML syntax errors with their line, `"TODO"`
values, an empty `taskgraph.project`, unknown sections or keys (with the
closest known key), wrong types, invalid time zones, and a missing brief
template. `get` and `model` refuse to answer while `check` fails. Exit codes:
0 OK, 2 config problem, 1 unexpected error. It needs Python 3.11 or later;
`scripts/python-path.sh` finds one.

## Briefs

Each worker brief has these sections: GOAL, SCOPE, CONTEXT, ACCEPTANCE,
VERIFY, TIMEBOX, FORBIDDEN, AUTONOMY, STANDING ORDERS, and REPORT (the
command that files the report). The report format lives in the worker agent.
[scripts/brief.py](scripts/brief.py) fills the template. Task content is copied from Taskgraph, never written by
hand. A custom template may reorder or reword the sections and use any of these
placeholders; an unknown placeholder stops the render:

| Placeholder | Value |
|-------------|-------|
| `{{TASK_ID}}`, `{{TASK_TITLE}}`, `{{PROJECT}}` | Task and project |
| `{{SESSION_NAME}}`, `{{TIMEZONE}}` | The worker's own session name (`task-<id>-<attempt>-<keyword>`, or `verify-<id>-<attempt>`) and the time-zone label |
| `{{GOAL}}` | Task title, plus the prose in its notes (why it is needed). Any `Word: text` line other than `Exit test:` and `Acceptance:` stays in the prose. |
| `{{SCOPE}}` | `scope` meta, plus `serialization.rules` |
| `{{TASKGRAPH_COMMAND}}`, `{{PLAN_FILE}}`, `{{CHECKPOINT}}`, `{{CONSULTANTS}}` | Context pointers. `{{CHECKPOINT}}` is the `Checkpoint:` line of this task's latest worker result. |
| `{{BASE}}` | The commit the worker resets its worktree to: the `Head:` of this task's previous worker result, else the Manager's `git rev-parse HEAD`. |
| `{{UPSTREAM}}` | This task's previous result (fix rounds), then the latest result of each task it depends on, in full. Both come from the Taskgraph result log, and results the Manager wrote itself (`DIED`, `BLOCKED`) are skipped. |
| `{{ACCEPTANCE}}` | `- [ ]` checklist items and `Exit test:` or `Acceptance:` lines in the notes |
| `{{VERIFY}}` | `verify` meta |
| `{{TIMEBOX}}` | Twice the `estimate` meta in hours; 2 hours without an estimate |
| `{{FORBIDDEN}}` | `[constraints]` |
| `{{AUTONOMY}}` | `autonomy.grant` and `autonomy.always_pause` |
| `{{STANDING_ORDERS}}` | `.agentic-team/standing-orders.md`, verbatim |
| `{{RESULT_COMMAND}}` | The exact `tg result add` command the worker runs last: the interpreter, `tg.py`, and the database (`$TASKGRAPH_DB`, else `~/.taskgraph/tasks.db`) by absolute path, with the `--kind`, `--attempt`, and `--by` set. The worker fills in only the status and the body. A template without it is refused. |

[verifier-brief.md](templates/verifier-brief.md) also uses `{{WORKER_REPORT}}`
(the worker's result, chosen with `--report <result id>`, else the latest for
the current attempt) and `{{VERDICT_REF}}`.

The worker runs `result add` from its own session, so its permission mode
must allow that command. Pin `--db` and allow only `--body-file -` if you
write a permission rule for it. In `auto` mode nothing enforces that rule: the
brief gives the worker the paths to `tg.py` and the database, and only the
worker's instructions keep it to the one `result add` command.

## Run directory

The Manager keeps run state in the gitignored `.agentic-team/`:

| Path | Content |
|------|---------|
| `standing-orders.md` | Numbered operator directives, pasted into every brief and resume. `STOP: <reason>` as the first line halts launches. A line can also allow the Manager to merge verified branches. |
| `gates.md` | Decisions that need the operator, each with options and a default. |
| `briefs/task-<id>-<attempt>.md` | Every brief sent, as rendered. A record only; never edited or read as a source. |
| `handoff.md` | Written by the pause playbook and read by pickup. |
| `last-report` | Time of the last status report. |

## Results

Worker reports live in the Taskgraph result log, not in files. Each result has
a `kind`, a `status`, an `attempt`, and an author (`--by`):

| Kind | Status | Written by | Meaning |
|------|--------|------------|---------|
| `task` | `PASS`, `ISSUES`, `BLOCKED` | The worker, as its last action | The report: Task, Status, Branch, Head, Worktree, Ran, Files, Issues, Deviations, Follow-ups, Checkpoint. |
| `task` | `DIED`, `BLOCKED` | The Manager (`--by manager`) | `DIED`: a session that ended with no result. `BLOCKED`: a session stopped while waiting on a permission prompt. |
| `verify` | `PASS`, `ISSUES`, `BLOCKED` | The verifier | The same report, plus a `Verdict:` line. |

`tg result ls <id>` lists them. An attempt has arrived when a result exists
for the task's current `attempt` and the task has no `verdict`.

## Task metadata

Task notes hold the purpose and acceptance criteria, following the Taskgraph
skill. Metadata holds everything else:

| Key | Set by | Meaning |
|-----|--------|---------|
| `scope`, `verify`, `tier`, `risk` | plan | Brief inputs. `risk=high` sends verification to a separate session. |
| `estimate` | plan | Taskgraph's own estimate in hours. The worker's timebox is twice it. |
| `started_at`, `session`, `model`, `attempt` | launch | The current attempt. |
| `merged_at`, `merged_by` | verify-and-close | Set when the task's branch is confirmed merged. `merged_by` is `manager` or `operator`; a squash or rebase merge needs the operator's word. A done task with a commit `verdict_ref` and no `merged_at` is listed as "Done, branch not merged", and tasks that depend on it do not launch. |
| `abandoned` | drain | One word: `died`, `tool-error`, `stuck`, or `unknown`. Set when attempt 3 has failed. Only this marker lists a task as abandoned. |
| `verdict`, `verdict_ref`, `verified_by` | verify-and-close | `artifact-verified`, `test-verified`, `check-only`, `verify-blocked`, or `verify-failed`, tied to the worker's `Head:` commit SHA (or to output checksums when the output is outside git). |
| `ended_at`, `tokens_output`, `tokens_input`, `tokens_cache_read`, `tokens_cache_write` | verify-and-close | From [tokens.py](scripts/tokens.py), which finds the transcript under the worker's worktree path. |

## Layout

| Path | Purpose |
|------|---------|
| `agents/manager.md` | The Manager index |
| `agents/worker.md` | The worker agent used for every task and verifier session |
| `playbooks/` | Step-by-step procedures the Manager follows |
| `skills/principle-*/` | One principle each, hidden from automatic invocation |
| `skills/setup/` | `/agentic-team:setup`, which creates the project config |
| `templates/` | Project config (`agentic-team.toml`), task and verifier briefs, standing orders, and gates |
| `assets/diagrams/` | Mermaid sources for the README diagrams, their SVGs, and `render.mjs` (Pele) |
| `scripts/tg-path.sh` | Finds the installed Taskgraph CLI. `TASKGRAPH_TG` overrides it. |
| `scripts/python-path.sh` | Finds a Python 3.11 or later. `AGENTIC_TEAM_PYTHON` overrides it. |
| `scripts/tokens.py` | Reads end time and token counts from a session transcript, found by the worker's worktree path |
| `scripts/config.py` | Reads, merges, and validates the project config; holds every default |
| `scripts/brief.py` | Renders task and verifier briefs from Taskgraph data |
| `scripts/status.py` | Builds the status report from Taskgraph data |
| `tests/` | Tests for the scripts. Run `"$PY" -m unittest discover plugins/agentic-team/tests`, with `PY` from `python-path.sh`. |

## Extending

- **A principle.** Add `skills/principle-<name>/SKILL.md` with
  `disable-model-invocation: true` and a description that starts with
  "Apply when". Add one row to the Principles table in
  `agents/manager.md`. If workers need it, point to it from
  `agents/worker.md`.
- **A playbook.** Add `playbooks/<name>.md` with numbered steps and a
  **Reply** line. Add one row to the Playbooks table in `agents/manager.md`.
- **A skill.** Use a short name; the plugin namespace already applies, so
  `skills/review/` becomes `/agentic-team:review`. Add settings to the
  project config only if they describe the project.
- **A project setting.** Add the key, with its type and default, to `SCHEMA`
  in [scripts/config.py](scripts/config.py), then document it under
  Configuration above and in [the template](templates/agentic-team.toml).
  Read it with `config.py get`.
- **Preloading.** The Manager's `skills:` list preloads only when it runs as a
  subagent; as the main agent it loads them itself (see `agents/manager.md`).
  Use qualified `plugin:skill` names, and keep the list short. Skills with
  `disable-model-invocation: true` cannot be preloaded, which is why
  principles are read by path.
