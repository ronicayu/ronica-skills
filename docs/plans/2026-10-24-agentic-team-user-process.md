# Agentic Team User Process Implementation Plan

**Goal:** Give the operator a visible, staged process for running the team.
It has one command per stage, a clear home for each kind of instruction, and
an autonomy level that decides when the team stops for the operator. Today
the structure exists only inside the Manager's playbooks. The operator sees a
setup command and an agent to talk to.

**Status:** Draft for operator review. Nothing here is built yet. The
decisions in "Decisions to confirm" came out of the 2026-10-24 discussion;
the rest is proposed.

**Architecture:** Three changes, all built on the existing playbooks and
scripts:

1. **Stages and commands.** The process becomes `setup → plan → approve →
   run ⇄ decide → report → close`, with `pause` and `resume` available at
   any point. Each stage has a slash command, and the Manager also accepts
   plain-language requests and names the stage it maps them to.
2. **Layers.** Every instruction has one home, chosen by how long it should
   last: CLAUDE.md, the project config, the plan, the run, or the task.
3. **Autonomy level.** `supervised`, `checkpoint` (default), or `autonomous`
   decides whether plan approval and product decisions wait for the
   operator. `autonomy.always_pause` gates and irreversible actions always
   wait, at every level.

**Tech stack:** Same as the TOML plan: Markdown playbooks and skills, Python
3.11 or later with the standard library only.

**Scope:** `plugins/agentic-team/` only, plus the root `README.md`. Commit
only when the operator asks.

---

## Decisions to confirm

The operator settled the first three on 2026-10-24. The last three are
proposals made while writing this plan.

| # | Decision | Source |
|---|---|---|
| 1 | Plan approval depends on the autonomy level; it is not always required. | Operator |
| 2 | Commands and plain language both work. Commands are the documented entry points. | Operator |
| 3 | `close` archives or deletes the run directory, set by `run.on_close`, default `"archive"`. | Operator |
| 4 | A per-run override (`/agentic-team:run --autonomous`) is written to `.agentic-team/run.toml`, a third config layer that `close` removes. Standing orders stay prose only. | Proposed |
| 5 | In `autonomous`, a decision outside the grant takes the gate's default at once and is reported, unless it is an `always_pause` gate. | Proposed |
| 6 | Running `/agentic-team:close` is the operator's confirmation for `run.on_close = "delete"`; the Manager does not ask again. | Proposed |

## Current state (read first)

- **Commands.** `/agentic-team:setup` is the only one
  (`skills/setup/SKILL.md`).
- **Routing.** `agents/manager.md` maps situations to playbooks: `plan`,
  `launch`, `drain`, `verify-and-close`, `report`, `pickup`, `pause`. There
  is no `decide` or `close` playbook.
- **Approval.** `playbooks/plan.md` step 5 shows the plan only when it adds
  more than three tasks.
- **Autonomy.** `autonomy.grant` and `autonomy.always_pause` in
  `.agentic-team.toml`, applied by
  `skills/principle-decision-forks/SKILL.md`. There is no level.
- **Run state.** `.agentic-team/`: `standing-orders.md`, `gates.md`,
  `briefs/`, `reports/`, `handoff.md`, `last-report`. Nothing ever cleans
  it up.
- **Config.** `scripts/config.py` merges `.agentic-team.toml` and
  `.agentic-team.local.toml`; `SCHEMA` holds every key and default.

## Design

### Layers: one home per instruction

| Layer | Holds | Lasts | Changed with |
|---|---|---|---|
| CLAUDE.md | Conventions for anyone in the repo | Permanently | The operator edits it |
| Project config | What the Manager needs: project, constraints, models, autonomy level | Permanently | `/agentic-team:setup` |
| Plan | Tasks, scope, acceptance, dependencies (Taskgraph) | Until done | `/agentic-team:plan`, approval |
| Run | Standing orders, gates, per-run overrides (`.agentic-team/`) | One run | `/agentic-team:order`, `decide`, `run --autonomous` |
| Task | Brief, report, verdict | One attempt | The Manager only |

The README states this table, and `close` asks for each standing order
whether to keep it, move it to CLAUDE.md or the config, or drop it.

### Stages and commands

| Stage | Command | Operator gets | Operator does | Playbook |
|---|---|---|---|---|
| Setup | `/agentic-team:setup` | A config that passes `check` | Answers questions | (skill) |
| Plan | `/agentic-team:plan <goal>` | Tasks, critical path, first batch | Approves when the level asks | `plan` |
| Run | `/agentic-team:run [--supervised \| --checkpoint \| --autonomous]` | Workers launched and verified | Nothing until needed | `launch`, `drain`, `verify-and-close` |
| Decide | `/agentic-team:decide` | Each open gate, with options and default | Answers in their own words | `decide` (new) |
| Report | `/agentic-team:status` | Status tables, decisions waiting at the top | Reads | `report` |
| Order | `/agentic-team:order <text>` | The new standing order, numbered | Nothing | `order` (new, short) |
| Pause | `/agentic-team:pause` | A handoff summary | Nothing | `pause` |
| Resume | `/agentic-team:resume` | Reconciled state and the next action | Nothing | `pickup` |
| Close | `/agentic-team:close` | Final summary, follow-ups, standing-order suggestions | Accepts or rejects each suggestion | `close` (new) |

Commands are skills (`skills/<name>/SKILL.md`, invoked as
`/agentic-team:<name>`), matching `setup`. Each has
`disable-model-invocation: true` and a body of a few lines: confirm the
session is the Manager, then follow the named playbook with `$ARGUMENTS`.
When the session is not the Manager, the skill tells the operator to select
`agentic-team:manager` and stops. The Manager reads playbooks directly, so
it never needs to invoke these skills.

For plain-language requests, the Manager matches the request to a stage and
starts its reply with the mapping, for example "Treating this as
`/agentic-team:order`."

### Autonomy levels

| Level | Plan approval | Decision outside the grant | Use when |
|---|---|---|---|
| `supervised` | Always waits | Gate; waits | New project, risky work |
| `checkpoint` | Waits when the plan adds more than `autonomy.approve_over` tasks, or any `risk=high` task | Gate; routes other work around it | Normal work (default) |
| `autonomous` | Never waits; the plan appears in the next report | Takes the gate's default at once, marks the gate `defaulted`, lists it in the next report | Unattended runs |

At every level:

- `autonomy.always_pause` gates and irreversible actions wait for the
  operator.
- Constraints, standing orders, and `STOP` apply in full.
- Every decision the Manager took alone appears in the next report, with what
  it chose and what the operator could say instead. The decision-forks
  principle already requires this.
- In `supervised`, the Manager does not use `autonomy.grant`.

The effective level is `config.py get autonomy.level`, which already includes
the run override (see below).

### Run layer: `.agentic-team/run.toml`

`config.py` gains a third, optional layer, merged after the local file. It
accepts only run-scoped keys: `autonomy.level`, `autonomy.approve_over`, and
`sessions.max_parallel`. Any other key is a `check` problem.
`/agentic-team:run --autonomous` writes it, and `close` deletes it. The
Manager edits it by text, as setup does for the main file.

Standing orders stay prose for workers. Settings the Manager acts on go in
`run.toml`, where `config.py` reads and validates them like any other key.

### Status line

Every Manager reply to the operator ends with one line:

```text
Stage: run · autonomous · 3 in flight · 1 waiting for verification · 2 waiting on you · next: verify #41
```

`status.py --line` prints the counts and the level. "Waiting on you" counts
open gates, plus a plan awaiting approval. The Manager adds the stage and the
next action.

### Close

`/agentic-team:close`:

1. Drains, then lists in-flight tasks. If any are in flight, it stops and
   asks whether to wait or stop them; closing never abandons work silently.
2. Writes `.agentic-team/summary.md`: tasks closed this run, with verdicts
   and tokens, open follow-ups, gates and their answers, and decisions taken
   by default.
3. For each standing order, suggests keep (next run), move to CLAUDE.md, move
   to the config, or drop, and applies the operator's answers. Under
   `autonomous`, it still asks; close is interactive by design.
4. Runs `scripts/close.py`, which reads `run.on_close`:
   - `"archive"` moves the run files to
     `.agentic-team/archive/<YYYY-MM-DD-HHMM>/`;
   - `"delete"` removes them.

   Either way, it removes `run.toml` and keeps the archive folder and any
   standing orders the operator chose to keep.

---

## Task 1: Config keys and the run layer

**Files:** modify `scripts/config.py` and `tests/test_config.py`.

- Add to `SCHEMA`:
  - `autonomy.level`: one of `supervised`, `checkpoint`, `autonomous`;
    default `"checkpoint"`. Add an enum type, so a typo is a `check` problem
    with a suggestion.
  - `autonomy.approve_over`: positive integer, default `3`.
  - A `[run]` section with `on_close`: `"archive"` or `"delete"`, default
    `"archive"`.
- Merge `.agentic-team/run.toml` after the local file. Allow only
  `RUN_KEYS = {"autonomy.level", "autonomy.approve_over",
  "sessions.max_parallel"}`. Report any other key as
  `run.toml: <key> cannot be set per run`.
- `show` marks which layer set each value, for example
  `level = "autonomous"  # run.toml`, so the operator can see why a value
  holds.

**Verify:** unit tests for each new key's default and bad value, a `run.toml`
override, a disallowed `run.toml` key, and `show` attribution. Run
`python3 -m unittest discover plugins/agentic-team/tests`.

## Task 2: Scripts

**Files:** modify `scripts/status.py`; create `scripts/close.py` and
`tests/test_close.py`.

- `status.py --line` prints one line: level, in flight, waiting for
  verification, and open gates. It reuses the existing counts; no new data
  sources.
- `close.py [--root DIR] [--dry-run]` reads `run.on_close` through
  `config.py`, then archives or deletes the run files listed above. It
  always removes `run.toml` and prints what it did. It refuses with exit 2
  when the run directory is missing. `--dry-run` prints the plan only.

**Verify:** `test_close.py` covers archive, delete, dry run, and a missing
directory in a temporary folder. Run `status.py --line` against a scratch
Taskgraph database, as in the TOML plan's Task 2.

## Task 3: Playbooks and principle

**Files:** modify `playbooks/plan.md`, `playbooks/drain.md`,
`playbooks/report.md`, `playbooks/pause.md`, `playbooks/pickup.md`, and
`skills/principle-decision-forks/SKILL.md`. Create `playbooks/decide.md`,
`playbooks/order.md`, and `playbooks/close.md`.

- **`plan.md` step 5.** Replace the three-task rule with the level table:
  show the plan and stop for approval under `supervised`, or under
  `checkpoint` above `approve_over` or with a `risk=high` task; otherwise
  continue and include the plan in the next report.
- **`drain.md` `BLOCKED` branch and the decision-forks principle.** Apply
  the level: gate and wait, gate and route around, or take the default and
  mark the gate `defaulted`.
- **`decide.md`.** List open gates. Record each answer in the operator's
  words with `Status: answered`, then relaunch or re-plan the work it
  blocked.
- **`order.md`.** Add, list, or remove a numbered standing order, and echo
  the result. `STOP` goes through `pause`.
- **`close.md`.** The steps in "Close" above.
- **`report.md`.** Put "Waiting on you" first, then the existing order. Add
  "Decided without you" when there are defaulted gates or grant decisions.

**Verify:** each playbook keeps numbered steps and a **Reply** line.

## Task 4: Manager

**Files:** modify `agents/manager.md`.

- Replace the Playbooks table with a Stages table: stage, command, plain
  examples ("how's it going", "keep going without me"), and playbook.
- Add rules: name the stage when a plain request maps to one; end every
  operator reply with the status line; read the level with
  `config.py get autonomy.level`, never from memory.
- In Escalation, replace the prose about what reaches the operator with a
  pointer to the level table, keeping the "never reaches the operator" list.

**Verify:** the Manager stays a short index; the line count may grow by at
most about 20 lines.

## Task 5: Commands

**Files:** create `skills/{plan,run,status,decide,order,pause,resume,close}/SKILL.md`.

Each has `name`, a description starting with what it does and when to use
it, `disable-model-invocation: true`, and a short body:

1. If this session is not running as `agentic-team:manager`, say how to
   start it and stop.
2. Otherwise follow `${CLAUDE_PLUGIN_ROOT}/playbooks/<name>.md` with
   `$ARGUMENTS`.

`run` also handles `--supervised`, `--checkpoint`, and `--autonomous` by
writing `run.toml`, then follows `launch`.

**Verify:** `./scripts/validate.sh` and
`claude plugin validate plugins/agentic-team`. Check that each command
appears as `/agentic-team:<name>` in a live session.

## Task 6: Template and setup

**Files:** modify `templates/agentic-team.toml` and `skills/setup/SKILL.md`.

- Template: add `level`, commented `approve_over`, and a `[run]` section
  with commented `on_close`.
- Setup asks one question about the level, explaining the three options in
  a sentence each, and accepts the default. It does not ask about
  `on_close`; the README documents it.

## Task 7: README and diagrams

**Files:** modify `plugins/agentic-team/README.md` and the root `README.md`;
create `assets/diagrams/stages.mmd`; re-render with `render.mjs`.

- Open the plugin README with "Using the team", for the operator: the stages
  diagram, the commands table, the layers table, and the autonomy levels.
  Use no internal terms (drain, verdict ref, tier) before the internals
  section.
- Move the current "How it works", "Briefs", "Run directory", and "Task
  metadata" sections under "Internals".
- Document `autonomy.level`, `autonomy.approve_over`, `run.on_close`, and
  `run.toml` in Configuration.
- Root README: list the commands in one line after the setup sentence.

## Task 8: Validation

Run the TOML plan's Task 7 checks, plus:

- a live smoke test from a scratch repository: `/agentic-team:status` in a
  Manager session prints the status line; `/agentic-team:run --autonomous`
  writes `run.toml`, and `config.py get autonomy.level` prints
  `autonomous`; `/agentic-team:close` with an empty run archives it;
- the grep from the TOML plan still returns nothing.

## Out of scope

- Changing the worker agent or brief format.
- Hooks that print the status line automatically.
- Scheduling or time-boxed autonomy ("autonomous until Friday"). The
  operator switches the level back by hand, or `close` resets it.
- Changes to the Taskgraph plugin.
