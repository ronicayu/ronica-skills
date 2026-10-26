# agentic-team

A Manager agent that runs project work through [Taskgraph](../taskgraph). The
Manager runs one script, `run.py`, for every state change. The script launches
a background worker session for each ready task in its own git worktree, reads
the results the workers file in Taskgraph, verifies them, closes and merges
verified work, and reports from Taskgraph data. Taskgraph owns the plan, task
state, and worker results. The Manager owns the plan content, the judgement
calls, and the contact with the operator. Workers do the work and commit it on
their own branch.

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

![The Manager reads config through config.py and runs run.py, one command per step. run.py renders briefs from Taskgraph and the run directory, launches worker and verifier sessions, and reads their results from Taskgraph. The Manager reports to the operator](assets/diagrams/overview.svg)

| Part | Role |
|------|------|
| [Manager](agents/manager.md) | A short index: startup, playbook routing, principles, escalation, standing orders, and session rules. |
| [Playbooks](playbooks/) | One file per situation: `plan`, `run`, `report`, and `pause`. The Manager copies the matching playbook's steps into its todo list word for word, and marks any it skips with a reason. |
| [Worker](agents/worker.md) | Each task session runs as `--agent agentic-team:worker`, in its own worktree. The worker agent holds the fixed rules and the report format (`PASS`, `ISSUES`, or `BLOCKED`), so briefs carry only task content. |
| [Principles](skills/) | One skill per principle (`principle-<name>`), hidden from automatic invocation. The Manager keeps a one-line index and reads the full rule only when it applies. |
| [Config script](scripts/config.py) | The only reader of the project config. It merges, fills defaults, validates, and answers `get`, `show`, `check`, and `model`. |
| [Run script](scripts/run.py) | Launches, drains, verifies, closes, merges, stops, abandons, and reports. It refuses an unscoped task, a fourth attempt, a launch under `STOP`, and a merge without a `MERGE:` line or into a dirty checkout. It matches sessions to tasks by worktree path, never by name. |

Three rules carry the rest:

- Completions are queue events. A worker's last action is one
  `tg result add`, and it sends no message. The Manager runs `run.py record`
  at drain points, reads one line per event, and returns to its current step.
- A worker cannot ask a question, so the brief is the product. Its task
  content comes only from Taskgraph. `run.py launch` refuses a task with no
  purpose, acceptance criteria, scope, or verify command, and the Manager
  fixes the task in Taskgraph rather than writing the brief by hand.
- A worker's `PASS` is a claim. A task closes only on a verdict tied to the
  exact output: the commit SHA the worker reports.

### Task lifecycle

Nothing is patched in place. A refused launch is fixed in Taskgraph, a retry
or fix round renders a fresh brief, and a closed task unblocks the next. Only
calls that need the operator leave the loop, as Taskgraph `decision` nodes.

`run.py launch <id>` renders the brief and starts the worker in its own
worktree (`.claude/worktrees/task-<id>-<attempt>`), on its own branch
(`worktree-task-<id>-<attempt>`). A new worktree starts from the default
branch, so the brief gives the worker a base commit, and the worker's first
step is `git reset --keep <base>`. The base is the Manager's `HEAD`, or the
`Head` commit of the task's previous worker result, or of a stopped attempt's
WIP commit. Before it files its report, whatever the status, the worker
commits on its branch (a `WIP task <id> attempt <n>: <status>` commit for
`ISSUES` or `BLOCKED`), so `Head` is always set and the worktree is clean. It
files its report with `tg result add`. The report names the `Branch`, the
`Head` commit SHA, and the `Worktree` path. The Manager never messages a
worker.

`run.py record` finds the result, one line per event. A session that ends with
no result is filed as `DIED` and retried; a complete report in `claude logs`
is filed as the worker's own. A session stuck on a permission prompt is
stopped and filed as `BLOCKED`. Attempt 3 is the last (`launch` refuses a
fourth): when it fails, `run.py abandon` marks the task abandoned. Its
worktrees stay, and the report lists them for the operator to remove.

The Manager then verifies the commit. For a `risk=low` task it reruns VERIFY
inside the worker's worktree. For a `risk=high` task, `run.py verify` starts a
verifier in a worktree of its own that checks out the `Head` commit. Then
`run.py close` records the verdict and the token counts, runs `tg done`, and
merges only when a standing-orders line starts with `MERGE:`, and only into
the checked-out branch of a clean main checkout. Without that line, `close`
lists the branch as ready to merge. On a conflict it aborts the merge and
prints the decision to add, naming both branches. A confirmed merge is
recorded as `merged_at` and `merged_by`. When the operator says a branch is
merged, by any method including squash or rebase, `run.py merged <id>` records
it. A task that builds on a done but unmerged branch waits, and the Manager
says so plainly in its replies and reports. After the merge, `run.py` removes
every session and worktree of the task with `claude rm`. `claude rm` refuses
work that is on no remote, so the script passes `--discard-unpushed` only for
a commit that `git merge-base --is-ancestor` finds in `HEAD`. It never deletes
a file and never forces a worktree removal.

A question only the operator can answer is a Taskgraph `decision` node that
`--blocks` the tasks it holds back. Blocked tasks leave `ready` by themselves,
and `run.py record` and `run.py status` list the open decisions.

A pause adds `STOP: ...` as the first standing-orders line. `run.py stop <id>`
stops a worker that cannot finish soon and files a `STOPPED` result. Once the
session has exited, `run.py record` commits the worktree's uncommitted work as
a WIP commit and files a second `STOPPED` row with its `Head`. The next
attempt starts fresh from that commit; there is no resume. A stopped attempt
does not count as a failure.

![A ready task is launched by run.py, recorded, then verified and closed, retried in a fix round, split, or turned into a decision for the operator](assets/diagrams/lifecycle.svg)

### One task, end to end

![Sequence: the Manager checks config, launches a worker with run.py, finds the worker's PASS result with run.py record, has a verifier confirm the commit, closes the task, and reports](assets/diagrams/sequence.svg)

The diagrams are rendered with [Pele](https://pele.run) from the Mermaid
sources in [assets/diagrams/](assets/diagrams/). After editing a `.mmd` file,
run `npm install -g pele` once, then
`node plugins/agentic-team/assets/diagrams/render.mjs`.

## `run.py`

[scripts/run.py](scripts/run.py) is the only writer of run state. The Manager
runs it from the repository root, with `PY` from `python-path.sh`:
`"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/run.py" [--root DIR] [--tg PATH] [--run-dir DIR] [--json] <command>`.
Nothing in it waits, sleeps, or polls: `claude --bg` returns at once, and the
Manager runs `record` later.

| Command | What it does |
|---------|--------------|
| `launch <id>` | Renders the brief, starts the worker, and records `session`, `model`, `attempt`, and `started_at`. Options: `--keyword`, `--tier`, `--model`, `--effort`, `--attempt`, `--dry-run`. If an open task already has a live session, it records the start instead (`repaired`). |
| `verify <id>` | Starts a verifier for a `PASS` result, pinned to its `Head`. Options: `--ref`, `--result`, `--model`, `--effort`, `--again`, `--dry-run`. |
| `record` | Reads the queue and prints one line per event: results that arrived, dead, stuck, and stopped sessions, verdicts, merges, open decisions, free slots, and ready tasks. |
| `close <id>` | Records the verdict and tokens, runs `tg done`, and merges or lists the branch as ready to merge. Options: `--verdict`, `--ref`, `--ran`. Rerun it if it stopped after `tg done`: it resumes at the merge. |
| `merged <id>` | Records that the operator merged a task branch (`--by operator`, the default), then removes its sessions and worktrees. |
| `stop <id>` | Stops a worker for a pause and files a `STOPPED` result. |
| `abandon <id> <mode>` | Marks a task abandoned after attempt 3 failed. `mode` is `died`, `tool-error`, `stuck`, or `unknown`. |
| `status` | Prints the status report as Markdown tables. Options: `--since`, `--limit`, `--mark`. |

Each event is one line: `<event> #<id> attempt <n>: <detail>`, followed by
` | next: <step>` when a step follows. `--json` prints one array of
`{"event", "task", "attempt", "session", "detail", "next"}` objects and nothing
else on stdout (`status --json` prints one object). Refusals go to stderr as
`run.py: <message>`.

| Exit code | Meaning |
|-----------|---------|
| 0 | The command ran. An event may still say `died` or `kept`. |
| 1 | A tool failed: `tg`, `git`, or `claude`. |
| 2 | The command refused. The message names the fix. |
| 3 | The standing orders say `STOP`. Only `launch` returns it. |

`run.py` finds `tg.py` through `--tg`, then `$TASKGRAPH_TG`, then
`scripts/tg-path.sh`. It matches a live session to its task by the session's
working directory, which ends `.claude/worktrees/<task|verify>-<id>-<attempt>`
in this repository. It never uses names, because `claude agents --all` lists
every project on the machine. A session that `claude stop` ended shows `state`
`stopped`, no `status`, and an unrelated directory. `run.py` counts it as exited
and ties it to a task only through the `Session: <id>` line of the result it
filed when it stopped that session (`stop`, a stuck session, `close`,
`abandon`); it derives the worktree path from the task and attempt. A worker
that the operator stopped by hand has no such line, so `run.py` treats it as no
session.

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

### `[constraints]`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `forbidden` | list | `[]` | One rule per item; they become FORBIDDEN in every brief. The template sets `["TODO"]` until someone confirms the list, even if it ends up empty. |

### `[autonomy]`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `grant` | string | `""` | Decisions and actions the Manager may take without asking. `""` means no standing grant. |
| `always_pause` | list | `[]` | Decisions that always need the operator, even under the grant. |

The grant never overrides safety rules, required approvals, or constraints.
See the [decision-forks principle](skills/principle-decision-forks/SKILL.md).

### `[sessions]`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `max_parallel` | positive integer | `2` | Cap on in-flight sessions, workers and verifiers. Start with 1 or 2. The Manager refills as sessions finish. |
| `permission_mode` | string | `"auto"` | `--permission-mode` for worker sessions. |
| `timezone` | string | System zone (`/etc/localtime`), else `"UTC"` | IANA zone name, for example `"Asia/Singapore"`. Used for all recorded times. |
| `timezone_label` | string | Derived from `timezone` | Label written after times, for example `"SGT"`. Set it when the derived label is an offset such as `+08`. |

### `[models]`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `mechanical` | model | `"haiku"` | Sweeps, counts, diffs, summaries. Use an alias: an older pinned id such as `claude-haiku-4-5-20251001` drops out of `auto` mode in a `--bg` worker and waits on a permission prompt. |
| `implementation` | model | `{ model = "sonnet", effort = "high" }` | Well-scoped build or edit work with a known answer shape. |
| `judgement` | model | `"opus"` | Judgement, review, prose readers rely on, long unattended runs. |
| `verifier` | model | unset | Verification sessions. Unset means a different model from the worker's: `opus`, or `sonnet` if the worker ran on `opus`. |
| `overrides` | table | `{}` | `[models.overrides]` maps a work type to a model, for example `"data migration" = { model = "opus", effort = "high" }`. Matched case-insensitively before the tiers. A task's `tier` meta may name an override key. |

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
closest known key), wrong types, and invalid time zones. `get` and `model`
refuse to answer while `check` fails. Exit codes: 0 OK, 2 config problem, 1
unexpected error. It needs Python 3.11 or later; `scripts/python-path.sh` finds
one.

## Briefs

[templates/task-brief.md](templates/task-brief.md) is the one brief template.
Its sections are GOAL, SCOPE, CONTEXT, ACCEPTANCE, VERIFY, TIMEBOX, FORBIDDEN,
AUTONOMY, STANDING ORDERS, and REPORT (the command that files the report). The
report format lives in the worker agent. `run.py` fills the template from
Taskgraph, the config, and the run directory. Task content is copied from
Taskgraph, never written by hand: GOAL is the title plus the prose in the
notes, ACCEPTANCE is the `- [ ]` items and `Exit test:` or `Acceptance:` lines,
SCOPE and VERIFY are the `scope` and `verify` meta, and TIMEBOX is twice the
`estimate` meta (2 hours without one). CONTEXT holds the base commit, the last
checkpoint, the previous report of a fix round, and the latest report of each
task this one depends on. To change the brief for every task, edit the
template. `run.py verify` fills the same template, with verifier values in
GOAL, SCOPE, SETUP, UPSTREAM, and AUTONOMY, and a `Verdict:` line request in
REPORT.

The worker runs `result add` from its own session, so its permission mode
must allow that command. Pin `--db` and allow only `--body-file -` if you
write a permission rule for it. In `auto` mode nothing enforces that rule: the
brief gives the worker the paths to `tg.py` and the database, and only the
worker's instructions keep it to the one `result add` command.

## Run directory

The Manager keeps run state in the gitignored `.agentic-team/`:

| Path | Content |
|------|---------|
| `standing-orders.md` | Numbered operator directives, pasted into every brief. `STOP: <reason>` as the first line halts launches. A line that starts with `MERGE:` lets the Manager merge verified branches into a clean main checkout. |
| `briefs/task-<id>-<attempt>.md` | Every brief sent, as rendered (`-verify` for a verifier brief, `-verify-<k>` for a second one). A record only; never edited or read as a source. |
| `last-report` | Time of the last status report. |

## Results

Worker reports live in the Taskgraph result log, not in files. Each result has
a `kind`, a `status`, an `attempt`, and an author (`--by`):

| Kind | Status | Written by | Meaning |
|------|--------|------------|---------|
| `task` | `PASS`, `ISSUES`, `BLOCKED` | The worker, as its last action | The report: Task, Status, Branch, Head, Worktree, Ran, Files, Issues, Deviations, Follow-ups, Checkpoint. |
| `task` | `DIED`, `BLOCKED` | The Manager (`--by manager`) | `DIED`: a session that ended with no result. `BLOCKED`: a session stopped while waiting on a permission prompt. A worker report that the Manager copied from `claude logs` keeps the worker's own status. |
| `task` | `STOPPED` | The Manager | A worker stopped for a pause (a second row carries the WIP commit `Head:`), or a session `close` stopped. |
| `task` | `ABANDONED` | The Manager | A session `abandon` stopped. |
| `verify` | `PASS`, `ISSUES`, `BLOCKED`, `DIED` | The verifier or the Manager | The verifier files the same report plus a `Verdict:` line. The Manager files its own verdict for a `risk=low` task, and `DIED` for a verifier that ended with no result. |

`verify` results by `manager` carry `Verdict:` and `Ran:`. Every row filed when
`run.py` stops a session carries `Session: <id>` and `Worktree: <path>` lines.

`tg result ls <id>` lists them. An attempt has arrived when a result exists
for the task's current `attempt` and the task has no `verdict`.

## Task metadata

Task notes hold the purpose and acceptance criteria, following the Taskgraph
skill. Metadata holds everything else, 15 keys:

| Key | Set by | Meaning |
|-----|--------|---------|
| `scope`, `verify`, `tier`, `risk` | plan | Brief inputs. `tier` is a tier name or a `models.overrides` key. `risk=high` sends verification to a separate session. |
| `estimate` | plan | Taskgraph's own estimate in hours. The worker's timebox is twice it. |
| `started_at`, `session`, `model`, `attempt` | `launch` | The current attempt, and when it started. |
| `verdict`, `verdict_ref` | `close` | `artifact-verified`, `test-verified`, `check-only`, `verify-blocked`, or `verify-failed`, tied to the worker's `Head:` commit SHA (or to output checksums when the output is outside git). |
| `tokens` | `close` | `"<out>/<in>"`, from the session transcript under the worker's worktree path. The cache counts are printed on the `tokens` event line. |
| `merged_at`, `merged_by` | `close`, `merged`, `record` | Set when the task's branch is confirmed merged. `merged_by` is `manager` or `operator`; a squash or rebase merge needs the operator's word. A done task with a commit `verdict_ref` and no `merged_at` is listed as "Done, branch not merged", and tasks that depend on it do not launch. |
| `abandoned` | `abandon` | One word: `died`, `tool-error`, `stuck`, or `unknown`. Set when attempt 3 has failed. Only this marker lists a task as abandoned. |

## Layout

| Path | Purpose |
|------|---------|
| `agents/manager.md` | The Manager index |
| `agents/worker.md` | The worker agent used for every task and verifier session |
| `playbooks/` | Step-by-step procedures the Manager follows |
| `skills/principle-*/` | One principle each, hidden from automatic invocation |
| `skills/setup/` | `/agentic-team:setup`, which creates the project config |
| `templates/` | Project config (`agentic-team.toml`), the brief, and standing orders |
| `assets/diagrams/` | Mermaid sources for the README diagrams, their SVGs, and `render.mjs` (Pele) |
| `scripts/tg-path.sh` | Finds the installed Taskgraph CLI. `TASKGRAPH_TG` overrides it. |
| `scripts/python-path.sh` | Finds a Python 3.11 or later. `AGENTIC_TEAM_PYTHON` overrides it. |
| `scripts/config.py` | Reads, merges, and validates the project config; holds every default |
| `scripts/run.py` | Launches, drains, verifies, closes, merges, stops, abandons, and reports |
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
