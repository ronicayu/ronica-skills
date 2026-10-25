---
name: taskgraph
description: Track project tasks and dependencies in a SQLite-backed DAG and explore them in an interactive graph. Use when planning backwards from a goal, adding or updating tasks, checking what is ready or blocked, tracking dates, decisions and outside dependencies, preparing a steering review, or viewing a plan.
---

# Taskgraph

Taskgraph stores project plans as tasks and dependency links. Agents use the command-line interface (CLI). People view plans in the graph.

## Start with the right project

If the user names a project, pass `--project NAME` to every command or set `TASKGRAPH_PROJECT`. Otherwise Taskgraph uses the repository name, then the directory name. A typo can create a new project without warning. If unsure, run `projects` to check the name. Parents cannot cross projects. Dependencies can cross projects only when they point to a milestone.

The CLI is in this skill's `scripts/` directory; in an installed plugin, use `${CLAUDE_PLUGIN_ROOT}/skills/taskgraph/scripts/tg.py`.

```bash
python3 scripts/tg.py --project NAME --json projects
python3 scripts/tg.py --project NAME --json ready
```

## Plan and update the graph

For a new plan, clarify the goal and how to tell when it is complete. Then work backwards. Ask what must be true before each goal is complete. Add each prerequisite with `--blocks GOAL_ID`. In each task's Markdown `--notes`, state why the task is needed and how to check that it is done. Keep programme plans coarse. See [planning and task semantics](./references/planning.md) for programme structure, dates, types, dependencies, and status rules.

Before adding work, search for an existing task with `ls --search TEXT`. Use imperative titles of at most 60 characters. Common operations:

```bash
python3 scripts/tg.py --project NAME --json ls --search TEXT
python3 scripts/tg.py --project NAME --json add "Verify the migration" --blocks GOAL_ID --notes "Why it is needed.\n\n- [ ] Acceptance check"
python3 scripts/tg.py --project NAME --json ready
python3 scripts/tg.py --project NAME --json show ID
python3 scripts/tg.py --project NAME --json start ID
python3 scripts/tg.py --project NAME --json done ID
```

`--depends ID` means the new task waits for `ID`. `--blocks ID` means `ID` waits for the new task. A parent means “part of,” not “must finish before.” Do not mark blocked work done without telling the user which dependencies remain unfinished. After bulk changes, offer to show the graph.

## Read and present project status

- Run `ready` to find work that can start now. Run `agenda` to find items that need attention. Run `path ID` to inspect upstream work and schedule outlook.
- Run `report --md` to create a written steering report. Add what the status means, what is being done, and what the reader needs to decide.
- Run `graph` to create a local interactive view. Run `serve` for a live view. `serve` blocks, so run it in the background and give the user its URL.

Use `--json` (or `--brief`) whenever parsing command output. Taskgraph uses SQLite at `$TASKGRAPH_DB`, defaulting to `~/.taskgraph/tasks.db`. See [the complete CLI reference](./references/cli.md) for command syntax; [steering and capacity](./references/steering.md) for reports, baselines, history, and workload; and [the graph guide](./references/graph.md) for views, filters, links, accessibility, export, and printing.
