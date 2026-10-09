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

1. `add` the goal.
2. Ask "what must be true before this is done?" and `add --blocks GOAL` for each prerequisite. Recurse on each prerequisite until tasks are half a day or less and concrete.
3. `ready` shows what can be done now. `start` before working, `done` when finished.
4. Run `graph` for a one-off snapshot file when the user wants to see the picture.
5. When the user wants to watch the plan as it changes, start `serve` as a background process (it blocks), give them the URL, and leave it running. One server per DB serves every project; the URL's `?project=` picks the view.

## Rules

- Always pass `--json` when parsing output.
- Titles are imperative verbs, at most 60 characters.
- Put the why and acceptance criteria in `--notes`.
- Use meta keys consistently: `estimate` (hours, number), `owner`, `tags` (array), `link`.
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
| `add TITLE [--depends ID ...] [--blocks ID ...] [--notes T] [--meta k=v ...]` | Create a task and its edges |
| `dep add TASK DEPENDS_ON` | Add a dependency (cycles rejected) |
| `dep rm TASK DEPENDS_ON` | Remove a dependency |
| `ls [--status open\|in_progress\|done\|ready\|blocked ...] [--all-projects]` | List tasks, done excluded by default |
| `ready [--all-projects]` | List tasks that can be started now |
| `show ID` | Full details with dependencies and dependents |
| `start ID` / `done ID` / `reopen ID` | Change status |
| `edit ID [--title T] [--notes N] [--meta k=v ...] [--unset-meta k ...]` | Edit fields, meta merges, values parsed as JSON when valid |
| `rm ID` | Delete a task and its edges |
| `why ID` | Chains from a task up to the goals it serves |
| `tree [ID]` | Goals with their dependencies indented below |
| `graph [--out PATH] [--all-projects] [--no-open]` | Write the interactive HTML graph and open it |
| `serve [--port N] [--all-projects] [--no-open]` | Serve every project of the DB live and open `/?project=NAME` (`/` with `--all-projects`); checks the DB every 30 s, Refresh button pulls immediately |
| `projects` | Projects with total, done, ready, blocked counts |

Statuses are `open`, `in_progress`, `done`. `blocked` and `ready` are derived: an open task is blocked while any dependency is not done, otherwise ready. Exit code 1 with a message on stderr signals an error.
