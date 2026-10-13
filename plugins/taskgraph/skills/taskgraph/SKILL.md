---
name: taskgraph
description: Track project tasks and their dependencies in a SQLite-backed DAG, then open an interactive graph. Use when the user wants to plan a project or programme backwards from a goal, decompose a goal into prerequisites, ask what can be worked on next or what is blocked, track dates, decisions and outside dependencies, prepare a weekly steering review, add or update tasks and dependencies, or see the plan as a picture — "work backwards from shipping v1", "what's next", "what's blocking X", "what's late", "下一步做什么", "任务依赖", "看图". Agents operate the CLI; humans view the graph.
---

# taskgraph

## When to use this skill

Use when the user wants to plan work backwards from a goal, track tasks with dependencies and dates, ask what can be done next or what is late, prepare a steering review, or see the plan as a picture. Agents drive the CLI; the user views the graph.

Trigger keywords (English): task, todo, dependency, work backwards, what's next, blocked, ready, late, agenda, programme
Trigger keywords (中文): 任务, 依赖, 计划, 下一步, 看图, 排期

## Choosing the project

Once the user names a plan, pass `--project NAME` on every command, or set `TASKGRAPH_PROJECT`. Otherwise the project falls back to the git repo name, then the directory name, and a typo silently starts a new project. `projects` lists what exists. Dependencies and parents cannot cross projects.

## Programme recipe

For a large plan (hundreds of nodes), build top-down and stay coarse:

1. `--type objective` for each programme aim.
2. `--type milestone` for each fixed point, with a date (`--due`).
3. The `--type decision` and `--type external` nodes that gate those milestones: who decides or delivers, and by when.
4. Workstream parents (a task with children, `--meta lane=<workstream>`) that depend on the gates.
5. Tasks only where the team does the work. Do not decompose a programme into half-day tasks; the half-day rule is for small personal projects only.

Work backwards: ask "what must be true before this is done?" and `add --blocks GOAL` for each answer. Put the why and acceptance criteria in `--notes`.

## Dates

All dates are `YYYY-MM-DD`, entered by hand, never computed from durations. Use the `date` command so you need not know the field names:

```bash
tg.py date ID --due 2027-01-15 --start +1w --clear start
tg.py date ID --promised 2027-02-01
```

- `--due` writes the type's own key: milestone `date`, decision `decide_by`, external `needed_by`, task and objective `due`.
- `--start`: when work begins (task) or when it was requested or ordered (external). Ignored for milestones and decisions.
- `--promised`: externals only, the date the outside party committed to. `add` takes it too.
- Values accept `today` and offsets `+3d`, `+2w`, `-1w` (`--due -1w` works). `add` takes `--start`, `--due` and `--promised` too. `start` after `due` is rejected.
- A dependency conflicts when it is due after the date its dependent needs it (the dependent's `start`, else its `due`); a child due after its parent's due conflicts; an external promised after `needed_by` conflicts. Conflicts show as `(conflict)` in `ls` and in `show`; JSON has `conflicts` per task.
- `late_days` is set for any unfinished node past `due` except objectives. A summary carries `span` (earliest start to latest due among its descendants). `$TASKGRAPH_TODAY=YYYY-MM-DD` overrides today.
- A finished summary or milestone reports `done_at` as the latest finish among what it waited for.

## Keeping it current

- A date moved: `date ID --due ...`.
- A decision was made: `done ID`, with the outcome in `edit ID --notes`.
- An external slipped: `date ID --promised ...` and `edit ID --meta chase=YYYY-MM-DD`.
- A new risk or blocker: `add` a decision or external and link it with `--blocks`.

## History

Every command that changes data records what changed (title, status, type, parent, dates, dependencies, notes, meta) in an `events` table, in the same transaction. `changes [--since 7d|2w|DATE]` reads it back as New, Started, Completed, Reopened, Slipped, Pulled in, Re-scoped (title, type, parent, dependencies, person, lane, team, a date set or cleared) and Removed. Changes are netted per task over the window, so a date moved and moved back shows nothing. History starts when this version first touches the DB; earlier changes were not recorded.

## Baselines

When the plan is agreed (a steering committee, a funding gate), run `baseline set --label "SteerCo 2026-10-13"`. It snapshots every task's start and due in the project; `--label` defaults to today and an existing label needs `--replace`. `baseline diff [--label L]` (latest by default) lists dates moved since then, milestones first and largest slip first, plus tasks added and removed since and a per-lane count of later and earlier dues. `show` prints the baseline due beside the current one, and the Timeline draws a grey tick where a bar was due at baseline. Task ids are never reused, so a baseline always refers to the same task.

## Weekly steering prep

1. `changes` for what moved since last week.
2. `agenda` groups what needs attention: Late, Conflicts, due soon (`--within DAYS`, default 14), Chase due, and decisions or externals with no date. `--type` and `--all-projects` narrow or widen it.
3. `ls --type decision` for open decisions; `ls --status done` lists completions, since `ls` hides done by default.
4. `serve` and open the Timeline view for the picture.

## Avoiding duplicates and big plans

- Run `ls --search TEXT` (title and notes, case-insensitive) before every `add`.
- Add `--brief` when scanning a big plan: it implies `--json` and cuts `ls`, `ready`, `agenda` and `show` to `id, title, type, derived_status, project, parent, lane, start, due, late_days, conflict_count` (`show` adds `depends_on` and `blocks` id lists).

## Types, parents, status

Stored as `meta.type`, absent means `task`. Unknown types are rejected; `--type task` clears it.

- `task`: work to do. Keys `owner`, `estimate` (hours).
- `milestone`: a fixed point, done once it has dependencies and all are done; never worked on.
- `decision`: a choice someone must make. Keys `decider`.
- `external`: something outside the team's control. Keys `party`, `contact`, `chase` (next chase date).
- `objective`: top-level aim that groups work; never scheduled. Key `owner`.

Parents:

- Parent = "part of", dependency = "must finish before". Parents must be a task or objective; an objective's parent must be an objective. No cycles.
- A task cannot depend on its own ancestor or descendant. Changes that would make nodes wait on each other forever fail with `deadlock: ...` naming the chain.
- A child inherits its ancestors' dependencies and is blocked while any is unfinished.
- A node with children, and every objective, is a summary. It is `done` only when it has children, all are done and its own dependencies are done; otherwise `in_progress` if any child started or finished, else `blocked`. Depending on a summary waits for all its children.
- `start`, `done`, `reopen` fail on summaries and milestones. `ready` lists leaf tasks, decisions and externals only.
- `rollup` is `{done, total}` over leaf descendants. `chase_due` is true for an external whose `chase` date has come.
- `rm ID` fails when the task has children; `--recursive` deletes the subtree.

## Rules

- Always pass `--json` (or `--brief`) when parsing output. With either, commands that print a stderr warning (`done` with unfinished dependencies) add `"warnings": [...]` to their object output; list outputs carry no warnings.
- Titles are imperative verbs, at most 60 characters.
- Use meta keys consistently: the per-type keys, plus `tags` (array), `link`, `lane` (the workstream; groups rows in the Swimlane view) and `team` (the team that owns the workstream). Set `lane` and `team` on the workstream parent: children inherit both. `owner` is one person.
- Never mark a blocked task done without telling the user which dependencies are unfinished.
- `--depends X` means the new task depends on X; `--blocks Y` means Y depends on the new task.
- After bulk changes, offer to run `graph` or `serve`. `serve` blocks: start it as a background process, give the user the URL and leave it running. One server per DB serves every project; the URL's `?project=` picks the view, and running it again reuses the server.

## Usage

```bash
python3 scripts/tg.py [--db PATH] [--project NAME] [--json | --brief] <command> ...
```

`scripts/` is relative to this skill's directory. Installed as a plugin it is `${CLAUDE_PLUGIN_ROOT}/skills/taskgraph/scripts/tg.py`. Python 3.10+ standard library only. The graph page works offline: Cytoscape.js, dagre and cytoscape-dagre (MIT) are vendored in `scripts/vendor/` and inlined.

Data lives in `$TASKGRAPH_DB`, default `~/.taskgraph/tasks.db`.

| Command | Purpose |
| --- | --- |
| `add TITLE [--type T] [--parent ID] [--depends ID ...] [--blocks ID ...] [--start D] [--due D] [--promised D] [--notes T] [--meta k=v ...]` | Create a task and its edges |
| `dep add TASK DEPENDS_ON` / `dep rm TASK DEPENDS_ON` | Add (cycles rejected) or remove a dependency |
| `ls [--status open\|in_progress\|done\|ready\|blocked ...] [--type T ...] [--parent ID] [--search TEXT] [--owner P] [--lane L] [--team T] [--meta k=v ...] [--due-before D] [--sort id\|due\|late] [--all-projects]` | List tasks with due date, person and lane; done excluded by default; repeated flags accumulate. `--owner` matches the owner, decider or party; `--lane` and `--team` see inherited values |
| `ready [--all-projects]` | Leaf tasks that can be started now |
| `show ID` | Full details, dependencies, dependents, conflicts |
| `start ID` / `done ID` / `reopen ID` | Change status |
| `date ID [--start D] [--due D] [--promised D] [--clear start\|due\|promised ...]` | Set or clear dates |
| `agenda [--within DAYS] [--type T ...] [--all-projects]` | Late, conflicts, due soon, chase due, missing dates |
| `edit ID [--title T] [--notes N] [--type T] [--parent ID \| --no-parent] [--meta k=v ...] [--unset-meta k ...]` | Edit fields; meta merges, values parsed as JSON when valid |
| `rm ID [--recursive]` | Delete a task and its edges |
| `why ID` | Chains up to the goals a task serves, through dependents and parents (`via`: `blocks` or `parent`) |
| `tree [ID]` / `tree --children [ID]` | Dependency tree from goals (milestones, objectives and nodes with dependencies that block nothing) / parent hierarchy |
| `graph [--out PATH] [--all-projects] [--no-open]` | Write the interactive HTML graph and open it |
| `serve [--port N] [--all-projects] [--no-open]` | Serve every project live; refreshes on DB change |
| `changes [--since 7d\|DATE] [--all-projects]` | What changed since a date: new, started, completed, reopened, slipped, pulled in, re-scoped, removed |
| `baseline set [--label L] [--replace]` / `baseline ls` / `baseline diff [--label L]` / `baseline rm LABEL` | Snapshot dates, list snapshots, compare now against one, delete one |
| `export [--all-projects] [--out PATH]` | JSON backup of tasks, meta and edges (no import) |
| `projects` | Projects with total, done, ready, blocked counts |

Stored statuses are `open`, `in_progress`, `done`; `blocked` and `ready` are derived. Exit code 1 with an `error:` message on stderr signals an error.
