---
name: taskgraph
description: Track project tasks and their dependencies in a SQLite-backed DAG, then open an interactive graph. Use when the user wants to plan a project or programme backwards from a goal, decompose a goal into prerequisites, ask what can be worked on next or what is blocked, track dates, decisions and outside dependencies, prepare a weekly steering review, add or update tasks and dependencies, or see the plan as a picture — "work backwards from shipping v1", "what's next", "what's blocking X", "what's late". Agents operate the CLI; humans view the graph.
---

# taskgraph

## When to use this skill

Use when the user wants to plan work backwards from a goal, track tasks with dependencies and dates, ask what can be done next or what is late, prepare a steering review, or see the plan as a picture. Agents drive the CLI; the user views the graph.

Trigger keywords (English): task, todo, dependency, work backwards, what's next, blocked, ready, late, agenda, programme

## Choosing the project

Once the user names a plan, pass `--project NAME` on every command, or set `TASKGRAPH_PROJECT`. Otherwise the project falls back to the git repo name, then the directory name, and a typo silently starts a new project. `projects` lists what exists. Parents cannot cross projects. A dependency may cross projects only onto another project's milestone, so a portfolio can say "the warehouse load waits for platform's Dev environment live"; that milestone then cannot change type while other projects depend on it.

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
- A dependency conflicts when it is due after the date its dependent needs it (the dependent's `start`, else its `due`); a child due after its parent's due conflicts; an external promised after `needed_by` conflicts. Conflicts show as `(conflict)` in `ls` and in `show`; JSON has `conflicts` per task, each with `kind`, `from` (the node due too late), `to` (the node that needs it; none for `promised`), `due`, `need`, `gap` (days, negative) and `message`. `agenda` prints each conflict once, worst gap first, with the person and lane on both sides; its JSON `conflicts` holds those edges, not tasks.
- `late_days` is set for any unfinished node past `due` except objectives. A summary carries `span` (earliest start to latest due among its descendants). `$TASKGRAPH_TODAY=YYYY-MM-DD` overrides today.
- A finished summary or milestone reports `done_at` as the latest finish among what it waited for.

## Keeping it current

- A date moved: `date ID --due ...`.
- A decision was made: `done ID`, with the outcome in `edit ID --notes`.
- An external slipped: `date ID --promised ...` and `edit ID --meta chase=YYYY-MM-DD`.
- A new blocker: `add` a decision, external or issue and link it with `--blocks`.
- A new risk: `add --type risk --blocks ID --due REVIEW_DATE --meta owner=... likelihood=high impact=medium mitigation="..."`. Mitigation is a key, not a separate node.
- A risk materialised: `edit ID --type issue --meta severity=high raised=YYYY-MM-DD` and `date ID --due ...`; from then on it blocks.
- A risk retired: `done ID`.

## Will we hit it?

`path ID` walks every unfinished node upstream of a milestone (or any node): its dependencies, and the children of a summary. Each hop shows the upstream node's due, the date it is needed (the dependent's start, else its due; a child is needed by its parent's due) and the slack between them. It ends with the driving chain, the chain whose worst slack is lowest, and a verdict: `at risk` when anything upstream is late or any hop has negative slack, `unknown` when nothing upstream has a date, else `on track`.

Every milestone and objective carries the same verdict as `outlook` (`verdict`, `min_slack`, `negative_slack`, `late_upstream`, `undated`, `open_risks`, `driving`). `show` prints it, `agenda` lists at-risk ones, and the graph outlines them in amber and labels them `at risk`. Slack comes from the dates you entered; nothing is rescheduled.

## History

Every command that changes data records what changed (title, status, type, parent, dates, dependencies, notes, meta) in an `events` table, in the same transaction. `changes [--since 7d|2w|DATE]` reads it back as New, Started, Completed, Reopened, Slipped, Pulled in, Re-scoped (title, type, parent, dependencies, person, lane, team, a date set or cleared) and Removed. Changes are netted per task over the window, so a date moved and moved back shows nothing. History starts when this version first touches the DB; earlier changes were not recorded.

## Baselines

When the plan is agreed (a steering committee, a funding gate), run `baseline set --label "SteerCo 2026-10-13"`. It snapshots every task's start and due in the project; `--label` defaults to today and an existing label needs `--replace`. `baseline diff [--label L]` (latest by default) lists dates moved since then, milestones first and largest slip first, plus tasks added and removed since and a per-lane count of later and earlier dues. `show` prints the baseline due beside the current one, and the Timeline draws a grey tick where a bar was due at baseline. Task ids are never reused, so a baseline always refers to the same task.

## Status report

`report [--by lane|team|owner|project] [--within 14] [--since 7d] [--risks 5] [--md]` writes the one-page status: overall RAG, a line of changes since `--since`, each open milestone with its outlook and baseline drift, a RAG row per group with the reasons, then decisions pending, externals, top risks by likelihood × impact, open issues and Asks (decisions late, undated or due within the window; externals late, chase due or promised late; open issues). `--md` prints Markdown to paste into a deck or doc.

The RAG rules are fixed so they mean the same every week:

- Red: anything late, a milestone or objective at risk, or a high-severity issue open.
- Amber: a date conflict, something due within `--within` days and still blocked, an open task whose start has passed, a chase due, a high/high risk open or a risk review due, or any other issue open.
- Green: none of these. A milestone is red when at risk, amber when its outlook is unknown or it has no date.

Add the narrative yourself: what the reds mean, what is being done, and what you need from the reader. The Asks list is the starting point.

## Capacity

`load [--by owner|team|lane] [--weeks 8] [--from DATE] [--week-hours 30]` shows who is over-committed, week by week. Each open item's `estimate` (hours) is spread evenly over the working days (Mon–Fri) left in its window: from its `start`, or the Monday of its due week when it has no start, to its due date, never before today. Work that is already late lands on today. Weeks start on Monday; the current week counts only the working days left. A cell over `--week-hours` is marked `!`, and each over-committed week lists the items filling it, biggest first. Summaries, milestones, risks and externals carry no load; an item with an estimate but no dates is unscheduled; open items without an estimate are listed so they can be sized. There is no availability calendar on purpose: set `--week-hours` to the hours a person really has for this programme. The page's Load view (fourth view button) uses the same rules on whatever the filters show, so a goal focus or an owner filter gives that slice's load: a heatmap of the next 12 weeks, blue by share of capacity and red with `!` when over, with Later and No dates columns. Hover a cell for the hours and percentage; click it to list the items filling it, each opening its panel. ⚙ View options sets Load by (owner, team, lane) and Hours a week; the URL carries `?view=load&loadby=team&hours=25`. Print… prints the table.

## Weekly steering prep

1. `changes` for what moved since last week.
2. `agenda` groups what needs attention: Late, At risk (milestones and objectives), Should have started (open tasks whose start has passed), Conflicts, due soon (`--within DAYS`, default 14), Chase due, Risk review due, and decisions, externals, risks or issues with no date. `--type` and `--all-projects` narrow or widen it.
3. `deps --cross lane --open` for hand-offs between workstreams and who owns each side.
4. `load` for who is over-committed in the coming weeks.
5. `ls --type decision` for open decisions; `ls --status done` lists completions, since `ls` hides done by default.
6. `serve` and open the Timeline view for the picture. The toolbar has two fixed rows. Row 1 is what you are looking at: project, goal, view (Graph, Swimlane, Timeline, Load), ⚙ View options, search and the live stamp. Row 2 is Filter, the active filters as removable chips with Clear all, Fit, and More (Expand all, Collapse all, Re-layout, Export PNG, Print…, Refresh now, Copy link to view). View options holds Lanes by, the legend toggle and the Timeline's Dependencies: conflicts only (default), the critical path (each open milestone's driving chain, as in `path`) or all dependencies; `?deps=critical` in the URL opens it that way. To look at one goal, type or pick a milestone or objective in the goal box, or press Focus on this goal (Show only what this needs, on other node types) in a node's panel: every view then shows only what that goal needs (its dependencies all the way down, finished work included, the children of summaries on the way, dependencies inherited from parents, and risks pointing at any of it), with done/total and the outlook beside the box. The URL carries `?goal=ID`, so give the user that link when they ask to see one goal, e.g. `http://127.0.0.1:7777/?project=NAME&goal=ID`. The Filter popover narrows by Status (done hidden by default), Flags (late, at risk, conflict, chase due), Types, Owner (owner, decider or party) and Lane (inherited); a summary stays while anything inside it matches. The URL carries them as `status=`, `flag=`, `types=`, `owner=` and `lane=` (comma-separated), so `?project=NAME&owner=Tom&flag=late,atrisk` is Tom's red and amber work. `?task=ID` opens one item's panel (loosening any filter that would hide it); give the user that link to point at a single item. The panel leads with who, when (and the drift against the baseline), lane and estimate, then why it is red or at risk (naming the late items upstream and the conflicts), what it blocks, what blocks it, the driving chain, parent, children and notes (links clickable), with type, project and other meta under Details. Following a row in the panel adds a back step (Alt+←); Copy link copies the item's URL; the panel's left edge drags wider. Search (`/` focuses it) matches title, `#id` (exact), owner, decider, party, contact, lane, team, tags and notes; it lists the hits under the box (arrows, Enter or a click open one; Enter alone steps through them, "2 of 3 matches"), expands collapsed summaries to show a hit and folds them again afterwards, and says when a filter hides a hit ("1 hidden by Types · Show"). Keys: F fit, E expand all, C collapse all, Esc clears the search box when it has focus, otherwise closes the open menu, otherwise the panel. Rows are grouped by lane in both the Swimlane and the Timeline; a child nests under its parent only when both are in the same lane, and objectives sit in an Objectives band at the top. Milestones are listed first in each lane. Each lane header carries a red, amber or green stripe and the word RED, AMBER or GREEN, from the same rules as `report`, over every open item in that lane whatever is expanded. A collapsed summary says how much late or conflicting work it hides ("1 late inside"). The page opens at a readable zoom and scrolls a big plan; Fit shows the whole plan however small; a click never leaves its node hidden behind the panel. Browser Back and Forward step through views, goals and projects. Hovering a dependency line says who waits for whom and, for a conflict, by how many days; clicking it opens the late side. A chase-due external names the party to chase. Collapse keeps objectives open. Export PNG saves the whole current view (as filtered, not just what is on screen) at 2x with a title bar naming the project, goal, view, date and active filters, and the legend, ready for a slide or an email. Print… (or the browser's own Print / Save as PDF) gives a landscape sheet instead of the controls: the same title and filters, the whole plan, the legend, and the open item's panel on a second page. Plans of several hundred items stay responsive; Graph switches to a faster layout above 250 items and reuses layouts it has already computed. Dates on the page read `14 Oct`, with the year only when it is not this year.
7. `report --md` for the written status; add the narrative.

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
- `risk`: something that may happen. Keys `owner`, `likelihood`, `impact` (`low`, `medium`, `high`), `mitigation`, `review` (its date; `--due` writes it). `--blocks X` records that it threatens X, but a risk never blocks: it is left out of status, conflicts, slack, deadlock checks, its parent's rollup, status and span. Threatened nodes list it as `threats`; outlooks count `open_risks`. A risk is never late; `agenda` lists it under Risk review due once `review` has come.
- `issue`: something that has happened and needs resolving. Keys `owner`, `severity`, `raised`, plus `due`. It blocks like a task.

Parents:

- Parent = "part of", dependency = "must finish before". Parents must be a task or objective; an objective's parent must be an objective. No cycles.
- A task cannot depend on its own ancestor or descendant. Changes that would make nodes wait on each other forever fail with `deadlock: ...` naming the chain.
- A child inherits its ancestors' dependencies and is blocked while any is unfinished.
- A node with children, and every objective, is a summary. It is `done` only when it has children, all are done and its own dependencies are done; otherwise `in_progress` if any child started or finished, else `blocked`. Depending on a summary waits for all its children.
- `start`, `done`, `reopen` fail on summaries and milestones. `ready` lists leaf tasks, decisions, externals and issues only, never risks.
- `rollup` is `{done, total}` over leaf descendants. `chase_due` is true for an external whose `chase` date has come.
- `rm ID` fails when the task has children; `--recursive` deletes the subtree.

## Rules

- Always pass `--json` (or `--brief`) when parsing output. With either, commands that print a stderr warning (`done` with unfinished dependencies) add `"warnings": [...]` to their object output; list outputs carry no warnings.
- Titles are imperative verbs, at most 60 characters.
- Use meta keys consistently: the per-type keys, plus `tags` (array), `link`, `lane` (the workstream; groups rows in the Swimlane and Timeline views) and `team` (the team that owns the workstream). Set `lane` and `team` on the workstream parent: children inherit both. `owner` is one person.
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
| `agenda [--within DAYS] [--type T ...] [--all-projects]` | Late, at risk, should have started, conflicts, due soon, chase due, missing dates |
| `edit ID [--title T] [--notes N] [--type T] [--parent ID \| --no-parent] [--meta k=v ...] [--unset-meta k ...]` | Edit fields; meta merges, values parsed as JSON when valid |
| `rm ID [--recursive]` | Delete a task and its edges |
| `path ID` | Upstream chain with slack per hop, driving chain and verdict |
| `why ID` | Chains up to the goals a task serves, through dependents and parents (`via`: `blocks` or `parent`) |
| `tree [ID]` / `tree --children [ID]` | Dependency tree from goals (milestones, objectives and nodes with dependencies that block nothing) / parent hierarchy |
| `graph [--out PATH] [--all-projects] [--no-open]` | Write the interactive HTML graph and open it |
| `serve [--port N] [--all-projects] [--no-open]` | Serve every project live; refreshes on DB change |
| `changes [--since 7d\|DATE] [--all-projects]` | What changed since a date: new, started, completed, reopened, slipped, pulled in, re-scoped, removed |
| `baseline set [--label L] [--replace]` / `baseline ls` / `baseline diff [--label L]` / `baseline rm LABEL` | Snapshot dates, list snapshots, compare now against one, delete one |
| `deps [--cross lane\|team\|owner\|project] [--open] [--all-projects]` | Dependency edges with both sides' person, lane and status and the slack between them, tightest first; `--cross` keeps hand-offs between lanes, teams or people, `--open` drops finished upstream work |
| `report [--by lane\|team\|owner\|project] [--within DAYS] [--since 7d\|DATE] [--risks N] [--md] [--all-projects]` | One-page status with RAG per group, milestones, decisions, externals, risks, issues and asks |
| `load [--by owner\|team\|lane] [--weeks N] [--from DATE] [--week-hours H] [--all-projects]` | Hours per person (or team, lane) per week from estimates, over-committed weeks and the items filling them, unscheduled hours, items with no estimate |
| `export [--all-projects] [--out PATH]` | JSON backup of tasks, meta and edges (no import) |
| `projects` | Portfolio: per project RAG (same rules as `report`), total, done, ready, blocked, late, conflicts, at-risk milestones and the next milestone |

Stored statuses are `open`, `in_progress`, `done`; `blocked` and `ready` are derived. Exit code 1 with an `error:` message on stderr signals an error.
