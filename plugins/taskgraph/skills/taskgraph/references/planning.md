# Planning and task semantics

## Choose a project and plan at the right level

Pass `--project NAME` on every command, or set `TASKGRAPH_PROJECT`. Without either, Taskgraph uses the git repository name, then the directory name. A typo silently creates a new project. Use `projects` to check names. Parents cannot cross projects. A dependency can cross projects only when it points to a milestone in another project. Do not change that milestone's type while another project depends on it.

For a large programme, build top-down and stay coarse:

1. Create an `objective` for each programme aim.
2. Create dated `milestone` nodes for fixed points.
3. Add the `decision` and `external` nodes that gate those milestones. Record who decides or delivers, and by when.
4. Group work under workstream parents, setting `lane=<workstream>` in their metadata.
5. Add tasks only for work the team must do. Do not break a programme into half-day tasks. Use that level of detail only for small personal projects.

For each goal, ask: “What must be true before this is done?” Add each prerequisite with `--blocks GOAL_ID`. In `--notes`, state why it is needed and list its acceptance criteria. A short paragraph and a Markdown checklist work well.

## Dates and schedule outlook

Enter dates as `YYYY-MM-DD`. Set them by hand; Taskgraph does not calculate them from durations. Use `date ID` to change a date:

```bash
tg.py date ID --due 2027-01-15 --start +1w --clear start
tg.py date ID --promised 2027-02-01
```

- `--due` sets the date field for the node type: `date` for milestones, `decide_by` for decisions, `needed_by` for externals, and `due` for tasks and objectives.
- `--start` sets when task work begins or when an external was requested or ordered. Taskgraph ignores it for milestones and decisions.
- `--promised` sets the date an external party committed to deliver. `add` also accepts this option.
- Dates can be `today` or offsets such as `+3d`, `+2w`, and `-1w`. Taskgraph rejects a `start` date after the `due` date. Set `$TASKGRAPH_TODAY=YYYY-MM-DD` to override today.
- A date conflict occurs if a dependency is due after its dependent needs it. The dependent needs it by its `start` date, or by its `due` date if it has no start date. A conflict also occurs if a child is due after its parent's due date, or an external's promised date is after its needed-by date. `ls` and `show` mark conflicts. `agenda` lists each conflict once.
- Unfinished nodes past due have `late_days`, except objectives. A summary's `span` runs from the earliest start to the latest due date among its descendants. A finished summary or milestone reports `done_at` as the latest finish among the work it waited for.

`path ID` follows every unfinished upstream dependency and summary child. It shows each due date, when the work is needed, and the slack. It identifies the driving chain and gives one of three verdicts: `at risk` if upstream work is late or has negative slack; `unknown` if no upstream item has a date; otherwise `on track`. Milestones and objectives show the same outlook. Taskgraph never reschedules dates automatically.

## Keep the plan current

- If a date changes, run `date ID --due ...`.
- When someone makes a decision, run `done ID`. Record the outcome with `edit ID --notes`.
- If an external slips, update `--promised` and set the next `chase` date in metadata.
- To record a new blocker, add a decision, external, or issue. Link it with `--blocks`.
- To record a risk, add `--type risk` and link the threatened item with `--blocks`. Set `owner`, `likelihood`, `impact`, `mitigation`, and the review date.
- If a risk happens, change it to an `issue`. Set `severity`, `raised`, and `due`. Issues block like tasks. Mark a retired risk done.

Before each `add`, run `ls --search TEXT` to check titles and notes for duplicates. The search ignores case. For a large plan, use `--brief`. It implies `--json` and returns fewer fields for `ls`, `ready`, `agenda`, and `show`.

## Types, parents, and status

The type is stored as `meta.type`; no type means `task`, and `--type task` clears it. Unknown types are rejected.

| Type | Meaning and metadata |
|---|---|
| `task` | Work to do. Metadata: `owner`, `estimate` (hours). |
| `milestone` | A fixed point. It is complete when it has dependencies and all are done. Do not work on a milestone directly. |
| `decision` | A choice someone must make. Metadata: `decider`. |
| `external` | Work outside the team's control. Metadata: `party`, `contact`, `chase` (next chase date). |
| `objective` | A top-level aim that groups work. Metadata: `owner`. Do not schedule objectives. |
| `risk` | Something that may happen. Metadata: `owner`, `likelihood`, `impact` (`low`, `medium`, `high`), `mitigation`, `review`. Use `--blocks` to record what the risk threatens. Risks do not block or affect status, conflicts, slack, deadlock checks, parent rollups, or span. Threatened nodes list risks in `threats`; outlook counts open risks in `open_risks`. Risks are never late. `agenda` lists them when review is due. |
| `issue` | A problem that has happened and needs resolving. Metadata: `owner`, `severity`, `raised`, `due`. Issues block like tasks. |

A parent means “part of.” A dependency means “must finish before.” Parents must be tasks or objectives. An objective's parent must also be an objective. Taskgraph rejects cycles. A task cannot depend on its own ancestor or descendant. Changes that create a deadlock fail and show the chain.

Children inherit their ancestors' dependencies. They remain blocked while any inherited dependency is unfinished. A node with children is a summary; every objective is also a summary. A summary is `done` only if it has children, all its children are done, and its own dependencies are done. Otherwise it is `in_progress` if a child has started or finished, or `blocked`. A dependency on a summary waits for all its children. The `start`, `done`, and `reopen` commands reject summaries and milestones. `ready` lists leaf tasks, decisions, externals, and issues. It does not list risks.

`rollup` gives `{done, total}` across leaf descendants. An external's `chase_due` is true when its chase date arrives. `rm ID` will not delete a node with children unless you use `--recursive`.

## Data and command safety

- When parsing output, always pass `--json` or `--brief`. If a command prints a warning to stderr (for example, `done` with unfinished dependencies), its object output includes `warnings`. List outputs do not.
- Use imperative titles no longer than 60 characters.
- Use type-specific metadata consistently. Also use `tags` (array), `link`, `lane`, and `team`. Set `lane` and `team` on workstream parents; children inherit them. Set one person as `owner`.
- `--depends X` means the new task waits for X; `--blocks Y` means Y waits for the new task.
- Never mark blocked work done without telling the user which dependencies are unfinished.
- After bulk changes, offer to run `graph` or `serve`. `serve` blocks. Start it in the background and give the user the URL. One server per database serves all projects. Use `?project=NAME` to select a project; running `serve` again reuses the server.
