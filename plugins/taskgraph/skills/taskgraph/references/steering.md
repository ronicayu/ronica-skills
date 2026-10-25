# Steering, history, and capacity

## Weekly steering preparation

1. Run `changes` to see what changed since the last review.
2. Run `agenda` to find late work, at-risk milestones and objectives, tasks that should have started, date conflicts, and items due soon (14 days by default). It also lists chase dates, risk reviews, and decisions, externals, risks, or issues without dates. Use `--type` or `--all-projects` to change the scope.
3. Run `deps --cross lane --open` to find hand-offs between workstreams and identify their owners.
4. Run `load` to find over-commitment by owner, team, or lane.
5. Run `ls --type decision` to list open decisions. Run `ls --status done` to list completed items.
6. Run `report --md` to create a written status. Add what the red items mean, what is being done, and what you need from the reader.
7. Run `serve` and open the Timeline to inspect the plan. See [the graph guide](./graph.md) for navigation and shareable links.

## History and baselines

Every command that changes data records the change in the `events` table in the same transaction. It records titles, statuses, types, parents, dates, dependencies, notes, and metadata. `changes [--since 7d|2w|DATE]` groups each task's net changes as New, Started, Completed, Reopened, Slipped, Pulled in, Re-scoped, or Removed. If you move a date and then move it back within the time window, the report shows no net change. History starts when this version first uses the database. It does not include older changes.

When a group agrees on a plan, take a snapshot with `baseline set --label "SteerCo 2026-10-13"`. This may be at a steering committee or funding gate. The label defaults to today. Use `--replace` if the label already exists. `baseline diff [--label L]` compares the current plan with the snapshot (latest by default). It lists date changes, milestones first and largest slips first, added or removed tasks, and per-lane counts of later and earlier due dates. `show` compares the current due date with the baseline. The Timeline marks the baseline date with a grey tick. Task IDs are never reused.

## Status report and RAG rules

`report [--by lane|team|owner|project] [--within 14] [--since 7d] [--risks 5] [--md]` creates a one-page status report. It includes the overall Red/Amber/Green (RAG) status, changes since `--since`, each open milestone's outlook and baseline drift, and a RAG row with reasons for each group. It also lists pending decisions, externals, top risks by likelihood × impact, open issues, and asks. Asks include decisions that are late, undated, or due within the selected window; externals that are late, due for a chase, or promised late; and open issues. `--md` prints Markdown.

Use the same RAG rules each week:

- **Red:** At least one item is late, a milestone or objective is at risk, or a high-severity issue is open.
- **Amber:** At least one date conflict exists; an item due within `--within` days is still blocked; an open task's start date has passed; a chase is due; a high-likelihood, high-impact risk is open; a risk review is due; or an issue is open.
- **Green:** None of these conditions apply. A milestone is red if it is at risk. It is amber if its outlook is unknown or it has no date.

## Capacity

`load [--by owner|team|lane] [--weeks 8] [--from DATE] [--week-hours 30]` estimates weekly workload. For each open item, Taskgraph spreads the `estimate` (hours) across the remaining working days (Monday–Friday) in its window. The window starts on its `start` date, or the Monday of its due week if it has no start date. It ends on its due date and never starts before today. Taskgraph counts late work from today. Weeks start on Monday. The current week includes only its remaining working days. Taskgraph marks a cell with `!` when it exceeds `--week-hours` and lists the largest contributors first.

Summaries, milestones, risks, and externals do not count toward load. Estimated work without dates is unscheduled. Taskgraph lists open work without an estimate so you can size it. Taskgraph has no availability calendar. Set `--week-hours` to the hours a person can spend on this programme.

The graph's Load view uses the same rules for visible, filtered items. It shows a 12-week heatmap by share of capacity. Red cells with `!` show weeks over capacity. The view also has Later and No dates columns. Select a heatmap cell to list its items. Use View options to group by owner, team, or lane and to set weekly hours. The URL parameters are `view=load`, `loadby=team`, and `hours=25`. You can print the table.
