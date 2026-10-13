---
name: taskgraph
description: Track project tasks and their dependencies in a SQLite-backed DAG, then open an interactive graph. Use when the user wants to plan a project backwards from a goal, decompose a goal into prerequisites, ask what can be worked on next or what is blocked, add or update tasks and dependencies, or see the plan as a picture — "work backwards from shipping v1", "what's next", "what's blocking X", "下一步做什么", "任务依赖", "看图". Agents operate the CLI; humans view the graph.
---

# taskgraph

## When to use this skill

Use when the user wants to plan work backwards from a goal, track tasks with dependencies, ask what can be done next, or see the plan as a picture.

Trigger keywords (English): task, todo, dependency, work backwards, what's next, blocked, ready
Trigger keywords (中文): 任务, 依赖, 计划, 下一步, 看图

## Work-backwards workflow

1. `add` the goal: `--type milestone` (with `--meta date=YYYY-MM-DD` when the date is fixed) or `--type objective` for a programme-level aim.
2. Ask "what must be true before this is done?" and `add --blocks GOAL` for each prerequisite. Recurse on each prerequisite until tasks are half a day or less and concrete. Set `--meta lane=<workstream>` on each task when decomposing. Mark choices someone must make as `--type decision` (`decider`, `decide_by`) and things waiting on outsiders as `--type external` (`party`, `needed_by`, `contact`, `chase`). Decompose big work into children with `--parent` instead of a long flat list.
3. `ready` shows what can be done now. `start` before working, `done` when finished.
4. Run `graph` for a one-off snapshot file when the user wants to see the picture.
5. When the user wants to watch the plan as it changes, start `serve` as a background process (it blocks), give them the URL, and leave it running. The page has a Graph | Swimlane toggle; Swimlane groups tasks into rows by `lane`, or by owner, tag or project. One server per DB serves every project; the URL's `?project=` picks the view.

## Types

Stored as `meta.type`, absent means `task`. Set with `add --type T` / `edit --type T` (`--type task` clears it); unknown types are rejected. Per-type meta keys are ordinary and not enforced. Date keys (`date`, `decide_by`, `needed_by`, `chase`) must be `YYYY-MM-DD`.

- `task`: work to do. Keys `owner`, `estimate` (hours).
- `milestone`: a fixed point that is reached when its dependencies are done; never worked on. Key `date` (fixed target date).
- `decision`: a choice someone must make. Keys `decider`, `decide_by`.
- `external`: something outside the team's control. Keys `party`, `needed_by`, `contact`, `chase` (next chase date).
- `objective`: top-level aim that groups tasks; never scheduled. Key `owner`.

## Parents and derived status

- Parent = "part of", dependency = "must finish before". `add --parent ID`, `edit --parent ID`, `edit --no-parent`, `ls --parent ID` (direct children), `tree --children [ID]` (parent hierarchy).
- Parents must be a `task` or `objective`; an objective's parent must be an objective. No cycles. A task cannot depend on its own ancestor or descendant; siblings and other subtrees are fine. Any change that would make nodes wait on each other forever (a dependency plus a parent chain, e.g. L1 depends on S, S's child L2 depends on L1) fails with `deadlock: ...` naming the chain.
- A child inherits its ancestors' dependencies: it is blocked while any of them is unfinished.
- A node with children, and every objective, is a summary: its status is derived from its children (all done is `done`, any started or done is `in_progress`, otherwise `blocked`). Depending on a summary means waiting for all its children.
- A milestone is `done` once it has dependencies and all are done, otherwise `blocked`.
- `start`, `done`, `reopen` fail on summaries and milestones. `ready` lists only leaf tasks, decisions and externals.
- `rollup` is `{done, total}` over leaf descendants. `late_days` is set for a milestone past `date`, a decision past `decide_by` or an external past `needed_by` while not done; `chase_due` is true for an external whose `chase` date has come. `$TASKGRAPH_TODAY=YYYY-MM-DD` overrides today.
- `rm ID` fails when the task has children; `rm ID --recursive` deletes the whole subtree.

## Rules

- Always pass `--json` when parsing output.
- Titles are imperative verbs, at most 60 characters.
- Put the why and acceptance criteria in `--notes`.
- Never mark a task with children, an objective or a milestone done; finish its children or dependencies.
- Use meta keys consistently: the per-type keys above, plus `tags` (array), `link`, `lane` (workstream name, groups rows in the Swimlane view).
- Never mark a blocked task done without telling the user which dependencies are unfinished.
- After bulk changes, offer to run `graph` or `serve`.
- `serve` runs one server per DB for all projects. Running it again, even from another project, reuses the server and opens that project's view, so it is safe to call whenever the user asks to see the graph.
- `--depends X` means the new task depends on X; `--blocks Y` means Y depends on the new task.

## Usage

```bash
python3 scripts/tg.py [--db PATH] [--project NAME] [--json] <command> ...
```

`scripts/` is relative to this skill's directory, not the working directory. Installed as a plugin it is `${CLAUDE_PLUGIN_ROOT}/skills/taskgraph/scripts/tg.py`. Python 3.10+ standard library only; the graph page loads Cytoscape.js from a CDN.

Data lives in `$TASKGRAPH_DB`, default `~/.taskgraph/tasks.db`. Project defaults to `--project`, then `$TASKGRAPH_PROJECT`, then the git repo name, then the current directory name.

| Command | Purpose |
| --- | --- |
| `add TITLE [--type T] [--parent ID] [--depends ID ...] [--blocks ID ...] [--notes T] [--meta k=v ...]` | Create a task and its edges |
| `dep add TASK DEPENDS_ON` | Add a dependency (cycles rejected) |
| `dep rm TASK DEPENDS_ON` | Remove a dependency |
| `ls [--status open\|in_progress\|done\|ready\|blocked ...] [--type T ...] [--parent ID] [--all-projects]` | List tasks, done excluded by default |
| `ready [--all-projects]` | List tasks that can be started now |
| `show ID` | Full details with dependencies and dependents |
| `start ID` / `done ID` / `reopen ID` | Change status |
| `edit ID [--title T] [--notes N] [--type T] [--parent ID \| --no-parent] [--meta k=v ...] [--unset-meta k ...]` | Edit fields, meta merges, values parsed as JSON when valid |
| `rm ID [--recursive]` | Delete a task and its edges; `--recursive` deletes its children too |
| `why ID` | Chains from a task up to the goals it serves |
| `tree [ID]` | Goals with their dependencies indented below |
| `tree --children [ID]` | The parent hierarchy, roots first, with derived status and type |
| `graph [--out PATH] [--all-projects] [--no-open]` | Write the interactive HTML graph and open it |
| `serve [--port N] [--all-projects] [--no-open]` | Serve every project of the DB live and open `/?project=NAME` (`/` with `--all-projects`); checks the DB every 30 s, Refresh button pulls immediately |
| `projects` | Projects with total, done, ready, blocked counts |

Stored statuses are `open`, `in_progress`, `done`. `blocked` and `ready` are derived: an open leaf is blocked while any effective dependency is not done, otherwise ready. Exit code 1 with a message on stderr signals an error.
