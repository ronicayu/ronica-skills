# Taskgraph CLI

## Invocation and data

```bash
python3 scripts/tg.py [--db PATH] [--project NAME] [--json | --brief] COMMAND ...
```

For an installed plugin, use `${CLAUDE_PLUGIN_ROOT}/skills/taskgraph/scripts/tg.py`. In the example, `scripts/` is relative to the skill directory. The script uses only the Python 3.10+ standard library. Data lives in `$TASKGRAPH_DB`; the default is `~/.taskgraph/tasks.db`. The graph works offline. Cytoscape.js, dagre, and cytoscape-dagre (MIT) are vendored in `scripts/vendor/` and inlined.

When parsing output, pass `--json` or `--brief`. See [planning and task semantics](./planning.md) for types, dates, status, and dependency flags.

## Commands

| Command | Purpose |
|---|---|
| `add TITLE [--type T] [--parent ID] [--depends ID ...] [--blocks ID ...] [--start D] [--due D] [--promised D] [--notes T] [--meta k=v ...]` | Create a task and its links. |
| `dep add TASK DEPENDS_ON` / `dep rm TASK DEPENDS_ON` | Add or remove a dependency. Taskgraph rejects cycles. |
| `ls [--status open\|in_progress\|done\|ready\|blocked ...] [--type T ...] [--parent ID] [--search TEXT] [--owner P] [--lane L] [--team T] [--meta k=v ...] [--due-before D] [--sort id\|due\|late] [--all-projects]` | List tasks with dates, people, and lanes. Done tasks are hidden by default. Repeated flags accumulate. `--owner` matches owner, decider, or party. `--lane` and `--team` include inherited values. |
| `ready [--all-projects]` | List leaf tasks that can start now. |
| `show ID` | Show details, dependencies, dependents, and conflicts. |
| `start ID` / `done ID` / `reopen ID` | Change a task's status. |
| `date ID [--start D] [--due D] [--promised D] [--clear start\|due\|promised ...]` | Set or clear dates. |
| `agenda [--within DAYS] [--type T ...] [--all-projects]` | List late, at-risk, conflicting, due-soon, and chase-due items. It also lists tasks whose start dates have passed and items without dates. |
| `edit ID [--title T] [--notes N] [--type T] [--parent ID \| --no-parent] [--meta k=v ...] [--unset-meta k ...]` | Edit fields. Metadata merges. Valid JSON values are parsed as JSON. |
| `rm ID [--recursive]` | Delete a task and its links. |
| `path ID` | Show the upstream chain, slack at each step, driving chain, and verdict. |
| `why ID` | Show the chains from a task to its goals, through dependencies and parents (`via`: `blocks` or `parent`). |
| `tree [ID]` / `tree --children [ID]` | Show the dependency tree from goals or the parent hierarchy. |
| `graph [--out PATH] [--all-projects] [--no-open]` | Create and open the interactive graph. |
| `serve [--port N] [--all-projects] [--no-open]` | Serve all projects live. The page refreshes when the database changes. |
| `changes [--since 7d\|2w\|DATE] [--all-projects]` | Show changes since a date. |
| `baseline set [--label L] [--replace]` / `baseline ls` / `baseline diff [--label L]` / `baseline rm LABEL` | Create, list, compare, or remove date snapshots. |
| `deps [--cross lane\|team\|owner\|project] [--open] [--all-projects]` | List dependency links with people, lanes, statuses, and slack. Use `--cross` to show only cross-group links and `--open` to hide completed work. |
| `report [--by lane\|team\|owner\|project] [--within DAYS] [--since 7d\|DATE] [--risks N] [--md] [--all-projects]` | Create a one-page status report. |
| `load [--by owner\|team\|lane] [--weeks N] [--from DATE] [--week-hours H] [--all-projects]` | Show estimated hours, over-committed weeks, unscheduled work, and work without estimates. |
| `result add ID --status S [--kind K] [--attempt N] [--by NAME] [--body TEXT \| --body-file PATH]` | Add one entry to a task's result log. `S` and `K` are one word of letters, digits, `_`, or `-`. `K` defaults to `task`. Use `--body-file -` to read the body from stdin. |
| `result ls [ID] [--kind K] [--attempt N] [--status S] [--latest] [--all-projects]` | List result entries, oldest first. Without `ID`, list the project's entries with each task's project and title. `--latest` keeps the newest match for each task. `--brief` leaves out the bodies. |
| `export [--all-projects] [--out PATH]` | Export tasks, metadata, links, and results as JSON. Taskgraph has no import command. |
| `projects` | Show each project's RAG status, totals, done, ready, blocked, late, conflicts, at-risk milestones, and next milestone. |

The result log is append-only. `result add` is one insert, so several writers can add to the same task at once. It does not change the task: not its status, notes, metadata, or `updated_at`, and it writes no history. Taskgraph has no command to edit or delete a single entry. Removing the task removes its entries. `show --json` lists the entries without bodies, `show --brief` leaves them out, and `result ls` reads them. Use this command as the one write that a background agent may make. A permission rule that allows it still lets the agent read any file it can open into the log through `--body-file PATH`, and create a database anywhere through `--db`. To narrow it, pin `--db` and allow only `--body` or `--body-file -`.

Stored statuses are `open`, `in_progress`, and `done`. Taskgraph derives `blocked` and `ready`. Exit code 1 and an `error:` message on stderr indicate an error.
